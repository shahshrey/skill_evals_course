"""
Eval type 2: is this skill trying to do something nasty?

Here is the thing about skills. A skill is just text, and the agent obeys it.
So a malicious skill is an attack wearing a friendly README. It can tell the
agent to go and read your SSH keys, to download a script off the internet and
run it, or to quietly send your files to someone else's server. The agent will
do all of that, because the instructions told it to and it has no way of
knowing the instructions are hostile.

This test never runs the skill. It reads every file in the folder and looks
for patterns known to be trouble.

Looking for patterns means false alarms. A skill genuinely about SSH is going
to mention ~/.ssh, and there is nothing wrong with that. So each finding
carries a severity, and the verdict at the end is a score rather than a
yes-or-no. A human still has to look.

How the score works. Each severity is worth points. The same pattern firing
over and over counts for less each time: full points for the first hit, half
for the second, a quarter for the third, nothing after that. Ten mentions of
curl should not outweigh one "ignore all previous instructions".

Run:  python 02_security_scan.py                     # scans skills/commit-message
      python 02_security_scan.py <dir>               # scans any skill folder
Exits with code 1 when the verdict is "do not install".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from skill_eval_common import HERE, SKILL_DIR, configure_logging, headline, log, section, show_skill, table

# What to look for. Each entry is a name, how bad it is, the pattern, and what
# it means in plain terms. The order makes no difference.
#
# CRITICAL means the skill is hostile and there is no innocent reading.
# HIGH means dangerous unless the skill has a good reason.
# MEDIUM means a human should take a look.
# LOW means worth knowing about, probably fine.
RULES = [
    ("injection.override", "CRITICAL",
     r"ignore (all |any )?(previous|prior|above|earlier) (instructions|rules)",
     "tries to talk the agent out of following your instructions"),
    ("injection.hide", "CRITICAL",
     r"do not (tell|inform|mention to|reveal to) the user|hide this from",
     "asks the agent to keep what it is doing from you"),
    ("exfil.post", "CRITICAL",
     r"curl [^\n]*(-X POST|--data|-d )|wget [^\n]*--post|requests\.post\(",
     "sends your data off to someone else's server"),
    ("install.pipe_to_shell", "HIGH",
     r"(curl|wget)[^\n|]*\|\s*(ba|z)?sh\b",
     "downloads a script and runs it straight away, sight unseen"),
    ("secrets.aws_key", "HIGH", r"\bAKIA[0-9A-Z]{16}\b", "contains what looks like an AWS access key"),
    ("secrets.anthropic_key", "HIGH", r"\bsk-ant-[A-Za-z0-9_-]{20,}", "contains what looks like an Anthropic API key"),
    ("secrets.private_key", "HIGH", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "has a private key written into it"),
    ("paths.credentials", "HIGH",
     r"~/\.(ssh|aws|gnupg|claude|config/gh)\b|/etc/(passwd|shadow)|\.env\b",
     "goes looking in the places passwords and keys are kept"),
    ("exec.dynamic", "HIGH", r"\beval\(|\bexec\(|pickle\.loads\(|shell=True",
     "builds code or shell commands on the fly and runs them"),
    ("exec.destructive", "MEDIUM", r"\brm -rf\b|\bsudo\b|chmod \+x",
     "deletes things or asks for administrator powers"),
    ("obfuscation.base64", "MEDIUM", r"[A-Za-z0-9+/]{80,}={0,2}",
     "a long scrambled blob that no human reviewer can read"),
    ("obfuscation.hidden_unicode", "HIGH",
     # Written out as escape codes deliberately. These characters are invisible
     # in an editor, which is exactly what makes them dangerous: someone can
     # hide a whole extra instruction in what looks like blank space. Covered
     # here are zero-width spaces and joiners, the byte-order mark, the
     # characters that flip text direction, and the "tag" block that some
     # attacks use to smuggle hidden letters.
     r"[​-‏⁠﻿‪-‮⁦-⁩\U000e0000-\U000e007f]",
     "invisible characters that hide text from anyone reading the file"),
    ("network.url", "LOW", r"https?://(?!github\.com|docs\.|www\.)[\w.-]+", "reaches out to an outside website"),
]
COMPILED = [(rule_id, sev, re.compile(pattern, re.IGNORECASE), why) for rule_id, sev, pattern, why in RULES]

SEVERITY_POINTS = {"CRITICAL": 50, "HIGH": 25, "MEDIUM": 10, "LOW": 5}
# Points for the first, second and third time the same pattern fires. After
# that it is free, because repetition is not extra evidence.
REPEAT_WEIGHTS = [1.0, 0.5, 0.25]
SCANNED_SUFFIXES = {".md", ".py", ".sh", ".txt", ".json", ".yaml", ".yml", ".toml"}


class Finding(BaseModel):
    """One suspicious line found in the skill's files."""

    rule: str = Field(description="Name of the pattern that matched, such as injection.override.")
    severity: str = Field(description="CRITICAL, HIGH, MEDIUM or LOW. Decides how many points it adds to the score.")
    file: str = Field(description="Which file inside the skill folder.")
    line: int = Field(description="Which line of it, counting from 1.")
    snippet: str = Field(description="The line itself, trimmed, so you can judge it without opening the file.")
    why: str = Field(description="What this pattern means when it shows up in a skill.")


