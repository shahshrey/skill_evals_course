"""
Shared toolbox for every eval script in this folder.

What is a skill? A folder with a SKILL.md file in it. The file tells an AI
assistant how to do one job well, in plain markdown. Claude Code reads the
installed skills, picks the one that fits what you asked for, and follows it.

What is an eval? A test for that skill. You cannot unit-test a skill the way
you unit-test a function, because the thing following the instructions is a
language model and it gives slightly different answers each time. So instead
you run it many times, measure what comes out, and compare against a version
that had no skill at all.

The numbered scripts (01 through 11) each demonstrate one kind of test. They
all lean on the same few helpers, which live here:

  load_skill()        Read a SKILL.md file into a Python object.
  run_agent()         Run Claude Code once, with or without the skill, and
                      hand back everything worth measuring.
  save_jsonl()        Write results to disk, so you can re-score them later
                      without paying for another round of agent runs.
  configure_logging() Colour-coded progress on screen, plain text in
                      logs/<script>.log. Set SKILL_EVAL_LOG=debug to also see
                      the full prompts and replies.
  section(), table(), headline(), explain()
                      The furniture that makes terminal output readable:
                      dividers between steps, result tables, a boxed verdict,
                      and yellow narration boxes that say what is going on.

One design decision is worth explaining, because it is the reason this code
uses the Claude Code CLI instead of calling an API directly.

Skills are loaded by the harness, not by the model. Claude Code reads every
installed skill's description, decides which one fits your request, and only
then shows the model the instructions. If you tested by pasting SKILL.md into
an API prompt yourself, you would skip that decision entirely, and you would
never learn whether your description is worded well enough to get picked. So
these scripts install the skill into a throwaway folder exactly the way a real
user would, and let Claude Code make the call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import ClassVar, TypeVar

import yaml
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, query
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from pydantic import BaseModel, Field
from rich import box
from rich.console import Console
from rich.highlighter import RegexHighlighter
from rich.logging import RichHandler
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

# ---------------------------------------------------------------------------
# Settings
#
# Anything a test should hold still lives up here. The whole point of an
# experiment is that one thing changes and everything else stays put, so these
# are set once and never fiddled with mid-run.
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
SKILL_DIR = HERE / "skills" / "commit-message"   # the skill being tested
FIXTURES_DIR = HERE / "fixtures"                 # sample inputs, kept on disk
RESULTS_DIR = HERE / "results"                   # saved scores, one file per script
LOGS_DIR = HERE / "logs"                         # play-by-play of each run

# The model that does the work. Naming an exact version matters more than it
# looks: if you just say "use the latest", your score quietly changes the day
# a new model ships, and you will blame your skill for it.
AGENT_MODEL = "claude-opus-5"

# The model that marks the homework in the scripts that use AI grading. It is
# deliberately a different model from the one being tested. Ask a model to
# grade its own writing and it tends to like what it sees.
JUDGE_MODEL = "claude-sonnet-5"

# What the agent is allowed to touch during a run. "Skill" has to be on this
# list, because that is the tool Claude Code uses to open a skill. Leave it off
# and we could never see whether the skill was picked up.
DEFAULT_TOOLS = ["Skill", "Read", "Bash"]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# Everything logs through this one logger. Think of it as two different
# audiences: the tables printed at the end are the results, and these log lines
# are the story of how those results came about.
log = logging.getLogger("skill_eval")


class EvalHighlighter(RegexHighlighter):
    """Colours the words worth spotting in a log line.

    Good news goes green, bad news red, and the rest gets a tint that tells you
    what kind of thing it is. Only the terminal is affected. The text written
    to logs/<script>.log stays plain, so it stays greppable.
    """

    base_style = "eval."
    highlights: ClassVar[list[str]] = [
        r"(?P<good>\b(PASS|ok|passes|helps|safe|True)\b)",
        r"(?P<bad>\b(FAIL|FAILED|MISMATCH|DROPPED|ERROR|REJECT|harms|False)\b|do not install)",
        r"(?P<tool>\btool call \d+: \w+)",
        r"(?P<arm>\bWITH skill \S+|\bWITHOUT skill\b|\b(with|without)_skill\b|\bbaseline\b|\bwith-skill\b)",
        r"(?P<case>\b(case|pair|pairwise|rubric grading|fast judge on) [\w-]+)",
        r"(?P<num>\$\d+\.\d+|\b\d+\.\d+s\b|\b\d+ turns\b|\b\d+ rows\b)",
        r"(?P<skill>the agent loaded the skill|installed [\w-]+ into)",
    ]


THEME = Theme({
    "eval.good": "bold green",
    "eval.bad": "bold red",
    "eval.tool": "cyan",
    "eval.arm": "magenta",
    "eval.case": "bold yellow",
    "eval.num": "bright_blue",
    "eval.skill": "bold cyan",
})


class _ConsoleFilter(logging.Filter):
    """Hides log records tagged file_only from the terminal.

    section() uses this to drop a divider into the log file without printing
    the same divider twice on screen.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "file_only", False)


