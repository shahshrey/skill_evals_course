"""
Chapter seven and a half: the same three questions, answered before you blink.

07 sat a large model down with each answer and waited while it read the
thing and wrote out its reasoning. That works. You watched it work. It also
takes seconds an answer and costs real money. So a marker like that usually
gets pointed at a handful of cases once, then quietly retired.

Here is the same job given to a different kind of instrument. Jev, from
TypeSafe, writes nothing. You hand it some text and a yes-or-no question. It
hands back the chance that the answer is yes. A tenth of a second, a fraction
of a penny. All three questions across all sixteen answers finish before the
model in 07 has got through its first one.

Two things change when marking gets that cheap.

You stop rationing it. A checklist that costs nothing is no longer an
occasional spot check. It runs on every change you make, for ever, without
anyone deciding it is worth it.

And you get a number instead of a verdict. 0.95 and 0.55 both round to yes.
They are nowhere near the same answer. Keep the number. Put the line in your
own code. Move the line when the stakes move.

The catch has not changed since 05. Prove the marker works before you
believe a word of it. This chapter does that twice. Answers known to be bad
have to score low, same as always. Then every verdict gets held up against
what the big model said about the same answer. The last column of the
results table is the share where the two agreed. Two markers built on
different technology reaching the same conclusion is far better evidence
than either alone. Where they part company, one of them is wrong. The only
way to find out which is to read the answer yourself.

Needs TYPESAFE_API_KEY in your environment or in a .env file. Reads what 06
saved, plus 07's verdicts if you have them. Run 06 first. 07 is optional.
Skip it and the most interesting column here comes back empty.

Both markers have now told you whether the writing is any good. Neither
looked at what the agent did to produce it. 08_trajectory_eval.py is where
that turns out to matter.

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

# The same three things 07 asks about, reworded as yes-or-no questions. Each
# asks about one property and spells out what a yes looks like. Ask vaguely
# and you get a number back that looks just as precise as a good one and
# means much less.
ASSERTIONS = {
    "imperative_subject": "Is the subject line (the first line) written in the imperative mood, "
                          "like \"add\" or \"fix\", rather than past tense or a noun phrase?",
    "explains_why": "Does the body explain why the change was made, rather than only restating what changed?",
    "standalone_body": "Would the body make sense to someone reading only the git log later, "
                       "without the diff or the conversation in front of them?",
}
# 07 numbers its questions 1, 2 and 3 in this order. This lines ours up with
# those. It is the only reason the two markers can be compared question by
# question rather than as two vague overall impressions.
LLM_JUDGE_NUMBER = {"imperative_subject": 1, "explains_why": 2, "standalone_body": 3}
PASS_THRESHOLD = 0.5      # a chance of yes at or above this counts as a pass. Your line, your call


# The shapes the answers come back in. The SDK fills in a class whose field
# names match the question names. A typo in a name breaks at once and says
# why, rather than three lines later in a way that takes an afternoon.
class RubricAnswers(SystemOneResponse):
    imperative_subject: NoulAnswer = Field(description="Probability of yes to: " + ASSERTIONS["imperative_subject"])
    explains_why: NoulAnswer = Field(description="Probability of yes to: " + ASSERTIONS["explains_why"])
    standalone_body: NoulAnswer = Field(description="Probability of yes to: " + ASSERTIONS["standalone_body"])


class PairAnswer(SystemOneResponse):
    better: ChoiceAnswer = Field(description="A, B or tie, with a probability for each and a confidence.")


def judge_rubric(client: TypeSafeClient, commit_message: str) -> dict[str, float]:
    """Ask all three checklist questions about one message, in one go.

    Args:
        client: A connected TypeSafe client.
        commit_message: The message to mark.

    Returns:
        The chance of a yes for each question, from 0 to 1, keyed by question
        name. Raw numbers, not passes and fails. Rounding them off is the
        caller's business. Doing it here would throw away the one thing this
        marker gives you that 07 does not.

    Example:
        chances = judge_rubric(client, run["final_text"])
    """
    questions = {name: Noul(instructions=text) for name, text in ASSERTIONS.items()}
    # >>> THIS SPENDS MONEY, but barely. One request to TypeSafe's Jev model.
    #     It answers all three questions with a number each and writes no
    #     prose about any of them.
    result = client.system_one({"commit_message": commit_message}, questions, response_model=RubricAnswers)
    probabilities = {name: getattr(result, name).noul for name in ASSERTIONS}
    log.info("  back it comes. How likely each answer is a yes: %s",
             {name: round(p, 2) for name, p in probabilities.items()})
    return probabilities


def judge_pair(client: TypeSafeClient, first: str, second: str, house_style: str) -> tuple[str, float]:
    """Ask which of two messages follows the house rules better.

    Same comparison 07 ran. This one also comes back with how sure it was.
    The big model could never give you that number.

    Args:
        client: A connected TypeSafe client.
        first: The message shown as A.
        second: The message shown as B.
        house_style: The rules to judge against, lifted straight from the skill.

    Returns:
        The winner, "A", "B" or "tie", and how sure the model was about it.

    Example:
        winner, sure = judge_pair(client, with_skill, without_skill, style)
    """
    # >>> THIS SPENDS MONEY, but barely. One request to Jev with both messages
    #     inside it.
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
    log.info("  it picks %s, %.0f%% sure. The rest of its confidence: %s", answer.choice,
             answer.confidence * 100, {k: round(v, 2) for k, v in answer.probabilities.items()})
    return answer.choice, answer.confidence


def sanity_check(client: TypeSafeClient) -> None:
    """Prove the marker rejects rubbish before trusting anything it passes.

    Third time you have watched this happen. It is the same ritual every
    time. New instrument, same two bad answers. It has to turn both down
    before it touches anything real.

    Args:
        client: A connected TypeSafe client.

    Raises:
        SystemExit: Something obviously bad scored above the pass line. Reword
            the questions before spending anything on real marking.
    """
    section("checking the marker itself")
    explain("You have seen this step twice already, in 05 and again in 07. It does not get skipped because the "
            "marker is new and fast. Two answers that have to fail go in. An empty reply, and an 'I don't "
            "know'. Every number has to come back under 0.5. A marker that passes an empty string will pass "
            "anything. Every figure printed after it would be decoration.")
    log.info("nothing real gets marked yet. First the marker meets two answers that are plainly wrong. It has "
             "to say so")
    for bad in ["", "I don't know how to write commit messages, sorry."]:
        probabilities = judge_rubric(client, bad)
        if any(p >= PASS_THRESHOLD for p in probabilities.values()):
            sys.exit(f"The marker passed an answer we know is bad, {bad!r}, scoring {probabilities}. Reword the "
                     "questions before you go further.")
    note("The marker failed both bad answers on every question. It can be trusted with the real ones.")


def main() -> None:
    configure_logging("07b_fast_judge")
    show_skill()
    load_dotenv()      # picks up TYPESAFE_API_KEY from .env if it is not set already
    # Same source 07 reads from. 06 paid for these answers once. Nobody
    # downstream pays again. Missing file means 06 runs, and then everybody
    # shares that one too.
    runs_path = results_from("06_ab_comparison.py", "06_ab_runs.jsonl")
    runs = [r for r in load_jsonl(runs_path) if not r["error"]]
    log.info("%d answers came back from %s, the same ones 07 marked", len(runs), runs_path.name)

    # And here is what the big model made of them, if you ran 07. Keyed the
    # same way ours are. The two can be laid side by side, answer by answer,
    # rather than compared as two averages that happen to be near each other.
    llm_verdicts = {}
    llm_path = RESULTS_DIR / "07_judge.jsonl"
    if llm_path.exists():
        for row in load_jsonl(llm_path):
            if row["kind"] == "rubric":
                llm_verdicts[(row["case"], row["rep"], row["arm"])] = {int(k): v for k, v in row["verdicts"].items()}
        log.info("and %d verdicts the big model already reached in %s, waiting to be argued with",
                 len(llm_verdicts), llm_path.name)

    explain("07 sat a large model down with each answer and waited for it to write out its reasoning. This asks "
            "Jev the same three questions. Jev writes nothing. It hands back the chance that the answer is yes, "
            "in about a tenth of a second. Same questions, different instrument. At the end you find out how "
            "often the two agreed.")
    client = TypeSafeClient()
    sanity_check(client)

    # --- the checklist, as numbers, without saying which side is which -------
    rows = []
    passes = defaultdict(lambda: defaultdict(int))
    count = defaultdict(int)
    agreements = defaultdict(list)       # agreements[question] -> did the two markers match, per answer
    section("one answer at a time, against the checklist, as numbers")
    explain(f"All {len(runs)} saved answers now get the three questions. The marker is never told which side "
            f"wrote any of them. Anything at or above {PASS_THRESHOLD} counts as a pass. The number itself gets "
            "written down too. 0.95 and 0.55 both round to yes, and one of them is a shrug.")
    for run in runs:
        log.info("handing the fast marker %s attempt %d. It is the %s answer. The marker is never told that",
                 run["case"], run["rep"], run["arm"])
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

    section("what the checklist came back with")
    explain("The last column is the one to read first. On what share of answers did this marker and the big "
            "model from 07 reach the same verdict? Two markers built on different technology agreeing is much "
            "stronger evidence than either alone. Where they part company, one of them is wrong. The only way "
            "to find out which is to read those answers yourself. 07 has a story about that. It cost an "
            "afternoon.", kind="reading")
    table("how often each question passed, by side",
          ["question", "with skill", "without skill", "agrees with the big model"],
          [[text,
            passes["with_skill"][name] / count["with_skill"],
            passes["without_skill"][name] / count["without_skill"],
            sum(agreements[name]) / len(agreements[name]) if agreements[name] else None]
           for name, text in ASSERTIONS.items()])
    note("Agreement below about 0.9 means the two markers are reading a question differently. Neither will "
         "tell you which one has it wrong. Go and look at those answers.")

    # --- comparing the two answers, in both orders ---------------------------
    house_style = load_skill().body
    pairs = defaultdict(dict)
    for run in runs:
        pairs[(run["case"], run["rep"])][run["arm"]] = run["final_text"]

    section("the same two answers, side by side, twice")
    explain("Both messages written for the same changes go in front of the marker. It picks the one that "
            "follows the house rules better. Markers tend to favour whatever they read first, so every pair "
            "gets judged twice with the order swapped. A verdict only counts when both rounds name the same "
            "side. Naming the same letter twice means it was going by position. That lands in its own column, "
            "where it cannot quietly join the score. Jev also says how sure it was each time. 07 could not give "
            "you that column.", kind="reading")
    wins = {"with_skill": 0, "without_skill": 0, "tie": 0, "disagree": 0}
    pair_rows = []
    for (case, rep), texts in sorted(pairs.items()):
        if len(texts) < 2:
            continue
        log.info("%s attempt %d goes in front of the marker twice. The sides are swapped the second time",
                 case, rep)
        first, conf_1 = judge_pair(client, texts["with_skill"], texts["without_skill"], house_style)
        second, conf_2 = judge_pair(client, texts["without_skill"], texts["with_skill"], house_style)
        verdict_1 = {"A": "with_skill", "B": "without_skill", "tie": "tie"}[first]
        verdict_2 = {"A": "without_skill", "B": "with_skill", "tie": "tie"}[second]
        agreed = verdict_1 if verdict_1 == verdict_2 else "disagree"
        wins[agreed] += 1
        rows.append({"kind": "pairwise", "case": case, "rep": rep, "order_1": verdict_1, "order_2": verdict_2,
                     "confidence": [conf_1, conf_2], "verdict": agreed})
        pair_rows.append([case, rep, verdict_1, verdict_2, f"{conf_1:.2f} / {conf_2:.2f}", agreed])

    section("who won, and whether the marker meant it")
    table("each pair, judged both ways round",
          ["case", "attempt", "with-skill shown first", "with-skill shown second", "how sure", "verdict"],
          pair_rows)
    total = sum(wins.values())
    headline(f"the skill won {wins['with_skill']} of {total} comparisons, the plain agent won "
             f"{wins['without_skill']}, {wins['tie']} were ties, and in {wins['disagree']} the marker "
             f"contradicted itself", good=wins["disagree"] == 0)
    note("Two markers have now read every answer and told you whether the writing is any good. Neither watched "
         "the agent produce it. 08_trajectory_eval.py opens up what happened during those runs. A good answer "
         "arrived at badly is its own kind of problem.")
    save_jsonl(RESULTS_DIR / "07b_fast_judge.jsonl", rows)


if __name__ == "__main__":
    main()
