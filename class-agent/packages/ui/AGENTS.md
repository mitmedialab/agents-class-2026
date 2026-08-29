# First-party UI library instructions

These rules apply to `packages/ui/` in addition to the repository-root and `class-agent`
instructions. Read `docs/UI.md` and `docs/WORKSPACE.md` before changing a registered
renderer or its visual contract.

## Component design

- Components must be independently importable, typed, understandable by students, and
  usable without depending on the web application's orchestration state.
- Prefer a small semantic prop API over exposing raw styles or implementation details.
- Keep rendering deterministic and side effects explicit through callbacks.
- Accept only the bounded values validated by the registered component protocol. Never
  accept model-provided HTML, CSS, JavaScript, class names, event handlers, Tailwind, or
  arbitrary style objects.
- Render model-controlled Markdown or text through the existing safe renderers; never use
  unsanitized HTML injection.
- A new trusted workspace component requires a genuine reusable platform capability, not
  a one-off answer layout. Coordinate its manifest/schema, Python and TypeScript
  validation, host renderer map, exports, tests, and documentation.

## Design system

`src/styles.css` is the first-party token and component-style source. Reuse its color,
surface, border, spacing, and radius variables. Add or change a token only when the choice
is reusable across components and consistent with the established interface.

The house style is restrained and editorial: predominantly monochrome, clear hierarchy,
fine rules, generous spacing, quiet controls, and minimal decoration. Avoid generic SaaS
dashboard styling, nested cards without information hierarchy, decorative gradients,
arbitrary accent palettes, oversized pills, novelty typography, and repeated shadows.

Visual compositions use semantic structures and variants:

- choose stack, row, or grid from the information relationship, not a default template;
- use side-by-side layouts only for genuinely parallel, comparative, or gallery content;
- keep text blocks concise and build scannable units with headings, facts, links, stages,
  timelines, or comparisons;
- use image presentation modes deliberately and preserve diagrams/screenshots with
  contain-fit;
- keep charts declarative, accessible, sourced, quantitatively defensible, and consistent
  with the bounded chart contract.

## Accessibility and resilience

- Use semantic elements, accessible names, visible keyboard focus, and correct disabled
  behavior.
- Support narrow containers and user font scaling; do not rely on a single viewport.
- Respect reduced-motion preferences and retain a usable static state.
- Provide safe empty, invalid, loading, and error states without exposing internals.
- Remote content must retain the documented HTTPS, sandbox, referrer, and authorization
  restrictions.

Add focused component tests for rendering and interaction behavior, and run the relevant
Vitest suite plus `pnpm typecheck` before handoff.
