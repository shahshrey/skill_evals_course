"""
Eval type 11: efficiency (cost, tokens, time).

A skill is not free. Loading it adds its whole body to the context on every
run, and a skill that makes the agent read three reference files before
answering can double the cost of a task it did not improve. So the last
question after "does it help" is "what does the help cost".

The two deltas combine into a verdict:

  quality up,   cost down  -> PARETO_BETTER   (ship it)
  quality up,   cost up    -> TRADEOFF        (decide)
  quality flat, cost down  -> CHEAPER          (ship it)
  quality flat, cost up    -> PARETO_WORSE    (why is this skill here?)
  quality down             -> REJECT

The method is plain: average each column per arm, compare. Two accounting
rules keep the averages honest. Token counts come from the API's usage
block, never from len(text)/4, and they include what the prompt cache
served, since the model read it either way. And every number is recorded
per run from the call that produced it, so a run's cost and duration always
describe that run and not some estimate made later.

Reads the rows from 06_ab_comparison.py. No model calls.

Run:  python 11_efficiency_eval.py
"""

from __future__ import annotations

from statistics import mean

from skill_eval_common import (
    configure_logging,
    headline,
    load_jsonl,
    log,
    results_from,
    section,
    show_skill,
    table,
)

QUALITY_NOISE = 0.05     # a quality delta smaller than this counts as flat
COST_NOISE = 0.05        # same for cost, as a fraction of the baseline


def classify(quality_delta: float, cost_delta_fraction: float) -> str:
    if quality_delta < -QUALITY_NOISE:
        return "REJECT"
    quality_up = quality_delta > QUALITY_NOISE
    cost_up = cost_delta_fraction > COST_NOISE
    cost_down = cost_delta_fraction < -COST_NOISE
    if quality_up:
        return "TRADEOFF" if cost_up else "PARETO_BETTER"
    if cost_down:
        return "CHEAPER"
    return "PARETO_WORSE" if cost_up else "NEUTRAL"


def main() -> None:
    configure_logging("11_efficiency_eval")
    show_skill()
    # >>> NO LIVE CALL: this file never runs the CLI or a model itself. It
    #     averages the token, cost and timing columns 06 saved; if those rows
    #     are missing, results_from() runs 06 once to make them.
    path = results_from("06_ab_comparison.py", "06_ab_runs.jsonl")
    rows = [r for r in load_jsonl(path) if not r["error"]]
    log.info("loaded %d graded rows from %s", len(rows), path.name)
    for r in rows:
        # What the model actually read: fresh tokens plus everything served
        # from or written to the prompt cache.
        r["context_tokens"] = r["input_tokens"] + r["cache_read_tokens"] + r["cache_write_tokens"]
    arms = {arm: [r for r in rows if r["arm"] == arm] for arm in ("with_skill", "without_skill")}

    section("per-arm averages")
    summary = {}
    rows_out = []
    for name in ("passed", "context_tokens", "output_tokens", "cost_usd", "duration_ms", "num_turns"):
        with_mean = mean(float(r[name]) for r in arms["with_skill"])
        without_mean = mean(float(r[name]) for r in arms["without_skill"])
        summary[name] = (with_mean, without_mean)
        rows_out.append([name, f"{with_mean:.3f}", f"{without_mean:.3f}", f"{with_mean - without_mean:+.3f}"])
    table("mean per run", ["metric", "with skill", "without skill", "delta"], rows_out)

    quality_delta = summary["passed"][0] - summary["passed"][1]
    cost_delta = (summary["cost_usd"][0] - summary["cost_usd"][1]) / summary["cost_usd"][1]
    log.info("quality delta %+.3f, cost delta %+.1f%% -> %s", quality_delta, cost_delta * 100,
             classify(quality_delta, cost_delta))
    section("verdict")
    label = classify(quality_delta, cost_delta)
    headline(f"{label}: quality delta {quality_delta:+.2f}, cost delta {cost_delta:+.0%}",
             good={"PARETO_BETTER": True, "CHEAPER": True, "REJECT": False, "PARETO_WORSE": False}.get(label))

    # Cost per passing run is the fair way to compare two skills on the same
    # cases: cheaper successes win.
    rows_out = []
    for arm, runs in arms.items():
        passes = sum(r["passed"] for r in runs)
        spent = sum(r["cost_usd"] for r in runs)
        rows_out.append([arm, f"${spent:.2f}", passes, f"${spent / passes:.2f}" if passes else "no passes"])
    table("cost per passing run", ["arm", "spent", "passes", "per pass"], rows_out)


if __name__ == "__main__":
    main()
