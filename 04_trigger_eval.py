"""
Chapter four: the first one that sends you a bill.

Everything so far has been you and a text file. 03 and 03b gave you two
educated guesses about whether your description would win the request. Both
were arithmetic standing in for a decision they never watched happen. Now
you stop guessing. This installs the skill in a fresh folder, starts the real
Claude Code, types a real request, and watches.

The thing under test is still that one line of description. When you ask
Claude Code for something, it does not read your instructions. It reads each
installed skill's name and one-line description, picks the one that looks
relevant, and only then opens what you wrote. Everything below the
description is a prize. The description has to win it alone.

So this is the test you re-run every time you touch that sentence. That is
why it is worth the money.

The method. Some requests that ought to load the skill, some that ought not
to, each run a few times, and a count of what happened.

Two mistakes almost everyone makes. Both are comfortable ones.

  Only testing the requests that should work. Write "use this for anything
  git related" and it will load for every commit message you ask for. It
  will also barge in on rebases, pull request descriptions and changelogs.
  You will never see it, because you only tested the cases you wanted to
  pass.

  Running each request once. The decision is not repeatable. Ask the same
  question twice and you can get two different answers. One run tells you
  almost nothing. Run each a few times and take a majority.

One subtler point, planted back in the shared kit. Whether the skill was
installed and whether the agent went and read it are two different
questions. skill_was_loaded() below counts both routes. Either way your
description did its job.

The two numbers at the end are the dials. Firing when it should not means
the description is greedy. Missing requests it should catch means it lacks
the words people type. They pull in opposite directions. That is what makes
writing a description harder than writing the skill.

This proves the skill turns up. It says nothing about whether the output is
any good. That is 05_deterministic_grading.py, where the marking starts.

Run:  python 04_trigger_eval.py
Saves results/04_trigger_runs.jsonl and results/04_trigger_summary.json
(10_regression_check.py reads the summary).
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from commit_message_checks import COMMIT_CASES, commit_prompt
from skill_eval_common import (
    RESULTS_DIR,
    SKILL_DIR,
    configure_logging,
    headline,
    log,
    note,
    read_fixture,
    run_agent,
    save_jsonl,
    section,
    show_skill,
    table,
)

REPS = 2                    # three is common. More attempts, less noise, larger bill
TRIGGER_THRESHOLD = 0.5     # counts as loaded when at least half the attempts load it

# None of the requests that should load the skill mentions it by name. Naming
# it would be cheating. Cheating here means shipping a description you never
# tested. The whole question is whether it gets picked on its own.
#
# The requests that should not load it sit close to the line on purpose. All
# are about git, so a greedy description swallows them whole. Each request
# carries a short id. Two prompts that open with the same four words look
# identical in a table.
POSITIVE_PROMPTS = [(case["id"], commit_prompt(read_fixture(case["diff"]))) for case in COMMIT_CASES]
NEGATIVE_PROMPTS = [
    ("neg-pr-description", "Write a pull request description for a branch that adds retry logic to the API client."),
    ("neg-git-rebase", "Explain what git rebase --onto does and when I would use it."),
    ("neg-changelog", "Add a changelog entry for version 2.3 saying we fixed the signup email bug."),
]


class TriggerRun(BaseModel):
    """One line in results/04_trigger_runs.jsonl: a single attempt at one request."""

    prompt_id: str = Field(description="Short name for the request, such as api-paging or neg-git-rebase.")
    should_trigger: bool = Field(description="Should this request have loaded the skill?")
    rep: int = Field(description="Which attempt this was. The decision is not repeatable, so we run each "
                                 "request more than once.")
    triggered: bool = Field(description="Did the agent actually open the skill this time?")
    model: str = Field(description="Which model served this attempt.")
    error: str | None = Field(description="Set when the attempt broke for reasons unrelated to the skill, such "
                                          "as a network failure. Those attempts are left out of the counting.")
    cost_usd: float = Field(description="What this attempt cost, in US dollars.")


def skill_was_loaded(run) -> bool:
    """Decide whether the agent got hold of the skill's instructions at all.

    There is more than one door. Loading the skill properly is the front one.
    But an agent that notices SKILL.md in the folder and reads the file has
    the same words in front of it. Counting that as a miss would score the
    mechanism rather than the outcome. Both count.

    Args:
        run: A finished AgentRun.

    Returns:
        True if the skill's instructions reached the agent, by either route.
    """
    if run.skill_invoked:
        return True
    return any(call.name == "Read" and "SKILL.md" in str(call.input.get("file_path", ""))
               for call in run.tool_calls)


def main() -> None:
    configure_logging("04_trigger_eval")
    show_skill()
    rows = []
    prompts = [(pid, p, True) for pid, p in POSITIVE_PROMPTS] + [(pid, p, False) for pid, p in NEGATIVE_PROMPTS]
    log.info("%d requests that should load the skill, %d that should not, %d attempts at each. That is %d "
             "runs of the real thing. Every one is billed.",
             len(POSITIVE_PROMPTS), len(NEGATIVE_PROMPTS), REPS, len(prompts) * REPS)

    for prompt_id, prompt, should_trigger in prompts:
        for rep in range(REPS):
            section(f"case {prompt_id} attempt {rep}  (should load the skill: {should_trigger})")
            note("the request: " + prompt.replace("\n", " ")[:120] + ("..." if len(prompt) > 120 else ""))
            # >>> THIS SPENDS MONEY. run_agent() starts the real Claude Code in
            #     a brand new folder with the skill installed. Four turns is
            #     plenty. You are watching for the moment the skill gets
            #     opened. Paying it to finish a commit message you will never
            #     read is paying for nothing.
            run = run_agent(prompt, skill_dir=SKILL_DIR, max_turns=4)
            rows.append(TriggerRun(prompt_id=prompt_id, should_trigger=should_trigger, rep=rep,
                                   triggered=skill_was_loaded(run), model=run.model, error=run.error,
                                   cost_usd=run.cost_usd))
            log.info("  the skill loaded: %s. It should have: %s. So: %s", rows[-1].triggered, should_trigger,
                     "ok" if rows[-1].triggered == should_trigger else "MISMATCH")

    # Now settle up. Each request gets one verdict. Did at least half its
    # attempts do the right thing? With two attempts, one is enough. That is
    # generous. Raise REPS and the majority gets harder to buy.
    section("results")
    summary = {"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0}
    result_rows = []
    for prompt_id, _, should_trigger in prompts:
        reps = [r for r in rows if r.prompt_id == prompt_id and not r.error]
        rate = sum(r.triggered for r in reps) / len(reps) if reps else 0.0
        triggered = rate >= TRIGGER_THRESHOLD
        if should_trigger:
            summary["true_positive" if triggered else "false_negative"] += 1
        else:
            summary["false_positive" if triggered else "true_negative"] += 1
        ok = triggered == should_trigger
        result_rows.append([prompt_id, "yes" if should_trigger else "no", rate, ok])
    table("how often each request loaded the skill",
          ["request", "should load it", "how often it did", "verdict"], result_rows)

    # Two ways of being wrong, pulling in opposite directions. Firing when it
    # should not means the description is greedy. Missing a request it should
    # catch means it lacks the words people use. Fix one carelessly and you
    # cause the other. That is the whole game.
    #
    # When nothing loaded the skill at all, the first number divides by zero.
    # It is reported as 0 rather than 1. A skill that never fires has not
    # earned a perfect score for never being wrong.
    log.info("counts: %s", {k: v for k, v in summary.items() if k.endswith("e")},
             extra={"file_only": True})
    tp, fp, fn = summary["true_positive"], summary["false_positive"], summary["false_negative"]
    summary["precision"] = tp / (tp + fp) if tp + fp else 0.0
    summary["recall"] = tp / (tp + fn) if tp + fn else 0.0
    summary["total_cost_usd"] = round(sum(r.cost_usd for r in rows), 4)
    headline(f"of the requests that loaded the skill, {summary['precision']:.0%} should have. "
             f"Of the requests that should have loaded it, {summary['recall']:.0%} did. "
             f"Cost ${summary['total_cost_usd']}",
             good=summary["precision"] == 1.0 and summary["recall"] == 1.0)
    note("The first number is called precision, the second recall. A low first number means the description is "
         "greedy. It keeps grabbing work that is not its own. A low second number means it is missing the words "
         "people type. You will spend more time on that one sentence than on the skill itself.")

    save_jsonl(RESULTS_DIR / "04_trigger_runs.jsonl", rows)
    (RESULTS_DIR / "04_trigger_summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
