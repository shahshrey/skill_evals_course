"""
Eval type 6: the head-to-head test. Does the skill actually help?

This is the test people mean when they ask "does the skill work". Ask the same
question twice, once with the skill installed and once without, mark both
answers the same way, and look at the difference. Every serious benchmark of
this kind boils down to this one loop.

Three rules keep it honest:

  Change one thing only. Same model, same question, same tools, same empty
  starting folder. The only difference is whether the skill's files are
  sitting in the folder. Switching the skill off with a flag is not good
  enough, because the files would still be there for the agent to go and read.

  Compare like with like. Each case is run twice on each side, and the two
  sides of one attempt are treated as a pair. Comparing paired results is much
  less jumpy than comparing two separate averages, and 09_statistics.py relies
  on that pairing.

  Report the difference, never the headline number on its own. "The skill
  scores 100 percent" tells you nothing if the plain agent already scored 95.
  Published figures for the average software engineering skill sit at a few
  percentage points, and plenty land at zero.

Marking is done by the plain code checks in commit_message_checks.py, not by
another AI, so the money here goes on the agent runs and none of it goes on
marking. Read 09_statistics.py straight after this one. It takes these results
and tells you whether the difference is real or luck.

Run:  python 06_ab_comparison.py
Saves results/06_ab_runs.jsonl, which scripts 07, 09, 10 and 11 all read.
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

REPS = 2      # attempts per case on each side. 09_statistics.py explains why one is not enough


class ABRun(BaseModel):
    """One line in results/06_ab_runs.jsonl. Scripts 07, 09, 10 and 11 read these."""

    case: str = Field(description="Name of the test case. Together with the attempt number it identifies one pair.")
    rep: int = Field(description="Which attempt this was. The with-skill and without-skill runs of the same "
                                 "attempt form one pair.")
    arm: Literal["with_skill", "without_skill"] = Field(description="Which side of the comparison this run was.")
    passed: bool = Field(description="True only when every single check passed.")
    failed_checks: list[str] = Field(description="Names of the checks that failed. Empty when everything passed.")
    checks: dict[str, bool] = Field(description="Every check that ran and whether it passed.")
    skill_invoked: bool = Field(description="Did the agent open the skill? Always false on the without-skill side.")
    model: str = Field(description="Which model served this run, so whoever reads the file later knows what "
                                   "produced it.")
    final_text: str = Field(description="What the agent wrote. Scripts 07 and 07b mark this text.")
    input_tokens: int = Field(description="Text the model read fresh, charged at full price.")
    cache_read_tokens: int = Field(description="Text the model had read before and got back cheaply.")
    cache_write_tokens: int = Field(description="Text saved for reuse on later runs.")
    output_tokens: int = Field(description="Text the model wrote.")
    cost_usd: float = Field(description="What this run cost. Script 11 compares the two sides on this.")
    duration_ms: int = Field(description="How long the run took, in milliseconds.")
    num_turns: int = Field(
        description="How many times the agent spoke. Opening a skill adds turns, and turns are where the extra "
                    "cost of a skill comes from.")
    error: str | None = Field(description="Set when the run broke for reasons unrelated to the skill. Those "
                                          "runs are not marked.")


def graded_run(prompt: str, case: dict, rep: int, with_skill: bool) -> ABRun:
    """Run the agent once on one side of the comparison, then mark the answer.

    Args:
        prompt: The request to send.
        case: The test case, carrying the id and the right answer to check against.
        rep: Which attempt this is.
        with_skill: True to install the skill first, False for the plain agent.

    Returns:
        An ABRun holding the marks, the answer itself, and what it cost.
    """
    # >>> THIS SPENDS MONEY. The real Claude Code program runs once per side.
    #     Passing no skill folder is the without-skill side: same program, same
    #     question, no skill anywhere in the folder.
    run = run_agent(prompt, skill_dir=SKILL_DIR if with_skill else None)
    results = check_commit_message(run.final_text, case["type"], case["scope"])
    log.info("  marked the %s answer. Checks that failed: %s. Overall: %s",
             "with-skill" if with_skill else "baseline",
             failed_names(results) or "none, all checks passed", "PASS" if all_passed(results) else "FAIL",
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
    """Say in words what one head-to-head comparison showed.

    Printed right after both sides have run, while the two answers are still on
    screen, so the reader can check the verdict against the text.

    Args:
        with_skill: The run that had the skill installed.
        without_skill: The run that did not.
    """
    if with_skill.passed and not without_skill.passed:
        explain(f"With the skill, every check passed. Without it, the message broke "
                f"{len(without_skill.failed_checks)} of them: {', '.join(without_skill.failed_checks)}. None of "
                "those are things the model could work out on its own. The Refs line at the bottom, the fixed "
                "list of allowed scopes, the exact way the message has to be wrapped: somebody has to say. That "
                "gap is what the skill is buying you.", kind="meaning")
    elif with_skill.passed and without_skill.passed:
        explain("Both sides passed. On this case the skill bought nothing at all. If that happens on every "
                "case, the skill is teaching the model something it already knew, and you could delete it "
                "without anyone noticing.", kind="meaning")
    elif not with_skill.passed:
        explain(f"The run with the skill failed on: {', '.join(with_skill.failed_checks)}. Either the skill is "
                "vague about that rule or the agent read it and ignored it. The answer is saved, so you can go "
                "and look at which.", kind="meaning")


def main() -> None:
    configure_logging("06_ab_comparison")
    rows = []
    log.info("%d cases, %d attempts each, run on both sides. That is %d agent runs, and they cost real money.",
             len(COMMIT_CASES), REPS, len(COMMIT_CASES) * REPS * 2)
    show_skill()
    explain(f"This is the test people mean when they ask whether a skill works. Each of the "
            f"{len(COMMIT_CASES)} cases runs {REPS} times, and every run happens twice: once in a brand new "
            "empty folder with the skill installed, and once in an identical empty folder without it. Same "
            "question, same model, same tools. The only difference between the two is whether the skill's "
            "files are there. Both answers get marked by the same plain code checks, and the number that "
            "matters is the gap between them.")
    for case in COMMIT_CASES:
        prompt = commit_prompt(read_fixture(case["diff"]))
        section(f"case {case['id']}: the request")
        show_text(f"what we ask the agent (from fixtures/{case['diff']})", prompt)
        for rep in range(REPS):
            section(f"pair {case['id']} attempt {rep}")
            explain(f"First side: the skill is installed. For this set of changes the correct answer is "
                    f"{case['type']}({case['scope']}).")
            # Both sides run back to back, so if the service is having a slow
            # afternoon, it slows both of them equally and the comparison holds.
            with_skill = graded_run(prompt, case, rep, with_skill=True)
            explain("Second side: the same question, a fresh empty folder, no skill anywhere. The agent has to "
                    "guess the house style from whatever it already knows.")
            without_skill = graded_run(prompt, case, rep, with_skill=False)
            rows += [with_skill, without_skill]
            show_pair("with the skill", with_skill.final_text, "without the skill", without_skill.final_text)
            explain_pair(with_skill, without_skill)

    graded = [r for r in rows if not r.error]
    by_arm = {arm: [r for r in graded if r.arm == arm] for arm in ("with_skill", "without_skill")}
    rate = {arm: sum(r.passed for r in runs) / len(runs) for arm, runs in by_arm.items()}
    log.info("marked %d runs (%d broke and were skipped). Pass rates: %s", len(graded), len(rows) - len(graded),
             rate, extra={"file_only": True})

    section("results")
    explain("The number to read is the gap: the pass rate with the skill minus the pass rate without it. Never "
            "quote the with-skill number on its own. A hundred percent means nothing if the plain agent was "
            "already at ninety-five. The second table breaks it down by check, which tells you which rules the "
            "plain agent already gets right. Those are the parts of the skill you could throw away.",
            kind="reading")
    pairs = defaultdict(dict)
    for r in graded:
        pairs[(r.case, r.rep)][r.arm] = r
    table("each head-to-head comparison",
          ["case", "attempt", "with skill", "without skill", "what the plain agent got wrong"],
          [[case, rep, p["with_skill"].passed, p["without_skill"].passed,
            ", ".join(p["without_skill"].failed_checks) or "-"]
           for (case, rep), p in sorted(pairs.items()) if len(p) == 2])

    # Break the results down check by check. The ones the plain agent already
    # passes are the parts of the skill nobody needed.
    #
    # The list of check names comes from the first run. If a later run is
    # missing a check, that is because an earlier check failed and stopped the
    # rest from running (a message with no header cannot be checked for header
    # format), so a missing check counts as a failure.
    rule_rows = []
    for name in graded[0].checks:
        per_arm = {arm: sum(r.checks.get(name, False) for r in runs) / len(runs)
                   for arm, runs in by_arm.items()}
        rule_rows.append([name, per_arm["with_skill"], per_arm["without_skill"]])
    table("how often each check passed", ["check", "with skill", "without skill"], rule_rows)

    lift = rate["with_skill"] - rate["without_skill"]
    headline(f"with the skill {rate['with_skill']:.0%} of answers passed, without it {rate['without_skill']:.0%}. "
             f"The skill changed the pass rate by {lift:+.0%}", good=lift > 0)
    note("Run 09_statistics.py next. It says whether that difference is real or whether we just got lucky.")

    save_jsonl(RESULTS_DIR / "06_ab_runs.jsonl", rows)


if __name__ == "__main__":
    main()
