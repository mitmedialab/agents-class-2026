# GenerativeAgents · placelab

3D simulation of the third floor (E14/E15) where the students of **Cognitive Agents** appear as
nameless characters with memory, following the *Generative Agents* architecture (Park et al., 2023):
they perceive, store memories with a *poignancy*, retrieve by recency × relevance × importance,
reflect (3 questions → insights with evidence) and converse. When they talk they cross what they
bring (project, interests, skills), and new ideas are born from that.

Interface: **profile** (accept or modify your profile) → **simulation** (3D, each character's memory)
→ **results** (idea heat map by space, conversations day by day, new ideas). The interface is in English by
default, with a Spanish switch at the top right.

## How to run the simulation

Three ways, from simplest to most complete:

1. **Nothing to install.** Clone the repo, open `GenerativeAgents/`, run `python3 build.py` once and
   double-click `dist/placelab.html`. It is a single file with everything inside; it only needs an
   internet connection to load three.js from a CDN. (`dist/` is git-ignored, which is why you build
   it first; remove it from `.gitignore` if you want the ready-made HTML to travel with the repo.)
2. **To develop or modify.** From `GenerativeAgents/`:
   ```bash
   python3 -m http.server 8000 --directory src
   ```
   then open `http://localhost:8000`. Edit the modules in `src/` (profiles, spaces, idea rules,
   texts) and reload the page.
3. **As a public web page.** Enable GitHub Pages for the repo (or copy `dist/placelab.html` to
   `docs/index.html`) and it lives at `https://<user>.github.io/agents-class-2026/…`. It can also be
   published as a claude.ai artifact.

The profile you accept is stored in your browser (localStorage); nobody else sees it. The interface
is in English by default, with a Spanish switch at the top right.

To change the people: edit `tools/students.csv`, then run
`python3 tools/roster2profiles.py tools/students.csv` and `python3 build.py`.

## Structure

```
src/
  index.html      page (band, profile, simulation, results)
  styles.css      Teenage-Engineering-style typography + black band
  data/plan.js    floor plan: walls, corridors and texture (generated from the plan image)
  profiles.js     PROFILES: nameless students (code, team, interests, skills, project)
  scene.js        three.js: floor, walls, navigation grid, mask of the common spaces
  memory.js       Generative Agents core: ConceptNode, AssociativeMemory, Scratch, retrieve, reflect, chat
  agents.js       common spaces, facts, ideas and the replaceable LLM_* functions (templates)
  i18n.js         EN/ES texts and rule-based translation of the generated sentences
  sim.js          population, movement, conversations, results, persistent profile
tools/sites2csv.py         students' public agentic websites -> tools/students.csv (bio + one column per weekly build)
tools/sites.txt            list of student sites (repo slug agents2026-xxx or full URL), one per line
tools/roster2profiles.py   students.csv or course-members.json (private roster) -> src/profiles.js, no names/emails
tools/students.csv         columns: code,team,site,bio,final_project,W00..Wnn,interests,skills,project
build.py                   -> dist/placelab.html (single file)
```

## Where to change things

| I want to change… | File |
| --- | --- |
| the students (code, team, interests, skills, project) | `src/profiles.js` (or `tools/roster2profiles.py` from the roster / CSV) |
| the common spaces, their facts and which areas can be walked | `src/agents.js` (`SP`, `FACTS`) and `src/scene.js` (`OPEN_ZONES`, `FORBID`) |
| how ideas are born and when someone joins one (the "LLM" functions) | `src/agents.js` (`LLM_utterance`, `tryBorn`, `ideaEvidence`) |
| the sentence templates and their translation | `src/agents.js` and `src/i18n.js` (`RULES`, `PRE`) |
| memory (retrieval, reflection, poignancy) | `src/memory.js` |
| day rhythm, breaks, conversation length | `src/sim.js` (`nextOuting`, `cafeMult`, `arrive`) |
| interface texts (EN/ES) | `src/i18n.js` (`UI`) |
| styles | `src/styles.css` |

## Loading the real students

The class roster is private and git-ignored, so it is **not** in this repository. What is public is
each student's agentic website on GitHub Pages (`https://mitmedialab.github.io/agents2026-<name>/`).
Put the site slugs in `tools/sites.txt` (one per line; the list comes from the class site or the
Course Agent's `list_student_projects`), then:

```bash
python3 tools/sites2csv.py tools/sites.txt      # scrapes bio + weekly builds -> tools/students.csv
python3 tools/roster2profiles.py tools/students.csv
python3 build.py
```

`students.csv` keeps one column per weekly build (W00, W01, …), the bio/about text and the final
project; the converter turns them into the profile the character carries (project = final project
or latest build; interests/skills from the builds unless the `interests`/`skills` columns are filled).

`src/profiles.js` must never contain names or emails: the converter only keeps `department`,
`keywords` and `project_ideas` of active members.
