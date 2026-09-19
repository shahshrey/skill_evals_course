"""
Eval type 3, second version: will the right skill get picked, judged by meaning?

03_routing_offline.py ranks skills by counting shared words. That is free and
it catches a description with the wrong vocabulary in it, but it has an
obvious blind spot: it cannot see that "summarise my changes for git" and
"write a commit message" are asking for the same thing. Not one word in common.

The real software can see that, because a model reads the descriptions.
04_trigger_eval.py tests exactly that, but it pays for a full agent run per
request per attempt, which adds up fast.

This script sits between the two. It hands a small, fast model the whole list
of installed descriptions plus one request, and asks a single multiple-choice
question: which of these should handle it? The model understands meaning, so
it catches what word counting misses, and it answers in about a tenth of a
second, cheap enough to run after every single edit to your description.

It is still not the real software, so 04 has the final word. But a description
that fails here will fail there too, and here you find out in seconds.

One nice extra: the answer comes back with a confidence figure for every
option, not just a winner. That tells you three different things.

  High confidence on the right skill means your description is doing its job.

  Confidence split between two skills means those two descriptions are
  competing for the same work. That is the same clash 03 looks for, caught by
  meaning this time rather than by shared words.

  Confidence on "none" for a request that belongs elsewhere means your
  description knows when to keep out of it.

Needs TYPESAFE_API_KEY set in your environment or in a .env file.

Run:  python 03b_routing_semantic.py
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv
from typesafe_sdk import Choice, TypeSafeClient

from skill_eval_common import (
    FIXTURES_DIR,
    SKILL_DIR,
    configure_logging,
    headline,
    load_skill,
    log,
    section,
    show_skill,
    table,
)

CATALOG_DIRS = [SKILL_DIR, *sorted((FIXTURES_DIR / "catalog").iterdir())]
OUR_SKILL = "commit-message"
NONE = "none"                 # the option meaning "none of these fits"

# Same setup as 03. Some requests should land on our skill, the rest should
# land somewhere else, and each of those names the skill that ought to win.
#
# Two of them belong to no skill at all, which 03 had no way of expressing. A
# chooser that always picks something rather than admitting nothing fits will
# fail those two, and that failure is worth catching.
POSITIVE_PROMPTS = [
    "write a commit message for this diff",
    "can you draft the commit for the changes I just made",
    "summarise these changes for git",
    "I need a commit message, here is the patch",
]
NEGATIVE_PROMPTS = [
    ("write a PR description for this branch", "pr-description"),
    ("add a changelog entry for version 2.3", "changelog-entry"),
    ("how does git rebase --onto work", "git-help"),
    ("what is the capital of Portugal", NONE),
    ("rename the variable x to count in main.py", NONE),
]
COLLISION_SHARE = 0.30        # a runner-up this confident means two descriptions are competing


def route(client: TypeSafeClient, prompt: str, catalog: dict[str, str]) -> tuple[str, dict[str, float]]:
    """Ask the model which skill a request belongs to.

    Args:
        client: A connected TypeSafe client.
        prompt: What the user typed.
        catalog: Every installed skill's description, keyed by skill name.

    Returns:
        The skill it picked, and how confident it was about every option
        including "none". The confidences add up to 1.

    Example:
        pick, confidence = route(client, "write a commit message", catalog)
    """
    criteria = dict(catalog)
    criteria[NONE] = "No installed skill applies to this request."
    # >>> THIS SPENDS MONEY, but barely. One request to a small fast model,
    #     carrying the whole list of skills. It picks one and says how
    #     confident it is about each.
    result = client.system_one(
        {"user_request": prompt, "installed_skills": catalog},
        {"skill": Choice(
            instructions="Which installed skill, if any, should handle the user's request? "
                         "Pick by what the user is asking for, not by shared words.",
            criteria=criteria,
        )},
    )
    answer = result.choices["skill"]
    probabilities = {k: round(v, 3) for k, v in answer.probabilities.items()}
    log.info("for the request %r it picked %s, %.0f%% sure. Full breakdown: %s",
             prompt, answer.choice, answer.confidence * 100, probabilities)
    return answer.choice, probabilities


def runner_up_share(probabilities: dict[str, float], winner: str) -> tuple[str, float]:
    """Find the second-place skill and how confident the model was about it.

    A close second means two descriptions are competing for the same work, and
    which one wins on any given day is close to a coin toss.

    Args:
        probabilities: How confident the model was about each option.
        winner: The option that came first.

    Returns:
        The runner-up's name and its confidence.
    """
    others = {k: v for k, v in probabilities.items() if k != winner}
    second = max(others, key=others.get)
    return second, others[second]


def main() -> int:
    configure_logging("03b_routing_semantic")
    show_skill()
    load_dotenv()
    catalog = {}
    for skill_dir in CATALOG_DIRS:
        skill = load_skill(skill_dir)
        catalog[skill.name] = skill.description
    log.info("%d skills to choose between: %s", len(catalog), sorted(catalog))
    client = TypeSafeClient()
    failures = 0

    section("requests that should land on our skill")
    rows = []
    for prompt in POSITIVE_PROMPTS:
        pick, probabilities = route(client, prompt, catalog)
        ok = pick == OUR_SKILL
        failures += not ok
        second, share = runner_up_share(probabilities, pick)
        collision = f"{second} at {share:.2f}" if share >= COLLISION_SHARE else "-"
        rows.append([prompt, pick, probabilities.get(OUR_SKILL, 0.0), collision, ok])
    table("should land on our skill",
          ["the request", "what it picked", "how sure about ours", "close second", "verdict"], rows)

    section("requests that belong to a different skill, or to none at all")
    rows = []
    for prompt, owner in NEGATIVE_PROMPTS:
        pick, probabilities = route(client, prompt, catalog)
        ok = pick == owner
        failures += not ok
        rows.append([prompt, pick, owner, probabilities.get(OUR_SKILL, 0.0), ok])
    table("should land elsewhere",
          ["the request", "what it picked", "who it belongs to", "how sure about ours", "verdict"], rows)

    headline(f"{failures} things went wrong", good=failures == 0)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
