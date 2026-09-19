"""
The plain code checks for the commit-message skill.

A plain check is an ordinary function. Text goes in, pass or fail comes out,
and you get the same answer every single time you run it. No AI is involved
anywhere, which is what makes these worth having: they cost nothing, they are
instant, and they never change their mind.

Four of the tests share these checks (05, 06, 08 and 10), so they live here in
one file rather than being copied four times.

Every check reports its own name and a short note about what it saw. That way
a report can say "subject_max_50 failed: 61 characters" instead of "score
0.7". The first tells you what to change in the skill. The second tells you
nothing at all.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

# These are lifted straight from the Rules section of
# skills/commit-message/SKILL.md. Change the skill and you must change these
# too, then run 05_deterministic_grading.py. Its first step feeds the checks a
# message known to be correct and refuses to go on if they reject it.
ALLOWED_TYPES = {"feat", "fix", "docs", "refactor", "test", "chore"}
ALLOWED_SCOPES = {"api", "web", "cli", "db", "infra"}
SUBJECT_MAX_CHARS = 50
BODY_MAX_LINE = 72

HEADER = re.compile(r"^(?P<type>[a-z]+)\((?P<scope>[a-z]+)\): (?P<subject>.+)$")
REFS_TRAILER = re.compile(r"^Refs: ACME-\d+$")
TEXT_FENCE = re.compile(r"```text\n(.*?)\n```", re.DOTALL)
ANY_FENCE = re.compile(r"```[a-z]*\n(.*?)\n```", re.DOTALL)


class CheckResult(BaseModel):
    """The outcome of one check."""

    name: str = Field(description="Which rule was checked, such as subject_max_50. Reports group on this.")
    passed: bool = Field(description="Did the message satisfy the rule?")
    detail: str = Field(default="",
                        description="What the check actually saw, so a failure explains itself: the header it "
                                    "read, the length it counted, the last line it found.")


def extract_message(agent_text: str) -> str:
    """Pull the commit message out of whatever the agent wrote around it.

    Rule 6 of the skill says the message belongs in a ```text block. This
    function is more forgiving than that: it takes a text block if there is
    one, any other kind of code block if not, and failing both, the whole
    reply.

    That leniency matters for the head-to-head comparison. An agent that never
    saw the skill has no idea it was meant to use a text block, and failing it
    outright would tell you nothing about whether it can write a good commit
    message. So the block rule is checked separately, on its own, and
    everything else gets marked on the message itself.

    Args:
        agent_text: The agent's full reply.

    Returns:
        The commit message, with surrounding whitespace removed.

    Example:
        extract_message("Here you go:\\n```text\\nfix(web): ...\\n```")
    """
    match = TEXT_FENCE.search(agent_text) or ANY_FENCE.search(agent_text)
    return match.group(1).strip() if match else agent_text.strip()


def check_commit_message(
    agent_text: str,
    expected_type: str | None = None,
    expected_scope: str | None = None,
) -> list[CheckResult]:
    """Run every rule that can be checked without an AI.

    Args:
        agent_text: The agent's full reply. The message is pulled out of it.
        expected_type: The correct type for this particular set of changes,
            such as "docs" for a documentation-only change. Leave it out when
            more than one answer would be defensible.
        expected_scope: The correct scope for this particular set of changes,
            such as "cli". Leave it out for the same reason.

    Returns:
        One result per rule. Some rules only run when an earlier one passed,
        because you cannot check the format of a header that is not there.

    Example:
        results = check_commit_message(reply, "docs", "cli")
        if not all_passed(results):
            print(failed_names(results))
    """
    message = extract_message(agent_text)
    lines = message.splitlines() or [""]
    # We take the layout the skill asks for as given: header on the first line,
    # the Refs line last, and the body in between. A message with no Refs line
    # therefore loses its final body line to the Refs slot, and fails both the
    # refs_trailer check and, if the body was only one line, has_body. That is
    # a little unfair on paper and entirely fine in practice, because such a
    # message was going to fail anyway.
    header, trailer = lines[0], lines[-1]
    body = [line for line in lines[1:-1] if line.strip()]

    results = [CheckResult(name="fenced_block", passed=TEXT_FENCE.search(agent_text) is not None,
                           detail="the reply wraps the message in a ```text block")]

    match = HEADER.match(header)
    results.append(CheckResult(name="header_format", passed=match is not None, detail=header))
    if match:
        commit_type, scope, subject = match["type"], match["scope"], match["subject"]
        results += [
            CheckResult(name="type_allowed", passed=commit_type in ALLOWED_TYPES, detail=commit_type),
            CheckResult(name="scope_allowed", passed=scope in ALLOWED_SCOPES, detail=scope),
            CheckResult(name="subject_max_50", passed=len(subject) <= SUBJECT_MAX_CHARS,
                        detail=f"{len(subject)} characters"),
            CheckResult(name="subject_starts_lowercase", passed=subject[0].islower(), detail=subject[:12]),
            CheckResult(name="subject_no_trailing_period", passed=not subject.endswith("."), detail=subject[-1]),
        ]
        if expected_type:
            results.append(CheckResult(name="expected_type", passed=commit_type == expected_type,
                                       detail=f"wrote {commit_type}, should have been {expected_type}"))
        if expected_scope:
            results.append(CheckResult(name="expected_scope", passed=scope == expected_scope,
                                       detail=f"wrote {scope}, should have been {expected_scope}"))

    results += [
        CheckResult(name="refs_trailer", passed=REFS_TRAILER.match(trailer) is not None, detail=trailer),
        CheckResult(name="has_body", passed=len(body) > 0, detail=f"{len(body)} lines of body text"),
        CheckResult(name="body_wrapped_72", passed=all(len(line) <= BODY_MAX_LINE for line in body),
                    detail=f"longest line is {max((len(line) for line in body), default=0)} characters"),
    ]
    return results


