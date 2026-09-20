"""
Chapter nine: the one that asks whether any of that was real.

06 ended on a headline. Something like "the skill changed the pass rate by
plus fifty per cent", in a colour meant to look like good news. Eight
comparisons produced that figure. This chapter asks an uncomfortable
question. Are eight comparisons allowed to produce a figure at all?

The trouble is that an AI agent will not give you the same answer twice.
Same prompt, same model, same afternoon. One attempt passes, the next fails.
Nothing changed in between except the weather inside the model. So when the
skill wins six of eight, you do not know whether you have a good skill or
whether you had a good afternoon.

People publish before checking this. Then the result that looked solid on
the first run falls apart on the fifth, and the number has to be taken back
in public. Ten free minutes here would have caught it.

So this reads the results 06 saved and asks four questions the pass rate
cannot answer on its own. Three letters keep turning up.

  n  how many attempts you ran for one case
  c  how many of those attempts passed
  k  how many tries you would give the agent in real life

And the four answers.

  If it gets k tries, does at least one work?
    Written pass@k. This is the number that matters when a human reviews the
    output anyway. One good attempt out of several counts as a win. The
    arithmetic is 1 - C(n-c, k) / C(n, k), where C counts the ways to choose.
    The tempting shortcut, 1 - (1 - c/n)^k, flatters small samples. Small
    samples are all you have.

  If it gets k tries, do all of them work?
    Written pass^k. The one to watch when the skill has to work every time,
    because nobody downstream is checking.

  How far would the answer move if you ran the whole thing again?
    You cannot afford to. So take the results you have, draw from them at
    random a couple of thousand times, and watch how far the average
    wanders. Report the middle 95 per cent of where it landed. That is a
    bootstrap confidence interval. If the range includes zero, you have not
    shown the skill helps. It may well. This data cannot say.

  What are the odds this is just luck?
    Suppose your skill does nothing. Then each comparison is a coin flip,
    and a win is as likely as a loss. Count how many of the possible
    coin-flip patterns would come out at least as lopsided as the one you
    got. That share is the p-value, from a sign-flip test. Below 0.05 is the
    usual bar for "probably not luck".

With the default of two attempts per case, k is 2. pass@k asks whether
either attempt worked. pass^k asks whether both did. Raise REPS in 06 to ask
about more tries, and pay 06's bill again for the privilege.

Nothing here costs a penny. No model runs. Nothing touches the network. It
finishes in milliseconds on results somebody already paid for.

Whatever this chapter concludes, it concludes about today. 10_regression_check.py
is the same question asked about next month.

Run:  python 09_statistics.py
"""

from __future__ import annotations

import itertools
import math
import random
from collections import defaultdict

from skill_eval_common import (
    configure_logging,
    explain,
    headline,
    load_jsonl,
    log,
    note,
    results_from,
    section,
    show_skill,
    table,
)

# Every random draw below is seeded. Two people running this on the same
# results get the same range down to the last digit. Randomness you cannot
# reproduce is not evidence. It is an anecdote with decimal places.
SEED = 1337
BOOTSTRAP_SAMPLES = 2000


def pass_at_k(n: int, c: int, k: int) -> float:
    """Work out the chance that at least one of k tries passes.

    Args:
        n: How many attempts were actually run.
        c: How many of those attempts passed.
        k: How many tries you want to ask about.

    Returns:
        A number from 0 to 1. At 0.75, three times out of four you would get
        at least one good answer within k tries.

    Example:
        pass_at_k(n=4, c=2, k=2)  # 0.833
    """
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_pow_k(n: int, c: int, k: int) -> float:
    """Work out the chance that all k tries pass.

    The unforgiving version of pass_at_k. Reach for it when one bad answer is
    a real problem, because nobody downstream will catch it for you.

    Args:
        n: How many attempts were actually run.
        c: How many of those attempts passed.
        k: How many tries you want to ask about.

    Returns:
        A number from 0 to 1, the chance that none of the k tries fails.

    Example:
        pass_pow_k(n=4, c=2, k=2)  # 0.167
    """
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)


