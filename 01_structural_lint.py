"""
Chapter one: before anything else, can the thing even load?

This one costs nothing and is rude about your formatting. No AI runs. Nothing
goes over the network. It finishes in milliseconds. It asks a smaller question
than the one you care about. Is this SKILL.md well-formed enough that the
software can pick it up at all?

You will want to skip it. Everybody wants to skip it. Then they meet the
failures.

A skill whose name does not match its folder never loads. A description that
never says when to use the skill never gets picked. One code fence you forgot
to close swallows every instruction below it. None of those prints an error.
The skill sits there doing nothing while you reread your prompt, convinced
the model has stopped listening. The model never saw your skill. You typed a
hyphen where the folder had an underscore.

So check the boring things first. The boring things fail silently. The rules
come from the Agent Skills specification at agentskills.io, plus a few extra
for the mistakes people make in practice.

What gets checked in the settings block at the top:
  it parses as YAML at all; name and description are both there; the name is
  lowercase letters, digits and single hyphens, no longer than 64 characters,
  and matches the folder name; the description is under 1024 characters and
  says when to use the skill; no settings that are not in the specification.

What gets checked in the instructions below:
  they are not empty; under 500 lines; every ``` fence has a matching close;
  every file the instructions point at actually exists.

None of this tells you whether the skill is any good. It tells you the door
opens. A perfectly formatted file can still tell the agent to read your SSH
keys. That is what 02_security_scan.py is for. It costs nothing either.

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

# Limits from the specification. Named here rather than typed in where they
# are used, so the rules below read like sentences.
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500
BODY_MAX_LINES = 500        # only advice, not a rule. Long instructions crowd out everything else you wrote

# The settings the specification allows, plus the extra ones Claude Code adds.
# Anything else is a typo or a leftover from another tool's format. Cursor
# rules use "globs" and "alwaysApply", for instance. Paste one of those in
# here and you get no error, no warning and no effect.
SPEC_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
CLAUDE_CODE_KEYS = {"disable-model-invocation", "user-invocable", "argument-hint", "model",
                    "context", "agent", "hooks"}
KNOWN_KEYS = SPEC_KEYS | CLAUDE_CODE_KEYS

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# The description has to say when to use the skill, not only what it does. A
# description that only describes itself reads well and almost never gets
# picked. 04 will charge you real money to learn that.
TRIGGER_PHRASE = re.compile(r"\buse (this )?(skill )?when\b|\bwhen (the )?user\b", re.IGNORECASE)


class Finding(BaseModel):
    """One thing wrong with the skill file, written down so you can act on it."""

    level: str = Field(description='"error" means the skill fails this test. "warn" is advice you can ignore.')
    rule: str = Field(description="Short name of the rule that fired, such as name_matches_folder.")
    message: str = Field(description="What was found, and what to change to fix it.")


def lint_skill(skill_dir: Path) -> list[Finding]:
    """Open one skill folder and write down everything wrong with it.

    The order is: is there a file, does it open with a settings block, does
    that block parse, and only then the rules. Each step depends on the one
    before, so an early failure comes back alone. There is no point
    complaining about the description of a file that does not exist.

    Args:
        skill_dir: Folder that should contain a SKILL.md.

    Returns:
        Every problem found, not sorted by severity. An empty list means the
        file is in good shape. That is a smaller compliment than it sounds. A
        problem bad enough to stop the parse comes back on its own, since
        nothing after it could be checked.

    Example:
        findings = lint_skill(Path("skills/commit-message"))
    """
    findings: list[Finding] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return [Finding(level="error", rule="file_exists", message=f"{skill_md} not found")]

    text = skill_md.read_text()
    # Split on the first two "---" lines and no further. Instructions love a
    # horizontal rule. A third divider halfway down the page must not be
    # mistaken for the end of the settings.
    parts = text.split("---", 2)
    if len(parts) < 3 or parts[0].strip():
        return [Finding(level="error", rule="frontmatter",
                        message="the file must open with a settings block wrapped in --- lines")]

    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        return [Finding(level="error", rule="frontmatter", message=f"the settings block is not valid YAML: {exc}")]
    body = parts[2]
    log.info("the settings block opened cleanly. It holds %s, with %d lines of instructions underneath",
             sorted(frontmatter), len(body.splitlines()))

    findings += lint_frontmatter(frontmatter, skill_dir.name)
    findings += lint_body(body, skill_dir)
    return findings


def lint_frontmatter(fm: dict, folder_name: str) -> list[Finding]:
    """Check the settings block at the top of the file.

    This is where the silent failures live. Everything checked here can be
    wrong in a way that produces no error, no warning and no skill.

    Args:
        fm: The settings, already parsed from YAML.
        folder_name: Name of the folder the file sits in. The name setting has
            to match it, or the skill never loads at all.

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
                                message=f"the name says {name!r} but the folder is called {folder_name!r}. They "
                                        "have to match. Otherwise the skill never loads, and never says why"))

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
                                        "starting 'Use when ...'. Without one it sits there unpicked"))
    if description and len(description) < 40:
        findings.append(Finding(level="warn", rule="description_too_short",
                                message=f"{len(description)} characters is almost nothing to decide on. This is "
                                        "the only part of your skill the model reads before choosing it"))

    if len(str(fm.get("compatibility", ""))) > COMPATIBILITY_MAX:
        findings.append(Finding(level="error", rule="compatibility_length",
                                message=f"the compatibility setting is longer than {COMPATIBILITY_MAX} characters"))
    if "metadata" in fm and not all(isinstance(v, str) for v in (fm["metadata"] or {}).values()):
        findings.append(Finding(level="error", rule="metadata_values",
                                message="every value under metadata has to be text"))

    for key in fm.keys() - KNOWN_KEYS:
        findings.append(Finding(level="warn", rule="unknown_key",
                                message=f"nothing reads the setting {key!r}. It is not in the specification, so "
                                        "it sits there looking like it does something"))
    return findings


