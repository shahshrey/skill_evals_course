"""
Eval type 3, variant b: semantic routing with a fast typed model.

03_routing_offline.py ranks skills by word overlap. That is free and catches
missing vocabulary, but it cannot tell that "summarise my changes for git"
and "write a commit message" mean the same thing. The real harness can,
because a model reads the descriptions. 04_trigger_eval.py tests that model
directly, at the cost of one full agent run per prompt per rep.

This file sits in between. It hands the whole catalog of descriptions and
one prompt to a System One model (Jev) and asks a single Choice question:
which skill should handle this? It understands meaning, so it catches what
word overlap misses, and it answers in about a tenth of a second, so you can
run every prompt on every edit to the description. It is still not the real
harness, so 04 remains the final word; but a description that fails here
will fail there too, and you find out for free.

The Choice comes back with a probability for every option. That is more
than a winner:

  - a high probability for the right skill means the description is clear;
  - probability split between two skills means their descriptions compete,
    which is the collision 03 looks for, found semantically instead of by
    word counts;
  - probability on "none" for a negative prompt means the description does
    not overreach.

Needs TYPESAFE_API_KEY in the environment or in .env.

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
NONE = "none"                 # the option for "no installed skill applies"

# Same shape as 03: positives should route to our skill, negatives to their
# rightful owner. Two negatives belong to no skill at all, which 03 could
# not express; a router that always picks something would fail them.
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
COLLISION_SHARE = 0.30        # a runner-up this likely means two descriptions compete


def route(client: TypeSafeClient, prompt: str, catalog: dict[str, str]) -> tuple[str, dict[str, float]]:
    """Ask which skill the prompt belongs to. Returns the pick and the full
    probability distribution over skills plus "none"."""
    criteria = dict(catalog)
    criteria[NONE] = "No installed skill applies to this request."
    # >>> LIVE CALL: one HTTP request to TypeSafe's Jev model with the whole
    #     catalog as state. It picks a skill and gives a probability for each.
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
    log.info("router picked %s (confidence %.2f) for %r: %s", answer.choice, answer.confidence, prompt, probabilities)
    return answer.choice, probabilities


def runner_up_share(probabilities: dict[str, float], winner: str) -> tuple[str, float]:
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
    log.info("catalog of %d skills: %s", len(catalog), sorted(catalog))
    client = TypeSafeClient()
    failures = 0

    section("positive prompts: our skill should win")
    rows = []
    for prompt in POSITIVE_PROMPTS:
        pick, probabilities = route(client, prompt, catalog)
        ok = pick == OUR_SKILL
        failures += not ok
        second, share = runner_up_share(probabilities, pick)
        collision = f"{second} at {share:.2f}" if share >= COLLISION_SHARE else "-"
        rows.append([prompt, pick, probabilities.get(OUR_SKILL, 0.0), collision, ok])
    table("positives", ["prompt", "picked", "p(ours)", "runner-up", "verdict"], rows)

    section("negative prompts: the owner should win, or none")
    rows = []
    for prompt, owner in NEGATIVE_PROMPTS:
        pick, probabilities = route(client, prompt, catalog)
        ok = pick == owner
        failures += not ok
        rows.append([prompt, pick, owner, probabilities.get(OUR_SKILL, 0.0), ok])
    table("negatives", ["prompt", "picked", "owner", "p(ours)", "verdict"], rows)

    headline(f"{failures} failures", good=failures == 0)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
