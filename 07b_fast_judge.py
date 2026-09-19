"""
Eval type 7, second version: the same marking, done in a fraction of a second.

07_llm_judge.py hands each answer to a big model and waits for it to read the
thing and write out a verdict. That works. It also takes seconds per answer and
costs real money, which is why most people run a marker like that on a handful
of cases once and call the job done.

This script asks the same three questions of a different kind of model. Jev,
from TypeSafe, does not write anything. You give it some text and a yes-or-no
question, and it hands back the chance that the answer is yes. A tenth of a
second, a fraction of a penny. Three questions across sixteen answers finish
before the big model has got through its first one.

Two things change once marking is that cheap.

You can mark everything, every time. A checklist that costs nothing to apply
stops being an occasional spot check and becomes something you run on every
change.

You get a number instead of a verdict. 0.95 and 0.55 both round to yes, but
they are nowhere near the same answer. Keep the number, decide in code where
the line sits, and move that line when the stakes change.

The catch is the same as for any marker: prove it works before you believe it.
This script does that twice over. Answers known to be bad have to score low.
And every verdict gets compared against what the big model said about the same
answer. Where two markers built on completely different technology disagree,
one of them is wrong and a person should go and look. Two independent markers
agreeing is far better evidence than either one on its own.

Needs TYPESAFE_API_KEY in your environment or in a .env file. Reads what
06_ab_comparison.py saved, and the verdicts from 07_llm_judge.py if they exist.
Run 06 first. 07 is optional, but without it there is nothing to compare
against.

Run:  python 07b_fast_judge.py
Saves results/07b_fast_judge.jsonl.
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

# The same three things 07 asks about, worded as yes-or-no questions. Each one
# asks about a single property and spells out what a yes means, because a vague
# question gets a vague number back.
ASSERTIONS = {
    "imperative_subject": "Is the subject line (the first line) written in the imperative mood, "
                          "like \"add\" or \"fix\", rather than past tense or a noun phrase?",
    "explains_why": "Does the body explain why the change was made, rather than only restating what changed?",
    "standalone_body": "Would the body make sense to someone reading only the git log later, "
                       "without the diff or the conversation in front of them?",
}
# 07 numbers its questions 1, 2 and 3 in this same order. This lines ours up
# with those so the two markers can be compared question by question.
LLM_JUDGE_NUMBER = {"imperative_subject": 1, "explains_why": 2, "standalone_body": 3}
PASS_THRESHOLD = 0.5      # a chance of yes at or above this counts as a pass


# The shapes the answers come back in. The SDK fills in a class whose field
# names match the question names, so a typo in a name fails immediately with a
# clear complaint rather than three lines later with a confusing one.
class RubricAnswers(SystemOneResponse):
    imperative_subject: NoulAnswer = Field(description="Probability of yes to: " + ASSERTIONS["imperative_subject"])
    explains_why: NoulAnswer = Field(description="Probability of yes to: " + ASSERTIONS["explains_why"])
    standalone_body: NoulAnswer = Field(description="Probability of yes to: " + ASSERTIONS["standalone_body"])


class PairAnswer(SystemOneResponse):
    better: ChoiceAnswer = Field(description="A, B or tie, with a probability for each and a confidence.")


def judge_rubric(client: TypeSafeClient, commit_message: str) -> dict[str, float]:
    """Ask all three checklist questions about one message at once.

    Args:
        client: A connected TypeSafe client.
        commit_message: The message to mark.

    Returns:
        The chance of a yes for each question, from 0 to 1, keyed by question
        name. The raw number, not a pass or fail. The caller decides where the
        line sits.

    Example:
        chances = judge_rubric(client, run["final_text"])
    """
    questions = {name: Noul(instructions=text) for name, text in ASSERTIONS.items()}
    # >>> THIS SPENDS MONEY, but barely. One request to TypeSafe's Jev model.
    #     It answers all three yes-or-no questions with a number each, and
    #     writes nothing.
    result = client.system_one({"commit_message": commit_message}, questions, response_model=RubricAnswers)
    probabilities = {name: getattr(result, name).noul for name in ASSERTIONS}
    log.info("  how likely each answer is a yes: %s", {name: round(p, 2) for name, p in probabilities.items()})
    return probabilities


def judge_pair(client: TypeSafeClient, first: str, second: str, house_style: str) -> tuple[str, float]:
    """Ask which of two messages follows the house rules better.

    Args:
        client: A connected TypeSafe client.
        first: The message shown as A.
        second: The message shown as B.
        house_style: The rules to judge against, taken from the skill itself.

    Returns:
        The winner, "A", "B" or "tie", and how sure the model was about it.

    Example:
        winner, sure = judge_pair(client, with_skill, without_skill, style)
    """
    # >>> THIS SPENDS MONEY, but barely. One request to Jev with both messages
    #     in it.
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
    log.info("  pairwise winner %s, %.0f%% sure. Full breakdown: %s", answer.choice, answer.confidence * 100,
             {k: round(v, 2) for k, v in answer.probabilities.items()})
    return answer.choice, answer.confidence


def sanity_check(client: TypeSafeClient) -> None:
    """Prove the marker rejects rubbish before trusting anything it passes.

    Args:
        client: A connected TypeSafe client.

    Raises:
        SystemExit: Something obviously bad scored above the pass line. Reword
            the questions before spending anything on real marking.
    """
    section("checking the marker itself")
    explain("Before trusting any marker, feed it answers that have to fail: an empty reply, and an 'I don't "
            "know'. Every number has to come back below 0.5. A marker that passes an empty string would pass "
            "anything, and every figure after this point would mean nothing.")
    log.info("before marking anything real, feeding the marker two answers that are obviously wrong")
    for bad in ["", "I don't know how to write commit messages, sorry."]:
        probabilities = judge_rubric(client, bad)
        if any(p >= PASS_THRESHOLD for p in probabilities.values()):
            sys.exit(f"The marker passed an answer we know is bad, {bad!r}, scoring {probabilities}. Reword the "
                     "questions before going any further.")
    note("The marker failed both bad answers on every question, so we can trust it.")


def main() -> None:
    configure_logging("07b_fast_judge")
    show_skill()
    load_dotenv()      # picks up TYPESAFE_API_KEY from .env if it is not set already
    # This script marks answers that 06 already produced. If they are not there
    # yet, 06 runs first and then its results get reused from here on.
    runs_path = results_from("06_ab_comparison.py", "06_ab_runs.jsonl")
    runs = [r for r in load_jsonl(runs_path) if not r["error"]]
    log.info("read %d saved answers from %s", len(runs), runs_path.name)

    # What the big model said, if 07 has been run. Keyed the same way as ours
    # so the two can be lined up answer by answer.
    llm_verdicts = {}
    llm_path = RESULTS_DIR / "07_judge.jsonl"
    if llm_path.exists():
        for row in load_jsonl(llm_path):
            if row["kind"] == "rubric":
                llm_verdicts[(row["case"], row["rep"], row["arm"])] = {int(k): v for k, v in row["verdicts"].items()}
        log.info("read %d verdicts from the big model in %s, to compare against", len(llm_verdicts), llm_path.name)

    explain("07 asked a large model to read each answer and write out a verdict. This script asks the same "
            "three questions of Jev, a model that writes nothing at all: it hands back the chance that the "
            "answer is yes, in about a tenth of a second. Same questions, completely different instrument. The "
            "two get compared at the end.")
    client = TypeSafeClient()
    sanity_check(client)

    # --- the checklist, as numbers, without saying which side is which -------
    rows = []
    passes = defaultdict(lambda: defaultdict(int))
    count = defaultdict(int)
    agreements = defaultdict(list)       # agreements[question] -> did the two markers match, per answer
    section("marking each answer against the checklist, as numbers")
    explain(f"Every one of the {len(runs)} saved answers now gets the three questions. The marker is never told "
            f"which side wrote the text. Anything at or above {PASS_THRESHOLD} counts as a pass, but the number "
            "itself gets kept, because 0.95 and 0.55 are not the same answer even though both round to yes.")
    for run in runs:
        log.info("fast judge on %s attempt %d (this one is the %s side)", run["case"], run["rep"], run["arm"])
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

    section("checklist results")
    explain("The last column is the part that matters. On what share of answers did this marker and the big "
            "model from 07 reach the same verdict? Two markers built on different technology agreeing is much "
            "stronger evidence than either one on its own. Where they disagree, one of them is wrong, and "
            "somebody should read those answers before believing either number.", kind="reading")
    table("how often each question passed",
          ["question", "with skill", "without skill", "agrees with the big model"],
          [[text,
            passes["with_skill"][name] / count["with_skill"],
            passes["without_skill"][name] / count["without_skill"],
            sum(agreements[name]) / len(agreements[name]) if agreements[name] else None]
           for name, text in ASSERTIONS.items()])
    note("Agreement below about 0.9 means the two markers are reading a question differently. Go and look at "
         "those answers.")

    # --- comparing the two answers, in both orders ---------------------------
    house_style = load_skill().body
    pairs = defaultdict(dict)
    for run in runs:
        pairs[(run["case"], run["rep"])][run["arm"]] = run["final_text"]

    section("comparing the two answers head to head, in both orders")
    explain("Show the marker both messages written for the same changes and ask which one follows the house "
            "rules better. Markers tend to favour whichever message they read first, so every pair gets judged "
            "twice with the order swapped. A verdict only counts when both rounds name the same side. Naming "
            "the same letter twice means it was going by position, and that lands in its own column. Jev also "
            "says how sure it was each time.", kind="reading")
    wins = {"with_skill": 0, "without_skill": 0, "tie": 0, "disagree": 0}
    pair_rows = []
    for (case, rep), texts in sorted(pairs.items()):
        if len(texts) < 2:
            continue
        log.info("pairwise %s attempt %d, judged both ways round", case, rep)
        first, conf_1 = judge_pair(client, texts["with_skill"], texts["without_skill"], house_style)
        second, conf_2 = judge_pair(client, texts["without_skill"], texts["with_skill"], house_style)
        verdict_1 = {"A": "with_skill", "B": "without_skill", "tie": "tie"}[first]
        verdict_2 = {"A": "without_skill", "B": "with_skill", "tie": "tie"}[second]
        agreed = verdict_1 if verdict_1 == verdict_2 else "disagree"
        wins[agreed] += 1
        rows.append({"kind": "pairwise", "case": case, "rep": rep, "order_1": verdict_1, "order_2": verdict_2,
                     "confidence": [conf_1, conf_2], "verdict": agreed})
        pair_rows.append([case, rep, verdict_1, verdict_2, f"{conf_1:.2f} / {conf_2:.2f}", agreed])

    section("head-to-head results")
    table("who won each comparison",
          ["case", "attempt", "with-skill shown first", "with-skill shown second", "how sure", "verdict"],
          pair_rows)
    total = sum(wins.values())
    headline(f"the skill won {wins['with_skill']} of {total} comparisons, the plain agent won "
             f"{wins['without_skill']}, {wins['tie']} were ties, and in {wins['disagree']} the marker "
             f"contradicted itself", good=wins["disagree"] == 0)
    save_jsonl(RESULTS_DIR / "07b_fast_judge.jsonl", rows)


if __name__ == "__main__":
    main()
