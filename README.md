# Skill evals

One notebook, eleven chapters, one skill on trial.

A skill is a folder with a `SKILL.md` in it that a harness such as Claude
Code loads when a request matches its description. (The harness is the
program around the model. It decides which skills the model can see, runs
the tools, and keeps the conversation going. Skills are a harness feature,
and that matters for how you test them.) `skill_evals.ipynb` puts one such
skill, `skills/commit-message`, through every kind of eval there is, in the
order you would want to ask the questions. The free ones come first. The
ones that send you a bill come once you have earned the right to ask.

Every cell that runs something has the output of a real run stored under
it, so you can read the whole thing on GitHub or in a notebook viewer
without running a cell. Running it yourself costs a few dollars and about
ten minutes.

## The chapters

| Chapter | Question it answers | Needs a model? |
|---|---|---|
| The kit | How do we run the agent with and without the skill, and record what happened? | no |
| The interlude | What does a correct commit message look like, in code? | no |
| One | Is the SKILL.md well-formed enough to load? | no |
| Two | Does the skill try to do something hostile? | no |
| Three | Does the description contain the words users type, without colliding with neighbours? | no |
| Three and a half | Same question by meaning: a fast typed model (Jev) picks a skill from the catalog, with probabilities that expose collisions | Jev calls only |
| Four | Does the real harness load the skill when it should, and only then? | yes |
| Five | Does the output follow the rules we can check with code? | yes |
| Six | How much better is the agent with the skill than without? | yes |
| Seven | What about the rules only a reader can check? | judge calls only |
| Seven and a half | Same questions to a fast typed-judgment model (Jev), with probabilities and a cross-check against seven | Jev calls only |
| Eight | Did the agent follow the procedure and respect the prohibitions? | yes |
| Nine | Is the lift real or noise? | no |
| Ten | Did anything get worse since the last run you trusted? | no |
| Eleven | What does the improvement cost in tokens, dollars and time? | no |

The kit (`eval_kit.py`) runs the agent in a throwaway project with or
without the skill installed and records everything an eval might grade:
final text, every tool call, tokens, cost, duration. The interlude
(`commit_message_checks.py`) holds the deterministic checks and the case
list for the sample skill, so four later chapters grade with one ruler.
The notebook imports both; its first cells set the four configuration
values and then the eleven chapters follow.
Everything specific to commit messages lives in those two places and in
the fixtures.

Every record is a Pydantic model with a description on each field: the
skill, an agent run and its tool calls, a check result, a lint or scan
finding, the reply shapes the judge must return, and the row each live
chapter writes to `results/`. The descriptions are the documentation for
those files, the judge's reply model is the JSON schema the API enforces,
and a row that does not match its model fails loudly instead of silently.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
claude            # log in once; the live chapters drive the real Claude Code
echo 'TYPESAFE_API_KEY=...' > .env   # chapters three and a half, seven and a half
```

Then open `skill_evals.ipynb` from this folder in VS Code or JupyterLab
and run all cells. The shared infrastructure lives in `eval_kit.py` and
`commit_message_checks.py` next to the notebook. The notebook imports both;
start it from this folder so the imports find them and the kit's paths
resolve correctly, or the first cell will stop and say so.
To run it without opening anything:

```bash
jupyter execute skill_evals.ipynb --inplace
```

The live chapters drive Claude Code through the official
`claude-agent-sdk`, which works with a Claude Code login and needs no API
key. The two "half" chapters call TypeSafe's Jev and read
`TYPESAFE_API_KEY` from the environment or a `.env` file. Jev returns
typed judgments with probabilities in about a tenth of a second, so those
two run on every edit where their full-size counterparts run once.

Skills are loaded by the harness, not the model, so pasting a SKILL.md
into a raw API system prompt would never tell you whether the description
triggers. Here the skill is copied into `.claude/skills/` in a fresh temp
folder, exactly as a user would install it.

Chapters four, five, six and eight each start the real agent. Chapter
seven sends chapter six's saved replies to a judge model. The defaults are
tiny (four cases, one or two attempts) so a full pass stays cheap. Chapter
nine will tell you, correctly, that eight pairs cannot resolve a
twenty-point effect. That is the lesson, not a bug: raise `AB_REPS` in chapter six
when you need a number you can defend.

Chapters seven, seven and a half, nine, ten and eleven do not start the
agent. They read rows that an earlier chapter saved to `results/`, and
stop with a message naming the chapter to run first if those rows are
missing. `results/` is not committed (it is in `.gitignore`, next to
`.env`), so the notebook's stored outputs are the only record of a run
until you make your own. That is the habit the notebook teaches: pay for
agent runs once, analyse them as often as you like.

## What you will see

Every chapter that touches the skill opens with a "skill under test"
panel: its name, its folder, and the description the harness routes on.
The live chapters show the exact prompt each case sends and the agent's
reply in a box before grading it. Chapter six shows the two arms' replies
side by side. Chapters six, seven and a half, eight and nine also narrate
themselves as they run, in yellow boxes titled "what happens next", "what
this means" and "how to read this", with the meaning written from the
actual outcome. Set `SKILL_EVAL_EXPLAIN=0` to silence them once you know
the material.

Every chapter logs what it is doing as it goes: which case is running,
whether the skill was installed, each tool call the agent makes, each
grading decision, and where results were saved. In the notebook the log
lines are coloured (via the rich library): green for passes, red for
failures, cyan for tool calls, magenta for the with and without arms,
yellow for case names. The same lines go to `logs/<chapter>.log` as plain
text. Set `SKILL_EVAL_LOG=debug` to also see full prompts, tool inputs and
judge replies. The tables at the end of each chapter are the results; the
log lines are how they came about.

## Words the notebook uses

- An arm is one side of a comparison: the with-skill arm and the
  without-skill arm.
- An oracle is a hand-written answer that should pass every check; a null
  is one that should fail. Both are used to prove a grader before trusting
  it.
- A trajectory is the ordered list of tool calls an agent made on the way
  to its answer.
- pass@k is the chance that at least one of k attempts passes; pass^k is
  the chance that all k do.
- A bootstrap interval is a range for a metric, found by re-sampling your
  own rows many times. A sign-flip test asks how often pure chance would
  produce a lift as large as the one you saw.
- Skill lift is the with-skill pass rate minus the without-skill pass rate.

## The sample skill

`skills/commit-message/SKILL.md` writes commit messages in a made-up house
style: a fixed set of types and scopes, a 50-character subject, a required
`Refs: ACME-1234` trailer, output only inside a ```text fence, and never run
`git commit`. It is made up on purpose. A skill for something the model
already knows (plain Conventional Commits) shows almost no lift, so you
learn nothing from the A/B. The rule is: make the task not answerable from
memory.

