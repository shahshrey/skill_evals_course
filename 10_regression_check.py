"""
Eval type 10: catching the day the numbers quietly get worse.

Skills go off. A description that reliably triggered in March stops triggering
after the software behind it changes how it picks skills. A rule you tightened
in the body breaks a case that used to pass. Nobody spots it, because nobody
goes back and runs the tests again.

This is what makes going back worth the trouble. It takes the numbers from the
last run you were happy with, compares today's against them, and complains
loudly when something has fallen.

The useful part is that it tells two very different situations apart.

You edited the skill and a number dropped. That is the normal cost of a
change. It gives you a warning and leaves it to you to decide whether the
trade was worth making.

You did not touch the skill and a number dropped anyway. Something underneath
you moved: the model, or the software running it. That is an error, because
nothing you did caused it and you would want to know.

It tells them apart by fingerprinting the skill folder. Same fingerprint means
you changed nothing.

Running this costs nothing. It only reads what 04, 05 and 06 already saved.
Refreshing those files is the expensive part.

Run:  python 10_regression_check.py --save-baseline    # after a run you trust
      python 10_regression_check.py                    # every run after that
It exits with an error code when something dropped for no reason you caused,
so an automated build can stop the change from going in.
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
# Anything that falls further than this counts as a real drop. Anything smaller
# is just the normal wobble between runs. Set it against how many runs you do:
# with 8 pairs in 06, one unlucky run moves the result by 0.125 on its own, so
# a limit of 0.10 would fire on pure chance. Tighten it as you add more runs.
TOLERANCE = 0.25


def skill_hash() -> str:
    """Boil the whole skill folder down to a short fingerprint.

    Every file in the folder, and its name, goes into the fingerprint, so
    editing a single character anywhere changes it.

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
    """Pull today's numbers out of the files the earlier scripts saved.

    Four things get watched. How often the skill loaded when it should have
    (trigger_precision and trigger_recall), how often the answers passed every
    rule (deterministic_pass_rate), and how much difference the skill made
    (ab_lift).

    Any results file that is missing gets produced by running its script first,
    which does cost money.

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
    # >>> THIS COSTS NOTHING. Nothing runs and nothing goes over the network.
    #     All this does is compare what 04, 05 and 06 already saved against the
    #     numbers stored last time.
    metrics = current_metrics()
    fingerprint = skill_hash()
    log.info("today's numbers, read from the results folder: %s", metrics)
    log.info("the skill folder currently fingerprints as %s", fingerprint)

    if "--save-baseline" in sys.argv:
        BASELINE_PATH.write_text(json.dumps({"skill_hash": fingerprint, "metrics": metrics}, indent=2))
        section("saving today's numbers to compare against later")
        table("these are the numbers to beat from now on", ["what was measured", "value"],
              [[k, v] for k, v in metrics.items()])
        headline(f"saved. Everything from here on gets compared against these, for skill {fingerprint}", good=True)
        return 0

    if not BASELINE_PATH.exists():
        sys.exit("There is nothing to compare against yet. Do a run you are happy with, then run this again "
                 "with --save-baseline to record it.")
    baseline = json.loads(BASELINE_PATH.read_text())
    skill_changed = baseline["skill_hash"] != fingerprint
    log.info("the numbers to beat: %s, taken when the skill fingerprinted as %s",
             baseline["metrics"], baseline["skill_hash"])
    section("today's numbers against the ones we saved")
    note(f"The skill {'CHANGED' if skill_changed else 'has not changed'} since those numbers were saved "
         f"({baseline['skill_hash']} -> {fingerprint}). That decides whether a drop is your doing or "
         "something else's.")

    exit_code = 0
    rows = []
    for name, now in metrics.items():
        before = baseline["metrics"].get(name)
        if now is None or before is None:
            rows.append([name, before, now, "no data"])
            continue
        dropped = before - now > TOLERANCE
        log.info("%s was %.2f, now %.2f. Anything worse than %.2f down counts as a real drop, so: %s",
                 name, before, now, TOLERANCE, "DROPPED" if dropped else "ok")
        if not dropped:
            status = "ok"
        elif skill_changed:
            status = "WARN it fell, but you did edit the skill"
        else:
            status = "ERROR it fell and nobody touched the skill"
            exit_code = 1
        rows.append([name, before, now, status])
    table("how each number compares", ["what was measured", "was", "now", "verdict"], rows)
    headline("nothing dropped that you did not cause yourself" if exit_code == 0 else
             "something dropped and nobody edited the skill, so something underneath us moved",
             good=exit_code == 0)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
