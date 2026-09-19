"""
Eval type 1: is the file even put together properly?

The cheapest test in this folder by a mile. No AI, nothing over the network,
finished in a few thousandths of a second. It belongs in your automated checks
on every commit. It asks one question: is this SKILL.md well-formed enough
that the software can load it at all?

That sounds too basic to bother with until you see how skills fail in real
life. A skill whose name does not match its folder never loads. A description
that never says when to use the skill never gets picked. One unclosed code
fence swallows half the instructions below it. Not one of these produces an
error message anywhere. The skill just quietly does nothing, and you spend an
afternoon wondering why the agent is ignoring you.

The rules come from the Agent Skills specification at agentskills.io, plus a
few extra checks for the mistakes people actually make.

What gets checked in the settings block at the top:
  it parses as YAML at all; name and description are both there; the name is
  lowercase letters, digits and single hyphens, no longer than 64 characters,
  and matches the folder name; the description is under 1024 characters and
  says when to use the skill; no settings that are not in the specification.

What gets checked in the instructions below:
  they are not empty; under 500 lines; every ``` fence has a matching close;
  every file the instructions point at actually exists.

Run:  python 01_structural_lint.py            # checks skills/commit-message
      python 01_structural_lint.py <dir>      # checks any skill folder
Exits with code 1 if anything serious is wrong, so your build can stop on it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from skill_eval_common import HERE, SKILL_DIR, configure_logging, headline, log, section, show_skill, table

# Limits from the specification. Named rather than typed inline, so the rules
# below read like sentences instead of arithmetic.
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500
BODY_MAX_LINES = 500        # the spec only advises this. Long instructions crowd out everything else

# The settings the specification allows, plus the extra ones Claude Code adds.
# Anything outside these two sets is either a typo or a leftover from a
# different tool's format. Cursor rules, for instance, use "globs" and
# "alwaysApply", and they do nothing here.
SPEC_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
CLAUDE_CODE_KEYS = {"disable-model-invocation", "user-invocable", "argument-hint", "model",
                    "context", "agent", "hooks"}
KNOWN_KEYS = SPEC_KEYS | CLAUDE_CODE_KEYS

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# The description has to say when to use the skill, not only what it does.
# One that only describes itself gets picked far too rarely.
TRIGGER_PHRASE = re.compile(r"\buse (this )?(skill )?when\b|\bwhen (the )?user\b", re.IGNORECASE)


class Finding(BaseModel):
    """One problem found in the skill file."""

    level: str = Field(description='"error" means the skill fails this test. "warn" is advice you can ignore.')
    rule: str = Field(description="Short name of the rule that fired, such as name_matches_folder.")
    message: str = Field(description="What was found, and what to change to fix it.")


def lint_skill(skill_dir: Path) -> list[Finding]:
    """Check one skill folder and report everything wrong with it.

    Args:
        skill_dir: Folder that should contain a SKILL.md.

    Returns:
        Every problem found, worst first is not guaranteed. An empty list means
        the file is in good shape. Problems bad enough to stop the parse are
        returned on their own, since nothing else can be checked after them.

    Example:
        findings = lint_skill(Path("skills/commit-message"))
    """
    findings: list[Finding] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return [Finding(level="error", rule="file_exists", message=f"{skill_md} not found")]

    text = skill_md.read_text()
    # Split on the first two "---" lines only. The instructions below often
    # contain their own dividers, and those must not confuse the split.
    parts = text.split("---", 2)
    if len(parts) < 3 or parts[0].strip():
        return [Finding(level="error", rule="frontmatter",
                        message="the file must open with a settings block wrapped in --- lines")]

    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        return [Finding(level="error", rule="frontmatter", message=f"the settings block is not valid YAML: {exc}")]
    body = parts[2]
    log.info("settings found: %s. Instructions are %d lines long.", sorted(frontmatter), len(body.splitlines()))

    findings += lint_frontmatter(frontmatter, skill_dir.name)
    findings += lint_body(body, skill_dir)
    return findings


def lint_frontmatter(fm: dict, folder_name: str) -> list[Finding]:
    """Check the settings block at the top of the file.

    Args:
        fm: The settings, already parsed from YAML.
        folder_name: Name of the folder the file sits in. The name setting has
            to match it, or the skill never loads.

    Returns:
        Every problem found in the settings.
    """
    findings = []
    name = str(fm.get("name", ""))
    description = str(fm.get("description", ""))

    if not name:
        findings.append(Finding(level="error", rule="name_required", message="the settings block needs a name"))
    elif not NAME_PATTERN.match(name):
        findings.append(Finding(level="error", rule="name_format",
                                message=f"the name {name!r} may only contain lowercase letters, digits and "
                                        "single hyphens"))
    elif len(name) > NAME_MAX:
        findings.append(Finding(level="error", rule="name_length",
                                message=f"the name is {len(name)} characters. The limit is {NAME_MAX}"))
    if name and name != folder_name:
        findings.append(Finding(level="error", rule="name_matches_folder",
                                message=f"the name says {name!r} but the folder is called {folder_name!r}. The "
                                        "specification requires them to match, and a skill that fails this "
                                        "never loads"))

    if not description.strip():
        findings.append(Finding(level="error", rule="description_required",
                                message="the settings block needs a description"))
    elif len(description) > DESCRIPTION_MAX:
        findings.append(Finding(level="error", rule="description_length",
                                message=f"the description is {len(description)} characters. The limit is "
                                        f"{DESCRIPTION_MAX}"))
    elif not TRIGGER_PHRASE.search(description):
        findings.append(Finding(level="warn", rule="description_trigger_phrase",
                                message="the description never says when to use the skill. Add a sentence "
                                        "starting 'Use when ...' or it will rarely get picked"))
    if description and len(description) < 40:
        findings.append(Finding(level="warn", rule="description_too_short",
                                message=f"{len(description)} characters gives the model almost nothing to "
                                        "decide on"))

    if len(str(fm.get("compatibility", ""))) > COMPATIBILITY_MAX:
        findings.append(Finding(level="error", rule="compatibility_length",
                                message=f"the compatibility setting is longer than {COMPATIBILITY_MAX} characters"))
    if "metadata" in fm and not all(isinstance(v, str) for v in (fm["metadata"] or {}).values()):
        findings.append(Finding(level="error", rule="metadata_values",
                                message="every value under metadata has to be text"))

    for key in fm.keys() - KNOWN_KEYS:
        findings.append(Finding(level="warn", rule="unknown_key",
                                message=f"the setting {key!r} is not in the specification and will be ignored"))
    return findings


def lint_body(body: str, skill_dir: Path) -> list[Finding]:
    """Check the instructions below the settings block.

    Args:
        body: Everything after the settings block.
        skill_dir: The skill's folder, used to check that files the
            instructions mention are actually shipped with it.

    Returns:
        Every problem found in the instructions.
    """
    findings = []
    lines = body.splitlines()

    if not body.strip():
        findings.append(Finding(level="error", rule="body_empty",
                                message="there are no instructions at all after the settings block"))
    if len(lines) > BODY_MAX_LINES:
        findings.append(Finding(level="warn", rule="body_length",
                                message=f"{len(lines)} lines is a lot. Move the detail into a references/ file "
                                        "and link to it"))
    if body.count("```") % 2 == 1:
        findings.append(Finding(level="error", rule="unclosed_code_fence",
                                message="there is an odd number of ``` markers, so one code block is never "
                                        "closed and everything after it disappears into it"))

    # A skill that tells the agent to run scripts/foo.py had better ship
    # scripts/foo.py.
    for referenced in re.findall(r"\b(scripts|references|assets)/[\w./-]+", body):
        if not (skill_dir / referenced).exists():
            findings.append(Finding(level="error", rule="missing_referenced_file",
                                    message=f"the instructions point at {referenced}, but that file is not here"))
    return findings


def main() -> int:
    configure_logging("01_structural_lint")
    skill_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else SKILL_DIR
    log.info("checking %s", skill_dir)
    show_skill(skill_dir)
    # >>> THIS COSTS NOTHING. No AI runs here and nothing goes over the
    #     network. lint_skill() is ordinary Python reading a text file.
    findings = lint_skill(skill_dir)
    errors = [f for f in findings if f.level == "error"]
    log.info("checked the settings and the instructions. Found %d things worth mentioning, %d of them serious.",
             len(findings), len(errors))

    shown = skill_dir.relative_to(HERE) if skill_dir.is_relative_to(HERE) else skill_dir
    section(f"results for {shown}")
    if findings:
        table("what we found", ["how bad", "rule", "what to do about it"],
              [[f.level, f.rule, f.message] for f in findings])
    headline(f"{len(errors)} things that must be fixed, {len(findings) - len(errors)} suggestions",
             good=not errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
