"""
Eval type 9: statistics over repeated runs.

Agents are stochastic. Run the same case twice and you can get a pass and a
fail with nothing changed. So a single with/without delta on a handful of
cases is mostly noise. Plenty of people have found this out after publishing
a number: a finding that looked solid on one run, refuted on the fifth.

This file reads the paired rows that 06_ab_comparison.py saved and answers
four questions the raw pass rate cannot. Throughout, for one case in one
arm: n is how many attempts were run, c is how many passed, and k is how
many tries you would allow in production.

  pass@k    "if I let the agent try k times, how often does at least one
            attempt pass?" Computed as 1 - C(n-c, k) / C(n, k), where C is
            "ways to choose". That is the unbiased form; the tempting
            1 - (1 - c/n)^k overstates it for small n.
  pass^k    "how often do all k attempts pass?" C(c, k) / C(n, k), a
            reliability metric. Ask for this when the skill has to work
            every single time.
  bootstrap interval  resample the paired differences with replacement,
            many times, and read off the 2.5th and 97.5th percentiles. If
            the interval straddles zero you have not shown the skill helps;
            call that verdict "placebo".
  sign-flip test  pretend the skill does nothing; then each pair's
            difference is as likely to be positive as negative. Count how
            many random sign patterns give a mean at least as extreme as
            the one observed. That share is the p-value. Exact for small n,
            sampled otherwise.

With the default of two attempts per case, k is 2, so pass@k asks "did
either attempt pass" and pass^k asks "did both". Raise REPS in 06 to ask
about larger k.

No model calls. Runs in milliseconds on the saved data.

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

SEED = 1337              # fixed so two people get the same interval from the same data
BOOTSTRAP_SAMPLES = 2000


def pass_at_k(n: int, c: int, k: int) -> float:
    """n attempts, c of them passed: probability that at least one of k
    randomly chosen attempts passed."""
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_pow_k(n: int, c: int, k: int) -> float:
    """n attempts, c passed: probability that all k randomly chosen attempts passed."""
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)


def bootstrap_interval(differences: list[float], samples: int, seed: int) -> tuple[float, float]:
    """95% interval for the mean paired difference."""
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        resample = [rng.choice(differences) for _ in differences]
        means.append(sum(resample) / len(resample))
    means.sort()
    return means[int(0.025 * samples)], means[int(0.975 * samples)]


def sign_flip_p_value(differences: list[float], max_exact_n: int = 14, samples: int = 4096, seed: int = SEED) -> float:
    """Two-sided paired permutation test on the sign of each difference."""
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
    return (extreme + 1) / (samples + 1)    # +1 so a sampled p is never exactly 0


def main() -> None:
    configure_logging("09_statistics")
    show_skill()
    # >>> NO LIVE CALL: this file never runs the CLI or a model itself. Every
    #     number below is computed from the rows 06 saved. The one exception:
    #     if those rows are missing, results_from() runs 06 once to make them.
    path = results_from("06_ab_comparison.py", "06_ab_runs.jsonl")
    rows = [r for r in load_jsonl(path) if not r["error"]]
    log.info("loaded %d graded rows from %s", len(rows), path.name)

    # Group attempts per case and arm, keep the pairing by (case, rep).
    attempts = defaultdict(list)            # attempts[(case, arm)] -> [passed, ...]
    paired = defaultdict(dict)              # paired[(case, rep)] -> {arm: passed}
    for r in rows:
        attempts[(r["case"], r["arm"])].append(r["passed"])
        paired[(r["case"], r["rep"])][r["arm"]] = r["passed"]

    cases = sorted({case for case, _ in attempts})
    n = min(len(v) for v in attempts.values())
    k = min(2, n)      # cannot ask about more tries than were run
    explain(f"Nothing here calls a model. 06 saved {len(rows)} rows: {len(cases)} cases, each run {n} times "
            f"in each arm. Agents are stochastic, so a single pass or fail per case is an anecdote; these "
            "numbers say how much to trust the lift.")
    section(f"per case: {len(cases)} cases, {n} attempts per case per arm, k={k}")
    explain(f"For one case in one arm, n is the attempts ({n}) and c is how many passed. pass@k asks: if I let "
            f"the agent try k={k} times, how often does at least one pass? pass^k asks: how often do all "
            f"{k} pass? The second is the one to watch for a skill that must work every time.", kind="reading")
    rows_out = []
    for case in cases:
        for arm in ("with_skill", "without_skill"):
            flags = attempts[(case, arm)]
            c = sum(flags)
            rows_out.append([case, arm, c / len(flags), pass_at_k(len(flags), c, k), pass_pow_k(len(flags), c, k)])
    table("reliability", ["case", "arm", "pass rate", "pass@k", "pass^k"], rows_out)

    differences = [float(p["with_skill"]) - float(p["without_skill"])
                   for p in paired.values() if len(p) == 2]
    log.info("paired differences (with minus without): %s", differences)
    mean_lift = sum(differences) / len(differences)
    log.info("bootstrapping %d resamples with seed %d", BOOTSTRAP_SAMPLES, SEED)
    low, high = bootstrap_interval(differences, BOOTSTRAP_SAMPLES, SEED)
    p_value = sign_flip_p_value(differences)
    log.info("lift %+.3f, interval [%+.3f, %+.3f], p=%.4f", mean_lift, low, high, p_value)

    section("paired lift")
    explain(f"Each pair gives one difference, with-skill pass minus without-skill pass, so {len(differences)} "
            f"numbers: {differences}. The bootstrap resamples those {BOOTSTRAP_SAMPLES} times with replacement "
            "and reads off the middle 95 percent of the resampled means. If that interval straddles zero, the "
            "data cannot tell a helpful skill from a placebo. The sign-flip test asks how often pure chance, "
            "flipping the sign of each difference at random, would give a lift this large.", kind="reading")
    table("skill lift", ["pairs", "mean lift", "95% interval", "sign-flip p-value"],
          [[len(differences), f"{mean_lift:+.2f}", f"[{low:+.2f}, {high:+.2f}]", f"{p_value:.3f}"]])
    if low > 0:
        verdict, good = "helps", True
    elif high < 0:
        verdict, good = "harms", False
    else:
        verdict, good = "placebo (cannot tell yet)", None
    headline(f"verdict: {verdict}", good=good)
    if good:
        explain(f"The whole interval [{low:+.2f}, {high:+.2f}] is above zero and the p-value is {p_value:.3f}, "
                "so the lift is not an accident of which runs happened to pass. Notice why it is this clean: "
                "every with-skill run passed and every baseline failed. A subtler skill would show a wider "
                "interval, and that is where the noise-floor line below starts to matter.", kind="meaning")
    elif good is None:
        explain(f"The interval [{low:+.2f}, {high:+.2f}] includes zero. That does not mean the skill does "
                "nothing; it means these runs cannot tell. More reps or more cases narrow the interval.",
                kind="meaning")

    # The honest part. For a pass/fail metric the interval is roughly
    # +/- 1/sqrt(N) wide (a rule of thumb; the exact width depends on how
    # varied the differences are), so 8 pairs cannot resolve a 20-point effect.
    noise = 1 / math.sqrt(len(differences))
    note(f"noise floor at this size is about +/-{noise:.2f}. "
         f"To see a 0.10 effect you need roughly {math.ceil(1 / 0.10 ** 2)} pairs.")


if __name__ == "__main__":
    main()
