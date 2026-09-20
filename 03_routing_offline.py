"""
Chapter three: your skill is fine. Nobody is calling it.

The file loads and it is not hostile. Two boxes ticked. Neither is the one
that keeps people up at night. The real worry is quieter. Your skill sits in
a folder next to four other skills. Someone types a request. Something has to
decide which of you gets it. If that goes the wrong way, everything you wrote
below the description might as well be a diary.

Here is how the decision gets made. Claude Code reads every installed skill's
name and description, compares them against what the user typed, and picks.
Your description is not documentation. It is the pitch. It is the only part
of your skill that competes.

Before you spend money finding out how the pitch lands, you can ask a cheaper
version of the question with arithmetic. Does the description contain the
words a real person would type? Does it stay out of the way of the skills
next to it?

The method is word counting. Count the words in each description. Care less
about the words every description shares. Score each one by how much it
overlaps with the request. Highest score wins. The technical name is TF-IDF
cosine similarity. If that term means something to you, this is the plain
version of it.

Be honest about what this does not prove. The real software does not count
words. It hands the descriptions to a model and lets the model choose. So
passing here proves nothing. But it is free, it gives the same answer every
time, and it catches two problems worth catching early:

  Missing vocabulary. A request that should be yours does not rank you first.
  Your description is missing the words people use.

  Descriptions that clash. Two skills describe themselves so alike that the
  winner is close to a coin toss. Coin tosses are not a feature.

The decoys in fixtures/catalog are all about git, on purpose. A test where
the right answer is obvious is not a test.

Next door, 03b_routing_semantic.py asks the same question by meaning instead
of by matching letters. That catches the case where your words are right and
your vocabulary is wrong. 04_trigger_eval.py stops guessing and asks the real
software. That one costs money.

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

# Everyone in the room when the decision gets made. The extra skills in
# fixtures/catalog are decoys. Every one is about git, because that is the
# situation you are in.
CATALOG_DIRS = [SKILL_DIR, *sorted((FIXTURES_DIR / "catalog").iterdir())]
OUR_SKILL = "commit-message"

# Requests that should land on our skill, and requests that should land
# elsewhere. Each of the second kind names the skill that ought to win. That
# turns "ours did not come first" into a head-to-head result.
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

# Words so common that knowing a request contains one tells you nothing.
STOPWORDS = {"a", "an", "the", "and", "or", "for", "to", "of", "in", "on", "with", "this", "that", "is", "are",
             "be", "it", "its", "as", "at", "by", "from", "when", "use", "user", "asks"}


def stem(word: str) -> str:
    """Chop common endings off a word so related forms match each other.

    "summarised", "summarise" and "summarising" all become "summaris". A
    request in one form still matches a description in another. Proper tools
    do this far better. This one is crude, and readable. Crude and readable
    beats clever and impossible to debug.

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

    A word in every description cannot tell you which skill to pick. A word in
    exactly one is close to a signature. So each word gets a weight. The rarer
    it is across the set, the more it counts. This is why "git" does you less
    good in your description than you think.

    The weights come from the descriptions and nothing else. A request gets
    scored against those weights, never against weights of its own. Otherwise
    a request could talk up its own words.

    Args:
        documents: Each skill's name and description, keyed by skill name.

    Returns:
        A weight for each word, keyed by the word.

    Example:
        idf = inverse_document_frequency({"a": "commit message", "b": "changelog"})
    """
    doc_count = len(documents)
    df = Counter(word for text in documents.values() for word in set(tokens(text)))
    # The tiny number on the end keeps a word that appears in every
    # description from being worth exactly zero. Zero makes it vanish. Things
    # that vanish cause odd behaviour three functions later.
    return {word: math.log((1 + doc_count) / (1 + count)) + 1e-9 for word, count in df.items()}


def vectorize(text: str, idf: dict[str, float]) -> dict[str, float]:
    """Turn text into a bag of weighted words.

    Each word's score is how many times it appears, multiplied by how rare it
    is overall.

    A word in the request that appears in no description still gets a weight.
    It cannot match anything. All it does is pull every score down by the
    same amount. The order comes out the same.

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

    Length is thrown away on purpose. Otherwise the longest description wins
    every time by containing more words. You would have written a test that
    rewards padding.

    Args:
        a: The first bag of weighted words.
        b: The second.

    Returns:
        0 for nothing in common, 1 for identical. Above about 0.5 and two
        descriptions are standing on each other's feet.
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
    # The name counts twice on purpose. Real choosers lean hard on the skill's
    # name, so this one leans on it too.
    catalog = {}
    for skill_dir in CATALOG_DIRS:
        skill = load_skill(skill_dir)
        catalog[skill.name] = f"{skill.name} {skill.name} {skill.description}"
        log.info("%s joins the lineup with %d words worth counting",
                 skill.name, len(tokens(catalog[skill.name])))
    # >>> THIS COSTS NOTHING. No AI runs here and nothing goes over the
    #     network. The chooser is word counting in ordinary Python. 03b hands
    #     the same job to a model. 04 asks the real software.
    idf = inverse_document_frequency(catalog)
    vectors = {name: vectorize(text, idf) for name, text in catalog.items()}
    log.info("%d skills in the running, %d different words between them. Each word is now weighted by how rare "
             "it is", len(catalog), len(idf))
    failures = 0

    section("requests that should land on our skill")
    rows = []
    for prompt in POSITIVE_PROMPTS:
        ranking = rank(prompt, vectors, idf)
        log.info("someone types %r. The ranking comes out: %s",
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
        log.info("someone types %r. Not ours. The order comes out: %s", prompt, " > ".join(order))
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
        note(f"No two descriptions overlap by more than {COLLISION_WARN:.0%}. Nobody is competing for anybody "
             "else's work.")
    headline(f"{failures} things went wrong", good=failures == 0)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
