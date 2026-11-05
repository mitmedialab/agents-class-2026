# Week 7: Final Project Proposal Presentation

**Presentation date:** Tuesday, November 3

This week, your team will present your focused proposal for your final project. The goal of the final project is to develop the foundation of a paper that could eventually be submitted to a research conference such as ICML, NeurIPS, ICLR, COLM, or CHI.

## 1. Define the contribution and research question

Choose **one primary contribution type** relevant to agents for cognitive augmentation:

1. Agent or agentic system
2. Environment, benchmark/gym, or evaluation method for agents
3. Human-subject study of an AI agent's effect on people
4. Novel model, interface, harness, MCP, or other agent technique to improve existing agents

State at the beginning of the presentation:

- Your research question or hypothesis in one sentence.
- The primary contribution you expect the project to make based on the above contribution types.
- The target user, setting, or scientific problem.
- What will be learned if the project succeeds, beyond whether you built a functioning system.

## 2. Motivate the cognitive augmentation objective

Identify the cognitive domain (e.g. learning) and **one concrete human outcome** (e.g. motivation to learn) your project is intended to support. Cognitive domains include learning, memory, reasoning, attention, creativity, reflection, decision-making, communication, or social connection.

Explain:

- Why this outcome matters and for whom.
- Why an agent, environment, feature, or study is appropriate for the problem.
- How the contribution augments human capability.
- Possible harms, tradeoffs, or ways the intervention could fail to improve the intended outcome.

## 3. Position the project against prior work

Identify approximately **3–5 of the closest papers, systems, benchmarks, or relevant studies**. Make sure to include both recent technical papers that use contemporary agents and evaluations, as well as literature that identifies metrics relevant to your cognitive outcome. Include a compact comparison showing:

- What each prior work contributes.
- What it does not establish or support.
- How your proposed contribution differs.

End with a precise research gap. Novelty should not rest only on applying an existing agent architecture to a new topic or combining existing components.


## 4. Proposed approach

Show one diagram of the proposed system, environment, benchmark, or study. Explain the components and relationships necessary for the audience to understand how the contribution works.

Use the following as **contribution-specific guidance**:

| Contribution type | Most important questions to answer |
| --- | --- |
| **Agent or agentic system** | What is the objective? What can the agent observe and do? What environment, tools, policy, interface, and human control make the proposed contribution possible? |
| **Environment** | What are the important states, observations, actions, transitions, and task distribution? What real process does the environment represent, and how will that representation be validated? |
| **Benchmark or evaluation** | What capability or construct is measured? How are tasks sampled and scored? Why should the benchmark be considered valid, reliable, and sufficiently representative? |
| **Human-subject study** | What are the hypotheses, conditions, measures, procedure, and planned analysis? What agent or interface are participants experiencing? |
| **Novel technique** | What does the technique change, how is it expected to work, and what assumptions does it make? Which components are genuinely new? |

Reuse formal vocabulary from earlier assignments when it makes the proposal more precise. You do not need to reproduce every Week 1–6 specification.

## 5. Claims and evaluation plan

State **one primary claim or hypothesis**. You may include up to two secondary claims if necessary. Then explain how the proposed evaluation could support or challenge those claims.

At minimum, identify:

- The tasks, data, environments, models, or participants that will be studied.
- A credible baseline, prior method, or control condition.
- The principal measures and why they capture the intended agent capability or human outcome.
- The planned scale of the evaluation—for example, number of tasks, trials, models, seeds, or participants—and how uncertainty will be represented.
- A result that would weaken the primary claim, plus one important limitation, confound, or failure case.

**Important:** A working demo, user preference, or an agent's self-report for a final project is not sufficient evidence by itself. When a measure is only a proxy (for example, quiz performance as a proxy for learning), explain what it captures and what it does not.

Choose additional rigor appropriate to the contribution:

- **Agent or technique:** strong baselines, repeated trials, and an ablation that isolates the proposed innovation.
- **Environment:** validation of the environment itself, separate from the performance of a particular agent.
- **Benchmark:** task coverage, contamination, annotation reliability, and results from several baseline models.
- **Human study or interface:** a meaningful comparison condition, a sample-size rationale, and an ethics/IRB plan before collecting research data.

## 6. Implementation and feasibility

Briefly identify:

- What your team will build, reuse, collect, or simulate.
- Major milestones and team-member responsibilities.
- Resources you must secure, such as data, hardware, models, compute, or participants.
- The largest technical or scientific risk and a feasible fallback scope.

End with the most important question on which you want feedback from the class.

## Presentation requirements

Each team has **10 minutes total**: **7 minutes for the presentation** and **3 minutes for questions**.

Based on the above, the presentation should allow the audience to identify:

1. One research question and primary contribution.
2. One cognitive augmentation outcome.
3. The closest prior work and the specific research gap.
4. The proposed system, study, or experimental approach.
5. One primary claim and the evidence that could support or refute it.
6. A feasible implementation and evaluation plan.

## Slide submission

Upload your presentation file (`.ppt` or `.key`) to your GitHub repository by **Tuesday, November 3 at 11:59 PM ET**. If the file is in a teammate's repository, link to it from your own repository.

## How we will assess the proposal

- **Originality:** Does the project offer a distinct contribution rather than only assembling existing components?
- **Novelty:** Is the gap from the closest prior work specific, accurate, and convincing?
- **Importance:** If the claims are supported, would the contribution matter to research, design, or practice in AI and human-AI interaction?
- **Correctness and methodological rigor:** Are the formalization, baselines, measures, experiments, and analyses appropriate for the claims and contribution type?
- **Feasibility and reproducibility:** Is there a credible plan, sufficient access to required resources, a useful fallback, and a path for others to reproduce the work?
- **Clarity:** Is the proposal focused, well structured, and understandable to its intended research audience?

## AI use and authorship

Slides, research arguments, and reflections should be authored by your team. You may use AI tools for brainstorming, literature discovery, coding assistance, or editing, but disclose substantive use and verify all generated claims and citations. Do not include unnecessary AI-generated text in your slides. Every team member should be able to explain and defend the proposed contribution, methods, and evaluation plan.
