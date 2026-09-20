"""
Chapter three and a half: the same question, asked by something that reads.

03 ranked your skill by counting shared words. That has one blind spot you
cannot patch. "Summarise my changes for git" and "write a commit message" are
the same request. They share no useful words. Word counting will never see
it, however carefully you choose your vocabulary. There is nothing to count.

The real software sees it, because a model reads the descriptions instead of
matching letters. 04_trigger_eval.py tests exactly that. It pays for a whole
agent run per request per attempt. You will not want to run 04 after every
small edit to a sentence.

So this one sits in the middle. It hands a small fast model the list of
installed descriptions and one request, and asks one multiple-choice
question. Which of these should take it? Meaning included, answer back in
about a tenth of a second. Cheap enough to run every time you touch the
description. That is the point.

Still not the real software. 04 has the last word. But a description that
fails here will fail there too. Here it fails in seconds instead of minutes
and money.

There is a bonus in the answer. It comes back with a confidence figure for
every option, not just the winner. That tells you three things.

  Confident on the right skill. Your description is doing its job.

  Confidence split between two skills. Those two descriptions are competing
  for the same work. That is the clash 03 measures, found by meaning this
  time rather than by shared words.

  Confidence on "none" for a request that belongs to nobody. Your description
  knows when to stay out of it. That is harder to teach than it sounds, and
  03 could not ask about it at all.

Needs TYPESAFE_API_KEY set in your environment or in a .env file.

After this, the guessing stops. 04_trigger_eval.py installs the skill and
watches the real thing decide.

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

# The same lineup as 03. Some requests should land on our skill. The rest
# belong elsewhere, and each names who ought to win.
#
# Two of them belong to nobody. 03 had no way to ask about that. A chooser
# that would rather pick something than admit nothing fits will fail those
# two. You want to know that about your chooser.
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
COLLISION_SHARE = 0.30        # a runner-up this confident is not a runner-up, it is a rival


def route(client: TypeSafeClient, prompt: str, catalog: dict[str, str]) -> tuple[str, dict[str, float]]:
    """Ask the model which skill a request belongs to.

    The "none" option is added here rather than listed with the skills,
    because it is not a skill. It is the escape hatch. Without one, the model
    has no way to tell you that your whole catalog is beside the point.

    Args:
        client: A connected TypeSafe client.
        prompt: What the user typed.
        catalog: Every installed skill's description, keyed by skill name.

    Returns:
        The skill it picked, and how confident it was about every option
        including "none". The confidences add up to 1, so a strong second
        place can only come out of the winner's share.

    Example:
        pick, confidence = route(client, "write a commit message", catalog)
    """
    criteria = dict(catalog)
    criteria[NONE] = "No installed skill applies to this request."
    # >>> THIS SPENDS MONEY, but barely. One question to a small fast model,
    #     carrying the whole catalog with it. It picks one and tells you how
    #     sure it was about every option. That last part is the useful bit.
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
    log.info("someone types %r. It picks %s, %.0f%% sure. The rest of its confidence: %s",
             prompt, answer.choice, answer.confidence * 100, probabilities)
    return answer.choice, probabilities


def runner_up_share(probabilities: dict[str, float], winner: str) -> tuple[str, float]:
    """Find the second-place skill and how confident the model was about it.

    A close second is the interesting result. It means two descriptions are
    competing for the same work. Which one wins on a given day is close to a
    coin toss. Winning is not the same as winning comfortably. Only the second
    kind survives a reworded request.

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
    log.info("%d skills on the table, plus the option of none of them: %s", len(catalog), sorted(catalog))
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
