# Slide deck source

`content.py` holds every word on every slide and writes `content.json`. `build.py` renders that JSON as the sixteen web slides in `project/slides/` and the index
`project/deck.json`, and `build_pptx.js` renders the same JSON as
`skill-evals.pptx`. The web version lives at
https://claude.ai/artifact/3nG8nSwm1T3BGjDjffago5.

To change a slide: edit `content.py`, then

```bash
python3 content.py                       # writes content.json
python3 build.py                         # web slides, republish the changed files
NODE_PATH=$(npm root -g) node build_pptx.js   # skill-evals.pptx
```

The deck covers ideas only: what each eval type asks, how it works, and
what to watch out for. The code is in the numbered files one level up.
