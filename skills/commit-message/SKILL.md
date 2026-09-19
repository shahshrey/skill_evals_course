---
name: commit-message
description: Writes git commit messages in the Acme house style. Use when the user asks for a commit message, says "write the commit", or pastes a diff or describes a set of changes and wants them summarised for git.
---

# Acme commit messages

Acme has a house style that differs from plain Conventional Commits. Follow it exactly.

## Format

```
<type>(<scope>): <subject>

<body>

Refs: ACME-<ticket>
```

## Rules

1. `type` must be one of: feat, fix, docs, refactor, test, chore.
2. `scope` is required and must be one of: api, web, cli, db, infra.
3. `subject` is imperative ("add", not "added"), starts lowercase, has no trailing period, and is at most 50 characters.
4. `body` explains why the change was made, not what changed. The diff already shows what. Wrap lines at 72 characters.
5. The `Refs:` trailer is required. If the user did not give a ticket number, use `ACME-0000`.
6. Output only the message, inside a single fenced code block marked `text`. No commentary before or after.
7. Never run `git commit`, `git add`, or any other git command that changes the repository. You write the message; the user commits.

## Procedure

1. Read the diff the user gave you. If they pointed at a file instead, read that file.
2. Pick the type and scope from the diff, not from the user's wording.
3. Write the message and return it in the fenced block.