def bootstrap_interval(differences: list[float], samples: int, seed: int) -> tuple[float, float]:
    """Work out how much the average result would move if we ran it all again.

    The trick is almost silly once you see it. You have one set of results and
    no budget to run the experiment a thousand more times. So you fake the
    thousand. Build each new set by drawing from the results you already
    have, at random, repeats allowed. Take the average of every fake set. How
    widely those averages scatter tells you how jumpy your real average was
    all along.

    Args:
        differences: One number per comparison. 1 means the skill won, -1 means
            it lost, 0 means both sides did the same.
        samples: How many fake sets to build. A couple of thousand is plenty.
        seed: Starting number for the randomness, so the answer repeats.

    Returns:
        The bottom and top of the middle 95 percent. A range that includes
        zero means this data cannot tell a helpful skill from a useless one.

    Example:
        low, high = bootstrap_interval([1.0, 1.0, 0.0], 2000, 1337)
    """
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        resample = [rng.choice(differences) for _ in differences]
        means.append(sum(resample) / len(resample))
    means.sort()
    return means[int(0.025 * samples)], means[int(0.975 * samples)]


def sign_flip_p_value(differences: list[float], max_exact_n: int = 14, samples: int = 4096, seed: int = SEED) -> float:
    """Work out the odds of getting this result by luck alone.

    Pretend for a moment that the skill does nothing. Then every comparison
    is a coin flip. Swapping the plus and minus signs around would have been
    exactly as likely as the result you got. So try every possible pattern of
    swaps and count how many come out at least as lopsided. That share is
    your answer.

    Up to 14 comparisons, every pattern gets checked and the answer is exact.
    Past that there are too many to list, so patterns get sampled instead.

    Args:
        differences: One number per comparison, as in bootstrap_interval.
        max_exact_n: Check every pattern up to this many comparisons. Above it,
            sample instead. 14 comparisons is 16,384 patterns, which is quick.
        samples: How many patterns to sample when there are too many to check.
        seed: Starting number for the randomness, so the answer repeats.

    Returns:
        A number from 0 to 1. At 0.008, under one run in a hundred would look
        this good by luck. Under 0.05 is the usual bar for believing it.

    Example:
        sign_flip_p_value([1.0] * 8)  # 0.0078
    """
    observed = abs(sum(differences))
    n = len(differences)
    if n <= max_exact_n:
        patterns = itertools.product((1, -1), repeat=n)
        total = 2 ** n
        extreme = sum(abs(sum(d * s for d, s in zip(differences, signs))) >= observed for signs in patterns)
        return extreme / total
    rng = random.Random(seed)
    extreme = 0
    for _ in range(samples):
        extreme += abs(sum(d * rng.choice((1, -1)) for d in differences)) >= observed
    # The +1 on both sides stops a sampled answer coming out at exactly zero.
    # We never checked every pattern, so we cannot honestly claim zero chance.
    return (extreme + 1) / (samples + 1)


