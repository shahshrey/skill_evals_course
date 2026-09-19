"""
Shared helpers for every eval file in this folder.

Each numbered eval file (01_..., 02_..., ...) shows one way of evaluating a
skill. They all need the same three things, so those live here:

  1. load_skill()  - read a SKILL.md into a small Skill object.
  2. run_agent()   - run Claude Code once, with or without the skill installed,
                     and return everything we might want to grade.
  3. save_jsonl()  - write results to disk so you can inspect or re-grade them.
  4. configure_logging() - colourful progress logs on the terminal (via the
                     rich library) and plain ones in logs/<script>.log, so you
                     can watch what each run is doing. Set SKILL_EVAL_LOG=debug
                     to also see prompts and tool inputs.
  5. section() / table() / headline() - dividers, result tables and a boxed
                     verdict, so the terminal output has landmarks: setup,
                     one block per case, then the results.

The agent under test is Claude Code, driven through the official
`claude-agent-sdk` package. That matters for skill evals: skills are loaded by
the harness (Claude Code), not by the model. If you tested by pasting SKILL.md
into a raw API system prompt, you would never find out whether the skill's
`description` is good enough for the harness to pick it. Here the skill is
installed into a throwaway project folder exactly the way a user would install
it, so the eval exercises the real triggering path.
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
# Configuration. Everything an eval should hold constant lives up here so the
# only thing that varies between runs is what you are testing.
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
SKILL_DIR = HERE / "skills" / "commit-message"   # the skill we evaluate
FIXTURES_DIR = HERE / "fixtures"
RESULTS_DIR = HERE / "results"
LOGS_DIR = HERE / "logs"

# The model that runs the task. Pin it: a score from an unpinned model tells you
# nothing once the default changes under you.
AGENT_MODEL = "claude-opus-5"

# The model that grades outputs in the LLM-judge evals. Use a different model
# from the one under test. A model judging its own output prefers its own style.
JUDGE_MODEL = "claude-sonnet-5"

# Tools the agent may use during a run. Skill is the tool Claude Code calls to
# load a skill, so it has to be here or we could never observe triggering.
DEFAULT_TOOLS = ["Skill", "Read", "Bash"]


# ---------------------------------------------------------------------------
# 0. Logging
# ---------------------------------------------------------------------------

# Every file logs through this one logger. Printed tables are the results;
# log lines are the play-by-play that explains how the results came about.
log = logging.getLogger("skill_eval")


class EvalHighlighter(RegexHighlighter):
    """Colours the words you scan for in a log line. Messages stay plain text,
    so the file log is unchanged; only the terminal gets the colour."""

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
    """Drop records marked file_only. section() uses that to put a divider in
    the file log without printing it twice on the terminal."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "file_only", False)


