"""
Eval type 3: offline routing test.

Harnesses pick a skill by reading every installed skill's name and
description and matching them against the user's request. So before you spend
a single model call, you can ask a cheaper question: does this description
contain the words a user would actually type, and does it stay clearly apart
from neighbouring skills?

This file answers that with TF-IDF cosine similarity. In plain words: count the
words in each description, give less weight to words every description
shares, and score each description by how much its word-bag overlaps the
prompt's. The "router" below is just that ranking. It is not how the real
harness routes (that is a model reading the descriptions), so a pass here is
not proof of triggering. But it is free and deterministic, and it catches two
real problems early:

  1. vocabulary gaps: the positive prompts do not rank the skill first, so
     the description is missing the words users say;
  2. collisions: two descriptions are so similar that the router will flip
     between them.

03b_routing_semantic.py asks the same question by meaning instead of word
overlap, and 04_trigger_eval.py is the live version against the real harness.

Run:  python 03_routing_offline.py
"""

from __future__ import annotations

import math
import re
import sys
from collections import Counter

from skill_eval_common import (
    FIXTURES_DIR,
    SKILL_DIR,
    configure_logging,
    headline,
    load_skill,
    log,
    note,
    section,
    show_skill,
    table,
)

# The catalog is every skill the router could choose from. The decoys in
# fixtures/catalog overlap with ours on purpose (all four talk about git).
CATALOG_DIRS = [SKILL_DIR, *sorted((FIXTURES_DIR / "catalog").iterdir())]
OUR_SKILL = "commit-message"

# Prompts that should route to our skill, and prompts that should route
# elsewhere. A negative names the skill that ought to win instead: that turns
# "we did not come first" into a real pairwise test rather than a free pass.
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
]
COLLISION_WARN, COLLISION_ERROR = 0.50, 0.75

STOPWORDS = {"a", "an", "the", "and", "or", "for", "to", "of", "in", "on", "with", "this", "that", "is", "are",
             "be", "it", "its", "as", "at", "by", "from", "when", "use", "user", "asks"}


def stem(word: str) -> str:
    """Crude suffix stripping so "summarised", "summarise" and "summarising"
    all become "summaris". Real stemmers do better; this is enough to route."""
    for suffix in ("ing", "ed", "es", "s", "e"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    """Lowercase, stemmed words with stopwords removed."""
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def inverse_document_frequency(documents: dict[str, str]) -> dict[str, float]:
    """Words that appear in every description carry no signal, so weight each
    word by how rare it is across the catalog. Computed once, from the catalog
    only; the query is scored against the catalog's idf, never its own."""
    doc_count = len(documents)
    df = Counter(word for text in documents.values() for word in set(tokens(text)))
    # The tiny epsilon keeps a word that appears in every description from
    # weighing exactly zero, which would make it vanish from every vector.
    return {word: math.log((1 + doc_count) / (1 + count)) + 1e-9 for word, count in df.items()}


def vectorize(text: str, idf: dict[str, float]) -> dict[str, float]:
    """Sparse vector: term frequency times idf. A prompt word no description
    contains gets a default weight; it cannot match anything, so it only
    scales every score down a little and never changes the ranking."""
    tf = Counter(tokens(text))
    return {word: count * idf.get(word, 1.0) for word, count in tf.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(a[w] * b.get(w, 0.0) for w in a)
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


def rank(prompt: str, vectors: dict[str, dict[str, float]], idf: dict[str, float]) -> list[tuple[str, float]]:
    """Skills ordered by similarity to the prompt, best first."""
    query = vectorize(prompt, idf)
    scored = [(name, cosine(query, vec)) for name, vec in vectors.items()]
    return sorted(scored, key=lambda pair: -pair[1])


def main() -> int:
    configure_logging("03_routing_offline")
    show_skill()
    # Name counts double: routers weight the name heavily, so the ranking should too.
    catalog = {}
    for skill_dir in CATALOG_DIRS:
        skill = load_skill(skill_dir)
        catalog[skill.name] = f"{skill.name} {skill.name} {skill.description}"
        log.info("catalog: %s -> %d tokens", skill.name, len(tokens(catalog[skill.name])))
    # >>> NO LIVE CALL: this file never runs the CLI or a model. The "router"
    #     is word counting in plain Python. 03b asks a model instead, and 04
    #     runs the real CLI.
    idf = inverse_document_frequency(catalog)
    vectors = {name: vectorize(text, idf) for name, text in catalog.items()}
    log.info("built idf over %d skills, %d distinct words", len(catalog), len(idf))
    failures = 0

    section("positive prompts: our skill should rank first")
    rows = []
    for prompt in POSITIVE_PROMPTS:
        ranking = rank(prompt, vectors, idf)
        log.info("ranking for %r: %s", prompt, ", ".join(f"{n}={s:.2f}" for n, s in ranking))
        winner, score = ranking[0]
        ok = winner == OUR_SKILL
        failures += not ok
        rows.append([prompt, winner, score, ok])
    table("positives", ["prompt", "ranked first", "score", "verdict"], rows)

    section("negative prompts: the owner should outrank our skill")
    rows = []
    for prompt, owner in NEGATIVE_PROMPTS:
        order = [name for name, _ in rank(prompt, vectors, idf)]
        log.info("ranking for %r: %s", prompt, " > ".join(order))
        ok = order.index(owner) < order.index(OUR_SKILL)
        failures += not ok
        rows.append([prompt, order[0], owner, ok])
    table("negatives", ["prompt", "ranked first", "owner", "verdict"], rows)

    section("collisions between descriptions")
    rows = []
    names = list(vectors)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            sim = cosine(vectors[a], vectors[b])
            if sim >= COLLISION_WARN:
                failures += sim >= COLLISION_ERROR
                rows.append([a, b, sim, "ERROR" if sim >= COLLISION_ERROR else "warn"])
    if rows:
        table("pairs above the warning threshold", ["skill", "skill", "similarity", "level"], rows)
    else:
        note(f"no pair of descriptions above {COLLISION_WARN:.2f} similarity")
    headline(f"{failures} failures", good=failures == 0)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