def all_passed(results: list[CheckResult]) -> bool:
    """Did every check pass?

    Args:
        results: What check_commit_message() returned.

    Returns:
        True only when nothing failed. One failure fails the message.
    """
    return all(r.passed for r in results)


def failed_names(results: list[CheckResult]) -> list[str]:
    """List the checks that failed.

    Args:
        results: What check_commit_message() returned.

    Returns:
        The name of each failed check, in the order they ran. Empty when
        everything passed.
    """
    return [r.name for r in results if not r.passed]


# ---------------------------------------------------------------------------
# The test cases that every live test runs.
#
# One entry per sample set of changes, paired with the answer a careful
# engineer would give. Keeping this list short is deliberate. Every live run
# costs real money, and 4 cases times 2 sides times however many attempts adds
# up faster than you would like.
# ---------------------------------------------------------------------------

COMMIT_CASES = [
    {"id": "api-paging", "diff": "diffs/add_paging_to_api_client.diff", "type": "feat", "scope": "api"},
    {"id": "web-null-email", "diff": "diffs/fix_null_email_in_web_signup.diff", "type": "fix", "scope": "web"},
    {"id": "cli-readme", "diff": "diffs/docs_cli_readme.diff", "type": "docs", "scope": "cli"},
    {"id": "db-migration-test", "diff": "diffs/test_db_migration.diff", "type": "test", "scope": "db"},
]


def commit_prompt(diff_text: str) -> str:
    """Build the request we send the agent for every case.

    It never mentions the skill by name. Asking the agent to "use the
    commit-message skill" would prove nothing, because the whole question is
    whether it reaches for the skill on its own.

    Args:
        diff_text: The code changes to write a message about.

    Returns:
        The request, worded the way a real user would word it.

    Example:
        commit_prompt(read_fixture("diffs/docs_cli_readme.diff"))
    """
    return f"Write a commit message for this diff:\n\n{diff_text}"
