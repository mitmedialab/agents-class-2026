# Placelab visual summary: decisions for the team

Started 2026-11-06 by Maya while prototyping the visual summary (`narrative-arcs.html`, `style-guide.html`). Each entry says what is undecided, the options, what the prototype does today, and a recommendation. Add your name and a comment under any entry, or change its status.

Status values: **open** (needs input), **leaning** (a direction is proposed but not agreed), **decided**.

---

## 1. Should agents show their students' names?

**Status:** open · **Affects:** the simulation, results, and any shared page

- **Context:** The repo's README and the simulation's intro text say agents are nameless and recognized only by their clothing ("only you know who you are"). The narrative chart now labels each lane "Name's Agent" so classmates can find their own agent.
- **Options:**
  - Keep agents nameless and let each person find themselves through their own saved profile.
  - Show first names everywhere.
  - Show names only on the results page, after the run.
  - Make it opt-in per person, using the consent step on the profile page.
- **Prototype today:** first names, taken from `profiles.js`.
- **Recommendation:** make names opt-in. It keeps the original privacy promise and still lets people find themselves.

---

## Decided

_None yet._
