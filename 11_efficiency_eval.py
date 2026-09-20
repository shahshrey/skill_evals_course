"""
Chapter eleven: the bill.

Ten chapters have been about whether your skill works. This one is about
what working costs. People skip that question. Then they answer it by
accident six months later, when somebody asks why the invoice grew.

A skill is not free. Every time it loads, its whole text gets added to what
the model has to read, on every request. A skill that sends the agent off to
open three reference files before it says anything can double the bill for a
job it did not improve.

Two numbers settle it. How much better the answers got, and how much more
the runs cost. Put together, they give you a verdict:

  better and cheaper       -> PARETO_BETTER   keep it
  better but dearer        -> TRADEOFF        your call, and it is a real one
  no better, but cheaper   -> CHEAPER         keep it
  no better and dearer     -> PARETO_WORSE    why is this skill here?
  worse                    -> REJECT

The method is not clever. Average each column on each side and subtract.
Two rules keep those averages honest. Both were set up chapters ago.

The token counts come from what the API reports, never from guessing at the
length of your text. They count everything handed to the model from its
cache too. It read that either way. Leave the cache out and your skill looks
free when it is nothing of the kind.

Every number was written down on the run that produced it, at the moment it
happened, back in 06. So a run's cost and its time describe that run. They
are not rebuilt afterwards from an average that has forgotten which runs it
came from.

Reads what 06 saved. Nothing runs. Nothing here costs a thing.

That is the last chapter. You started with a file that might not even parse.
You end with a price per working answer. Go back to 01 whenever you edit the
skill. The whole thing costs less than the afternoon you would otherwise
spend arguing about whether it helps.

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

QUALITY_NOISE = 0.05     # smaller than this is not a change. It is the wobble 09 warned you about
COST_NOISE = 0.05        # the same again for money, measured against what it cost before


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
        change at all. That stops a rounding error being promoted to a
        finding.

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
    # >>> THIS COSTS NOTHING. Nothing runs. Nothing goes near the network. The
    #     counts, costs and timings 06 wrote down get averaged. That is the
    #     whole chapter. If the file is missing, 06 runs once to make it. That
    #     is the fifth and last time this repo can surprise you with a bill.
    path = results_from("06_ab_comparison.py", "06_ab_runs.jsonl")
    rows = [r for r in load_jsonl(path) if not r["error"]]
    log.info("%d marked runs came back from %s, carrying the receipts 06 wrote at the time", len(rows), path.name)
    for r in rows:
        # Everything the model had to read. The fresh text, plus what it was
        # handed from the cache, plus what it put into the cache for next
        # time. Cheaper per token is not the same as free.
        r["context_tokens"] = r["input_tokens"] + r["cache_read_tokens"] + r["cache_write_tokens"]
    arms = {arm: [r for r in rows if r["arm"] == arm] for arm in ("with_skill", "without_skill")}

    section("what an average run looks like on each side")
    summary = {}
    rows_out = []
    for name in ("passed", "context_tokens", "output_tokens", "cost_usd", "duration_ms", "num_turns"):
        with_mean = mean(float(r[name]) for r in arms["with_skill"])
        without_mean = mean(float(r[name]) for r in arms["without_skill"])
        summary[name] = (with_mean, without_mean)
        rows_out.append([name, f"{with_mean:.3f}", f"{without_mean:.3f}", f"{with_mean - without_mean:+.3f}"])
    table("per run, on average", ["what was measured", "with skill", "without skill", "difference"], rows_out)

    quality_delta = summary["passed"][0] - summary["passed"][1]
    cost_delta = (summary["cost_usd"][0] - summary["cost_usd"][1]) / summary["cost_usd"][1]
    log.info("the skill moved the pass rate by %+.3f and the bill by %+.1f%%. Together those come out as: %s",
             quality_delta, cost_delta * 100, classify(quality_delta, cost_delta))
    section("the verdict, with the price attached")
    label = classify(quality_delta, cost_delta)
    headline(f"{label}. The skill changed the pass rate by {quality_delta:+.2f} and the bill by {cost_delta:+.0%}",
             good={"PARETO_BETTER": True, "CHEAPER": True, "REJECT": False, "PARETO_WORSE": False}.get(label))

    # The last table in the book. It holds the fairest single number for
    # comparing two skills doing the same work. What did one answer that
    # passed cost you? A side that fails half its runs pays for those
    # failures out of the successes. This is where that shows up.
    #
    # Whatever it says, you now know four things about your skill that you
    # did not know at the start of 01. Whether it loads. Whether it gets
    # picked. Whether it helps. What the help costs. Edit the skill and the
    # whole story runs again from the top.
    rows_out = []
    for arm, runs in arms.items():
        passes = sum(r["passed"] for r in runs)
        spent = sum(r["cost_usd"] for r in runs)
        rows_out.append([arm, f"${spent:.2f}", passes, f"${spent / passes:.2f}" if passes else "nothing passed"])
    table("what one answer that passed cost",
          ["side", "spent in total", "answers that passed", "cost per pass"], rows_out)


if __name__ == "__main__":
    main()
