"""
Eval type 5: marking the answer with code instead of with another AI.

The skill has loaded. Now, does the agent's answer actually follow the rules
the skill laid down? For any rule you can write as code, write it as code. A
pattern for the header, a length limit, a line that has to be at the bottom:
all of those are ordinary programming. Save the AI marker for the things code
genuinely cannot see, like whether the explanation makes sense.

Code marking is cheap, gives the same answer every time, and tells you exactly
which rule broke rather than handing you a vague score.

The checks themselves live in commit_message_checks.py, and that is the file
to read first. This one is about the routine around them:

  Prove the marker works before you trust a word it says. Feed it a message
  written by hand to be perfect, and it must pass. Feed it one written to be
  wrong, and it must fail. Skip this and the numbers further down might be
  measuring the marker rather than the skill, and you would have no way of
  telling which.

  Run the agent on each case with the skill installed.

  Report how each rule did separately, not one blended number. There is a
  world of difference between losing on "the subject line is too long" and
  losing on "the Refs line is missing", and a single score hides both.

Run:  python 05_deterministic_grading.py
Saves results/05_deterministic_runs.jsonl.
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

# One attempt per case, on purpose. This script is about proving the marker
# works. Repetition, and the cost that comes with it, belongs in 06 and 09.
REPS = 1

# A message written by hand to be perfect. Every rule must accept it. If the
# marker rejects this, the marker is broken and nothing else here means
# anything.
ORACLE_REPLY = """```text
docs(cli): document supported environment variables

The CLI reads its token and base URL from the environment, but the
README never said so. Listing both lets users configure the CLI
without reading the source.

Refs: ACME-0000
```"""

# A message that looks plausible at a glance and breaks several rules at once.
# No code block, a capital letter and a full stop in the subject, a scope
# nobody allows, no body, no Refs line. The marker must reject it. A marker
# that waves this through is too soft to catch anything.
NULL_REPLY = "Docs(readme): Documented the environment variables."


class GradedRun(BaseModel):
    """One line in results/05_deterministic_runs.jsonl."""

    case: str = Field(description="Name of the test case, such as cli-readme.")
    rep: int = Field(description="Which attempt at this case.")
    model: str = Field(description="Which model served this run.")
    skill_invoked: bool = Field(description="Did the agent open the skill?")
    passed: bool = Field(description="True only when every rule passed.")
    failed_checks: list[str] = Field(description="Names of the rules that failed. Empty when everything passed.")
    checks: dict[str, bool] = Field(description="Every rule that ran and whether it passed.")
    final_text: str = Field(description="What the agent wrote, kept so you can mark it again later against "
                                        "different rules without paying for another run.")
    error: str | None = Field(description="Set when the run broke for reasons unrelated to the skill. Those "
                                          "runs are not marked.")
    cost_usd: float = Field(description="What this run cost, in US dollars.")


def sanity_check_grader() -> None:
    """Prove the marker works before trusting anything it says.

    Two messages go in: one written by hand to be perfect, one written to be
    wrong. The first must pass and the second must fail. Anything else and the
    marker itself is the problem.

    Raises:
        SystemExit: The marker rejected the good message or accepted the bad
            one. Either way there is no point running the agent yet.
    """
    section("checking the marker itself")
    log.info("before marking anything real, feeding the marker one message known to be right and one known "
             "to be wrong")
    oracle = check_commit_message(ORACLE_REPLY, expected_type="docs", expected_scope="cli")
    null = check_commit_message(NULL_REPLY)
    log.info("  the good message scored: %s. The bad message scored: %s",
             {r.name: r.passed for r in oracle}, {r.name: r.passed for r in null})
    if not all_passed(oracle):
        sys.exit(f"The marker rejected a message we know is correct, failing on {failed_names(oracle)}. "
                 "The marker is wrong, not the skill. Fix it before going any further.")
    if all_passed(null):
        sys.exit("The marker accepted a message we know is wrong. It is too soft to catch anything. Fix it "
                 "before going any further.")
    note(f"The marker passed the good message and caught the bad one on {failed_names(null)}. We can trust it.")


def main() -> None:
    configure_logging("05_deterministic_grading")
    show_skill()
    sanity_check_grader()

    rows = []
    log.info("%d cases, %d attempt each, all with the skill installed", len(COMMIT_CASES), REPS)
    for case in COMMIT_CASES:
        for rep in range(REPS):
            section(f"case {case['id']} attempt {rep}  "
                    f"(the right answer is {case['type']}({case['scope']}))")
            # >>> THIS SPENDS MONEY. The real Claude Code program runs the case
            #     with the skill installed. Marking happens afterwards, on
            #     whatever it wrote.
            run = run_agent(commit_prompt(read_fixture(case["diff"])), skill_dir=SKILL_DIR)
            results = check_commit_message(run.final_text, case["type"], case["scope"])
            show_text("the agent's reply", run.final_text)
            log.info("  marked: %s", {r.name: r.passed for r in results})
            rows.append(GradedRun(case=case["id"], rep=rep, model=run.model, skill_invoked=run.skill_invoked,
                                  passed=all_passed(results), failed_checks=failed_names(results),
                                  checks={r.name: r.passed for r in results}, final_text=run.final_text,
                                  error=run.error, cost_usd=run.cost_usd))

    section("results")
    graded = [r for r in rows if not r.error]
    table("how each run did", ["case", "attempt", "skill loaded", "what it got wrong", "verdict"],
          [[r.case, r.rep, "yes" if r.skill_invoked else "no", ", ".join(r.failed_checks) or "-", r.passed]
           for r in graded])
    per_check = Counter()
    for row in graded:
        for name, passed in row.checks.items():
            per_check[name] += passed
    table("how each rule did", ["rule", "passed", "out of"],
          [[name, passes, len(graded)] for name, passes in sorted(per_check.items())])
    all_passed_runs = sum(r.passed for r in graded)
    headline(f"{all_passed_runs} of {len(graded)} runs got every single rule right",
             good=all_passed_runs == len(graded))

    save_jsonl(RESULTS_DIR / "05_deterministic_runs.jsonl", rows)


if __name__ == "__main__":
    main()
