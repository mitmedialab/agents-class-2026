# GenerativeAgents · placelab

3D simulation of the third floor (E14/E15) where the students of **Cognitive Agents** appear as
nameless characters with memory, following the *Generative Agents* architecture (Park et al., 2023):
they perceive, store memories with a *poignancy*, retrieve by recency × relevance × importance,
reflect (3 questions → insights with evidence) and converse. When they talk they cross what they
bring (project, interests, skills), and new ideas are born from that.

Interface: **profile** (accept or modify your profile, dress your avatar, optionally from your
camera, and pick the two initials shown next to it) → **simulation** (3D, each character's memory) →
**report**, four tabs: **who talked to whom** (the chart from `visual-summary/`), **newsletter** (the
run written up), **where** (the idea heat map: the plan warms up where conversations happened and
where ideas were born, with a time slider from day 1 to day 3, and a few lines on each space) and
**evaluation** (reserved, still to be written). The page follows the system's light or dark mode; the
switch in the band pins one. It also opens inside the course site (`class-agent/apps/web`) under the
**Place Lab** entry of its header, at `/placelab`. Run it again and the agents remember earlier runs. The interface is in English by
default, with a Spanish switch at the top right.

## The pipeline

1. **Your character.** Pick your code. Your teammates' characters come from their `people/` files,
   including their `avatar`. Dress yours with the swatches, or press **use my camera**: the camera
   never leaves the page; each frame is shrunk at once to the 16 × 24 avatar (skin, hair and shirt
   snapped to the palettes, a 7 × 5 face grid, a head tilt), and only that avatar is shown and kept.
   **Copy for my people/ file** gives you the `avatar` entry to commit.
2. **The run.** The active agents wander the common spaces and talk. With `serve.py` and a Gemini key,
   each conversation is written by Gemini Flash: each agent brings one weekly build or one research
   interest from its `people/` file, picked at random, plus the memories it retrieves; the
   conversation ends with an insight and sometimes a new idea, or a new version of an idea in play.
   Without AI (no server, no key, the single file, or a failed call), `src/offline.js` writes the
   same kind of conversation with fixed rules: what each agent brought, the word their two pieces of
   work share, a skill one offers the other, an insight, and sometimes an idea. Everything downstream
   (cards, memory, follow-ups, the newsletter) works the same way.
3. **Memory.** Each conversation becomes an episode (who, where, what each brought, the insight, the
   idea) in `data/episodes.jsonl`. Later runs load them into the agents' memory, so the next
   conversation between the same two picks up the thread, and ideas can build on earlier runs' ideas.
4. **The report.** When the run ends: a newsletter of the new ideas, the insights, your agent's
   column, conversations and achievements (written by Gemini, or by fixed rules without AI), the chart of who
   talked to whom, and the details. **Run again** starts the next run; earlier reports stay
   in `data/runs/` and can be reopened from the report.

## How to run the simulation

Four ways:

1. **With Gemini (the full pipeline).** Copy `.env.example` to `.env`, put your key in
   `GEMINI_API_KEY` (from https://aistudio.google.com/apikey), and from `GenerativeAgents/`:
   ```bash
   python serve.py          # then open http://127.0.0.1:8000
   ```
   Standard library only. It regenerates `src/profiles.js` from `people/`, checks the model, serves
   `src/` and `visual-summary/` (nothing else: not `.env`, not `data/`), and forwards conversations
   to Gemini. The key stays in the server; the browser never sees it. The model defaults to
   `gemini-flash-lite-latest`, about 1.5 s per conversation (`gemini-flash-latest` thinks first and
   takes 25-50 s); set `GEMINI_MODEL` in `.env` to pin another (the server lists the Flash
   models your key can use if the default is unavailable). A three-day run with four agents makes
   roughly 30-60 calls plus one for the newsletter; free-tier daily limits allow a few runs a day.
   What is sent to Google: the agents' projects, skills, interests and weekly builds from `people/`,
   their remembered insights and the ideas in play, never names (the newsletter refers to agents as
   handles such as `@S02` and the page puts the names back).
2. **Nothing to install.** Clone the repo, open `GenerativeAgents/`, run `python3 build.py` once and
   double-click `dist/placelab.html`. It is a single file with everything inside (the report's chart
   too); it only needs an internet connection to load three.js from a CDN. It has no server, so the
   agents use the offline conversations (`src/offline.js`), and the memories across runs are kept in
   your browser. (`dist/` is git-ignored, which is why you build
   it first; remove it from `.gitignore` if you want the ready-made HTML to travel with the repo.)
3. **To develop without a key.** `python serve.py` without a key runs everything with the offline
   conversations of `src/offline.js`. A plain static server also works, started from `GenerativeAgents/` so that the
   chart in `visual-summary/` is reachable: `python -m http.server 8000`, then open
   `http://localhost:8000/src/`. Edit the modules in `src/` and reload the page.
4. **As a public web page.** Enable GitHub Pages for the repo (or copy `dist/placelab.html` to
   `docs/index.html`) and it lives at `https://<user>.github.io/agents-class-2026/…`. It can also be
   published as a claude.ai artifact.

The profile you accept is stored in your browser (localStorage); nobody else sees it. The interface
is in English by default, with a Spanish switch at the top right.

To change the people: the active characters come from `people/` (one JSON file per team member, see
`people/README.md`), and the idle background characters come from `tools/students.csv`. `serve.py`
regenerates the profiles when it starts; otherwise run `python tools/roster2profiles.py` (and
`python build.py` for the single file).

## Structure

```
src/
  index.html      page (band, profile, simulation, results)
  styles.css      Teenage-Engineering-style typography + black band
  data/plan.js    floor plan: walls, corridors and texture (generated from the plan image)
  profiles.js     PROFILES, generated by tools/roster2profiles.py (do not edit by hand)
  scene.js        three.js: floor, walls, navigation grid, mask of the common spaces
  memory.js       Generative Agents core: ConceptNode, AssociativeMemory, Scratch, retrieve, reflect, chat
  agents.js       common spaces, facts, ideas and the replaceable LLM_* functions (templates)
  i18n.js         EN/ES texts and rule-based translation of the generated sentences
  strings.js      EN/ES texts for the camera, the model conversations and the report
  talk.js         conversations written by Gemini (through serve.py) and the episodic memory across runs
  offline.js      the same conversations without AI: fixed rules over each person's file
  camera.js       the camera avatar: frames shrunk to the avatar grid in the page, never shown or kept
  report.js       the final report: run record, newsletter, achievements, chart, earlier runs
  sim.js          population, movement, conversations, results, persistent profile
serve.py                   local server: the page, Gemini calls (key from .env), data/ for memory and runs
prompts/converse.md        the conversation prompt (what each agent brings, insight, idea or not)
prompts/newsletter.md      the newsletter prompt
.env.example               copy to .env (git-ignored) and add GEMINI_API_KEY
data/                      git-ignored: episodes.jsonl (memory across runs) and runs/run-N.json (reports)
visual-summary/            the "who talked to whom" chart: standalone with its sample run, or inside the report
people/*.json              the team: one file per person who agreed to be simulated; the only active characters
tools/sites2csv.py         students' public agentic websites -> tools/students.csv (bio + one column per weekly build)
tools/sites.txt            list of student sites (repo slug agents2026-xxx or full URL), one per line
tools/roster2profiles.py   people/*.json (active) + students.csv or course-members.json (idle background) -> src/profiles.js
tools/students.csv         background characters; columns: code,team,site,bio,final_project,W00..Wnn,interests,skills,project
build.py                   -> dist/placelab.html (single file), and a copy for the course site at
                           class-agent/apps/web/public/placelab/index.html (served at /placelab)
```

## Where to change things

| I want to change… | File |
| --- | --- |
| the active team (code, team, interests, skills, project, weekly builds) | `people/*.json`, then `tools/roster2profiles.py` |
| the idle background characters | `tools/students.csv`, then `tools/roster2profiles.py` |
| the common spaces, their facts and which areas can be walked | `src/agents.js` (`SP`, `FACTS`) and `src/scene.js` (`OPEN_ZONES`, `FORBID`) |
| what the model is asked in each conversation, and for the newsletter | `prompts/converse.md`, `prompts/newsletter.md` |
| what each agent brings and remembers in a model conversation | `src/talk.js` (`topicsOf`, `episodeMemories`, `startModelTalk`) |
| the model and how many calls run at once | `.env` (`GEMINI_MODEL`), `serve.py` (`GATE`) |
| the conversations without AI (fixed rules) | `src/offline.js` (`localConverse`, `OFF_T`) |
| the original template conversations, now a last resort | `src/agents.js` (`LLM_utterance`, `tryBorn`, `ideaEvidence`) |
| the newsletter, achievements and the report | `src/report.js` |
| avatar options and the camera | `src/scene.js` (`avatarRows`, palettes), `src/camera.js` |
| the sentence templates and their translation | `src/agents.js` and `src/i18n.js` (`RULES`, `PRE`) |
| memory (retrieval, reflection, poignancy) | `src/memory.js` |
| day rhythm, breaks, conversation length | `src/sim.js` (`nextOuting`, `cafeMult`, `arrive`) |
| interface texts (EN/ES) | `src/i18n.js` (`UI`), `src/strings.js` (`UI2`) |
| styles, light and dark tokens | `src/styles.css` (`:root`, `:root[data-theme="dark"]`) |
| the evaluation tab of the report | `src/index.html` (`#rp-eval`), a `renderEvaluation()` in `src/sim.js` |

## The team: `people/`

Only people with a file in `people/` are active: they walk, talk, remember and form ideas. Each
member writes their own file from their own documentation repository, for example with Claude and
`people/hyungwoon.json` as the example (see `people/README.md`), reads the result, and commits it.
`tools/roster2profiles.py`
checks every file and refuses to generate `src/profiles.js` if one is invalid.

## Background characters

Everyone in the background source is idle: they stay in room 341 and never talk, whatever the
`active` column says. A background row whose `code` matches a `people/` file is skipped. The class
roster is private and git-ignored, so it is **not** in this repository. What is public is
each student's agentic website on GitHub Pages (`https://mitmedialab.github.io/agents2026-<name>/`).
Put the site slugs in `tools/sites.txt` (one per line; the list comes from the class site or the
Course Agent's `list_student_projects`), then:

```bash
python3 tools/sites2csv.py tools/sites.txt      # scrapes bio + weekly builds -> tools/students.csv (overwrites it)
python3 tools/roster2profiles.py tools/students.csv
python3 build.py
```

`sites2csv.py` rewrites `students.csv` from scratch: hand-added columns such as `name` are lost, and
only the sites listed in `sites.txt` remain.

`students.csv` keeps one column per weekly build (W00, W01, …), the bio/about text and the final
project; the converter turns them into the profile the character carries (project = final project
or latest build; interests/skills from the builds unless the `interests`/`skills` columns are filled).

What reaches `src/profiles.js` from a CSV row: code, team, interests, skills, project, weekly-build
titles, bio, site and name. These are shown in the profile picker. From `course-members.json` the
converter keeps only `department`, `keywords` and `project_ideas` of active members, with no names.
