"""
Eval type 6: paired A/B comparison (skill lift).

This is the eval everyone means when they say "does the skill work". Run the
same prompt twice, once with the skill installed and once without, grade
both the same way, and report the difference. Every serious skill benchmark
reduces to this loop.

Three rules make it a fair test:

  1. Hold everything else constant: same model, same prompt, same tools,
     same fresh workspace. The only difference is whether .claude/skills/
     contains the skill. A "--no-skills" flag is not enough; the files have
     to be absent, or the agent can go and read them.
  2. Pair the runs. Each (case, rep) produces one with-skill result and one
     without-skill result. Paired differences are far less noisy than
     comparing two independent averages, and 09_statistics.py depends on the
     pairing.
  3. Report the delta, not the absolute. "With skill: 100%" means nothing if
     the baseline was already 95%. Published benchmarks put the average
     software engineering skill at a few points of lift, and some at zero.

Grading is the deterministic checker from commit_message_checks.py, so this
file spends its budget on agent runs and nothing on judging. Read
09_statistics.py right after this one: it turns these rows into an interval.

Run:  python 06_ab_comparison.py
Writes results/06_ab_runs.jsonl, which 07, 09, 10 and 11 read.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from commit_message_checks import COMMIT_CASES, all_passed, check_commit_message, commit_prompt, failed_names
from skill_eval_common import (
    RESULTS_DIR,
    SKILL_DIR,
    configure_logging,
    explain,
    headline,
    log,
    note,
    read_fixture,
    run_agent,
    save_jsonl,
    section,
    show_pair,
    show_skill,
    show_text,
    table,
)

REPS = 2      # paired reps per case; 09_statistics.py explains why 1 is not enough


class ABRun(BaseModel):
    """One row of results/06_ab_runs.jsonl. Files 07, 09, 10 and 11 read these."""

    case: str = Field(description="Id of the case. Together with rep it names the pair.")
    rep: int = Field(description="Which repetition; the with and without rows of one rep are a pair.")
    arm: Literal["with_skill", "without_skill"] = Field(description="Which side of the comparison this run was.")
    passed: bool = Field(description="True only when every deterministic rule passed.")
    failed_checks: list[str] = Field(description="Names of the rules that failed; empty when passed.")
    checks: dict[str, bool] = Field(description="Every rule that was checked and whether it passed.")
    skill_invoked: bool = Field(description="Whether the agent loaded the skill; always False in the without arm.")
    model: str = Field(description="The model that served the run, so a later reader knows what produced the row.")
    final_text: str = Field(description="The agent's reply; the judges in 07 and 07b grade this text.")
    input_tokens: int = Field(description="Uncached input tokens.")
    cache_read_tokens: int = Field(description="Input tokens served from the prompt cache.")
    cache_write_tokens: int = Field(description="Input tokens written to the cache.")
    output_tokens: int = Field(description="Tokens the model generated.")
    cost_usd: float = Field(description="What the run cost; 11 compares this per arm.")
    duration_ms: int = Field(description="Wall-clock time of the run.")
    num_turns: int = Field(
        description="Assistant turns; loading a skill adds turns, which is where its cost comes from.")
    error: str | None = Field(description="Infrastructure failure, if any; such rows are not graded.")


def graded_run(prompt: str, case: dict, rep: int, with_skill: bool) -> ABRun:
    # >>> LIVE CALL: the real Claude Code CLI runs once per arm. skill_dir=None
    #     is the without-skill arm: same CLI, same prompt, no skill folder.
    run = run_agent(prompt, skill_dir=SKILL_DIR if with_skill else None)
    results = check_commit_message(run.final_text, case["type"], case["scope"])
    log.info("  graded %s arm: %s -> %s", "with-skill" if with_skill else "baseline",
             failed_names(results) or "all checks passed", "PASS" if all_passed(results) else "FAIL",
             extra={"file_only": True})
    return ABRun(
        case=case["id"], rep=rep, arm="with_skill" if with_skill else "without_skill",
        passed=all_passed(results), failed_checks=failed_names(results),
        checks={r.name: r.passed for r in results}, skill_invoked=run.skill_invoked, model=run.model,
        final_text=run.final_text, input_tokens=run.input_tokens, cache_read_tokens=run.cache_read_tokens,
        cache_write_tokens=run.cache_write_tokens, output_tokens=run.output_tokens, cost_usd=run.cost_usd,
        duration_ms=run.duration_ms, num_turns=run.num_turns, error=run.error,
    )


def explain_pair(with_skill: ABRun, without_skill: ABRun) -> None:
    """Interpret one pair in words, right after both arms finished."""
    if with_skill.passed and not without_skill.passed:
        explain(f"With the skill every rule passed. Without it the message broke {len(without_skill.failed_checks)} "
                f"rules: {', '.join(without_skill.failed_checks)}. Those are things the model cannot know without "
                "being told: the Refs trailer, the fixed scope list, the text fence. That gap is the skill's value.",
                kind="meaning")
    elif with_skill.passed and without_skill.passed:
        explain("Both arms passed. On this case the skill bought nothing; if that happens on every case, the "
                "skill is teaching the model something it already knew.", kind="meaning")
    elif not with_skill.passed:
        explain(f"The with-skill arm failed on {', '.join(with_skill.failed_checks)}. Either the skill is unclear "
                "on that rule or the agent ignored it; the saved reply lets you check which.", kind="meaning")


def main() -> None:
    configure_logging("06_ab_comparison")
    rows = []
    log.info("%d cases x %d reps x 2 arms -> %d agent runs", len(COMMIT_CASES), REPS, len(COMMIT_CASES) * REPS * 2)
    show_skill()
    explain(f"This is the eval people mean by 'does the skill work'. Each of the {len(COMMIT_CASES)} cases runs "
            f"{REPS} times, and each run happens twice: once with the skill installed in a fresh temp folder, "
            "once in an identical folder without it. Same prompt, same model, same tools. The only difference "
            "between the two arms is whether .claude/skills/commit-message exists. Both are graded by the same "
            "code checks, and the number we care about is the difference.")
    for case in COMMIT_CASES:
        prompt = commit_prompt(read_fixture(case["diff"]))
        section(f"case {case['id']}: the prompt")
        show_text(f"prompt to the agent (fixtures/{case['diff']})", prompt)
        for rep in range(REPS):
            section(f"pair {case['id']} rep {rep}")
            explain(f"Arm 1 of the pair: the skill is installed. The right answer for this diff is "
                    f"{case['type']}({case['scope']}).")
            # Both arms back to back, so a slow afternoon at the API hits both equally.
            with_skill = graded_run(prompt, case, rep, with_skill=True)
            explain("Arm 2 of the pair: the same prompt in a fresh folder with no skill anywhere. The agent has "
                    "to guess the house style from general knowledge.")
            without_skill = graded_run(prompt, case, rep, with_skill=False)
            rows += [with_skill, without_skill]
            show_pair("with the skill", with_skill.final_text, "without the skill", without_skill.final_text)
            explain_pair(with_skill, without_skill)

    graded = [r for r in rows if not r.error]
    by_arm = {arm: [r for r in graded if r.arm == arm] for arm in ("with_skill", "without_skill")}
    rate = {arm: sum(r.passed for r in runs) / len(runs) for arm, runs in by_arm.items()}
    log.info("%d graded rows (%d errored); pass rates %s", len(graded), len(rows) - len(graded), rate,
             extra={"file_only": True})

    section("results")
    explain("Lift is the with-skill pass rate minus the without-skill pass rate. Report the lift, never the "
            "with-skill number alone: 100 percent means nothing if the baseline was already 95. The per-rule "
            "table shows which rules the baseline gets right on its own; those are the parts of the skill you "
            "could delete.", kind="reading")
    pairs = defaultdict(dict)
    for r in graded:
        pairs[(r.case, r.rep)][r.arm] = r
    table("per pair", ["case", "rep", "with skill", "without skill", "baseline failed on"],
          [[case, rep, p["with_skill"].passed, p["without_skill"].passed,
            ", ".join(p["without_skill"].failed_checks) or "-"]
           for (case, rep), p in sorted(pairs.items()) if len(p) == 2])

    # Per-rule view: which rules does the baseline already get right on its
    # own? Those are the parts of the skill you could delete. The rule names
    # come from the first row; a row missing a rule (header_format failed, so
    # the header rules were never checked) counts that rule as failed.
    rule_rows = []
    for name in graded[0].checks:
        per_arm = {arm: sum(r.checks.get(name, False) for r in runs) / len(runs)
                   for arm, runs in by_arm.items()}
        rule_rows.append([name, per_arm["with_skill"], per_arm["without_skill"]])
    table("pass rate per rule", ["rule", "with skill", "without skill"], rule_rows)

    lift = rate["with_skill"] - rate["without_skill"]
    headline(f"pass rate with skill {rate['with_skill']:.2f}   without {rate['without_skill']:.2f}   "
             f"lift {lift:+.2f}", good=lift > 0)
    note("run 09_statistics.py next to see whether that lift survives an interval")

    save_jsonl(RESULTS_DIR / "06_ab_runs.jsonl", rows)


if __name__ == "__main__":
    main()
