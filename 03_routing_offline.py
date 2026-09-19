"""
Eval type 3: will the right skill get picked, judged by word overlap alone?

When you ask Claude Code to do something, it decides which skill to use by
reading every installed skill's name and description and comparing them with
what you typed. So before spending a penny on real runs, there is a cheaper
question worth asking: does this description contain the words a real person
would type, and does it stay clearly out of the way of the skills sitting next
to it?

This script answers that by counting words. Count the words in each
description, care less about words that every description happens to share,
and then score each description by how much its words overlap with the
request. Whichever scores highest wins. That is the whole method. The
technical name for it is TF-IDF cosine similarity, and if you already know the
term, this is the ordinary version of it.

Be clear about what this does not prove. The real software does not count
words, it has a model read the descriptions and decide. So passing here is not
proof the skill will trigger. But it costs nothing, it gives the same answer
every time, and it catches two genuine problems before you spend anything:

  Missing vocabulary. A request that should obviously go to your skill does
  not rank it first. That means your description is missing the words people
  actually use.

  Descriptions that clash. Two skills describe themselves so similarly that
  whichever gets picked is close to a coin toss.

03b_routing_semantic.py asks the same question by meaning rather than by
overlapping words. 04_trigger_eval.py is the real thing, against the real
software.

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

# Everything the chooser gets to pick between. The extra skills in
# fixtures/catalog are decoys, and they overlap with ours deliberately: all
# four of them are about git. A test where the right answer is obvious is not
# a test.
CATALOG_DIRS = [SKILL_DIR, *sorted((FIXTURES_DIR / "catalog").iterdir())]
OUR_SKILL = "commit-message"

# Requests that should land on our skill, and requests that should land
# somewhere else. Each of the second kind names the skill that ought to win
# instead. That turns "ours did not come first" into a real head-to-head
# question rather than a free pass for coming second to nobody in particular.
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

# Words so common they tell you nothing about what a request is for.
STOPWORDS = {"a", "an", "the", "and", "or", "for", "to", "of", "in", "on", "with", "this", "that", "is", "are",
             "be", "it", "its", "as", "at", "by", "from", "when", "use", "user", "asks"}


def stem(word: str) -> str:
    """Chop common endings off a word so related forms match each other.

    "summarised", "summarise" and "summarising" all become "summaris", which
    means a request using one form still matches a description using another.
    Proper tools do this far better. This is crude and good enough.

    Args:
        word: A single lowercase word.

    Returns:
        The word with one common ending removed, if removing it leaves at
        least three characters behind.

    Example:
        stem("summarising")  # "summaris"
    """
    for suffix in ("ing", "ed", "es", "s", "e"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    """Break text into the words worth comparing.

    Everything goes lowercase, endings get chopped off, and the very common
    words are thrown away.

    Args:
        text: Any text, such as a request or a description.

    Returns:
        The words left over, in the order they appeared.

    Example:
        tokens("Write a commit message")  # ["writ", "commit", "messag"]
    """
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def inverse_document_frequency(documents: dict[str, str]) -> dict[str, float]:
    """Work out how much each word is worth, based on how rare it is.

    A word that turns up in every description tells you nothing about which
    skill to pick. A word that turns up in only one is a strong hint. So each
    word gets a weight: the rarer it is across the whole set, the more it is
    worth.

    The weights are worked out once, from the descriptions only. A request is
    always scored against those weights, never against its own, or a request
    could invent its own importance.

    Args:
        documents: Each skill's name and description, keyed by skill name.

    Returns:
        A weight for each word, keyed by the word.

    Example:
        idf = inverse_document_frequency({"a": "commit message", "b": "changelog"})
    """
    doc_count = len(documents)
    df = Counter(word for text in documents.values() for word in set(tokens(text)))
    # The tiny number on the end stops a word that appears in every single
    # description from being worth exactly zero. Exactly zero would make it
    # disappear entirely, and disappearing has odd knock-on effects further down.
    return {word: math.log((1 + doc_count) / (1 + count)) + 1e-9 for word, count in df.items()}


def vectorize(text: str, idf: dict[str, float]) -> dict[str, float]:
    """Turn text into a bag of weighted words.

    Each word's score is how many times it appears, multiplied by how rare it
    is overall.

    A word in the request that appears in no description at all gets a default
    weight. It cannot match anything, so all it does is drag every score down
    by the same amount, which leaves the ranking unchanged.

    Args:
        text: The text to convert.
        idf: The word weights from inverse_document_frequency().

    Returns:
        A score per word, keyed by the word. Words not in the text are simply
        absent rather than zero.
    """
    tf = Counter(tokens(text))
    return {word: count * idf.get(word, 1.0) for word, count in tf.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Measure how much two bags of weighted words overlap.

    Length is deliberately ignored, so a long description is not favoured over
    a short one just for having more words in it.

    Args:
        a: The first bag of weighted words.
        b: The second.

    Returns:
        0 for nothing in common, 1 for identical. Anything above about 0.5
        means two descriptions are treading on each other.
    """
    dot = sum(a[w] * b.get(w, 0.0) for w in a)
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