Every rule in the skill maps to an eval: the format rules to the
interlude's checks, the "why not what" rule to the judge, the "read the
diff first" step and the git prohibition to the trajectory eval.

## Fixtures

- `fixtures/diffs/` are the four inputs, each with a known right type and scope.
- `fixtures/bad_skills/sneaky-helper/` is a deliberately hostile and
  malformed skill so chapters one and two have a known-bad case. Do not
  install it.
- `fixtures/catalog/` are three decoy skills that overlap with ours on
  vocabulary, so chapter three has something to collide with.

## What every good eval setup agrees on

The same handful of rules keeps coming back, whoever builds the harness.

1. Test the description before the body. A skill that does not trigger
   cannot help. Run positives and negatives, several times each.
2. Grade with code wherever you can, and prove the grader on a known-good
   and a known-bad answer before trusting it. Use a judge only for what
   code cannot see, and calibrate the judge the same way.
3. Pair the with and without runs, hold everything else fixed, and report
   the delta with an interval. One run is an anecdote.
4. Grade the end state and the tool log, not the transcript's narration.
5. Keep the skill files physically absent from the baseline workspace. A
   flag is not enough; the agent can go and read them.
6. Save every raw row. Chapters nine and eleven re-read what six saved,
   ten re-reads what four, five and six saved, and seven grades six's
   saved outputs, so none of them pays for a new agent run.

One thing worth knowing before you start: published benchmarks put the
average software engineering skill at a few points of lift, and find that
most add nothing measurable. If your A/B says "placebo", the eval may be
working fine.

## What the stored run found

The outputs stored in the notebook come from one pass, top to bottom, in
about nine minutes. The four chapters that start the agent spent a little
under three dollars between them, most of it in chapter four, and the
judge in chapter seven added a few cents. Five things are worth knowing
before you run your own.

- The offline routing test once caught a real vocabulary gap. "summarise
  these changes for git" routed to the git-help decoy because the
  description never said "changes". Adding the word fixed it. The live
  trigger eval now scores precision 1.00 and recall 1.00 over 14 runs, and
  Jev agrees on every prompt with a probability of 0.00 on ours for the
  ones that belong elsewhere.
- The A/B lift is +1.00 over 8 pairs (with skill 8/8, without 0/8). The
  baseline never produced the Refs trailer or the fence, which is the
  point of a made-up house style: the model cannot know it. Chapter nine
  calls the result real, and adds that at 8 pairs anything under about
  0.35 would have been noise.
- An earlier version of the judge had a fourth assertion, "no commentary
  outside the commit message", and it failed 7 of 8 with-skill outputs.
  Reading those outputs showed the judge counting the ```text fence itself
  as commentary. The assertion was dropped, and the lesson stayed in the
  chapter's opening: spot-check the failures, because some of them are
  grader bugs. Both markers now pick the with-skill answer 8 times out of 8
  and never contradict themselves.
- The trajectory eval is the chapter that varies most from run to run. In
  the stored run, the agent asked to "go ahead and commit them" wrote the
  message, quoted the skill's rule 7 back at the user and held off, so the
  limit held. An earlier run committed anyway. What failed this time was
  the order: the agent ran `git status` before it loaded the skill, so the
  "load the skill, then work" sequence the skill assumes is not what
  happened. One case of two scored full marks. No other chapter can see
  either of those things.
- The efficiency eval classifies the skill as a TRADEOFF: pass rate up
  from 0 to 1, bill up by about a quarter. The extra cost comes from turns,
  not from the skill body. A with-skill run takes three turns (load the
  skill, read the result, answer) where the baseline takes one, and each
  turn re-reads the whole context.

## Swapping in your own skill

Set `eval_kit.SKILL_DIR` in the notebook's config section to your folder,
rewrite `commit_message_checks.py` with checks and cases for your skill,
and replace the fixtures. Then edit the prompts that are specific to commit
messages: the positive and negative prompts and the decoy catalog in
chapters three and three and a half, the negative prompts in chapter four,
the assertions at the top of chapter seven and the questions at the top of
seven and a half, and the trajectory cases in chapter eight. Chapters one,
two, five, six, nine, ten and eleven need no changes.
