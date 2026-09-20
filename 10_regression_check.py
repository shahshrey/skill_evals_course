"""
Chapter ten: the day your numbers quietly got worse and nobody noticed.

09 told you whether today's result was real. It said nothing about tomorrow.
Skills go off. A description that triggered reliably in March stops
triggering in June, because the software underneath changed how it picks
skills. A rule you tightened in the body breaks a case that used to sail
through. Nobody spots either one. Nobody goes back and runs the tests a
second time.

This is what makes going back cheap enough to bother with. It takes the
numbers from the last run you were happy with, holds today's up against
them, and makes a scene when something has fallen.

The useful part is that it can tell two situations apart. No single pass
rate ever could.

You edited the skill and a number dropped. That is the ordinary price of
changing something. You get a warning. Whether the trade was worth it stays
your call.

You touched nothing and a number dropped anyway. Then something underneath
you moved. The model, or the software running it. You found out from a test
rather than from a colleague. That is an error, and it stops the build.

It tells the two apart by fingerprinting the skill folder. Same fingerprint,
same skill. Any drop belongs to somebody else.

Running this costs nothing. It reads what 04, 05 and 06 already saved.
Refreshing those files is where all the money went.

Run:  python 10_regression_check.py --save-baseline    # after a run you trust
      python 10_regression_check.py                    # every run after that
It exits with an error code when something fell for a reason you did not
cause. An automated build can then stop the change going in while you are
asleep.

One question is left. Your skill works, and it holds up. What is it costing
you every time it runs? 11_efficiency_eval.py asks.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from skill_eval_common import (
    RESULTS_DIR,
    SKILL_DIR,
    configure_logging,
    headline,
    load_jsonl,
    log,
    note,
    results_from,
    section,
    show_skill,
    table,
)

BASELINE_PATH = RESULTS_DIR / "baseline.json"
# Anything falling further than this counts as a real drop. Anything smaller
# is the ordinary wobble 09 spent a whole chapter on. Set it against how many
# runs you do. With 8 pairs in 06, one unlucky run shifts the result by 0.125
# on its own. A limit of 0.10 would fire on nothing at all. Tighten it as you
# buy more runs, and not before.
TOLERANCE = 0.25


def skill_hash() -> str:
    """Boil the whole skill folder down to a short fingerprint.

    Every file in the folder goes in, and so does its name. Change a single
    character anywhere and you get a different fingerprint. That is the only
    thing standing between "you broke it" and "it broke".

    Returns:
        Twelve characters that stand for the current contents of the skill.

    Example:
        skill_hash()  # "3f9c1a0b7e42"
    """
    digest = hashlib.sha256()
    for path in sorted(SKILL_DIR.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(SKILL_DIR).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def pass_rate(path: Path, arm: str | None = None) -> float | None:
    """Work out what share of saved runs passed.

    Args:
        path: A results file that one of the earlier scripts saved.
        arm: Count only the runs with the skill ("with_skill") or only those
            without it ("without_skill"). Leave it out to count everything.

    Returns:
        A number from 0 to 1, or nothing at all when the file holds no runs
        worth counting. Runs that broke for unrelated reasons are ignored.
    """
    rows = [r for r in load_jsonl(path) if not r["error"] and (arm is None or r["arm"] == arm)]
    return sum(r["passed"] for r in rows) / len(rows) if rows else None


def current_metrics() -> dict[str, float | None]:
    """Pull today's numbers out of the files the earlier chapters saved.

    Four things get watched, one from each chapter that produced a number
    worth watching. How often the skill loaded when it should have, and how
    often it barged in when it should not, both from 04 (trigger_precision
    and trigger_recall). How often the answers passed every rule, from 05
    (deterministic_pass_rate). And how much difference the skill made, from
    06 (ab_lift).

    A missing results file gets made by running its script first. That is
    the one way this chapter can cost you money.

    Returns:
        The four numbers, keyed by name. A number is missing when there was
        nothing to work it out from.
    """
    trigger = json.loads(results_from("04_trigger_eval.py", "04_trigger_summary.json").read_text())
    ab_path = results_from("06_ab_comparison.py", "06_ab_runs.jsonl")
    with_skill = pass_rate(ab_path, "with_skill")
    without_skill = pass_rate(ab_path, "without_skill")
    return {
        "trigger_precision": trigger.get("precision"),
        "trigger_recall": trigger.get("recall"),
        "deterministic_pass_rate": pass_rate(
            results_from("05_deterministic_grading.py", "05_deterministic_runs.jsonl")),
        "ab_lift": None if None in (with_skill, without_skill) else with_skill - without_skill,
    }


def main() -> int:
    configure_logging("10_regression_check")
    show_skill()
    # >>> THIS COSTS NOTHING. No agent runs, nothing touches the network. All
    #     that happens here is that what 04, 05 and 06 wrote down gets held up
    #     against what they wrote down last time.
    metrics = current_metrics()
    fingerprint = skill_hash()
    log.info("today's numbers, straight out of the results folder: %s", metrics)
    log.info("the skill folder right now fingerprints as %s", fingerprint)

    if "--save-baseline" in sys.argv:
        BASELINE_PATH.write_text(json.dumps({"skill_hash": fingerprint, "metrics": metrics}, indent=2))
        section("writing today down, to be held against you later")
        table("the numbers to beat from here on", ["what was measured", "value"],
              [[k, v] for k, v in metrics.items()])
        headline(f"saved. Every run from now on gets compared against these, for skill {fingerprint}", good=True)
        return 0

    if not BASELINE_PATH.exists():
        sys.exit("There is nothing to compare against yet. Get a run you are happy with, then come back and "
                 "run this with --save-baseline to record it.")
    baseline = json.loads(BASELINE_PATH.read_text())
    skill_changed = baseline["skill_hash"] != fingerprint
    log.info("here is what you were beating: %s. It was taken when the skill fingerprinted as %s",
             baseline["metrics"], baseline["skill_hash"])
    section("today, against the day you were happy")
    note(f"The skill {'CHANGED' if skill_changed else 'has not changed'} since those numbers were written down "
         f"({baseline['skill_hash']} -> {fingerprint}). Everything below hangs on that one fact. It decides "
         "whether a drop is your doing or somebody else's.")

    exit_code = 0
    rows = []
    for name, now in metrics.items():
        before = baseline["metrics"].get(name)
        if now is None or before is None:
            rows.append([name, before, now, "no data"])
            continue
        dropped = before - now > TOLERANCE
        log.info("%s was %.2f and is now %.2f. The line is a fall of more than %.2f. This one is: %s",
                 name, before, now, TOLERANCE, "DROPPED" if dropped else "ok")
        if not dropped:
            status = "ok"
        elif skill_changed:
            status = "WARN it fell, but you did edit the skill"
        else:
            status = "ERROR it fell and nobody touched the skill"
            exit_code = 1
        rows.append([name, before, now, status])
    table("every number, then and now", ["what was measured", "was", "now", "verdict"], rows)
    headline("nothing dropped that you did not cause yourself" if exit_code == 0 else
             "something dropped and nobody edited the skill. Something underneath you moved",
             good=exit_code == 0)
    note("That is the story more or less told. One thing left. Your skill works and it keeps working. But "
         "every request it wins costs more than one it loses. 11_efficiency_eval.py reads the same saved runs "
         "and puts a price on it.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
