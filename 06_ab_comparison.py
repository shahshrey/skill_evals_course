"""
Chapter six: the one that can tell you your skill was never needed.

05 told you how many rules the agent got right with your skill installed. It
could not tell you the only thing that matters. Did it need your skill to do
that? Maybe a plain agent writes the same message. Maybe the model already
knew. You cannot tell, because you never asked with the skill taken away.

So ask. The same request, twice. Once with the skill installed. Once in an
identical empty folder with no skill anywhere. Mark both the same way. Read
the gap. Every serious benchmark of this kind is this loop wearing a longer
paper.

Three rules keep it honest. All three are easy to break by accident.

  Change one thing. Same model, same request, same tools, same empty starting
  folder. The only difference is whether the skill's files are present.
  Switching the skill off with a flag does not count. The files are still
  there, and the agent can read a file.

  Compare like with like. Each case runs twice on each side. The two sides of
  one attempt stay together as a pair. Paired results are far steadier than
  two separate averages. 09_statistics.py leans on that pairing hard. Break
  it here and you quietly invalidate that chapter too.

  Report the gap, never the headline on its own. "The skill scores 100
  percent" means nothing if the plain agent was already at 95. Published
  figures for the average software engineering skill sit at a few percentage
  points. A good number land on zero. Be ready for that. A skill that changes
  nothing is a real result. Finding out costs less than maintaining it for a
  year.

Marking is done by the free code checks in commit_message_checks.py. Every
penny here goes on agent runs and none on marking.

This is also the source everything downstream reads from. The answers it
saves get marked again by a model in 07 and 07b, walked through step by step
in 08, tested in 09, compared against last month in 10 and priced in 11. You
pay for these runs once. Five chapters live off them.

07_llm_judge.py is next. It goes after the rules code cannot check. 09 asks
whether this gap was real or whether you got lucky with eight runs. It will
not be gentle.

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

REPS = 2      # attempts per case on each side. 09_statistics.py explains, at length, why one is not enough


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
    model: str = Field(description="Which model served this run. Whoever reads the file later knows what "
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

    The answer text, the token counts, the cost and the timings all come back
    on one object, recorded as they happened. Four later scripts read this.
    None of them pay for a run of their own.

    Args:
        prompt: The request to send.
        case: The test case, carrying the id and the right answer to check against.
        rep: Which attempt this is.
        with_skill: True to install the skill first, False for the plain agent.

    Returns:
        An ABRun holding the marks, the answer itself, and what it cost.
    """
    # >>> THIS SPENDS MONEY. The real Claude Code runs once per side. Handing
    #     it no skill folder is the whole of the without-skill side. Same
    #     program, same question, nothing in the folder to find.
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

    Printed the moment both sides have run, while the two answers are still
    on screen. You can check the verdict against the text, rather than take
    it on faith and find out three chapters later.

    Args:
        with_skill: The run that had the skill installed.
        without_skill: The run that did not.
    """
    if with_skill.passed and not without_skill.passed:
        explain(f"With the skill, every check passed. Without it, the message broke "
                f"{len(without_skill.failed_checks)} of them: {', '.join(without_skill.failed_checks)}. None of "
                "those is something the model could work out unaided. The Refs line at the bottom, the fixed "
                "list of allowed scopes, the exact wrapping. Somebody has to say so. That gap is what you are "
                "paying the skill for.", kind="meaning")
    elif with_skill.passed and without_skill.passed:
        explain("Both sides passed. On this case your skill bought you nothing. If that holds across every "
                "case, the skill is teaching the model something it already knew. You could delete it "
                "tomorrow and nobody would notice.", kind="meaning")
    elif not with_skill.passed:
        explain(f"The run with the skill failed on: {', '.join(with_skill.failed_checks)}. Either the skill is "
                "vague about that rule, or the agent read it and ignored it. Those need different fixes. The "
                "answer is saved. Read it before you start rewriting.", kind="meaning")


def main() -> None:
    configure_logging("06_ab_comparison")
    rows = []
    log.info("%d cases, %d attempts each, both sides every time. That is %d runs of the real thing. This is "
             "the expensive chapter.",
             len(COMMIT_CASES), REPS, len(COMMIT_CASES) * REPS * 2)
    show_skill()
    explain(f"This is the test people mean when they ask whether a skill works. Each of the "
            f"{len(COMMIT_CASES)} cases runs {REPS} times. Every run happens twice. Once in a brand new empty "
            "folder with the skill installed. Once in an identical empty folder without it. Same question, "
            "same model, same tools. The only difference is whether the skill's files are there. Both answers "
            "get marked by the same plain code checks. The number that matters is the gap between them, not "
            "either one on its own.")
    for case in COMMIT_CASES:
        prompt = commit_prompt(read_fixture(case["diff"]))
        section(f"case {case['id']}: the request")
        show_text(f"what we ask the agent (from fixtures/{case['diff']})", prompt)
        for rep in range(REPS):
            section(f"pair {case['id']} attempt {rep}")
            explain(f"First side. The skill is installed. For this set of changes the correct answer is "
                    f"{case['type']}({case['scope']}).")
            # The two sides run back to back on purpose. If the service is
            # having a slow afternoon, it slows both. The pair still compares.
            # Run them hours apart and you are measuring the weather.
            with_skill = graded_run(prompt, case, rep, with_skill=True)
            explain("Second side. The same question, a fresh empty folder, no skill anywhere in it. The agent "
                    "has to guess your house style from whatever it already knows.")
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
    explain("The number to read is the gap. The pass rate with the skill, minus the pass rate without it. Never "
            "quote the with-skill number on its own. A hundred percent means nothing if the plain agent was "
            "already at ninety-five. The second table breaks it down check by check. It shows the rules the "
            "plain agent gets right unaided. Those rules are the parts of your skill nobody needed. Delete "
            "them and everything left is easier to follow.",
            kind="reading")
    pairs = defaultdict(dict)
    for r in graded:
        pairs[(r.case, r.rep)][r.arm] = r
    table("each head-to-head comparison",
          ["case", "attempt", "with skill", "without skill", "what the plain agent got wrong"],
          [[case, rep, p["with_skill"].passed, p["without_skill"].passed,
            ", ".join(p["without_skill"].failed_checks) or "-"]
           for (case, rep), p in sorted(pairs.items()) if len(p) == 2])

    # Broken down check by check. The ones the plain agent already passes are
    # the parts of your skill that were never earning their keep.
    #
    # The list of names comes from the first run. A later run missing a check
    # means an earlier check failed and stopped the rest from running. A
    # message with no header cannot be asked about header format. So a
    # missing check counts as a failure. That is the honest reading.
    rule_rows = []
    for name in graded[0].checks:
        per_arm = {arm: sum(r.checks.get(name, False) for r in runs) / len(runs)
                   for arm, runs in by_arm.items()}
        rule_rows.append([name, per_arm["with_skill"], per_arm["without_skill"]])
    table("how often each check passed", ["check", "with skill", "without skill"], rule_rows)

    lift = rate["with_skill"] - rate["without_skill"]
    headline(f"with the skill {rate['with_skill']:.0%} of answers passed, without it {rate['without_skill']:.0%}. "
             f"The skill changed the pass rate by {lift:+.0%}", good=lift > 0)
    note("Run 09_statistics.py next. It reads these same results and tells you whether that difference is real "
         "or whether you got lucky with a handful of runs. It costs nothing. It is the least flattering script "
         "here.")

    save_jsonl(RESULTS_DIR / "06_ab_runs.jsonl", rows)


if __name__ == "__main__":
    main()