def configure_logging(script_name: str) -> None:
    """Colourful, readable logs on the terminal; plain text in logs/<script_name>.log.

    INFO shows every run, tool call and grading decision. SKILL_EVAL_LOG=debug
    adds the prompts, tool inputs and judge replies in full.
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
    # The SDKs announce every request at INFO; keep that out of the play-by-play
    # unless you asked for debug output.
    for noisy in ("claude_agent_sdk", "typesafe_sdk", "httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.DEBUG if level == logging.DEBUG else logging.WARNING)
    log.info("starting %s (log level %s, file logs/%s.log)", script_name, logging.getLevelName(level), script_name)


# Results go to stdout through this console; logs go to stderr. Piping stdout
# to a file therefore keeps the tables and drops the play-by-play.
out = Console()


def section(title: str) -> None:
    """A labelled horizontal rule. Use it between phases and between cases so
    the tool-call logs of one run do not blur into the next."""
    out.print()
    out.rule(f"[bold]{escape(title)}", style="grey50", align="left")
    log.info("---- %s ----", title, extra={"file_only": True})


def table(title: str, columns: list[str], rows: list[list]) -> None:
    """A results table. Booleans render as pass/FAIL, floats to two decimals,
    None as a dash."""
    t = Table(title=title, title_justify="left", title_style="bold", box=box.SIMPLE_HEAVY,
              header_style="bold", show_edge=False, pad_edge=False)
    for column in columns:
        t.add_column(column)
    for row in rows:
        t.add_row(*(_cell(value) for value in row))
    out.print(t)


def _cell(value) -> str:
    if isinstance(value, bool):
        return "[bold green]pass[/]" if value else "[bold red]FAIL[/]"
    if value is None:
        return "[dim]-[/]"
    if isinstance(value, float):
        return f"{value:.2f}"
    return escape(str(value))


def headline(text: str, good: bool | None = None) -> None:
    """The one line a reader should take away, in a box. Green when the news
    is good, red when it is bad, blue when it is just a number."""
    colour = {True: "green", False: "red", None: "blue"}[good]
    out.print(Panel(escape(text), border_style=colour, expand=False))
    log.info("headline: %s", text, extra={"file_only": True})


def note(text: str) -> None:
    """A quiet line under a table or headline."""
    out.print(f"[dim]{escape(text)}[/]")


def show_skill(skill_dir: Path = SKILL_DIR) -> None:
    """Print the skill under test: its name, where it lives, and the description
    the harness routes on. Every script that touches a skill calls this first,
    so a viewer always knows what is being evaluated."""
    shown = skill_dir.relative_to(HERE) if skill_dir.is_relative_to(HERE) else skill_dir
    try:
        skill = load_skill(skill_dir)
    except (OSError, ValueError, KeyError, yaml.YAMLError):
        # 01 and 02 are pointed at broken skills on purpose; say so and let
        # them report the details.
        out.print(Panel(f"[dim]{escape(str(shown))}/SKILL.md[/]\n\ncould not be parsed; see the findings below",
                        title="skill under test", border_style="cyan", title_align="left"))
        log.info("skill under test: %s (could not be parsed)", shown, extra={"file_only": True})
        return
    body = (f"[bold]{escape(skill.name)}[/]   [dim]{escape(str(shown))}/SKILL.md[/]\n\n"
            f"{escape(skill.description)}")
    out.print(Panel(body, title="skill under test", border_style="cyan", title_align="left"))
    log.info("skill under test: %s (%s): %s", skill.name, shown, skill.description, extra={"file_only": True})


def show_text(title: str, text: str, colour: str = "grey50") -> None:
    """A block of text in a labelled box: the prompt the agent got, or the
    reply it gave. Seeing the real text is what makes a grade believable."""
    out.print(Panel(escape(text.strip() or "(empty)"), title=title, border_style=colour, title_align="left"))
    log.info("%s:\n%s", title, text, extra={"file_only": True})


def show_pair(left_title: str, left: str, right_title: str, right: str) -> None:
    """Two texts side by side, for comparing the arms of an A/B pair."""
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
    """Narration for someone watching the eval run, in a yellow box whose title
    says which kind of help it is:

      next     what is about to happen and why we do it
      meaning  what the result that just appeared tells us
      reading  how to read the table or number that follows

    Set SKILL_EVAL_EXPLAIN=0 to silence it once you know the material."""
    if os.environ.get("SKILL_EVAL_EXPLAIN", "1") == "0":
        return
    title = EXPLAIN_TITLES[kind]
    out.print(Panel(escape(text), title=title, title_align="left", border_style="yellow"))
    log.info("%s: %s", title, text, extra={"file_only": True})


# ---------------------------------------------------------------------------
# 1. Reading a skill
# ---------------------------------------------------------------------------

class Skill(BaseModel):
    """A parsed SKILL.md. Pydantic models are used for every record in this
    course: the field descriptions are the documentation, and a record that
    does not match its model fails loudly instead of silently."""

    name: str = Field(description="The skill's id from the frontmatter; must equal the folder name.")
    description: str = Field(
        description="What the skill does and when to use it. The harness routes on this text alone.")
    frontmatter: dict = Field(description="Every key from the YAML block at the top of SKILL.md.")
    body: str = Field(
        description="The markdown instructions after the frontmatter; the model sees this once the skill loads.")
    path: Path = Field(description="The folder that holds SKILL.md.")


def load_skill(skill_dir: Path = SKILL_DIR) -> Skill:
    """Parse SKILL.md. The file is YAML frontmatter between two '---' lines,
    then markdown."""
    text = (skill_dir / "SKILL.md").read_text()
    # Split on the first two "---" only, so a horizontal rule in the body is safe.
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
    """Read a file from fixtures/, e.g. read_fixture('diffs/docs_cli_readme.diff')."""
    return (FIXTURES_DIR / relative_path).read_text()


# ---------------------------------------------------------------------------
# 2. Running the agent
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    name: str = Field(description="The tool the agent called: Skill, Read, Bash, and so on.")
    input: dict = Field(
        description="The arguments it passed. Bash has 'command', Read has 'file_path', Skill has 'skill'.")


class AgentRun(BaseModel):
    """Everything one agent run produced. Evals grade these; they never grade
    the live agent directly, so a saved AgentRun can be re-graded later."""

    prompt: str = Field(description="The user request the agent was given.")
    skill_installed: bool = Field(description="Was the skill present in the workspace? True for the with-skill arm.")
    skill_invoked: bool = Field(default=False, description="Did the agent load the skill through the Skill tool?")
    final_text: str = Field(default="", description="The agent's last message; what the graders read.")
    tool_calls: list[ToolCall] = Field(default_factory=list, description="Every tool call in order: the trajectory.")
    model: str = Field(default="", description="The model that actually served the run, read from the response.")
    num_turns: int = Field(default=0, description="Assistant turns the run took; each one re-reads the whole context.")
    cost_usd: float = Field(default=0.0, description="Cost reported by the harness for this run.")
    input_tokens: int = Field(default=0, description="Uncached input tokens, billed at full price.")
    cache_read_tokens: int = Field(default=0, description="Input tokens served from the prompt cache; cheap.")
    cache_write_tokens: int = Field(default=0,
                                    description="Input tokens written to the cache; slightly dearer than uncached.")
    output_tokens: int = Field(default=0, description="Tokens the model generated.")
    duration_ms: int = Field(default=0, description="Wall-clock time for the whole run.")
    error: str | None = Field(
        default=None, description="Set when the run failed for infrastructure reasons. Graders skip such rows.")


def run_agent(
    prompt: str,
    skill_dir: Path | None = SKILL_DIR,
    workspace_files: dict[str, str] | None = None,
    model: str = AGENT_MODEL,
    allowed_tools: list[str] = DEFAULT_TOOLS,
    max_turns: int = 8,
    git_init: bool = False,
) -> AgentRun:
    """Run Claude Code once on `prompt` inside a fresh temporary project.

    skill_dir=None runs the "without skill" arm. Everything else stays the same,
    so the two arms differ only by the skill's presence.

    workspace_files lets a case drop files into the project first, e.g.
    {"changes.diff": "..."} when the prompt says "see changes.diff".

    git_init=True turns the workspace into a git repository, for cases that
    need to check what the agent did (or refused to do) with git.
    """
    skill_name = load_skill(skill_dir).name if skill_dir else None
    arm = f"WITH skill {skill_name}" if skill_dir else "WITHOUT skill"
    log.info("agent run %s | model %s | prompt: %.70r", arm, model, prompt.replace("\n", " "))
    log.debug("full prompt:\n%s", prompt)

    # A fresh directory per run. Nothing leaks between cases: no files, no git
    # history, no cached results. The setup is plain blocking code; only the
    # conversation with the CLI is async.
    with tempfile.TemporaryDirectory(prefix="skill-eval-") as workspace:
        workspace = Path(workspace)
        log.debug("workspace %s", workspace)
        if skill_dir:
            # This is where Claude Code looks for project skills.
            shutil.copytree(skill_dir, workspace / ".claude" / "skills" / skill_name)
            log.info("  installed %s into .claude/skills/", skill_name)
        for relative_path, content in (workspace_files or {}).items():
            (workspace / relative_path).write_text(content)
            log.info("  wrote workspace file %s (%d chars)", relative_path, len(content))
        if git_init:
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
            log.info("  initialised a git repo and staged the workspace files")
        return asyncio.run(_run_agent_async(prompt, workspace, skill_name, model, allowed_tools, max_turns))


async def _run_agent_async(prompt: str, workspace: Path, skill_name: str | None, model: str,
                           allowed_tools: list[str], max_turns: int) -> AgentRun:
    """The async half of run_agent: talk to the CLI in the prepared workspace."""
    options = ClaudeAgentOptions(
        cwd=workspace,
        model=model,
        # "project" = read .claude/ from cwd only. We deliberately skip the
        # user's global settings so their own skills and plugins cannot
        # contaminate the run. The same goes for MCP servers: none, and
        # none loaded from the account either.
        setting_sources=["project"],
        mcp_servers={},
        strict_mcp_config=True,
        allowed_tools=allowed_tools,
        # The workspace is disposable, so let tools run without prompting.
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )

    run = AgentRun(prompt=prompt, skill_installed=skill_name is not None, model=model)
    started = time.monotonic()

    # >>> LIVE CALL: this is where the real Claude Code CLI runs. query()
    #     spawns the `claude` binary as a subprocess with the workspace as
    #     its working directory, sends the prompt over stdin, and streams
    #     back every message the agent produces. Everything the evals
    #     grade comes out of this loop.
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            run.model = message.model
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    run.tool_calls.append(ToolCall(name=block.name, input=block.input))
                    log.info("  tool call %d: %s %s", len(run.tool_calls), block.name,
                             _summarise_input(block.input))
                    log.debug("  tool input: %s", block.input)
                    if block.name == "Skill" and block.input.get("skill") == skill_name:
                        run.skill_invoked = True
                        log.info("  the agent loaded the skill")
                elif isinstance(block, TextBlock):
                    # An agent talks several times across its turns ("let me
                    # read that", then the answer). The last text is the answer.
                    run.final_text = block.text
        elif isinstance(message, ResultMessage):
            run.num_turns = message.num_turns
            run.cost_usd = message.total_cost_usd or 0.0
            usage = message.usage or {}
            # All four token buckets, straight from the API. Adding only
            # input_tokens would miss the cached system prompt, which is
            # most of what a run reads.
            run.input_tokens = usage.get("input_tokens", 0)
            run.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
            run.cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
            run.output_tokens = usage.get("output_tokens", 0)
            if message.is_error:
                run.error = f"{message.subtype}: {message.result or message.errors}"

    run.duration_ms = int((time.monotonic() - started) * 1000)
    if run.error:
        log.warning("  run failed: %s", run.error)
    log.info("  done in %.1fs | %d turns | skill invoked: %s | cost $%.4f | reply: %.60r",
             run.duration_ms / 1000, run.num_turns, run.skill_invoked, run.cost_usd,
             run.final_text.replace("\n", " "))
    log.debug("full reply:\n%s", run.final_text)
    return run


def _summarise_input(tool_input: dict) -> str:
    """The one field of a tool call worth showing at INFO level."""
    detail = tool_input.get("command") or tool_input.get("file_path") or tool_input.get("skill") or ""
    return str(detail).replace("\n", " ")[:80]


# ---------------------------------------------------------------------------
# 3. Saving and loading results
# ---------------------------------------------------------------------------

def save_jsonl(path: Path, rows: list[BaseModel | dict]) -> None:
    """One JSON object per line. Easy to grep, easy to append, easy to re-grade.
    Rows are usually Pydantic models; their field descriptions document the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            data = row.model_dump(mode="json") if isinstance(row, BaseModel) else row
            f.write(json.dumps(data) + "\n")
    log.info("saved %d rows to %s", len(rows), path.relative_to(HERE))


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def results_from(producer: str, filename: str) -> Path:
    """The path of a results file, producing it first if it is missing.

    Every file in the course runs on its own. The offline ones analyse rows
    that a live script saved, and rather than telling you to go and run that
    script, they run it for you the first time. After that the saved rows are
    reused, which is the habit the course is teaching: pay for agent runs
    once, analyse them as many times as you like.
    """
    path = RESULTS_DIR / filename
    if not path.exists():
        log.warning("%s is missing; running %s to produce it (this spends agent runs)", filename, producer)
        subprocess.run([sys.executable, str(HERE / producer)], check=True)
    return path


