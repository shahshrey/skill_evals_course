"""
Eval type 10: regression check.

Skills rot. The description that triggered fine in March stops triggering
after the harness updates its routing prompt; a rule you tightened in the
body quietly breaks a case that used to pass. Nobody notices because nobody
re-runs the evals. A regression check is what makes re-running them worth
doing: it compares today's numbers with a saved baseline and fails loudly
when they drop.

The interesting design question is telling two situations apart:

  - the skill file changed and a number dropped: that is expected churn.
    Warn, and let the author decide whether the trade was worth it.
  - the skill file did NOT change and a number dropped anyway: that is
    drift in the model or harness. Error, because nothing you wrote caused
    it and you want to know.

The skill's content hash is what distinguishes them. This file reads the
summaries the earlier evals saved, so it costs nothing to run; the expensive
part is re-running 04, 05 and 06 to refresh those summaries.

Run:  python 10_regression_check.py --save-baseline    # after a run you trust
      python 10_regression_check.py                    # on every later run
Exit code 1 on an unexplained regression, so CI can block the merge.
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
# A drop bigger than this is a regression; smaller is noise. Size it to your
# run counts: with 8 pairs in 06 one flaky run moves the lift by 0.125, so a
# tolerance of 0.10 would flag pure luck. Tighten it as you add reps.
TOLERANCE = 0.25


def skill_hash() -> str:
    """Fingerprint of every file in the skill folder, so any edit changes it."""
    digest = hashlib.sha256()
    for path in sorted(SKILL_DIR.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(SKILL_DIR).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def pass_rate(path: Path, arm: str | None = None) -> float | None:
    rows = [r for r in load_jsonl(path) if not r["error"] and (arm is None or r["arm"] == arm)]
    return sum(r["passed"] for r in rows) / len(rows) if rows else None


def current_metrics() -> dict[str, float | None]:
    """The handful of numbers worth watching, pulled from saved results.
    Any results file that is missing gets produced by its script first."""
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
    # >>> NO LIVE CALL: this file never runs the CLI or a model. It compares
    #     the summaries 04, 05 and 06 saved against a stored baseline.
    metrics = current_metrics()
    fingerprint = skill_hash()
    log.info("current metrics from results/: %s", metrics)
    log.info("skill fingerprint %s", fingerprint)

    if "--save-baseline" in sys.argv:
        BASELINE_PATH.write_text(json.dumps({"skill_hash": fingerprint, "metrics": metrics}, indent=2))
        section("baseline")
        table("saved as the new baseline", ["metric", "value"], [[k, v] for k, v in metrics.items()])
        headline(f"baseline saved for skill {fingerprint}", good=True)
        return 0

    if not BASELINE_PATH.exists():
        sys.exit("no baseline yet; run with --save-baseline after a run you trust")
    baseline = json.loads(BASELINE_PATH.read_text())
    skill_changed = baseline["skill_hash"] != fingerprint
    log.info("baseline metrics: %s (skill %s)", baseline["metrics"], baseline["skill_hash"])
    section("comparison against the baseline")
    note(f"skill {'CHANGED' if skill_changed else 'unchanged'} since the baseline "
         f"({baseline['skill_hash']} -> {fingerprint})")

    exit_code = 0
    rows = []
    for name, now in metrics.items():
        before = baseline["metrics"].get(name)
        if now is None or before is None:
            rows.append([name, before, now, "no data"])
            continue
        dropped = before - now > TOLERANCE
        log.info("%s: %.2f -> %.2f (tolerance %.2f) %s", name, before, now, TOLERANCE, "DROPPED" if dropped else "ok")
        if not dropped:
            status = "ok"
        elif skill_changed:
            status = "WARN dropped after a skill edit (expected churn?)"
        else:
            status = "ERROR dropped with no skill edit (drift)"
            exit_code = 1
        rows.append([name, before, now, status])
    table("metrics", ["metric", "baseline", "now", "status"], rows)
    headline("no unexplained regressions" if exit_code == 0 else "regression with no skill edit: something drifted",
             good=exit_code == 0)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
