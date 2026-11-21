# people/

One JSON file per team member who agreed to be simulated. These files are the only source of the
**active** characters in placelab: they walk, talk, remember and form ideas. Everyone else in the
simulation is an idle background character from `tools/students.csv` and never talks.

| File | Person | Data |
| --- | --- | --- |
| `hyungwoon.json` | S02 · Hyungwoon Lee | summarized from his documentation repository (weeks 1–6) |
| `roma.json` | S07 · Roma Luo | summarized from his documentation repository (weeks 1–5), course site (week 6) and final project proposal |
| `leticia.json` | S08 · Leticia | migrated from the public course site |
| `mdetwiller.json` | S17 · mdetwiller | placeholder until she sends her own data |

After you add or edit a file, regenerate the simulation's profiles from `GenerativeAgents/`:

```bash
python tools/roster2profiles.py   # people/*.json + tools/students.csv -> src/profiles.js
python build.py                   # optional: single-file dist/placelab.html
```

The generator refuses to write `src/profiles.js` if any file is invalid, and names the file and field.

## Updating your own file

Open Claude (or any assistant) in a clone of your own documentation repository and give it
`hyungwoon.json` as the example, with a prompt such as:

> Read my course documentation in this repository and write my placelab person file in the same
> format as the attached `hyungwoon.json`. Keep `code`, `name`, `team` and `site` from my existing
> file. `project` is a short lowercase phrase (under 140 characters) that reads well after "my
> project is about". `interests` and `skills` are 1–5 short terms each. Write `bio` in the third
> person. Give each interest a short `term` and a `description` of a few sentences on what you
> mean by it and how your work approaches it. Add one `weekly_builds` entry per documented week,
> with a summary of a few sentences: what you built, how, and what you found. Leave out other
> people's names and personal details.

Ideas form only when two characters share an interest or skill **word for word**, so reuse a
teammate's exact term (for example `simulation`) where it is true of you. Read the result before
you commit it: it comes from your own repository and becomes public once it is in this one.

## Format (`schema_version` 1)

```json
{
  "schema_version": 1,
  "code": "S02",
  "name": "Hyungwoon Lee",
  "team": "MIT Media Lab",
  "site": "https://mitmedialab.github.io/agents2026-hyung/",
  "bio": "One or two sentences.",
  "project": "The current or final project, in one sentence.",
  "interests": [
    {"term": "working memory", "description": "A few sentences on what you mean by it and how your work approaches it."},
    "wearables"
  ],
  "skills": ["simulation", "interfaces"],
  "weekly_builds": [
    {"week": "W04", "title": "working memory simulation on Aria Gen 2", "summary": "What you built, how, and what you found."}
  ],
  "source": {"method": "how this file was produced", "date": "2026-11-07"}
}
```

| Field | Rule | Used in the simulation as |
| --- | --- | --- |
| `code` | required, unique, never change it (browsers store it to remember your character) | identity |
| `name`, `team`, `site` | strings, maintained by hand | profile picker and results |
| `bio` | string, may be empty | profile preview |
| `project` | required, at most 200 characters | what the character talks about; the base of every idea it starts |
| `interests` | 1–5 entries, each a term (at most 40 characters) or `{term, description}` | the **term** is matched word for word in template conversations; with Gemini, the description is what the agent talks about when it brings this interest |
| `skills` | 1–5 short phrases | what the character offers to others' projects |
| `weekly_builds` | list of `{week: "W01".."W99", title, summary}` | with Gemini, each conversation starts from one weekly build or one interest description per agent, picked at random: richer summaries make richer conversations |
| `avatar` | optional: `{"t", "h", "s", "p"}` (shirt, hair, skin and pants palette indexes) plus optional `"hs"` (hair style), `"g"` (glasses, 0 or 1) and `"face"` (35 of `s d e h`, from the camera) | your character's look; get it from **copy for my people/ file** in the page. The four current ones are placeholders |
| `source` | free-form provenance | not used; tells readers where the data came from |
