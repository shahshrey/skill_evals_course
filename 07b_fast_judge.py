"""
Eval type 7, variant b: a fast typed judge.

07_llm_judge.py asks a large model to read an output and write a verdict.
That works, but each call takes seconds and costs real money, so people run
the judge once on a handful of cases and call it done. This file asks the
same questions to a System One model (Jev, from TypeSafe), which does not
generate text at all. You hand it the state and a yes/no question and it
returns the probability that the answer is yes, in a fraction of a second,
for a fraction of a cent. Ask it three questions on sixteen outputs and you
are done before the LLM judge has finished its first.

Two things change when the judge is this cheap:

  1. You can afford to grade everything, every run. A rubric that costs
     nothing to apply becomes a regression test instead of a spot check.
  2. You get a probability, not a verdict. A 0.95 and a 0.55 both round to
     "yes", but they are not the same answer. Log the number, choose the
     threshold in code, and move it when the stakes change.

The catch is the same as for any judge: it has to be calibrated before you
trust it. This file does that two ways. Known-bad outputs must score low,
and every verdict is compared with the LLM judge's verdict on the same
output. Where two independent judges disagree, one of them is wrong, and a
human should look. Agreement between judges of different families is far
stronger evidence than either judge alone.

Needs TYPESAFE_API_KEY in the environment or in .env. Reads the rows that
06_ab_comparison.py saved and, if present, the verdicts 07_llm_judge.py
saved. Run 06 first; 07 is optional but makes the comparison possible.

Run:  python 07b_fast_judge.py
Writes results/07b_fast_judge.jsonl.
"""

from __future__ import annotations

import sys
from collections import defaultdict

from dotenv import load_dotenv
from pydantic import Field
from typesafe_sdk import Choice, ChoiceAnswer, Noul, NoulAnswer, SystemOneResponse, TypeSafeClient

from skill_eval_common import (
    RESULTS_DIR,
    configure_logging,
    explain,
    headline,
    load_jsonl,
    load_skill,
    log,
    note,
    results_from,
    save_jsonl,
    section,
    show_skill,
    table,
)

# The same three properties 07 asks about, phrased as yes/no questions.
# Keep each one narrow: one property per question, and say what "yes" means.
ASSERTIONS = {
    "imperative_subject": "Is the subject line (the first line) written in the imperative mood, "
                          "like \"add\" or \"fix\", rather than past tense or a noun phrase?",
    "explains_why": "Does the body explain why the change was made, rather than only restating what changed?",
    "standalone_body": "Would the body make sense to someone reading only the git log later, "
                       "without the diff or the conversation in front of them?",
}
# 07 numbers its assertions 1, 2, 3 in the same order; this maps ours onto those.
LLM_JUDGE_NUMBER = {"imperative_subject": 1, "explains_why": 2, "standalone_body": 3}
PASS_THRESHOLD = 0.5      # probability of "yes" at or above this counts as PASS


# Typed replies. The SDK fills a SystemOneResponse subclass whose field names
# match the question ids, so a typo in a key fails at validation instead of
# at a KeyError three lines later.
class RubricAnswers(SystemOneResponse):
    imperative_subject: NoulAnswer = Field(description="Probability of yes to: " + ASSERTIONS["imperative_subject"])
    explains_why: NoulAnswer = Field(description="Probability of yes to: " + ASSERTIONS["explains_why"])
    standalone_body: NoulAnswer = Field(description="Probability of yes to: " + ASSERTIONS["standalone_body"])


class PairAnswer(SystemOneResponse):
    better: ChoiceAnswer = Field(description="A, B or tie, with a probability for each and a confidence.")


def judge_rubric(client: TypeSafeClient, commit_message: str) -> dict[str, float]:
    """One request, three questions, three probabilities."""
    questions = {name: Noul(instructions=text) for name, text in ASSERTIONS.items()}
    # >>> LIVE CALL: one HTTP request to TypeSafe's Jev model. It answers the
    #     three yes/no questions with probabilities; no text is generated.
    result = client.system_one({"commit_message": commit_message}, questions, response_model=RubricAnswers)
    probabilities = {name: getattr(result, name).noul for name in ASSERTIONS}
    log.info("  fast judge: %s", {name: round(p, 2) for name, p in probabilities.items()})
    return probabilities


