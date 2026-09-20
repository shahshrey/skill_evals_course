"""
Chapter five: the skill turns up. Is the work any good?

04 proved the agent reaches for your skill. That closes one question and
opens a better one. A skill that loads reliably and then gets ignored is a
more embarrassing result than one that never loads at all.

So now you mark the answer. The rule is simple, and people break it all the
time. Anything you can check with code, check with code. A pattern for the
header. A length limit. A line that has to sit at the bottom. All of that is
ordinary programming. Save the AI marker for the things code cannot see,
like whether an explanation makes sense. There are fewer of those than you
assumed.

Code marking is free. It says the same thing every time. It names the rule
that broke instead of handing you a number and a shrug.

The checks live in commit_message_checks.py. Read that file first. This one
is about the routine built around them. The first step is the one worth
stealing.

  Prove the marker works before you believe a word it says. Feed it a message
  written by hand to be perfect. It must pass. Feed it one written to be
  wrong. It must fail. Skip that and every number below might be measuring
  your marker rather than your skill, and nothing in the output would tell
  you which. You will see this move again in 07. It matters more there,
  because that marker is a model and has opinions.

  Then run the agent on each case with the skill installed.

  Then report each rule separately rather than blending them. "The subject
  line is too long" and "the Refs line is missing" are different problems
  with different fixes. One averaged score hides both equally well.

What this cannot tell you is whether the skill deserves any credit. Perhaps
a plain agent with no skill writes commit messages just as good. That is
06_ab_comparison.py. It is the most expensive thing here.

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

# One attempt per case, on purpose. This chapter is about proving the marker
# works. Repetition, and the bill that comes with it, belongs to 06 and 09.
REPS = 1

# Written by hand to be perfect. Every rule has to accept it. If the marker
# turns this down, the marker is broken. Every number after it is noise.
ORACLE_REPLY = """```text
docs(cli): document supported environment variables

The CLI reads its token and base URL from the environment, but the
README never said so. Listing both lets users configure the CLI
without reading the source.

Refs: ACME-0000
```"""

# This one looks fine for about two seconds and breaks five rules. No code
# block. A capital letter and a full stop in the subject. A scope nobody
# allows. No body. No Refs line. The marker has to reject it. A marker that
# waves this through will wave anything through, and report excellent
# results for ever.
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
    final_text: str = Field(description="What the agent wrote. Kept so you can mark it again later against "
                                        "different rules without paying for another run.")
    error: str | None = Field(description="Set when the run broke for reasons unrelated to the skill. Those "
                                          "runs are not marked.")
    cost_usd: float = Field(description="What this run cost, in US dollars.")


def sanity_check_grader() -> None:
    """Prove the marker works before trusting a word it says.

    Two messages go in. One written by hand to be perfect, one written to be
    wrong. The first has to pass. The second has to fail. Anything else means
    the marker is the thing that needs fixing. It takes no time and no money.
    It is the step that stops you shipping a confident number that measured
    nothing.

    Raises:
        SystemExit: The marker turned down the good message, or let the bad
            one through. Either way there is no point paying for agent runs
            you cannot mark.
    """
    section("checking the marker itself")
    log.info("nothing real gets marked yet. First the marker meets one message known to be right and one known "
             "to be wrong. It has to tell them apart")
    oracle = check_commit_message(ORACLE_REPLY, expected_type="docs", expected_scope="cli")
    null = check_commit_message(NULL_REPLY)
    log.info("  what it made of the good one: %s. And of the bad one: %s",
             {r.name: r.passed for r in oracle}, {r.name: r.passed for r in null})
    if not all_passed(oracle):
        sys.exit(f"The marker turned down a message we know is correct. It failed on {failed_names(oracle)}. "
                 "The marker is wrong here, not the skill. Fix it before you spend anything.")
    if all_passed(null):
        sys.exit("The marker accepted a message we know is wrong. It is too soft to catch anything, and would "
                 "have reported a perfect score. Fix it before you spend anything.")
    note(f"The marker passed the good message and caught the bad one on {failed_names(null)}. It can be "
         "trusted with the real thing.")


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
            # >>> THIS SPENDS MONEY. The real Claude Code runs the case with
            #     the skill installed. The marking happens afterwards, for
            #     free, on whatever it wrote. That is why the text gets saved.
            run = run_agent(commit_prompt(read_fixture(case["diff"])), skill_dir=SKILL_DIR)
            results = check_commit_message(run.final_text, case["type"], case["scope"])
            show_text("the agent's reply", run.final_text)
            log.info("  the marker's verdict, rule by rule: %s", {r.name: r.passed for r in results})
            rows.append(GradedRun(case=case["id"], rep=rep, model=run.model, skill_invoked=run.skill_invoked,
                                  passed=all_passed(results), failed_checks=failed_names(results),
                                  checks={r.name: r.passed for r in results}, final_text=run.final_text,
                                  error=run.error, cost_usd=run.cost_usd))

    section("results")
    graded = [r for r in rows if not r.error]
    table("what happened on each run", ["case", "attempt", "skill loaded", "what it got wrong", "verdict"],
          [[r.case, r.rep, "yes" if r.skill_invoked else "no", ", ".join(r.failed_checks) or "-", r.passed]
           for r in graded])
    per_check = Counter()
    for row in graded:
        for name, passed in row.checks.items():
            per_check[name] += passed
    table("rule by rule: which ones your skill keeps losing", ["rule", "passed", "out of"],
          [[name, passes, len(graded)] for name, passes in sorted(per_check.items())])
    all_passed_runs = sum(r.passed for r in graded)
    headline(f"{all_passed_runs} of {len(graded)} runs got every rule right",
             good=all_passed_runs == len(graded))

    save_jsonl(RESULTS_DIR / "05_deterministic_runs.jsonl", rows)


if __name__ == "__main__":
    main()