def lint_body(body: str, skill_dir: Path) -> list[Finding]:
    """Check the instructions below the settings block.

    Fewer rules down here. Prose is mostly a matter of taste, and this script
    has none. What it can catch is formatting that eats your work. A fence
    left open. A file you promised the agent and never shipped.

    Args:
        body: Everything after the settings block.
        skill_dir: The skill's folder, used to check that the files the
            instructions point at are actually there.

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
                                message=f"{len(lines)} lines is a lot to hold in one head. Move the detail into "
                                        "a references/ file and link to it"))
    if body.count("```") % 2 == 1:
        findings.append(Finding(level="error", rule="unclosed_code_fence",
                                message="there is an odd number of ``` markers, so one code block never closes "
                                        "and swallows everything written after it"))

    # A skill that tells the agent to run scripts/foo.py had better ship
    # scripts/foo.py. Otherwise the agent looks, finds nothing, and improvises.
    for referenced in re.findall(r"\b(scripts|references|assets)/[\w./-]+", body):
        if not (skill_dir / referenced).exists():
            findings.append(Finding(level="error", rule="missing_referenced_file",
                                    message=f"the instructions send the agent to {referenced}, and there is no "
                                            "such file here"))
    return findings


def main() -> int:
    configure_logging("01_structural_lint")
    skill_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else SKILL_DIR
    log.info("opening %s to see whether it is put together properly", skill_dir)
    show_skill(skill_dir)
    # >>> THIS COSTS NOTHING. No AI runs here and nothing goes over the
    #     network. lint_skill() is ordinary Python reading a text file. It is
    #     done before you finish reading this comment.
    findings = lint_skill(skill_dir)
    errors = [f for f in findings if f.level == "error"]
    log.info("settings and instructions both read. %d things worth mentioning, %d of them serious enough to "
             "fix before you go further",
             len(findings), len(errors))

    shown = skill_dir.relative_to(HERE) if skill_dir.is_relative_to(HERE) else skill_dir
    section(f"results for {shown}")
    if findings:
        table("everything the check turned up", ["how bad", "rule", "what to do about it"],
              [[f.level, f.rule, f.message] for f in findings])
    headline(f"{len(errors)} things that must be fixed, {len(findings) - len(errors)} suggestions",
             good=not errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
