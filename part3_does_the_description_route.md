# Part 3: Does the description route?

**Cost:** Free (offline) + Jev calls (semantic)

---

The file loads and it's not hostile. Two boxes ticked. Neither is the one that keeps people up at night.

The real worry is quieter. Your skill sits in a folder next to four other skills. Someone types a request. Something has to decide which of you gets it. If that goes the wrong way, everything you wrote below the description might as well be a diary.

## How the decision gets made

Claude Code reads every installed skill's name and description, compares them against what the user typed, and picks. Your description is not documentation. It's the pitch. It's the only part of your skill that competes.

Before you spend money finding out how the pitch lands, you can ask a cheaper version of the question.

## Part 3a: Offline routing (TF-IDF)

The method is word counting. Count the words in each description. Care less about words every description shares. Score each one by how much it overlaps with the request. Highest score wins.

The technical name is TF-IDF cosine similarity. If that means something to you, this is the plain version.

### What this catches

**Missing vocabulary.** A request that should be yours doesn't rank you first. Your description is missing the words people use.

**Descriptions that clash.** Two skills describe themselves so alike that the winner is close to a coin toss. Coin tosses are not a feature.

### What this doesn't prove

The real software doesn't count words. It hands the descriptions to a model and lets the model choose. Passing here proves nothing. But it's free, it gives the same answer every time, and it catches problems worth catching early.

### The fixtures

`fixtures/catalog/` has three decoy skills, all about git, on purpose. A test where the right answer is obvious is not a test.

```python
ROUTING_POSITIVES = [
    "Write me a commit message for this diff",
    "Summarize these changes for git",
    # ...
]

ROUTING_NEGATIVES = [
    ("git-help", "How do I rebase onto main?"),
    ("pr-description", "Write a PR description for this branch"),
    # ...
]
```

---

## Part 3b: Semantic routing (Jev)

Same question, asked by something that reads.

Jev, from TypeSafe, takes a prompt and a list of skill descriptions. It returns probabilities: how likely is each skill to be the right choice? A tenth of a second, a fraction of a penny.

### Why probabilities matter

A model that picks "commit-message" with 0.95 confidence and one that picks it at 0.51 are not the same. The second one is a coin flip away from picking something else. Keep the number. Put the threshold in your own code.

### Cross-checking

Run the same prompts through both methods. Where they disagree, one of them is wrong. The only way to find out which is to read the prompt yourself.

### What the stored run found

The offline routing test once caught a real vocabulary gap. "summarize these changes for git" routed to the git-help decoy because the description never said "changes". Adding the word fixed it.

Jev agrees on every prompt, with probabilities near 0.00 on ours for the ones that belong elsewhere.

---

## Run it

### Offline (free)

```python
configure_logging("03_routing_offline")
# ... builds catalog, runs positives and negatives
```

Logs go to `logs/03_routing_offline.log`.

### Semantic (Jev)

Needs `TYPESAFE_API_KEY` in your environment or `.env` file.

```python
configure_logging("03b_routing_semantic")
# ... same prompts, but scored by meaning
```

Logs go to `logs/03b_routing_semantic.log`.

---

[Previous: Part 2 - Is the skill hostile?](part2_is_the_skill_hostile.md) | [Next: Part 4 - Does the real harness trigger it?](part4_does_the_real_harness_trigger_it.md)
