"""
Eval type 4: does the skill get picked up at all?

A skill that never loads is worth nothing, however good the instructions
inside it are. When you ask Claude Code something, it does not read every
skill you have installed. It reads each one's name and one-line description,
picks whichever looks relevant, and only then opens the full instructions. So
that one line is doing all the work.

This is the first test that spends money, and the one to re-run every single
time you reword the description.

The idea is simple. Write some requests that ought to make the skill load, and
some that ought not to. Run each of them a few times. Watch whether the skill
actually gets opened.

Two mistakes almost everyone makes here:

  Only testing the requests that should work. Write a description saying "use
  this for anything git related" and it will load for every commit message you
  ask for. It will also barge in when you ask about rebasing, about pull
  request descriptions, and about changelogs. You cannot see that problem
  without testing requests that should be left alone.

  Running each request once. The decision is not repeatable. Ask twice and you
  can get two different answers. Run each request a few times and count it as
  loaded when at least half the attempts load it.

The two numbers at the bottom are what you tune the description against. If
it fires when it should not, the description is too greedy. If it misses
requests it should catch, the description is missing the words real people
type.

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

REPS = 2                    # three is common. More attempts, less noise, more money
TRIGGER_THRESHOLD = 0.5     # counts as loaded when at least half the attempts load it

# The requests that should load the skill never mention it by name. That would
# be cheating: the point is to find out whether the description gets picked on
# its own merits.
#
# The requests that should not load it are deliberately close to the mark. They
# are all about git, so a sloppy description will swallow them. Each request
# carries a short id, because two requests that start with the same words are
# impossible to tell apart in a report otherwise.
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
    """Decide whether the agent got hold of the skill's instructions.

    There is more than one route in. Opening the skill properly is the normal
    one, but an agent that spots SKILL.md sitting in the folder and reads the
    file directly has the same instructions in front of it. Either way the
    description did its job, so both count.

    Args:
        run: A finished AgentRun.

    Returns:
        True if the skill's contents reached the agent.
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
    log.info("%d requests that should load the skill and %d that should not, %d attempts each. "
             "That is %d agent runs, and they cost real money.",
             len(POSITIVE_PROMPTS), len(NEGATIVE_PROMPTS), REPS, len(prompts) * REPS)

    for prompt_id, prompt, should_trigger in prompts:
        for rep in range(REPS):
            section(f"case {prompt_id} attempt {rep}  (should load the skill: {should_trigger})")
            note("the request: " + prompt.replace("\n", " ")[:120] + ("..." if len(prompt) > 120 else ""))
            # >>> THIS SPENDS MONEY. run_agent() starts the real Claude Code
            #     program in a brand new folder with the skill installed. Four
            #     turns is plenty: we only want to see whether the skill gets
            #     opened, not wait for a finished commit message.
            run = run_agent(prompt, skill_dir=SKILL_DIR, max_turns=4)
            rows.append(TriggerRun(prompt_id=prompt_id, should_trigger=should_trigger, rep=rep,
                                   triggered=skill_was_loaded(run), model=run.model, error=run.error,
                                   cost_usd=run.cost_usd))
            log.info("  the skill loaded: %s. It should have: %s. Verdict: %s", rows[-1].triggered, should_trigger,
                     "ok" if rows[-1].triggered == should_trigger else "MISMATCH")

    # Now settle each request. Did at least half its attempts do the right
    # thing? With two attempts that means one is enough. Raise REPS if you want
    # a stricter majority.
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

    # Two ways of being wrong, and they need fixing in opposite directions.
    # Firing when it should not means the description is too greedy. Missing a
    # request it should catch means the description lacks the words people use.
    #
    # When nothing loaded the skill at all, the first number is undefined. We
    # report it as 0 rather than 1, because a skill that never fires has not
    # earned a perfect score.
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
         "too greedy and grabs work that is not its own. A low second means it is missing the words people "
         "actually type.")

    save_jsonl(RESULTS_DIR / "04_trigger_runs.jsonl", rows)
    (RESULTS_DIR / "04_trigger_summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
