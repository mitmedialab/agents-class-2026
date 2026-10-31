# Course MCP

The standalone Course MCP lets a student use selected course capabilities inside
supported AI clients while keeping authorization in the course platform. It is a second client
for the same course account and data. See [the setup and access guide](../docs/MCP.md).

The maintained [assignment instruction](learning-contract.md) accompanies each
assignment read. It asks whichever connected model the student uses to preserve
the student's intellectual work, ask assignment-specific questions, and check
understanding. Before substantive suggestions, diagrams, architecture, or
implementation, it asks the model to warn about AI-idea bias and wait for the
student's explicit confirmation. It directs the model to check the assignment,
schedule, and relevant class slides/readings before outside material, and not
to invent a diagram in place of an uninspected class slide. The MCP does not
save or grade check-ins, and has no tool to write website documentation. Model
behavior cannot be guaranteed by MCP text.
Students can read the exact maintained instruction at the public
`/learning-contract` page or its `/learning-contract.md` source before connecting.
The course website's `/ai-connect` page links to client setup screens and gives
the MCP URL and manual steps; opening a client link alone grants no access.

The MCP now exposes released assignments; searchable, authorized course resources
(including readings and extracted slide text); updates and deadlines; and the
student's own staff communications. If the website's GitHub integration is
enabled, it can also inspect deployed project sites and the student's own
repository. Those tools are read-only. With messaging enabled, the MCP can also
prepare student-authored messages and replies; only a signed-in student can
deliver them by reviewing and pressing Send on the course website. See the
[capability details](../docs/MCP.md).

The resource tools let a connected assistant read course slides and readings, explain
terminology, and connect those sources to a student's build. Assignment reads also include
instructions to ask questions about the student's own work and check understanding before
offering substantial implementation help. These instructions guide the client model; the
course platform cannot enforce the quality of its answers.

## Class AI Policy
AI use is allowed with transparency. Show when and why you used AI to help with an
assignment. Because AI coding tools are readily available, the course expects clear
motivation, a solution that addresses the chosen problem thoroughly, and work that you can
explain in weekly lectures. You should understand the underlying structures, design
choices, and limitations, even if you cannot explain every line of code.
