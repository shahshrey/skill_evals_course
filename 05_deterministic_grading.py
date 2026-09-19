"""
Eval type 5: deterministic grading.

Once the skill loads, does the agent's output follow the skill's rules? For
rules you can express as code (a regex for the header, a length limit, a
required trailer) you should grade with code. Try code first; fall back to
a model judge only for what code cannot see.

Code graders are cheap, reproducible, and they tell you exactly which rule
broke. The checks themselves live in commit_message_checks.py; read that
file first. This file is about the process around them:

  1. Prove the grader works before trusting it. A hand-written perfect
     message must pass, and a wrong one must fail. If either sanity check
     fails, the numbers below would be measuring the grader, not the skill.
  2. Run the agent with the skill on each case.
  3. Report pass rate per rule, not one blended score, so you can see
     whether the skill is losing on "subject_max_50" or on "refs_trailer".

Run:  python 05_deterministic_grading.py
Writes results/05_deterministic_runs.jsonl.
"""

from __future__ import annotations

import sys
from collections import Counter

from pydantic import BaseModel, Field

from commit_message_checks import COMMIT_CASES, all_passed, check_commit_message, commit_prompt, failed_names
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
    show_text,
    table,
)

# One rep per case here on purpose: this file is about proving the grader,
# and 06 and 09 are where repetition (and its cost) belongs.
REPS = 1

# Oracle: an answer written by hand that every rule must accept.
ORACLE_REPLY = """```text
docs(cli): document supported environment variables

The CLI reads its token and base URL from the environment, but the
README never said so. Listing both lets users configure the CLI
without reading the source.

Refs: ACME-0000
```"""

# Null: a plausible answer that breaks several rules (no fence, capitalised
# subject with a period, unknown scope, no body, no trailer). It must fail.
NULL_REPLY = "Docs(readme): Documented the environment variables."


class GradedRun(BaseModel):
    """One row of results/05_deterministic_runs.jsonl."""

    case: str = Field(description="Id of the case, e.g. cli-readme.")
    rep: int = Field(description="Which repetition of the case.")
    model: str = Field(description="The model that served the run.")
    skill_invoked: bool = Field(description="Whether the agent loaded the skill.")
    passed: bool = Field(description="True only when every rule passed.")
    failed_checks: list[str] = Field(description="Names of the rules that failed; empty when passed.")
    checks: dict[str, bool] = Field(description="Every rule that was checked and whether it passed.")
    final_text: str = Field(description="The agent's reply, kept so the row can be re-graded later.")
    error: str | None = Field(description="Infrastructure failure, if any; such rows are not graded.")
    cost_usd: float = Field(description="What the run cost.")


def sanity_check_grader() -> None:
    section("grader sanity check")
    log.info("sanity-checking the grader on a known-good and a known-bad reply")
    oracle = check_commit_message(ORACLE_REPLY, expected_type="docs", expected_scope="cli")
    null = check_commit_message(NULL_REPLY)
    log.info("  oracle: %s | null: %s", {r.name: r.passed for r in oracle}, {r.name: r.passed for r in null})
    if not all_passed(oracle):
        sys.exit(f"grader rejects the oracle answer: {failed_names(oracle)}. Fix the grader first.")
    if all_passed(null):
        sys.exit("grader accepts the null answer. It is too lenient; fix it first.")
    note(f"oracle passes every rule; null fails on {failed_names(null)}")


def main() -> None:
    configure_logging("05_deterministic_grading")
    show_skill()
    sanity_check_grader()

    rows = []
    log.info("%d cases x %d reps, all with the skill installed", len(COMMIT_CASES), REPS)
    for case in COMMIT_CASES:
        for rep in range(REPS):
            section(f"case {case['id']} rep {rep}  (expect {case['type']}({case['scope']}))")
            # >>> LIVE CALL: the real Claude Code CLI runs the case with the
            #     skill installed. Grading happens after, on run.final_text.
            run = run_agent(commit_prompt(read_fixture(case["diff"])), skill_dir=SKILL_DIR)
            results = check_commit_message(run.final_text, case["type"], case["scope"])
            show_text("the agent's reply", run.final_text)
            log.info("  graded: %s", {r.name: r.passed for r in results})
            rows.append(GradedRun(case=case["id"], rep=rep, model=run.model, skill_invoked=run.skill_invoked,
                                  passed=all_passed(results), failed_checks=failed_names(results),
                                  checks={r.name: r.passed for r in results}, final_text=run.final_text,
                                  error=run.error, cost_usd=run.cost_usd))

    section("results")
    graded = [r for r in rows if not r.error]
    table("per run", ["case", "rep", "skill invoked", "failed checks", "verdict"],
          [[r.case, r.rep, "yes" if r.skill_invoked else "no", ", ".join(r.failed_checks) or "-", r.passed]
           for r in graded])
    per_check = Counter()
    for row in graded:
        for name, passed in row.checks.items():
            per_check[name] += passed
    table("per rule", ["rule", "passed", "of"],
          [[name, passes, len(graded)] for name, passes in sorted(per_check.items())])
    all_passed_runs = sum(r.passed for r in graded)
    headline(f"all rules passed in {all_passed_runs}/{len(graded)} runs", good=all_passed_runs == len(graded))

    save_jsonl(RESULTS_DIR / "05_deterministic_runs.jsonl", rows)


if __name__ == "__main__":
    main()