def judge_pair(client: TypeSafeClient, first: str, second: str, house_style: str) -> tuple[str, float]:
    """Which of two messages follows the house style better? Returns the
    winner ("A", "B" or "tie") and the model's confidence in that pick."""
    # >>> LIVE CALL: one HTTP request to Jev with both responses in the state.
    result = client.system_one(
        {"house_style": house_style, "response_a": first, "response_b": second},
        {"better": Choice(
            instructions="Which response follows the house style more closely? "
                         "Judge against the style only; ignore length and polish.",
            criteria={"A": "response_a follows the style better",
                      "B": "response_b follows the style better",
                      "tie": "they follow it equally well or equally badly"},
        )},
        response_model=PairAnswer,
    )
    answer = result.better
    log.info("  pairwise: %s (confidence %.2f, probabilities %s)", answer.choice, answer.confidence,
             {k: round(v, 2) for k, v in answer.probabilities.items()})
    return answer.choice, answer.confidence


def sanity_check(client: TypeSafeClient) -> None:
    """Known negatives must score low on every assertion."""
    section("fast judge sanity check")
    explain("Before trusting any judge, feed it outputs that must fail: an empty reply and an 'I don't know'. "
            "Every probability has to come back below 0.5. A judge that passes an empty string would pass "
            "anything, and every number after this point would be meaningless.")
    log.info("sanity-checking the fast judge on two known-bad outputs")
    for bad in ["", "I don't know how to write commit messages, sorry."]:
        probabilities = judge_rubric(client, bad)
        if any(p >= PASS_THRESHOLD for p in probabilities.values()):
            sys.exit(f"fast judge passed a known-bad output {bad!r}: {probabilities}. Rephrase the questions.")
    note("both known negatives fail every assertion")


