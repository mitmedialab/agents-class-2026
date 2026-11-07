# Visual summary prototype

A prototype of the results view for Placelab: a narrative chart of who talked to whom over the three simulated days. It is here for review and is not wired into the simulation.

## Open it

Open `narrative-arcs.html` in a browser. It needs `narrative-data.js` in the same folder and nothing else; no server or API key.

## What it shows

- Each line is one agent, grouped into students, professors and TAs. Each day has its own lane order, chosen to keep lines from jumping around.
- Each dot is one conversation, colored by outcome. Click a dot for its topic and transcript, or click a line or name for that agent's conversations.
- Click an outcome in the legend to highlight those conversations. In an agent's panel, "play their path" walks through their conversations in order.

## Where the data came from

`narrative-data.js` is one headless run of `GenerativeAgents/src` (unchanged) with every profile switched on: 177 conversations and 53 ideas. The run is random, so another run would look different. Some transcript lines are part Spanish because the translation in `src` is incomplete.

## Other files

- `style-guide.html`: the tokens and components the prototype uses, taken from `src/styles.css`.
- `DECISIONS.md`: open questions for the team, starting with whether agents should show students' names.
