"""
Eval type 11: what the improvement costs.

A skill is not free. Every time it loads, its whole text gets added to what
the model has to read. A skill that sends the agent off to read three
reference files before it answers can double the bill for a job it did not
make any better. So after "does it help" comes the question people forget to
ask: what is the help costing?

Two numbers decide it. How much better the answers got, and how much more the
runs cost. Together they give a verdict.

  better and cheaper       -> PARETO_BETTER   use it
  better but dearer        -> TRADEOFF        your call
  no better, but cheaper   -> CHEAPER         use it
  no better and dearer     -> PARETO_WORSE    why is this skill here?
  worse                    -> REJECT

The method is nothing clever: average each column for each side and compare.
Two rules keep those averages honest.

The token counts come from what the API reports, never from guessing at the
length of the text. And they include everything the model was handed from its
cache, because it read that either way. A count that leaves the cache out will
tell you a skill is free when it is not.

Every number is recorded on the run that produced it, at the moment it
happened. So a run's cost and its time always describe that run, rather than
being worked out afterwards from an average.

Reads what 06_ab_comparison.py saved. Nothing runs, so this costs nothing.

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

QUALITY_NOISE = 0.05     # a change smaller than this is not a change, it is wobble
COST_NOISE = 0.05        # the same again for money, measured against what it used to cost


def classify(quality_delta: float, cost_delta_fraction: float) -> str:
    """Turn the two changes into a verdict.

    Args:
        quality_delta: How much the pass rate moved, from -1 to 1. Positive
            means the skill made things better.
        cost_delta_fraction: How much the bill moved, as a share of what it was
            before. 0.2 means a fifth dearer.

    Returns:
        One of REJECT, TRADEOFF, PARETO_BETTER, CHEAPER, PARETO_WORSE or
        NEUTRAL. Anything smaller than the wobble thresholds counts as no
        change at all, so a rounding error never gets read as a result.

    Example:
        classify(0.20, -0.10)   # "PARETO_BETTER"
        classify(0.20, 0.30)    # "TRADEOFF"
    """
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
    # >>> THIS COSTS NOTHING. Nothing runs and nothing goes over the network.
    #     All this does is average the counts, costs and timings that 06 saved.
    #     If those are missing, 06 gets run once to produce them, and that does
    #     cost money.
    path = results_from("06_ab_comparison.py", "06_ab_runs.jsonl")
    rows = [r for r in load_jsonl(path) if not r["error"]]
    log.info("read %d marked runs from %s", len(rows), path.name)
    for r in rows:
        # Everything the model actually had to read: the new text, plus
        # everything handed to it from the cache, plus everything put into the
        # cache for next time.
        r["context_tokens"] = r["input_tokens"] + r["cache_read_tokens"] + r["cache_write_tokens"]
    arms = {arm: [r for r in rows if r["arm"] == arm] for arm in ("with_skill", "without_skill")}

    section("averages for each side")
    summary = {}
    rows_out = []
    for name in ("passed", "context_tokens", "output_tokens", "cost_usd", "duration_ms", "num_turns"):
        with_mean = mean(float(r[name]) for r in arms["with_skill"])
        without_mean = mean(float(r[name]) for r in arms["without_skill"])
        summary[name] = (with_mean, without_mean)
        rows_out.append([name, f"{with_mean:.3f}", f"{without_mean:.3f}", f"{with_mean - without_mean:+.3f}"])
    table("average per run", ["what was measured", "with skill", "without skill", "difference"], rows_out)

    quality_delta = summary["passed"][0] - summary["passed"][1]
    cost_delta = (summary["cost_usd"][0] - summary["cost_usd"][1]) / summary["cost_usd"][1]
    log.info("the skill changed the pass rate by %+.3f and the bill by %+.1f%%, which comes out as %s",
             quality_delta, cost_delta * 100, classify(quality_delta, cost_delta))
    section("verdict")
    label = classify(quality_delta, cost_delta)
    headline(f"{label}. The skill changed the pass rate by {quality_delta:+.2f} and the bill by {cost_delta:+.0%}",
             good={"PARETO_BETTER": True, "CHEAPER": True, "REJECT": False, "PARETO_WORSE": False}.get(label))

    # What one good answer costs is the fairest way to compare two skills on
    # the same work. Cheap successes beat expensive ones.
    rows_out = []
    for arm, runs in arms.items():
        passes = sum(r["passed"] for r in runs)
        spent = sum(r["cost_usd"] for r in runs)
        rows_out.append([arm, f"${spent:.2f}", passes, f"${spent / passes:.2f}" if passes else "nothing passed"])
    table("what one passing answer costs", ["side", "spent in total", "answers that passed", "cost per pass"],
          rows_out)


if __name__ == "__main__":
    main()
