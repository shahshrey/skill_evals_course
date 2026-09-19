"""
Deterministic checks for the commit-message skill.

A deterministic check is a plain function: text in, pass or fail out, and the
same answer every time you run it. No model is involved. Several evals share
these checks (05, 06, 08, 10), so they live in one file.

Each check reports its own name and a short detail. That way a report can say
"subject_max_50 failed: 61 chars", which tells you what to fix in the skill.
"subject_max_50" is more useful than "score 0.7".
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

# These come straight from the Rules section of skills/commit-message/SKILL.md.
# If you change the skill, change these, then re-run 05_deterministic_grading.py:
# its first step proves the checks still accept a known-good message.
ALLOWED_TYPES = {"feat", "fix", "docs", "refactor", "test", "chore"}
ALLOWED_SCOPES = {"api", "web", "cli", "db", "infra"}
SUBJECT_MAX_CHARS = 50
BODY_MAX_LINE = 72

HEADER = re.compile(r"^(?P<type>[a-z]+)\((?P<scope>[a-z]+)\): (?P<subject>.+)$")
REFS_TRAILER = re.compile(r"^Refs: ACME-\d+$")
TEXT_FENCE = re.compile(r"```text\n(.*?)\n```", re.DOTALL)
ANY_FENCE = re.compile(r"```[a-z]*\n(.*?)\n```", re.DOTALL)


class CheckResult(BaseModel):
    name: str = Field(description="The rule that was checked, e.g. subject_max_50. Reports group by this.")
    passed: bool = Field(description="Whether the message satisfied the rule.")
    detail: str = Field(default="",
                        description="What the check saw, so a failure says why: the header, a length, a trailer.")


def extract_message(agent_text: str) -> str:
    """Pull the commit message out of the agent's reply.

    Rule 6 says it lives in a ```text fence, but we also accept any fence and,
    failing that, the whole reply. That leniency matters for the A/B eval: an
    agent that never saw the skill still deserves to be graded on the header
    and body rules, not failed outright for not knowing about the fence. The
    fence rule gets its own check below."""
    match = TEXT_FENCE.search(agent_text) or ANY_FENCE.search(agent_text)
    return match.group(1).strip() if match else agent_text.strip()


def check_commit_message(
    agent_text: str,
    expected_type: str | None = None,
    expected_scope: str | None = None,
) -> list[CheckResult]:
    """Run every rule we can check with code. Returns one result per rule.

    expected_type / expected_scope are per-case answers (a docs-only diff must
    be type "docs"). Leave them None when a case has no single right answer.
    """
    message = extract_message(agent_text)
    lines = message.splitlines() or [""]
    # We assume the layout the skill demands: header first, Refs trailer last,
    # body in between. A message with no trailer therefore loses its last body
    # line to the trailer slot and fails both refs_trailer and, if the body was
    # one line, has_body. That is fine: it was wrong either way.
    header, trailer = lines[0], lines[-1]
    body = [line for line in lines[1:-1] if line.strip()]

    results = [CheckResult(name="fenced_block", passed=TEXT_FENCE.search(agent_text) is not None,
                           detail="reply uses a ```text fence")]

    match = HEADER.match(header)
    results.append(CheckResult(name="header_format", passed=match is not None, detail=header))
    if match:
        commit_type, scope, subject = match["type"], match["scope"], match["subject"]
        results += [
            CheckResult(name="type_allowed", passed=commit_type in ALLOWED_TYPES, detail=commit_type),
            CheckResult(name="scope_allowed", passed=scope in ALLOWED_SCOPES, detail=scope),
            CheckResult(name="subject_max_50", passed=len(subject) <= SUBJECT_MAX_CHARS,
                        detail=f"{len(subject)} chars"),
            CheckResult(name="subject_starts_lowercase", passed=subject[0].islower(), detail=subject[:12]),
            CheckResult(name="subject_no_trailing_period", passed=not subject.endswith("."), detail=subject[-1]),
        ]
        if expected_type:
            results.append(CheckResult(name="expected_type", passed=commit_type == expected_type,
                                       detail=f"got {commit_type}, wanted {expected_type}"))
        if expected_scope:
            results.append(CheckResult(name="expected_scope", passed=scope == expected_scope,
                                       detail=f"got {scope}, wanted {expected_scope}"))

    results += [
        CheckResult(name="refs_trailer", passed=REFS_TRAILER.match(trailer) is not None, detail=trailer),
        CheckResult(name="has_body", passed=len(body) > 0, detail=f"{len(body)} body lines"),
        CheckResult(name="body_wrapped_72", passed=all(len(line) <= BODY_MAX_LINE for line in body),
                    detail=f"longest line {max((len(line) for line in body), default=0)} chars"),
    ]
    return results


def all_passed(results: list[CheckResult]) -> bool:
    return all(r.passed for r in results)


def failed_names(results: list[CheckResult]) -> list[str]:
    return [r.name for r in results if not r.passed]


# ---------------------------------------------------------------------------
# The cases every live eval runs. One entry per fixture diff, with the answer
# a careful engineer would give. Keep the list short: each live run costs
# real tokens, and 4 cases x 2 arms x N reps adds up fast.
# ---------------------------------------------------------------------------

COMMIT_CASES = [
    {"id": "api-paging", "diff": "diffs/add_paging_to_api_client.diff", "type": "feat", "scope": "api"},
    {"id": "web-null-email", "diff": "diffs/fix_null_email_in_web_signup.diff", "type": "fix", "scope": "web"},
    {"id": "cli-readme", "diff": "diffs/docs_cli_readme.diff", "type": "docs", "scope": "cli"},
    {"id": "db-migration-test", "diff": "diffs/test_db_migration.diff", "type": "test", "scope": "db"},
]


def commit_prompt(diff_text: str) -> str:
    """The user request for every case. It never mentions the skill by name;
    a prompt that says "use the commit-message skill" would test nothing."""
    return f"Write a commit message for this diff:\n\n{diff_text}"
