"""
Eval type 4: live trigger eval.

A skill that never loads cannot help anyone. In Claude Code the model sees
each installed skill's name and description and nothing else, so those two
fields are the whole triggering mechanism. This is the first live eval to
run and the one to re-run after every edit to the description.

The test is simple. Take prompts that should trigger the skill and prompts
that should not, run each one a few times through the real harness, and
watch whether the agent calls the Skill tool for our skill. Every live
trigger test has this same shape; the only choices are how you detect the
trigger and where you set the pass threshold.

Two things beginners get wrong here:

  1. Only testing positives. A description that says "use for anything git
     related" triggers on every positive and also hijacks every PR-description
     and rebase question. You need negatives to see that.
  2. Running each prompt once. Triggering is stochastic. Run each query a
     few times and call it triggered when at least half fire.

The confusion-matrix output (precision, recall) is what you tune the
description against. If precision is low, the description is too greedy; if
recall is low, it is missing the words users actually type.

Run:  python 04_trigger_eval.py
Writes results/04_trigger_runs.jsonl and results/04_trigger_summary.json
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

REPS = 2                    # three is common; more reps, less noise, more cost
TRIGGER_THRESHOLD = 0.5     # "triggered" when at least half the reps fired

# Positives never name the skill. Negatives are deliberately nearby: git
# topics that a greedy description would swallow. Each prompt gets an id so
# the report can name it; two prompts that start the same way would
# otherwise be indistinguishable.
POSITIVE_PROMPTS = [(case["id"], commit_prompt(read_fixture(case["diff"]))) for case in COMMIT_CASES]
NEGATIVE_PROMPTS = [
    ("neg-pr-description", "Write a pull request description for a branch that adds retry logic to the API client."),
    ("neg-git-rebase", "Explain what git rebase --onto does and when I would use it."),
    ("neg-changelog", "Add a changelog entry for version 2.3 saying we fixed the signup email bug."),
]


class TriggerRun(BaseModel):
    """One row of results/04_trigger_runs.jsonl."""

    prompt_id: str = Field(description="Short id of the prompt, e.g. api-paging or neg-git-rebase.")
    should_trigger: bool = Field(description="Whether the prompt ought to load the skill.")
    rep: int = Field(description="Which repetition of this prompt; triggering is stochastic.")
    triggered: bool = Field(description="Whether the agent loaded the skill in this run.")
    model: str = Field(description="The model that served the run.")
    error: str | None = Field(description="Infrastructure failure, if any; such rows are not counted.")
    cost_usd: float = Field(description="What the run cost.")


def skill_was_loaded(run) -> bool:
    """The agent can get at the skill's content by more than one path. Calling
    the Skill tool is the normal one, but reading SKILL.md directly also
    counts. Both mean the description did its job."""
    if run.skill_invoked:
        return True
    return any(call.name == "Read" and "SKILL.md" in str(call.input.get("file_path", ""))
               for call in run.tool_calls)


def main() -> None:
    configure_logging("04_trigger_eval")
    show_skill()
    rows = []
    prompts = [(pid, p, True) for pid, p in POSITIVE_PROMPTS] + [(pid, p, False) for pid, p in NEGATIVE_PROMPTS]
    log.info("%d positive and %d negative prompts, %d reps each -> %d agent runs",
             len(POSITIVE_PROMPTS), len(NEGATIVE_PROMPTS), REPS, len(prompts) * REPS)

    for prompt_id, prompt, should_trigger in prompts:
        for rep in range(REPS):
            section(f"case {prompt_id} rep {rep}  (should trigger: {should_trigger})")
            note("prompt: " + prompt.replace("\n", " ")[:120] + ("..." if len(prompt) > 120 else ""))
            # >>> LIVE CALL: run_agent() starts the real Claude Code CLI in a
            #     fresh workspace with the skill installed. Four turns is
            #     plenty to see the Skill call; we do not need the finished
            #     commit message here, only whether the skill loaded.
            run = run_agent(prompt, skill_dir=SKILL_DIR, max_turns=4)
            rows.append(TriggerRun(prompt_id=prompt_id, should_trigger=should_trigger, rep=rep,
                                   triggered=skill_was_loaded(run), model=run.model, error=run.error,
                                   cost_usd=run.cost_usd))
            log.info("  triggered=%s expected=%s -> %s", rows[-1].triggered, should_trigger,
                     "ok" if rows[-1].triggered == should_trigger else "MISMATCH")

    # Per prompt: did at least half the reps do the right thing? With REPS=2
    # that means one firing counts; raise REPS for a stricter majority.
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
    table("trigger rate per prompt", ["prompt", "should trigger", "rate", "verdict"], result_rows)

    # Precision: of the prompts that triggered, how many should have?
    # Recall: of the prompts that should trigger, how many did?
    # When nothing triggered at all, precision is undefined; report 0, not 1.
    log.info("confusion matrix: %s", {k: v for k, v in summary.items() if k.endswith("e")},
             extra={"file_only": True})
    tp, fp, fn = summary["true_positive"], summary["false_positive"], summary["false_negative"]
    summary["precision"] = tp / (tp + fp) if tp + fp else 0.0
    summary["recall"] = tp / (tp + fn) if tp + fn else 0.0
    summary["total_cost_usd"] = round(sum(r.cost_usd for r in rows), 4)
    headline(f"precision {summary['precision']:.2f}   recall {summary['recall']:.2f}   "
             f"cost ${summary['total_cost_usd']}", good=summary["precision"] == 1.0 and summary["recall"] == 1.0)
    note("precision: of the prompts that triggered, how many should have. "
         "recall: of the prompts that should trigger, how many did.")

    save_jsonl(RESULTS_DIR / "04_trigger_runs.jsonl", rows)
    (RESULTS_DIR / "04_trigger_summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
