"""
Eval type 1: structural lint.

The cheapest eval there is. No model, no network, runs in milliseconds, so it
belongs in CI on every commit. It answers one question: is this SKILL.md
well-formed enough that a harness can even load it?

That sounds trivial until you see how skills fail in practice. A name that
does not match its folder never loads. A description with no "use when"
phrase never triggers. An unclosed code fence swallows half the instructions.
None of these show up as errors anywhere; the skill just silently does
nothing. Lint catches them for free.

The rules here come from the Agent Skills specification (agentskills.io) plus
a few checks that catch the mistakes people actually make:

  frontmatter: parses as YAML; name and description present; name is
      lowercase letters, digits and single hyphens, at most 64 characters,
      and equals the folder name; description at most 1024 characters and
      says when to use the skill; no keys outside the spec's list.
  body: not empty; under 500 lines; every ``` fence is closed; every
      scripts/, references/ or assets/ path it mentions exists.

Run:  python 01_structural_lint.py            # lints skills/commit-message
      python 01_structural_lint.py <dir>      # lints any skill folder
Exit code 1 if any rule at level "error" fails, so CI can gate on it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from skill_eval_common import HERE, SKILL_DIR, configure_logging, headline, log, section, show_skill, table

# Limits from the spec. Keep them as named numbers so a rule reads like prose.
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500
BODY_MAX_LINES = 500        # advisory in the spec; long bodies eat context

# Frontmatter keys the spec allows, plus the extra ones Claude Code documents.
# Anything else is a typo or a leftover from another tool's format (Cursor
# rules use "globs" and "alwaysApply").
SPEC_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
CLAUDE_CODE_KEYS = {"disable-model-invocation", "user-invocable", "argument-hint", "model",
                    "context", "agent", "hooks"}
KNOWN_KEYS = SPEC_KEYS | CLAUDE_CODE_KEYS

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Require a trigger phrase. A description that only says what the skill
# does, never when to use it, under-triggers badly.
TRIGGER_PHRASE = re.compile(r"\buse (this )?(skill )?when\b|\bwhen (the )?user\b", re.IGNORECASE)


class Finding(BaseModel):
    level: str = Field(description='"error" blocks the skill from passing; "warn" is advice.')
    rule: str = Field(description="Short id of the rule that fired, e.g. name_matches_folder.")
    message: str = Field(description="What was found and what to change.")


def lint_skill(skill_dir: Path) -> list[Finding]:
    findings: list[Finding] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return [Finding(level="error", rule="file_exists", message=f"{skill_md} not found")]

    text = skill_md.read_text()
    parts = text.split("---", 2)     # first two "---" only; the body may contain more
    if len(parts) < 3 or parts[0].strip():
        return [Finding(level="error", rule="frontmatter", message="file must start with a --- YAML block ---")]

    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        return [Finding(level="error", rule="frontmatter", message=f"YAML does not parse: {exc}")]
    body = parts[2]
    log.info("frontmatter keys: %s | body: %d lines", sorted(frontmatter), len(body.splitlines()))

    findings += lint_frontmatter(frontmatter, skill_dir.name)
    findings += lint_body(body, skill_dir)
    return findings


def lint_frontmatter(fm: dict, folder_name: str) -> list[Finding]:
    findings = []
    name = str(fm.get("name", ""))
    description = str(fm.get("description", ""))

    if not name:
        findings.append(Finding(level="error", rule="name_required", message="frontmatter needs a name"))
    elif not NAME_PATTERN.match(name):
        findings.append(Finding(level="error", rule="name_format",
                                message=f"name {name!r} must be lowercase letters, digits and single hyphens"))
    elif len(name) > NAME_MAX:
        findings.append(Finding(level="error", rule="name_length",
                                message=f"name is {len(name)} chars, max {NAME_MAX}"))
    if name and name != folder_name:
        findings.append(Finding(level="error", rule="name_matches_folder",
                                message=f"name {name!r} but folder is {folder_name!r}; the spec says they must match"))

    if not description.strip():
        findings.append(Finding(level="error", rule="description_required", message="frontmatter needs a description"))
    elif len(description) > DESCRIPTION_MAX:
        findings.append(Finding(level="error", rule="description_length",
                                message=f"description is {len(description)} chars, max {DESCRIPTION_MAX}"))
    elif not TRIGGER_PHRASE.search(description):
        findings.append(Finding(level="warn", rule="description_trigger_phrase",
                                message="description never says when to use the skill; add a 'Use when ...' sentence"))
    if description and len(description) < 40:
        findings.append(Finding(level="warn", rule="description_too_short",
                                message=f"{len(description)} chars is too little for the model to route on"))

    if len(str(fm.get("compatibility", ""))) > COMPATIBILITY_MAX:
        findings.append(Finding(level="error", rule="compatibility_length",
                                message=f"compatibility exceeds {COMPATIBILITY_MAX} chars"))
    if "metadata" in fm and not all(isinstance(v, str) for v in (fm["metadata"] or {}).values()):
        findings.append(Finding(level="error", rule="metadata_values", message="metadata values must all be strings"))

    for key in fm.keys() - KNOWN_KEYS:
        findings.append(Finding(level="warn", rule="unknown_key",
                                message=f"frontmatter key {key!r} is not in the spec"))
    return findings


def lint_body(body: str, skill_dir: Path) -> list[Finding]:
    findings = []
    lines = body.splitlines()

    if not body.strip():
        findings.append(Finding(level="error", rule="body_empty",
                                message="there are no instructions after the frontmatter"))
    if len(lines) > BODY_MAX_LINES:
        findings.append(Finding(level="warn", rule="body_length",
                                message=f"{len(lines)} lines; move detail into references/ and link to it"))
    if body.count("```") % 2 == 1:
        findings.append(Finding(level="error", rule="unclosed_code_fence", message="odd number of ``` fences"))

    # A skill that tells the agent to run scripts/foo.py had better ship it.
    for referenced in re.findall(r"\b(scripts|references|assets)/[\w./-]+", body):
        if not (skill_dir / referenced).exists():
            findings.append(Finding(level="error", rule="missing_referenced_file",
                                    message=f"{referenced} is mentioned but absent"))
    return findings


def main() -> int:
    configure_logging("01_structural_lint")
    skill_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else SKILL_DIR
    log.info("linting %s", skill_dir)
    show_skill(skill_dir)
    # >>> NO LIVE CALL: this file never runs the CLI or a model. lint_skill()
    #     is plain Python reading SKILL.md.
    findings = lint_skill(skill_dir)
    errors = [f for f in findings if f.level == "error"]
    log.info("checked frontmatter and body: %d findings (%d errors)", len(findings), len(errors))

    shown = skill_dir.relative_to(HERE) if skill_dir.is_relative_to(HERE) else skill_dir
    section(f"lint results for {shown}")
    if findings:
        table("findings", ["level", "rule", "message"], [[f.level, f.rule, f.message] for f in findings])
    headline(f"{len(errors)} errors, {len(findings) - len(errors)} warnings", good=not errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