def scan_skill(skill_dir: Path) -> list[Finding]:
    """Read every file in the skill folder and look for trouble.

    Args:
        skill_dir: The folder to scan. Subfolders are included.

    Returns:
        Every suspicious line found, in file order. An empty list means nothing
        matched, which is not the same as proof the skill is safe.

    Example:
        findings = scan_skill(Path("skills/commit-message"))
    """
    findings = []
    for path in sorted(skill_dir.rglob("*")):
        if path.suffix not in SCANNED_SUFFIXES or not path.is_file():
            continue
        log.info("reading %s, checking it against %d patterns", path.relative_to(skill_dir), len(COMPILED))
        for line_no, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            for rule_id, severity, pattern, why in COMPILED:
                if pattern.search(line):
                    log.info("  %s match on %s at line %d", severity, rule_id, line_no)
                    findings.append(Finding(rule=rule_id, severity=severity, file=str(path.relative_to(skill_dir)),
                                            line=line_no, snippet=line.strip()[:70], why=why))
    return findings


def risk_score(findings: list[Finding]) -> int:
    """Turn a list of findings into a single number from 0 to 100.

    The same pattern firing repeatedly adds less each time. One serious finding
    should outrank a dozen trivial ones.

    Args:
        findings: Everything scan_skill() turned up.

    Returns:
        0 for a clean skill, 100 for an obviously hostile one.

    Example:
        risk_score(findings)  # 0
    """
    hits_per_rule: dict[str, int] = {}
    score = 0.0
    for f in findings:
        count = hits_per_rule.get(f.rule, 0)
        hits_per_rule[f.rule] = count + 1
        if count < len(REPEAT_WEIGHTS):
            score += SEVERITY_POINTS[f.severity] * REPEAT_WEIGHTS[count]
    return min(100, round(score))


def verdict(score: int) -> str:
    """Turn the score into advice.

    Args:
        score: The number risk_score() produced.

    Returns:
        What to do about it, in one phrase.
    """
    if score <= 20:
        return "safe"
    if score <= 50:
        return "caution: read the findings before you install this"
    return "do not install"


def main() -> int:
    configure_logging("02_security_scan")
    skill_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else SKILL_DIR
    log.info("scanning %s", skill_dir)
    show_skill(skill_dir)
    # >>> THIS COSTS NOTHING. No AI runs here, nothing goes over the network,
    #     and the skill itself is never run. scan_skill() only reads the files
    #     and looks for patterns.
    findings = scan_skill(skill_dir)
    score = risk_score(findings)
    log.info("found %d suspicious lines. Risk score %d out of 100, which means: %s",
             len(findings), score, verdict(score))

    shown = skill_dir.relative_to(HERE) if skill_dir.is_relative_to(HERE) else skill_dir
    section(f"security scan results for {shown}")
    if findings:
        table("what we found", ["how bad", "pattern", "where", "the line itself", "what it means"],
              [[f.severity, f.rule, f"{f.file}:{f.line}", f.snippet, f.why] for f in findings])
    headline(f"risk score {score} out of 100: {verdict(score)}", good=score <= 20)
    return 1 if score > 50 else 0


if __name__ == "__main__":
    sys.exit(main())
