# Week 8: help matchmaking on the Course Agent

Group 1 (Jad Bendarkawi, Yuxiang Cheng, Stacey Cho). This folder lists what the branch
`week8-inspectable-memory` adds to the Course Agent on top of
`student/week-8-personalization-starter`. It is reference material for the group and for
reviewers. The Week 8 writeup and reflection are written separately by the group.

- [backend.md](backend.md): database, service, agent tools, prompt, HTTP routes, tests.
- [frontend.md](frontend.md): People panel, API client, header button, styles, tests.

## What the feature does

The Course Agent remembers what a student says about themself and uses it in later
conversations. A student can also let classmates see what they can help with. When another
student is stuck, the agent can suggest that classmate and draft an introduction. Nothing is
sent until the requester clicks Send, and the helper chooses to accept or decline.

1. **Learn.** When a student states a background, goal, preference, project, something they can
   help with (`can_help`) or something they need help with (`needs_help`), the agent saves it
   with `memory.save_mine`. Each memory records the user message it came from.
2. **Adapt.** Every turn, the student's own newest memories are given to the agent, which uses
   them to shape explanations and next steps.
3. **Match.** When a student is stuck, the agent calls `peers.find_helpers`. That tool returns
   only what classmates chose to share. The agent names a fitting classmate and offers an
   introduction.
4. **Introduce.** After the student agrees, `peers.request_introduction` creates a draft in the
   People panel. The student sends it, and the helper accepts or declines there.

## Whose information, from where, who can see or change it

| | |
|---|---|
| Whose | Only the logged-in student's own statements. The agent is told not to save guesses, grades or information about other people. |
| From where | A user message in that student's own conversation. The memory stores that message's event id and a 280-character excerpt, which People shows as "From your message". |
| Only me (`personal`, the default) | Readable only by the owner, in People and in the agent's context for the owner's own turns. |
| Classmates (`course_private`) | Set only when the student agrees. `peers.find_helpers` may show the item to other active students. |
| Course staff | No surface. No staff tool or route reads memories. |
| Who can change it | Only the owner. In People the owner can correct the text, change visibility or forget the memory; the owner can also ask the agent to forget one. Every route and tool takes identity from the session (`PrincipalContext`), never from arguments. |
| Introductions | A draft is visible only to the requester. After Send, the helper sees the requester's name, the topic and the message. A decline shows the requester only "Not available this time", with no reason. |

The two privacy values are the ones already defined by the constitution's `Memory` contract
(section 22). The contract was not changed.

## Example interaction (local run, live model)

These turns ran against a local copy of the agent using local demo accounts named after the
group. Jad's and Stacey's statements were **written for the demo**; neither teammate said them.

1. *jad*: "I finally got OAuth working for my Course MCP connector ... happy to help classmates
   who get stuck on MCP auth, and you can share that." The agent saves a `can_help` memory
   visible to classmates.
2. *stacey* shares that they can help with study and evaluation design. The agent saves it,
   visible to classmates.
3. *yuxiang*: "I come from hardware and firmware ... explanations land best as physical analogies
   ... keep that private." The agent saves a private `preference` and a private `background`.
4. *yuxiang*, in a **new conversation**, asks about a `redirect_uri` mismatch and PKCE. The answer
   opens with a building-access-badge analogy, which comes from the private preference. It also
   suggests Jad, because Jad shared that experience; the agent picked Jad from three shared
   offers.
5. The same question from an account with no memories got no analogy, but got the same
   suggestion. The private memory changed how the agent explained, and the shared memory
   changed what it did.
6. *yuxiang* agrees. The draft appears in People, and *yuxiang* clicks Send. *jad* opens People,
   sees "From Yuxiang Cheng" and clicks Accept.

## Known gaps

- The helper is not notified of a new request. It is visible only when they open People.
- There is no follow-up asking whether the help worked.
- Matching is the model's judgement over all shared offers. That is enough for one class, but
  it would need retrieval as the number of offers grows.

## Run it locally

Follow `class-agent/examples/memory_starter/README.md` (setup, `.env`, API and web app).
Setup applies the new migration automatically. Log in as a student and open **People** in
the header.
