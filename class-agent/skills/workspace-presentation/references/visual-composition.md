# Visual composition guidance

Build `visual-composition` only from registered group, image, heading, text, badge, link, facts,
chart, input, textarea, divider, and spacer elements. Element IDs are objects and group children
reference those IDs.

If a course-resource read returns `registered_assets`, set the composition's `resource_uri` to that
resource and use an exact returned `asset_id` without a URL. Never invent an asset ID or convert a
relative Markdown path into an image URL.

Open a new composition for a new question or analytical angle. Update the existing composition only
when the user is explicitly revising that current UI. Complete the presentation pass before the
first open:

- Use strong hierarchy, generous outer padding and spacing, balanced composition, and surfaced
  grouping where useful.
- Treat stack, row, and grid as equal options. Use columns only for genuinely parallel material,
  direct comparisons, or a coherent gallery.
- Do not repeat one hero-and-card template or multiple two-column sections merely for decoration.
- Keep text elements short. Convert enumerations into scannable facts, stages, timelines, cards, or
  badges.
- Put a diagrammatic group or meaningful image in the first visible section when the subject
  supports one.

Choose image presentation deliberately: `banner` for a strong panoramic or wide figure, `feature`
for a large image beside concise copy, `card` for repeated examples, and `avatar` for a compact
person profile. Use `contain` for diagrams and screenshots and `cover` for photographic banners and
cards. A contained image with aspect ratio 2:1 or wider should be full-width in a stack, never placed
beside a substantially taller text card. Reserve split features for portrait, square, or moderately
landscape media.

Use a display heading at most once. Do not let display-scale text crowd out primary media. In a hero
or feature, primary imagery should normally occupy roughly one-third to one-half of the width or a
full-width region.

Use charts only for verified quantitative comparisons or trends: bar for categories, line for an
ordered sequence or time, and area only for meaningful magnitude or accumulation. A chart may have
at most 16 labels and four series. Every chart must declare `data_kind`, `data_source`,
`comparison_basis`, and `unit`. `data_kind` is `measured`, `user-provided`, or `derived`.

Never invent or estimate numbers for visual richness. Do not chart qualitative ranks, directional
placeholders, or incomparable outcomes. When defensible numbers are absent, use a process, timeline,
facts, or another non-chart visual.

A chart is a primary full-width editorial section, not a nested decorative card. Series objects use
`label` and `values`, never `name`, with optional `tone` or per-value `tones`. Put `tones` inside the
series object aligned one-for-one with labels; never put `tones` or `value_tones` on the chart element.
Prefer one to three deliberate palette tones instead of arbitrary rainbow coloring.

When a composition opens or changes successfully, the workspace carries the detailed answer. The
final chat response should be one short handoff sentence and should not repeat the facts already
shown there.
