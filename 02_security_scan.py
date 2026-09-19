"""
Eval type 2: security scan.

A skill is text that an agent will obey, so a malicious skill is a prompt
injection with a nice README. It can tell the agent to read your SSH keys,
pipe a remote script into bash, or post your working directory to a server,
and the agent will do it because the skill said so.

This eval never runs the skill. It reads every file in the skill folder and
matches known-bad patterns. Static scanning has false positives (a skill
about SSH will mention ~/.ssh) so findings carry a severity and the final
verdict is a score, not a single boolean.

Scoring: each severity has a point value, and repeat hits on the same rule
count less each time (full, half, quarter, then nothing). Ten "curl" mentions should not outrank one "ignore previous
instructions".

Run:  python 02_security_scan.py                     # scans skills/commit-message
      python 02_security_scan.py <dir>               # scans any skill folder
Exit code 1 when the verdict is "do not install".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from skill_eval_common import HERE, SKILL_DIR, configure_logging, headline, log, section, show_skill, table

# (rule id, severity, regex, what it means). Order does not matter.
# Severity: CRITICAL = the skill is hostile; HIGH = dangerous unless justified;
# MEDIUM = needs a human look; LOW = worth knowing.
RULES = [
    ("injection.override", "CRITICAL",
     r"ignore (all |any )?(previous|prior|above|earlier) (instructions|rules)",
     "tries to override the user's or system's instructions"),
    ("injection.hide", "CRITICAL",
     r"do not (tell|inform|mention to|reveal to) the user|hide this from",
     "asks the agent to hide behaviour from the user"),
    ("exfil.post", "CRITICAL",
     r"curl [^\n]*(-X POST|--data|-d )|wget [^\n]*--post|requests\.post\(",
     "sends data to a remote endpoint"),
    ("install.pipe_to_shell", "HIGH",
     r"(curl|wget)[^\n|]*\|\s*(ba|z)?sh\b",
     "pipes a downloaded script straight into a shell"),
    ("secrets.aws_key", "HIGH", r"\bAKIA[0-9A-Z]{16}\b", "looks like an AWS access key"),
    ("secrets.anthropic_key", "HIGH", r"\bsk-ant-[A-Za-z0-9_-]{20,}", "looks like an Anthropic API key"),
    ("secrets.private_key", "HIGH", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "embeds a private key"),
    ("paths.credentials", "HIGH",
     r"~/\.(ssh|aws|gnupg|claude|config/gh)\b|/etc/(passwd|shadow)|\.env\b",
     "reads credential or secret files"),
    ("exec.dynamic", "HIGH", r"\beval\(|\bexec\(|pickle\.loads\(|shell=True",
     "executes dynamic code or shell strings"),
    ("exec.destructive", "MEDIUM", r"\brm -rf\b|\bsudo\b|chmod \+x", "destructive or privileged commands"),
    ("obfuscation.base64", "MEDIUM", r"[A-Za-z0-9+/]{80,}={0,2}", "long base64 blob a human cannot review"),
    ("obfuscation.hidden_unicode", "HIGH",
     # Written as escapes on purpose: these characters are invisible in an
     # editor, which is the whole problem with them. Zero-width spaces and
     # joiners, the byte-order mark, bidirectional overrides, and the "tag"
     # block some injection attacks use to smuggle hidden ASCII.
     r"[\u200b-\u200f\u2060\ufeff\u202a-\u202e\u2066-\u2069\U000e0000-\U000e007f]",
     "zero-width or bidirectional characters that hide text from readers"),
    ("network.url", "LOW", r"https?://(?!github\.com|docs\.|www\.)[\w.-]+", "contacts an external host"),
]
COMPILED = [(rule_id, sev, re.compile(pattern, re.IGNORECASE), why) for rule_id, sev, pattern, why in RULES]

SEVERITY_POINTS = {"CRITICAL": 50, "HIGH": 25, "MEDIUM": 10, "LOW": 5}
REPEAT_WEIGHTS = [1.0, 0.5, 0.25]     # 1st, 2nd, 3rd hit of the same rule; later hits are free
SCANNED_SUFFIXES = {".md", ".py", ".sh", ".txt", ".json", ".yaml", ".yml", ".toml"}


class Finding(BaseModel):
    rule: str = Field(description="Id of the pattern that matched, e.g. injection.override.")
    severity: str = Field(description="CRITICAL, HIGH, MEDIUM or LOW; sets the points in the risk score.")
    file: str = Field(description="Path inside the skill folder.")
    line: int = Field(description="1-based line number of the match.")
    snippet: str = Field(description="The matching line, trimmed, so a reader can judge it without opening the file.")
    why: str = Field(description="What this pattern means in a skill.")


def scan_skill(skill_dir: Path) -> list[Finding]:
    findings = []
    for path in sorted(skill_dir.rglob("*")):
        if path.suffix not in SCANNED_SUFFIXES or not path.is_file():
            continue
        log.info("scanning %s against %d rules", path.relative_to(skill_dir), len(COMPILED))
        for line_no, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            for rule_id, severity, pattern, why in COMPILED:
                if pattern.search(line):
                    log.info("  %s hit %s at line %d", severity, rule_id, line_no)
                    findings.append(Finding(rule=rule_id, severity=severity, file=str(path.relative_to(skill_dir)),
                                            line=line_no, snippet=line.strip()[:70], why=why))
    return findings


def risk_score(findings: list[Finding]) -> int:
    """0 (clean) to 100 (hostile). Same rule firing many times adds less each time."""
    hits_per_rule: dict[str, int] = {}
    score = 0.0
    for f in findings:
        count = hits_per_rule.get(f.rule, 0)
        hits_per_rule[f.rule] = count + 1
        if count < len(REPEAT_WEIGHTS):
            score += SEVERITY_POINTS[f.severity] * REPEAT_WEIGHTS[count]
    return min(100, round(score))


def verdict(score: int) -> str:
    if score <= 20:
        return "safe"
    if score <= 50:
        return "caution: review the findings before installing"
    return "do not install"


def main() -> int:
    configure_logging("02_security_scan")
    skill_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else SKILL_DIR
    log.info("scanning %s", skill_dir)
    show_skill(skill_dir)
    # >>> NO LIVE CALL: this file never runs the CLI or a model, and it never
    #     runs the skill either. scan_skill() is regex over the files.
    findings = scan_skill(skill_dir)
    score = risk_score(findings)
    log.info("%d findings -> risk score %d/100 (%s)", len(findings), score, verdict(score))

    shown = skill_dir.relative_to(HERE) if skill_dir.is_relative_to(HERE) else skill_dir
    section(f"security scan results for {shown}")
    if findings:
        table("findings", ["severity", "rule", "where", "snippet", "why it matters"],
              [[f.severity, f.rule, f"{f.file}:{f.line}", f.snippet, f.why] for f in findings])
    headline(f"risk score {score}/100: {verdict(score)}", good=score <= 20)
    return 1 if score > 50 else 0


if __name__ == "__main__":
    sys.exit(main())
