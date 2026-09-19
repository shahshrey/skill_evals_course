"""
Eval type 9: are the numbers real, or did we get lucky?

Here is the problem this script exists to solve. An AI agent does not give the
same answer twice. Run the identical test on the identical prompt and one
attempt passes, the next fails, with nothing changed in between. So when you
run eight comparisons and the skill wins six of them, you genuinely do not
know whether the skill is good or whether you had a good afternoon.

People publish numbers before checking this and then have to take them back.
A result that looked solid on the first run falls apart on the fifth.

This script reads the results that 06_ab_comparison.py saved and answers four
questions the plain pass rate cannot. Three letters show up throughout:

  n  how many attempts we ran for one case
  c  how many of those attempts passed
  k  how many tries you would let the agent have in real life

And the four answers:

  If I let it try k times, does at least one attempt work?
    Written pass@k. Useful when a human reviews the output anyway, so one
    good attempt out of several is a win. The arithmetic is
    1 - C(n-c, k) / C(n, k), where C is the number of ways to choose. The
    obvious shortcut, 1 - (1 - c/n)^k, flatters small samples, so we use the
    longer form.

  If I let it try k times, do all of them work?
    Written pass^k. This is the one to watch when the skill has to work every
    single time and nobody is checking.

  How much would the answer move if we ran it all again?
    Take the results we have, draw from them at random thousands of times,
    and see how far the average wanders. Report the middle 95 percent of
    where it landed (a bootstrap confidence interval). If that range includes
    zero, we have not shown the skill helps. It might, but this data cannot
    tell.

  What are the odds this is just luck?
    Assume for a moment the skill does nothing. Then each comparison is a coin
    flip, and a win is as likely as a loss. Count how many of the possible
    coin-flip patterns would produce a result at least as lopsided as the one
    we actually got. That share is the p-value (a sign-flip test). Below 0.05
    is the usual bar for "probably not luck".

With the default of two attempts per case, k is 2. So pass@k asks whether
either attempt worked, and pass^k asks whether both did. Raise REPS in
06_ab_comparison.py to ask about more tries.

Nothing here costs money. No model is called, no network is touched. It runs
in milliseconds on results that were already paid for.

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

# The random draws below are seeded, so two people running this on the same
# results get exactly the same range. Randomness you cannot reproduce is not
# evidence, it is an anecdote.
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

    The strict version of pass_at_k. Use it when one bad answer is a problem,
    because nobody downstream is going to catch it.

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

    The trick is simple once you see it. We only have one set of results, and
    we cannot afford to run the whole experiment a thousand more times. So we
    fake it: build a thousand new sets by drawing from the results we have, at
    random, with repeats allowed. Take the average of each fake set. The
    spread of those averages tells you how jumpy the real average is.

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

    Pretend the skill does nothing at all. If that were true, each comparison
    would be a coin flip, and flipping the plus and minus signs around would be
    just as likely a result as the one we saw. So try every possible pattern of
    flips and count how many come out at least as lopsided. That share is the
    answer.

    Up to 14 comparisons, every pattern is checked, so the answer is exact.
    Beyond that there are too many, and patterns are sampled at random instead.

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
    # >>> THIS COSTS NOTHING. No model runs here and nothing goes over the
    #     network. Every number below comes from results 06 already saved. One
    #     exception: if those results are missing, results_from() runs 06 once
    #     to produce them, and that does spend money.
    path = results_from("06_ab_comparison.py", "06_ab_runs.jsonl")
    rows = [r for r in load_jsonl(path) if not r["error"]]
    log.info("read %d finished runs from %s", len(rows), path.name)

    # Sort the runs two ways. First by case and side, to count how often each
    # side passed. Second by case and attempt number, which keeps the two sides
    # of one comparison together. That pairing is the whole point: comparing
    # like with like is far more sensitive than comparing two separate averages.
    attempts = defaultdict(list)            # attempts[(case, side)] -> [passed, ...]
    paired = defaultdict(dict)              # paired[(case, attempt)] -> {side: passed}
    for r in rows:
        attempts[(r["case"], r["arm"])].append(r["passed"])
        paired[(r["case"], r["rep"])][r["arm"]] = r["passed"]

    cases = sorted({case for case, _ in attempts})
    n = min(len(v) for v in attempts.values())
    k = min(2, n)      # you cannot ask about more tries than you actually ran
    explain(f"No model runs in this script and nothing costs money. Script 06 already saved {len(rows)} runs: "
            f"{len(cases)} test cases, each tried {n} times with the skill and {n} times without. An AI agent "
            "gives a different answer every time you ask, so one pass or one fail proves nothing on its own. "
            "The numbers below say how much to trust the result.")
    section(f"per case: {len(cases)} cases, {n} attempts per case per side, k={k}")
    explain(f"For one case on one side, n is how many attempts we ran ({n}) and c is how many passed. "
            f"pass@k answers: if the agent gets {k} tries, how often does at least one work? pass^k answers: "
            f"how often do all {k} work? The second matters when nobody is going to check the output.",
            kind="reading")
    rows_out = []
    for case in cases:
        for arm in ("with_skill", "without_skill"):
            flags = attempts[(case, arm)]
            c = sum(flags)
            rows_out.append([case, arm, c / len(flags), pass_at_k(len(flags), c, k), pass_pow_k(len(flags), c, k)])
    table("how reliable is each case", ["case", "side", "pass rate", "at least 1 of k", "all k"], rows_out)

    differences = [float(p["with_skill"]) - float(p["without_skill"])
                   for p in paired.values() if len(p) == 2]
    log.info("result of each head-to-head comparison, 1 = the skill won, -1 = it lost, 0 = tie: %s", differences)
    mean_lift = sum(differences) / len(differences)
    log.info("building %d rerolls of the data, starting from seed %d, to see how far the average moves",
             BOOTSTRAP_SAMPLES, SEED)
    low, high = bootstrap_interval(differences, BOOTSTRAP_SAMPLES, SEED)
    p_value = sign_flip_p_value(differences)
    log.info("on average the skill changed the pass rate by %+.3f. Rerunning the experiment would most likely "
             "land between %+.3f and %+.3f. Odds this is luck: %.1f%%",
             mean_lift, low, high, p_value * 100)

    section("did the skill actually help")
    explain(f"Each head-to-head comparison gives one number: did the skill win, lose or tie? That is "
            f"{len(differences)} numbers, and here they are: {differences}. A 1 means the skill passed where "
            f"the plain agent failed. To see how solid that is, we rebuild the experiment {BOOTSTRAP_SAMPLES} "
            "times by drawing from those numbers at random, and look at where the average lands. If the "
            "middle 95 percent of those averages includes zero, this data cannot tell a helpful skill from a "
            "useless one. The last column asks the same thing a different way: if the skill did nothing, how "
            "often would pure luck look this good?", kind="reading")
    table("did the skill help",
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
        explain(f"The skill helped, and the result holds up. Even the gloomiest reroll of the data still shows "
                f"an improvement of {low:+.2f}, and the odds of luck producing this are {p_value * 100:.1f} "
                "percent. Worth knowing why the result is this clean, though: every run with the skill passed "
                "and every run without it failed. A skill that helps a little rather than a lot would give a "
                "much wider range, and then the note at the bottom about sample size starts to bite.",
                kind="meaning")
    elif good is None:
        explain(f"The likely range, {low:+.2f} to {high:+.2f}, includes zero. That is not the same as proving "
                "the skill does nothing. It means we ran too few comparisons to tell. More attempts per case, "
                "or more cases, would narrow the range.", kind="meaning")

    # The honest bit that most write-ups leave out. With pass/fail results, the
    # range you can resolve is roughly plus or minus one over the square root of
    # the number of comparisons. It is a rule of thumb, not a formula; the real
    # width depends on how varied the results are. Either way, 8 comparisons
    # cannot detect a 20-point improvement, and pretending otherwise is how
    # people end up retracting numbers.
    noise = 1 / math.sqrt(len(differences))
    note(f"At {len(differences)} comparisons, anything smaller than about {noise:.2f} is indistinguishable from "
         f"random variation. To spot an improvement as small as 0.10 you would need roughly "
         f"{math.ceil(1 / 0.10 ** 2)} comparisons.")


if __name__ == "__main__":
    main()