def rank(prompt: str, vectors: dict[str, dict[str, float]], idf: dict[str, float]) -> list[tuple[str, float]]:
    """Put the skills in order of how well they match a request.

    Args:
        prompt: What the user typed.
        vectors: Each skill's bag of weighted words, keyed by skill name.
        idf: The word weights from inverse_document_frequency().

    Returns:
        Skill names paired with their scores, best match first.

    Example:
        rank("write a commit message", vectors, idf)[0]
    """
    query = vectorize(prompt, idf)
    scored = [(name, cosine(query, vec)) for name, vec in vectors.items()]
    return sorted(scored, key=lambda pair: -pair[1])


def main() -> int:
    configure_logging("03_routing_offline")
    show_skill()
    # The name is counted twice on purpose. Real choosers lean heavily on the
    # skill's name, so this ranking should lean on it too.
    catalog = {}
    for skill_dir in CATALOG_DIRS:
        skill = load_skill(skill_dir)
        catalog[skill.name] = f"{skill.name} {skill.name} {skill.description}"
        log.info("added %s to the list of candidates, %d useful words in its description",
                 skill.name, len(tokens(catalog[skill.name])))
    # >>> THIS COSTS NOTHING. No AI runs here and nothing goes over the
    #     network. The chooser is word counting in ordinary Python. 03b asks a
    #     model instead, and 04 runs the real thing.
    idf = inverse_document_frequency(catalog)
    vectors = {name: vectorize(text, idf) for name, text in catalog.items()}
    log.info("weighed up %d candidate skills and %d different words between them", len(catalog), len(idf))
    failures = 0

    section("requests that should land on our skill")
    rows = []
    for prompt in POSITIVE_PROMPTS:
        ranking = rank(prompt, vectors, idf)
        log.info("for the request %r the order came out: %s",
                 prompt, ", ".join(f"{n}={s:.2f}" for n, s in ranking))
        winner, score = ranking[0]
        ok = winner == OUR_SKILL
        failures += not ok
        rows.append([prompt, winner, score, ok])
    table("should land on our skill", ["the request", "what won", "score", "verdict"], rows)

    section("requests that belong to a different skill")
    rows = []
    for prompt, owner in NEGATIVE_PROMPTS:
        order = [name for name, _ in rank(prompt, vectors, idf)]
        log.info("for the request %r the order came out: %s", prompt, " > ".join(order))
        ok = order.index(owner) < order.index(OUR_SKILL)
        failures += not ok
        rows.append([prompt, order[0], owner, ok])
    table("should land elsewhere", ["the request", "what won", "who it belongs to", "verdict"], rows)

    section("descriptions that tread on each other")
    rows = []
    names = list(vectors)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            sim = cosine(vectors[a], vectors[b])
            if sim >= COLLISION_WARN:
                failures += sim >= COLLISION_ERROR
                rows.append([a, b, sim, "ERROR" if sim >= COLLISION_ERROR else "warn"])
    if rows:
        table("pairs of descriptions that overlap too much",
              ["one skill", "the other", "how similar", "how bad"], rows)
    else:
        note(f"No two descriptions overlap by more than {COLLISION_WARN:.0%}, so nothing is competing.")
    headline(f"{failures} things went wrong", good=failures == 0)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