def main() -> None:
    configure_logging("07b_fast_judge")
    show_skill()
    load_dotenv()      # picks up TYPESAFE_API_KEY from .env if it is not already set
    # This file grades the outputs 06 saved. If they are not there yet, 06
    # runs first; after that its rows are reused.
    runs_path = results_from("06_ab_comparison.py", "06_ab_runs.jsonl")
    runs = [r for r in load_jsonl(runs_path) if not r["error"]]
    log.info("loaded %d saved outputs from %s", len(runs), runs_path.name)

    # The LLM judge's verdicts, if 07 has run, keyed the same way as ours.
    llm_verdicts = {}
    llm_path = RESULTS_DIR / "07_judge.jsonl"
    if llm_path.exists():
        for row in load_jsonl(llm_path):
            if row["kind"] == "rubric":
                llm_verdicts[(row["case"], row["rep"], row["arm"])] = {int(k): v for k, v in row["verdicts"].items()}
        log.info("loaded %d LLM-judge verdicts from %s for comparison", len(llm_verdicts), llm_path.name)

    explain("07 asked a large language model to read each output and write a verdict. This file asks the same "
            "three questions to Jev, a model that does not generate text at all: it returns the probability "
            "that the answer is yes, in about a tenth of a second. Same rubric, different instrument. We will "
            "compare the two judges at the end.")
    client = TypeSafeClient()
    sanity_check(client)

    # --- rubric: probabilities per assertion, blind to arm ---------------------
    rows = []
    passes = defaultdict(lambda: defaultdict(int))
    count = defaultdict(int)
    agreements = defaultdict(list)       # agreements[assertion] -> [True/False per output]
    section("rubric grading with probabilities, blind to arm")
    explain(f"Now every one of the {len(runs)} saved outputs gets the three questions. The judge is not told "
            f"which arm produced the text. A probability at or above {PASS_THRESHOLD} counts as PASS; the "
            "number itself is kept, because 0.95 and 0.55 are not the same answer even if both round to yes.")
    for run in runs:
        log.info("fast judge on %s rep %d (%s)", run["case"], run["rep"], run["arm"])
        probabilities = judge_rubric(client, run["final_text"])
        verdicts = {name: p >= PASS_THRESHOLD for name, p in probabilities.items()}
        rows.append({"kind": "rubric", "case": run["case"], "rep": run["rep"], "arm": run["arm"],
                     "probabilities": probabilities, "verdicts": verdicts})
        count[run["arm"]] += 1
        for name, passed in verdicts.items():
            passes[run["arm"]][name] += passed
        llm = llm_verdicts.get((run["case"], run["rep"], run["arm"]))
        if llm:
            for name, number in LLM_JUDGE_NUMBER.items():
                agreements[name].append(llm[number] == verdicts[name])

    section("rubric results")
    explain("The last column is the calibration: on what share of outputs did this judge and the LLM judge in "
            "07 give the same verdict? Two judges from different model families agreeing is much stronger "
            "evidence than either alone. Where they disagree, one of them is wrong, and a human should read "
            "those outputs before trusting either number.", kind="reading")
    table("pass rate per assertion", ["assertion", "with skill", "without skill", "agrees with LLM judge"],
          [[text,
            passes["with_skill"][name] / count["with_skill"],
            passes["without_skill"][name] / count["without_skill"],
            sum(agreements[name]) / len(agreements[name]) if agreements[name] else None]
           for name, text in ASSERTIONS.items()])
    note("agreement below about 0.9 means the two judges read an assertion differently; look at those outputs")

    # --- pairwise, both orders, with confidence -------------------------------
    house_style = load_skill().body
    pairs = defaultdict(dict)
    for run in runs:
        pairs[(run["case"], run["rep"])][run["arm"]] = run["final_text"]

    section("pairwise comparison, both orders")
    explain("Pairwise: show the judge both messages for the same diff and ask which follows the house style "
            "better. Judges favour whichever response comes first, so every pair is judged twice with the order "
            "swapped. A verdict only counts when both orders name the same arm; naming the same letter twice "
            "is position bias and lands in its own column. Jev also reports how confident each pick was.",
            kind="reading")
    wins = {"with_skill": 0, "without_skill": 0, "tie": 0, "disagree": 0}
    pair_rows = []
    for (case, rep), texts in sorted(pairs.items()):
        if len(texts) < 2:
            continue
        log.info("pairwise %s rep %d, both orders", case, rep)
        first, conf_1 = judge_pair(client, texts["with_skill"], texts["without_skill"], house_style)
        second, conf_2 = judge_pair(client, texts["without_skill"], texts["with_skill"], house_style)
        verdict_1 = {"A": "with_skill", "B": "without_skill", "tie": "tie"}[first]
        verdict_2 = {"A": "without_skill", "B": "with_skill", "tie": "tie"}[second]
        agreed = verdict_1 if verdict_1 == verdict_2 else "disagree"
        wins[agreed] += 1
        rows.append({"kind": "pairwise", "case": case, "rep": rep, "order_1": verdict_1, "order_2": verdict_2,
                     "confidence": [conf_1, conf_2], "verdict": agreed})
        pair_rows.append([case, rep, verdict_1, verdict_2, f"{conf_1:.2f} / {conf_2:.2f}", agreed])

    section("pairwise results")
    table("winner per pair", ["case", "rep", "with-skill as A", "with-skill as B", "confidence", "agreed verdict"],
          pair_rows)
    total = sum(wins.values())
    headline(f"with-skill wins {wins['with_skill']}/{total}   baseline wins {wins['without_skill']}   "
             f"ties {wins['tie']}   position-dependent {wins['disagree']}", good=wins["disagree"] == 0)
    save_jsonl(RESULTS_DIR / "07b_fast_judge.jsonl", rows)


if __name__ == "__main__":
    main()
