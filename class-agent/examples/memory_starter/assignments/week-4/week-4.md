# Week 4: Building an Agent Environment

*See this week's tutorial, where Sheer built a [simulated environment of a student's laptop](https://github.com/skarny0/learnos).*

In previous weeks, you built an agent loop, expanded it with tools, and designed how it interacts with a human. This week, you will build the **environment the agent acts within**.
Your environment can be almost anything: physical, digital, simulated, real, social, app, game-emulator, or YOU can be the environment! You are allowed to improve upon a previous environment.

## 1. Analyze one to two existing agent environments

Read at least **one** paper that build or evaluate agent environments. You may choose examples from the Week 4 slides/readings or find papers relevant to the environment you intend to build.

For the chosen paper, briefly identify:
- The **environment states \(S\)** (including cognitive states of human agents in the environment where relevant), **observation space \(O\)**, **action space \(A\)**, and importantly **transition dynamics**, i.e. the logic and probabilities of changes in the environment (with or without actions). Environment states and transition dynamics, are unique to the environment, while the observation and action space define what the agent can observe and do within an environment.
- How tasks or initial states are generated.
- Where the environment falls on the dimensions from *Russell and Norvig (1995)* (see slides).
- The **unit of evaluation** and **scoring procedure** used (see slides for taxonomy).
- How the authors **validate the environment itself**, if they do.
End with 2–3 sentences on what you would borrow, change, or avoid when designing your own environment.

## 2. Define a task environment

For your weekly build, choose an agent objective related to cognitive augmentation. Briefly explain:
- Why your interactive environment is interesting for agents to act within compared to an agent returning a text response / answer.
- What objectives agents could try to achieve in the environment.
- What success and failure would mean in the real problem you are trying to represent in the environment.
Then characterize your environment using the terminology from class:

| Component | What to specify |
| --- | --- |
| **Environment state \(S\)** | What variables constitute the state of the world? |
| **Observation space \(O\)** | Independently of one agent implementation, what are all the possible observations of the environment that any agent can receive (e.g. screeshots of gameboy)? What remains hidden? |
| **Action space \(A\)** | Independently of one agent implementation, what are all the possible actions that any agent can do to the environment? |
| **Transition dynamics** | How do actions and other non-agent events change the environment state? |
| **Initial state / task distribution** | How are starting conditions and task instances generated? |
| **Agent objective / reward** | What are some possible agent objectives in the environment? |
| **Stopping condition** | When does an episode end? |

Also characterize your task environment along the dimensions from *Russell and Norvig (1995)*: **fully vs. partially observable, single- vs. multi-agent, deterministic vs. stochastic, episodic vs. sequential, static vs. dynamic, discrete vs. continuous, and known vs. unknown.**
Be explicit when an **observation is only a proxy for an underlying state**. For example, what a student says is observable, while what the student actually understands may be a partially observable or hidden state.

## 3. Build the environment

Implement a functioning environment in which an LLM-based agent can complete tasks. Your environment should:
1. Maintain explicit **environment states** and define how those states change.
2. Build an agent-environment interface that define an **observation space** and **action space** from which any agent may be able to partially or fully draw from. Ensure that the **environment logic** is separated from the **agent policy** as much as possible in the interface (see slides).
3. Implement meaningful **transition dynamics** in response to actions and, where relevant, other factors such as time, other agents, or stochastic events.
4. Support a reset or initialization procedure that can produce multiple task instances or starting states.

## 4. Validate your environment

If your environment is intended to represent or simulate something in the real world, perform **at least one simple validation** of the part of the environment that matters most for your claim. If external validation is not meaningful for your environment, explain why.
Choose a validation strategy appropriate to your environment, such as:
- **Theory or construct grounding:** Are important states and transition rules grounded in a relevant theory or established model? For example, a learning environment might ground knowledge-state transitions in a learning or knowledge-tracing model.
- **Perceived realism:** Do relevant users or experts judge the environment, states, or transitions as realistic?
- **Real-world data alignment:** Do simulated states, actions, or transition dynamics resemble available real-world data? Calculate a match score.
- **Real-world outcome validity:** Do effects observed in the environment reproduce, predict, or align with effects observed in the real world?
Keep this validation small and feasible (spend 30-45 min total time on validation). The goal is to provide some evidence for why the environment is a reasonable test bed.

## 5. Document your progress

Overall, in your Week 4 documentation, include:
- **Prior environments:** Your analysis of the paper and what you learned from their environment design, validation, and evaluation, according to criteria in (1).
- **Environment specification:** \(S\), \(O\), \(A\), transition dynamics, initial state/task distribution, stopping condition, and the Russell and Norvig task-environment dimensions.
- **Technical overview and flow:** A diagram showing the agent, environment, agent–environment interface, relevant states, and grader(s).
- **Environment validation:** What you validated, how, what evidence you obtained, and what remains uncertain.
- **Failure analysis:** What went wrong, unvalidated and where the environment is could be improved to be more realistic or impactful.
- A link to your code and an example run
- Images or video documentation.
- A short reflection on what you learned and what you would improve.
- A disclosure of how and why you used AI.
As in previous weeks, your documentation and reflection should be written by you rather than generated by AI. AI coding assistance is allowed as long as you understand and can explain the resulting system.

## 6. Submission and in-class sharing

Publish your Week 4 documentation and code to the private GitHub repository associated with the GitHub ID you provided to the course staff. Test the links and demo media from a signed-out or fresh browser session where possible.
You may be randomly selected to present your week 4 and 5 work in class. Be ready to explain:
1. **The problem:** What objectives is the environment trying to enable agents to complete?
2. **The environment:** What are \(S\), \(O\), \(A\), the transition dynamics, task distribution, and stopping condition?
3. **What you learned:** One interesting failure, limitation, or result from your environment build and testing.