Reply = TypeVar("Reply", bound=BaseModel)


def ask_model(prompt: str, response_model: type[Reply], model: str = JUDGE_MODEL) -> Reply | None:
    """One model call with no tools, whose reply must fit a Pydantic model.
    Used by the LLM-judge eval.

    Graders should return structured data, not prose. Parsing a number out of
    a paragraph is where a lot of judge bugs hide. The model's JSON schema,
    field descriptions included, is sent to the API, and the reply is validated
    against the same model on the way back. Returns None when the model
    produced nothing usable, so the caller can fail closed.

    This goes through the same SDK as run_agent, so it works with a Claude
    Code login. With an ANTHROPIC_API_KEY you could call the Messages API
    directly instead; the evals would not change.
    """
    log.info("judge call | model %s | prompt %d chars | reply type %s", model, len(prompt), response_model.__name__)
    log.debug("judge prompt:\n%s", prompt)
    result = asyncio.run(_ask_model_async(prompt, model, response_model.model_json_schema()))
    if not result or result.structured_output is None:
        log.warning("  no usable judge reply")
        return None
    reply = response_model.model_validate(result.structured_output)
    log.info("  judge replied: %.100s", reply.model_dump_json())
    return reply


async def _ask_model_async(prompt: str, model: str, output_schema: dict) -> ResultMessage | None:
    # Producing schema-checked JSON takes the harness an extra turn or two, so
    # max_turns=1 fails intermittently. Three is enough with no tools enabled.
    options = ClaudeAgentOptions(model=model, setting_sources=[], allowed_tools=[], tools=[],
                                 max_turns=3, output_format={"type": "json_schema", "schema": output_schema})
    result = None
    try:
        # >>> LIVE CALL: the judge model runs here, through the same CLI but
        #     with no tools and a JSON schema it must answer in.
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result = message
    except ClaudeSDKError as exc:
        # A judge that crashes is a grader problem, not a fact about the skill.
        # Report it and let the caller fail closed rather than abort the run.
        print(f"  judge call failed: {exc}")
    return result