def main() -> None:
    configure_logging("09_statistics")
    show_skill()
    # >>> THIS COSTS NOTHING. No model runs here. Nothing goes near the
    #     network. Every number below is squeezed out of results 06 already
    #     bought. One exception. If those results are missing, results_from()
    #     runs 06 once to make them, and that does spend money.
    path = results_from("06_ab_comparison.py", "06_ab_runs.jsonl")
    rows = [r for r in load_jsonl(path) if not r["error"]]
    log.info("%d finished runs came back from %s. None will be re-run, only re-read",
             len(rows), path.name)

    # The runs get sorted twice. Once by case and side, to count how often each
    # side passed. Once by case and attempt number, which keeps the two halves
    # of one comparison together. That second grouping is the one 06 went out
    # of its way to protect. It is why the numbers below are as sensitive as
    # they are. Comparing like with like beats comparing two averages that
    # happen to be standing near each other.
    attempts = defaultdict(list)            # attempts[(case, side)] -> [passed, ...]
    paired = defaultdict(dict)              # paired[(case, attempt)] -> {side: passed}
    for r in rows:
        attempts[(r["case"], r["arm"])].append(r["passed"])
        paired[(r["case"], r["rep"])][r["arm"]] = r["passed"]

    cases = sorted({case for case, _ in attempts})
    n = min(len(v) for v in attempts.values())
    k = min(2, n)      # you cannot ask about more tries than you actually ran
    explain(f"Nothing here runs a model or costs a penny. 06 already bought and saved {len(rows)} runs. "
            f"{len(cases)} cases, each tried {n} times with the skill and {n} times without. An AI agent gives "
            "you a different answer every time you ask. A single pass or fail proves nothing. What follows is "
            "the arithmetic that decides how much of 06's headline you get to keep.")
    section(f"case by case: {len(cases)} cases, {n} attempts a side, k={k}")
    explain(f"For one case on one side, n is how many attempts ran ({n}) and c is how many passed. pass@k "
            f"asks this. Give the agent {k} tries, how often does at least one work? pass^k asks how often "
            f"all {k} work. The second one matters when nobody downstream is checking the output.",
            kind="reading")
    rows_out = []
    for case in cases:
        for arm in ("with_skill", "without_skill"):
            flags = attempts[(case, arm)]
            c = sum(flags)
            rows_out.append([case, arm, c / len(flags), pass_at_k(len(flags), c, k), pass_pow_k(len(flags), c, k)])
    table("how steady each case is, side by side", ["case", "side", "pass rate", "at least 1 of k", "all k"],
          rows_out)

    differences = [float(p["with_skill"]) - float(p["without_skill"])
                   for p in paired.values() if len(p) == 2]
    log.info("every comparison boiled down to one number. 1 = the skill won, -1 = it lost, 0 = nobody did: %s",
             differences)
    mean_lift = sum(differences) / len(differences)
    log.info("now rebuilding the experiment %d times from seed %d, drawing at random from those numbers, to "
             "watch how far the average wanders", BOOTSTRAP_SAMPLES, SEED)
    low, high = bootstrap_interval(differences, BOOTSTRAP_SAMPLES, SEED)
    p_value = sign_flip_p_value(differences)
    log.info("the skill moved the pass rate by %+.3f on average. Run it all again and it would most likely "
             "land between %+.3f and %+.3f. Odds that pure luck looks this good: %.1f%%",
             mean_lift, low, high, p_value * 100)

    section("so did the skill help")
    explain(f"Every head-to-head comparison comes down to one number. Did the skill win, lose or tie? That is "
            f"{len(differences)} numbers, and here they are: {differences}. A 1 means the skill passed where "
            f"the plain agent failed. To find out how solid that is, the experiment gets rebuilt "
            f"{BOOTSTRAP_SAMPLES} times by drawing from those numbers at random. The averages get lined up. If "
            "the middle 95 per cent of them includes zero, this data cannot tell a helpful skill from a useless "
            "one. No amount of confident phrasing changes that. The last column asks the same question from "
            "the other end. If the skill did nothing, how often would luck alone look this good?",
            kind="reading")
    table("the whole experiment, in one row",
          ["comparisons", "average change in pass rate", "likely range if rerun", "chance this is luck"],
          [[len(differences), f"{mean_lift:+.2f}", f"[{low:+.2f}, {high:+.2f}]", f"{p_value * 100:.1f}%"]])
    if low > 0:
        verdict, good = "helps", True
    elif high < 0:
        verdict, good = "harms", False
    else:
        verdict, good = "placebo (cannot tell yet)", None
    headline(f"verdict: {verdict}", good=good)
    if good:
        explain(f"The skill helped and the result holds up. Even the gloomiest rebuild of the data still shows "
                f"an improvement of {low:+.2f}. Luck would produce something this lopsided {p_value * 100:.1f} "
                "per cent of the time. Worth knowing why it came out this clean, though. Every run with the "
                "skill passed and every run without it failed. That is about as easy as this arithmetic ever "
                "gets. A skill that helps a little rather than a lot gives a far wider range. That is when the "
                "note at the bottom about sample size stops being a footnote.", kind="meaning")
    elif good is None:
        explain(f"The likely range, {low:+.2f} to {high:+.2f}, includes zero. That is not a finding that your "
                "skill does nothing. It is a finding that you ran too few comparisons to tell either way. More "
                "attempts per case, or more cases, and the range closes in. Both cost money. That is the trade "
                "06 has been quietly setting up for you.", kind="meaning")

    # Here is the honest bit that most write-ups leave out. With pass-or-fail
    # results, the smallest difference you can resolve is roughly one over
    # the square root of the number of comparisons. A rule of thumb, not a
    # law. The real width depends on how varied the results are. Either way,
    # eight comparisons cannot see a twenty-point improvement. Pretending
    # otherwise is how numbers end up retracted.
    noise = 1 / math.sqrt(len(differences))
    note(f"At {len(differences)} comparisons, anything smaller than about {noise:.2f} is indistinguishable from "
         f"random variation. To catch an improvement as small as 0.10 you would need somewhere near "
         f"{math.ceil(1 / 0.10 ** 2)} comparisons. 06 would send you the bill. Whatever the verdict above, it "
         "is a verdict about today. 10_regression_check.py asks the same question about next month, after the "
         "model changes underneath you.")


if __name__ == "__main__":
    main()