def configure_logging(script_name: str) -> None:
    """Set up colour logs on screen and plain logs in a file.

    Call this once, first thing, in every script. At the normal setting you see
    every agent run, every tool the agent reached for, and every scoring
    decision. Set the SKILL_EVAL_LOG environment variable to "debug" and you
    also get the full prompts, the full replies, and every argument passed to
    every tool. That is a lot of text, but it is the fastest way to work out
    why a run went sideways.

    Args:
        script_name: Name of the calling script, minus the .py. Used for the
            log file name, so 09_statistics writes to logs/09_statistics.log.

    Example:
        configure_logging("09_statistics")
    """
    level = logging.DEBUG if os.environ.get("SKILL_EVAL_LOG", "").lower() == "debug" else logging.INFO
    LOGS_DIR.mkdir(exist_ok=True)

    console = RichHandler(
        console=Console(theme=THEME, stderr=True),
        highlighter=EvalHighlighter(),
        show_path=False,
        log_time_format="%H:%M:%S",
        rich_tracebacks=True,
    )
    console.setFormatter(logging.Formatter("%(message)s"))
    console.addFilter(_ConsoleFilter())

    file = logging.FileHandler(LOGS_DIR / f"{script_name}.log", mode="w")
    file.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file)
    # The underlying libraries announce every single network request. That
    # buries the story we actually want to read, so quieten them unless
    # somebody explicitly asked for debug output.
    for noisy in ("claude_agent_sdk", "typesafe_sdk", "httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.DEBUG if level == logging.DEBUG else logging.WARNING)
    log.info("started %s. Detail level: %s. Full log saved to logs/%s.log",
             script_name, logging.getLevelName(level), script_name)


# Results print to stdout through this console; log lines go to stderr. That
# split means you can pipe the results to a file and keep the tables while the
# running commentary stays on screen.
out = Console()


def section(title: str) -> None:
    """Draw a labelled line across the terminal to mark a new step.

    Without these, the tool calls from one run run straight into the next and
    the output turns into a wall of text.

    Args:
        title: Short label for what is about to happen.

    Example:
        section("case api-paging rep 0")
    """
    out.print()
    out.rule(f"[bold]{escape(title)}", style="grey50", align="left")
    log.info("---- %s ----", title, extra={"file_only": True})


def table(title: str, columns: list[str], rows: list[list]) -> None:
    """Print a results table.

    Values are tidied on the way in so the table stays scannable: True and
    False become a green "pass" and a red "FAIL", decimals are rounded to two
    places, and anything missing shows as a dash.

    Args:
        title: Caption shown above the table.
        columns: Column headings, left to right.
        rows: One list of values per row, in the same order as the columns.

    Example:
        table("findings", ["level", "rule"], [["error", "name_required"]])
    """
    t = Table(title=title, title_justify="left", title_style="bold", box=box.SIMPLE_HEAVY,
              header_style="bold", show_edge=False, pad_edge=False)
    for column in columns:
        t.add_column(column)
    for row in rows:
        t.add_row(*(_cell(value) for value in row))
    out.print(t)


def _cell(value) -> str:
    """Turn one table value into display text.

    Args:
        value: Anything a row can hold.

    Returns:
        Markup for the cell. True and False become "pass" and "FAIL", None
        becomes a dash, decimals get two places, everything else is shown
        as-is.
    """
    if isinstance(value, bool):
        return "[bold green]pass[/]" if value else "[bold red]FAIL[/]"
    if value is None:
        return "[dim]-[/]"
    if isinstance(value, float):
        return f"{value:.2f}"
    return escape(str(value))


def headline(text: str, good: bool | None = None) -> None:
    """Print the one line a reader should walk away with, in a box.

    Args:
        text: The takeaway, written as a full sentence where possible.
        good: True for good news (green box), False for bad (red), and None
            when it is neither, just a number worth reading (blue).

    Example:
        headline("0 errors, 2 warnings", good=True)
    """
    colour = {True: "green", False: "red", None: "blue"}[good]
    out.print(Panel(escape(text), border_style=colour, expand=False))
    log.info("headline: %s", text, extra={"file_only": True})


def note(text: str) -> None:
    """Print a quiet footnote under a table or a headline.

    Args:
        text: A short aside. Use it for caveats and pointers, not results.
    """
    out.print(f"[dim]{escape(text)}[/]")


def show_skill(skill_dir: Path = SKILL_DIR) -> None:
    """Print which skill is being tested and what it claims to do.

    Every script calls this before it does anything else, so a reader watching
    the output always knows what is on trial. The description shown here is the
    exact text Claude Code reads when it decides whether to reach for this
    skill, which is why it gets its own box rather than a log line.

    Args:
        skill_dir: Folder holding SKILL.md. Defaults to the commit-message
            skill that ships with these scripts.

    Example:
        show_skill()
    """
    shown = skill_dir.relative_to(HERE) if skill_dir.is_relative_to(HERE) else skill_dir
    try:
        skill = load_skill(skill_dir)
    except (OSError, ValueError, KeyError, yaml.YAMLError):
        # Scripts 01 and 02 get pointed at deliberately broken skills, so a
        # parse failure here is often the whole point. Say so plainly and let
        # the script report the details.
        out.print(Panel(f"[dim]{escape(str(shown))}/SKILL.md[/]\n\ncould not be read; the findings below explain why",
                        title="skill under test", border_style="cyan", title_align="left"))
        log.info("skill under test: %s (the file could not be read)", shown, extra={"file_only": True})
        return
    body = (f"[bold]{escape(skill.name)}[/]   [dim]{escape(str(shown))}/SKILL.md[/]\n\n"
            f"{escape(skill.description)}")
    out.print(Panel(body, title="skill under test", border_style="cyan", title_align="left"))
    log.info("skill under test: %s (%s): %s", skill.name, shown, skill.description, extra={"file_only": True})


def show_text(title: str, text: str, colour: str = "grey50") -> None:
    """Print a block of text in a labelled box.

    Used for the request sent to the agent and the answer it gave back. Seeing
    the real words is what turns a score into something you believe.

    Args:
        title: Label for the box, e.g. "the agent's reply".
        text: The text to show. Blank text prints as "(empty)".
        colour: Border colour. The default grey suits neutral content.
    """
    out.print(Panel(escape(text.strip() or "(empty)"), title=title, border_style=colour, title_align="left"))
    log.info("%s:\n%s", title, text, extra={"file_only": True})


def show_pair(left_title: str, left: str, right_title: str, right: str) -> None:
    """Print two blocks of text side by side.

    This is how the before-and-after comparison reads best: the answer with the
    skill on the left, the answer without it on the right, so the difference is
    right there instead of half a screen apart.

    Args:
        left_title: Label for the left box.
        left: Text for the left box.
        right_title: Label for the right box.
        right: Text for the right box.
    """
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(ratio=1)
    t.add_column(ratio=1)
    t.add_row(Panel(escape(left.strip() or "(empty)"), title=left_title, border_style="green", title_align="left"),
              Panel(escape(right.strip() or "(empty)"), title=right_title, border_style="magenta", title_align="left"))
    out.print(t)
    log.info("%s:\n%s\n%s:\n%s", left_title, left, right_title, right, extra={"file_only": True})


EXPLAIN_TITLES = {
    "next": "what happens next",
    "meaning": "what this means",
    "reading": "how to read this",
}


def explain(text: str, kind: str = "next") -> None:
    """Print a yellow box that narrates what is happening, for the reader.

    These scripts are meant to be watched, not just run, so the narration is
    part of the output rather than a comment in the source. Three kinds:

      next     what is about to happen, and why it is worth doing
      meaning  what the result that just appeared actually tells you
      reading  how to make sense of the table or number coming up

    Set SKILL_EVAL_EXPLAIN=0 in your environment to turn all of this off once
    you know the material and just want the numbers.

    Args:
        text: The explanation, in plain sentences.
        kind: One of "next", "meaning" or "reading". Sets the box title.

    Example:
        explain("Both arms passed, so the skill bought nothing here.",
                kind="meaning")
    """
    if os.environ.get("SKILL_EVAL_EXPLAIN", "1") == "0":
        return
    title = EXPLAIN_TITLES[kind]
    out.print(Panel(escape(text), title=title, title_align="left", border_style="yellow"))
    log.info("%s: %s", title, text, extra={"file_only": True})


# ---------------------------------------------------------------------------
# Reading a skill
# ---------------------------------------------------------------------------

class Skill(BaseModel):
    """A SKILL.md file, parsed into fields.

    Every record in these scripts is a Pydantic model, for two reasons. The
    field descriptions below are the documentation, kept next to the data
    instead of in a README that drifts out of date. And a record that does not
    match its model blows up immediately, rather than turning into a confusing
    number three steps later.
    """

    name: str = Field(description="The skill's id, taken from the top of SKILL.md. Must match the folder name.")
    description: str = Field(
        description="What the skill does and when to use it. This sentence is all Claude Code reads when it "
                    "decides whether to open the skill, so it does the heavy lifting.")
    frontmatter: dict = Field(description="Every setting from the YAML block at the top of SKILL.md.")
    body: str = Field(
        description="The markdown instructions below the settings block. The model only sees this after the "
                    "skill has been opened.")
    path: Path = Field(description="The folder that holds SKILL.md.")


def load_skill(skill_dir: Path = SKILL_DIR) -> Skill:
    """Read and parse a SKILL.md file.

    The file has two parts: a settings block written in YAML, wrapped in a pair
    of '---' lines, then the instructions in markdown.

    Args:
        skill_dir: Folder holding SKILL.md.

    Returns:
        A Skill with the settings and the instructions split apart.

    Raises:
        ValueError: The file has no settings block to split on.
        KeyError: The settings block is missing name or description.

    Example:
        skill = load_skill()
        print(skill.name)  # "commit-message"
    """
    text = (skill_dir / "SKILL.md").read_text()
    # Split on the first two "---" only. The instructions below may contain
    # their own horizontal rules, and those must not confuse the split.
    _, frontmatter_text, body = text.split("---", 2)
    frontmatter = yaml.safe_load(frontmatter_text)
    return Skill(
        name=frontmatter["name"],
        description=frontmatter["description"],
        frontmatter=frontmatter,
        body=body.strip(),
        path=skill_dir,
    )


def read_fixture(relative_path: str) -> str:
    """Read a sample input file from the fixtures/ folder.

    Args:
        relative_path: Path under fixtures/, e.g. "diffs/docs_cli_readme.diff".

    Returns:
        The file's contents as text.

    Example:
        diff = read_fixture("diffs/docs_cli_readme.diff")
    """
    return (FIXTURES_DIR / relative_path).read_text()


# ---------------------------------------------------------------------------
# Running the agent
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    """One action the agent took, such as reading a file or running a command."""

    name: str = Field(description="Which tool was used: Skill to open a skill, Read to read a file, Bash to run "
                                  "a shell command, and so on.")
    input: dict = Field(
        description="The arguments passed to it. Bash carries 'command', Read carries 'file_path', and Skill "
                    "carries 'skill'.")


class AgentRun(BaseModel):
    """Everything one run of the agent produced.

    Scoring always happens on one of these, never on a live agent. That is on
    purpose: a saved run can be re-scored next month with a different set of
    rules, and you pay for the agent time only once.
    """

    prompt: str = Field(description="The request the agent was given.")
    skill_installed: bool = Field(description="Was the skill present in the workspace? True for the with-skill "
                                              "side of a comparison.")
    skill_invoked: bool = Field(default=False, description="Did the agent actually open the skill?")
    final_text: str = Field(default="", description="The agent's last message. This is what gets marked.")
    tool_calls: list[ToolCall] = Field(default_factory=list,
                                       description="Every action the agent took, in order. Script 08 scores this.")
    model: str = Field(default="", description="Which model served the run, read back from the response rather "
                                               "than assumed.")
    num_turns: int = Field(default=0, description="How many times the agent spoke. Each turn re-reads the whole "
                                                  "conversation, which is where the cost comes from.")
    cost_usd: float = Field(default=0.0, description="What this run cost, in US dollars.")
    input_tokens: int = Field(default=0, description="Text the model read fresh, charged at full price. A token "
                                                     "is roughly three quarters of a word.")
    cache_read_tokens: int = Field(default=0, description="Text the model had read before and got back cheaply.")
    cache_write_tokens: int = Field(default=0,
                                    description="Text saved for reuse on later runs. Slightly dearer than reading "
                                                "it fresh, much cheaper the next time round.")
    output_tokens: int = Field(default=0, description="Text the model wrote.")
    duration_ms: int = Field(default=0, description="How long the run took, in milliseconds, start to finish.")
    error: str | None = Field(
        default=None, description="Set when the run broke for reasons that have nothing to do with the skill, "
                                  "such as a network failure. Scoring skips these rows.")


def run_agent(
    prompt: str,
    skill_dir: Path | None = SKILL_DIR,
    workspace_files: dict[str, str] | None = None,
    model: str = AGENT_MODEL,
    allowed_tools: list[str] = DEFAULT_TOOLS,
    max_turns: int = 8,
    git_init: bool = False,
) -> AgentRun:
    """Run Claude Code once on a request, inside a brand new throwaway folder.

    Each run gets its own empty folder, which is then thrown away. Nothing
    carries over between runs: no leftover files, no history, no cached
    answers. That isolation is what lets two runs be compared fairly.

    Args:
        prompt: The request to send, worded the way a real user would word it.
        skill_dir: Folder holding the skill to install. Pass None to run
            without any skill at all, which is the comparison baseline.
        workspace_files: Files to drop into the folder before starting, as
            {filename: contents}. Use this when the request refers to a file,
            e.g. {"changes.diff": "..."} for "summarise changes.diff".
        model: Which model to use. Defaults to the pinned AGENT_MODEL.
        allowed_tools: What the agent is permitted to use.
        max_turns: Stop the agent after this many turns, so a confused run
            cannot spend money forever.
        git_init: Set up a real git repository in the folder first. Needed for
            cases that check what the agent did, or refused to do, with git.

    Returns:
        An AgentRun holding the reply, every action taken, and what it cost.

    Example:
        run = run_agent("Write a commit message for this diff:\\n\\n...")
        print(run.skill_invoked, run.cost_usd)
    """
    skill_name = load_skill(skill_dir).name if skill_dir else None
    arm = f"WITH skill {skill_name}" if skill_dir else "WITHOUT skill"
    log.info("running the agent %s, on %s. Request begins: %.70r", arm, model, prompt.replace("\n", " "))
    log.debug("the full request:\n%s", prompt)

    # A fresh directory for every run. The setup below is ordinary blocking
    # code; only the back-and-forth with Claude Code needs to be async.
    with tempfile.TemporaryDirectory(prefix="skill-eval-") as workspace:
        workspace = Path(workspace)
        log.debug("working folder for this run: %s", workspace)
        if skill_dir:
            # .claude/skills/ is where Claude Code looks for a project's skills.
            shutil.copytree(skill_dir, workspace / ".claude" / "skills" / skill_name)
            log.info("  installed %s into .claude/skills/, the folder Claude Code reads", skill_name)
        for relative_path, content in (workspace_files or {}).items():
            (workspace / relative_path).write_text(content)
            log.info("  put the file %s in the folder (%d characters)", relative_path, len(content))
        if git_init:
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
            log.info("  made the folder a git repository with the files staged, ready to tempt the agent")
        return asyncio.run(_run_agent_async(prompt, workspace, skill_name, model, allowed_tools, max_turns))


async def _run_agent_async(prompt: str, workspace: Path, skill_name: str | None, model: str,
                           allowed_tools: list[str], max_turns: int) -> AgentRun:
    """Talk to Claude Code in a folder that run_agent has already prepared.

    Args:
        prompt: The request to send.
        workspace: The prepared folder to run in.
        skill_name: Name of the installed skill, or None if none was installed.
        model: Which model to use.
        allowed_tools: What the agent is permitted to use.
        max_turns: Hard stop on the number of turns.

    Returns:
        An AgentRun assembled from the messages that came back.
    """
    options = ClaudeAgentOptions(
        cwd=workspace,
        model=model,
        # "project" means read settings from this folder only. Your own global
        # settings are deliberately ignored, so your personal skills and
        # plugins cannot wander into the test and change the result. Same
        # reasoning for the MCP servers: none, and none from your account.
        setting_sources=["project"],
        mcp_servers={},
        strict_mcp_config=True,
        allowed_tools=allowed_tools,
        # The folder gets deleted afterwards, so there is nothing to protect
        # and no reason to stop and ask before each command.
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )

    run = AgentRun(prompt=prompt, skill_installed=skill_name is not None, model=model)
    started = time.monotonic()

    # >>> THIS IS THE REAL THING. query() launches the actual `claude` program
    #     as a subprocess, pointed at the folder we just built, sends it the
    #     request, and streams back every message it produces. Everything these
    #     scripts measure comes out of the loop below.
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            run.model = message.model
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    run.tool_calls.append(ToolCall(name=block.name, input=block.input))
                    log.info("  tool call %d: %s %s", len(run.tool_calls), block.name,
                             _summarise_input(block.input))
                    log.debug("  what it was given: %s", block.input)
                    if block.name == "Skill" and block.input.get("skill") == skill_name:
                        run.skill_invoked = True
                        log.info("  the agent loaded the skill")
                elif isinstance(block, TextBlock):
                    # An agent talks more than once on its way to an answer
                    # ("let me read that file first", then the answer itself).
                    # The last thing it says is the answer.
                    run.final_text = block.text
        elif isinstance(message, ResultMessage):
            run.num_turns = message.num_turns
            run.cost_usd = message.total_cost_usd or 0.0
            usage = message.usage or {}
            # All four counts, straight from the API. Recording only
            # input_tokens would miss the reused system instructions, which are
            # most of what a run reads.
            run.input_tokens = usage.get("input_tokens", 0)
            run.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
            run.cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
            run.output_tokens = usage.get("output_tokens", 0)
            if message.is_error:
                run.error = f"{message.subtype}: {message.result or message.errors}"

    run.duration_ms = int((time.monotonic() - started) * 1000)
    if run.error:
        log.warning("  this run broke before it finished: %s", run.error)
    log.info("  finished in %.1fs, %d turns. Skill loaded: %s. Cost $%.4f. Answer begins: %.60r",
             run.duration_ms / 1000, run.num_turns, run.skill_invoked, run.cost_usd,
             run.final_text.replace("\n", " "))
    log.debug("the full answer:\n%s", run.final_text)
    return run


def _summarise_input(tool_input: dict) -> str:
    """Pick the one detail from a tool call worth showing in the log.

    Args:
        tool_input: The arguments the agent passed to a tool.

    Returns:
        The command, file path or skill name, trimmed to 80 characters and
        flattened to a single line. Empty when there is nothing useful.
    """
    detail = tool_input.get("command") or tool_input.get("file_path") or tool_input.get("skill") or ""
    return str(detail).replace("\n", " ")[:80]


# ---------------------------------------------------------------------------
# Saving and loading results
# ---------------------------------------------------------------------------

def save_jsonl(path: Path, rows: list[BaseModel | dict]) -> None:
    """Save results as one JSON object per line.

    This format is deliberately boring. One line per record means you can grep
    it, append to it, open it in anything, and re-score it later without
    re-running a single agent. The rows are usually Pydantic models, whose
    field descriptions document the file for whoever opens it next.

    Args:
        path: Where to write. Parent folders are created if missing.
        rows: The records to save.

    Example:
        save_jsonl(RESULTS_DIR / "06_ab_runs.jsonl", rows)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            data = row.model_dump(mode="json") if isinstance(row, BaseModel) else row
            f.write(json.dumps(data) + "\n")
    log.info("saved %d rows to %s", len(rows), path.relative_to(HERE))


def load_jsonl(path: Path) -> list[dict]:
    """Read back a file written by save_jsonl().

    Args:
        path: The file to read.

    Returns:
        One dictionary per non-empty line.
    """
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def results_from(producer: str, filename: str) -> Path:
    """Find a results file, and create it first if it does not exist yet.

    Every script here can be run on its own, in any order. The cheap scripts
    work from rows that an expensive script saved earlier, and rather than
    stopping to tell you which one to run first, they run it for you. After
    that the saved rows are reused.

    That reuse is the habit these scripts are trying to teach. Agent runs cost
    real money and take real time. Pay for them once, then score them as many
    times as you like.

    Args:
        producer: Script that creates the file, e.g. "06_ab_comparison.py".
        filename: Name of the file inside results/.

    Returns:
        Path to the results file, now guaranteed to exist.

    Example:
        path = results_from("06_ab_comparison.py", "06_ab_runs.jsonl")
    """
    path = RESULTS_DIR / filename
    if not path.exists():
        log.warning("%s does not exist yet, so %s has to run first. This will spend money on agent runs.",
                    filename, producer)
        subprocess.run([sys.executable, str(HERE / producer)], check=True)
    return path


Reply = TypeVar("Reply", bound=BaseModel)


def ask_model(prompt: str, response_model: type[Reply], model: str = JUDGE_MODEL) -> Reply | None:
    """Ask a model one question and make it answer in a fixed shape.

    Used by the scripts where a model marks another model's homework. The
    marker gets no tools and no conversation, just the question and a required
    answer format.

    The fixed shape matters more than it sounds. A marker that replies in
    prose forces you to fish a score out of a paragraph with string matching,
    and that fishing is where a lot of scoring bugs hide. Instead, the shape of
    the answer is sent to the API up front, and the reply is checked against
    that same shape on the way back.

    This goes through Claude Code like everything else, so it works with a
    normal Claude Code login. With an API key you could call the API directly
    instead and nothing about the scoring would change.

    Args:
        prompt: The question, including whatever text is being marked.
        response_model: The shape the answer must fit, as a Pydantic model.
        model: Which model to ask. Defaults to JUDGE_MODEL, deliberately a
            different model from the one being tested.

    Returns:
        The answer, already checked against response_model. None when the
        model produced nothing usable, so the caller can treat that as a
        failure rather than quietly counting it as a pass.

    Example:
        reply = ask_model("Grade this...", RubricReply)
        if reply is None:
            ...  # treat as a fail
    """
    log.info("asking the marker model %s to judge. Question is %d characters. Answer must fit: %s",
             model, len(prompt), response_model.__name__)
    log.debug("the full question put to the marker:\n%s", prompt)
    result = asyncio.run(_ask_model_async(prompt, model, response_model.model_json_schema()))
    if not result or result.structured_output is None:
        log.warning("  the marker gave nothing usable back, so this counts as a fail")
        return None
    reply = response_model.model_validate(result.structured_output)
    log.info("  the marker answered: %.100s", reply.model_dump_json())
    return reply


async def _ask_model_async(prompt: str, model: str, output_schema: dict) -> ResultMessage | None:
    """Put one question to a model with no tools and a required answer shape.

    Args:
        prompt: The question.
        model: Which model to ask.
        output_schema: JSON schema the answer must satisfy.

    Returns:
        The final message from the model, or None if the call failed.
    """
    # Producing an answer that satisfies a schema takes Claude Code an extra
    # turn or two, so allowing only one turn fails at random. Three is plenty
    # when there are no tools to get distracted by.
    options = ClaudeAgentOptions(model=model, setting_sources=[], allowed_tools=[], tools=[],
                                 max_turns=3, output_format={"type": "json_schema", "schema": output_schema})
    result = None
    try:
        # >>> THIS IS THE REAL THING. The marker model runs here, through the
        #     same Claude Code program, but with no tools and a required
        #     answer format.
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result = message
    except ClaudeSDKError as exc:
        # A marker that crashes tells you something about your setup, not about
        # the skill. Report it and let the caller count it as a fail, rather
        # than killing the whole run.
        print(f"  the call to the marker model failed: {exc}")
    return result
