# Week 2: Building Tools and Skills

Last week, you built the agent loop yourself. This week, you will expand that loop with *tools*, *skills* and *MCPs*.

## 1. Work through the Week 2 tutorial

Work through the [**Tool Use and Agent Interfaces**](https://colab.research.google.com/drive/1dpMfcWGZojZ7cbPeHX3TtdMfuckzCA8-?usp=sharing) notebook. It introduces structured outputs, agent frameworks, custom tools, MCP, skills, persistence, and agent-authored tools. You do not need to submit the completed tutorial notebook on your website. If you connect your real email via MCP, use only accounts and actions you are comfortable putting in scope, keep credentials out of your code and model context.

## 2. Build an agent with tools

Build tools and skills, connect MCP servers, and integrate them into an agent for a task of your choice. For the task, the agent should be designed to augment a human cognitive ability such as learning, memory, reasoning, attention, creativity, reflection, decision-making, communication, or social connection.

Using `smolagents`, design and implement **at least two distinct tools** for your agent. The tools you build should be "novel" in the sense that it is designed or meaningfully adapted for your task rather than a copy of a popular standard tool or library. We encourage you to think out of the box (connect to hardware, sensors, programs, other agents, model user behavior over time, etc.).

Your agent must:
- Have **at least two tools that you designed and implemented** available in its action space that does not copy existing standard tools.
- Use the `smolagents` tool interface and agent loop. Built-in framework tools do not count toward the two tools.
- Create at least one skill, and connect your agent to at least one external MCP.
- Reflect on your tool hygiene. Do your tools follow the do's and don'ts on the week 2 slides?
- Demonstrate at least one run in which the agent uses **two or more tools in sequence** and a tool result affects what it does next.
- Optional: Experiment with scheduling and agents creating tools and using them during their run.

In your Week 2 documentation, include:
- **Objective:** The cognitive augmentation task your tools and agent addresses and why you chose it.
- **Technical overview and flow:** A figure you made showing the model, harness or runtime, tools, state, environment, and any approval or sandbox boundary. Rough diagrams are fine. Also describe your tools and the reasoning for their existence and format.
- A link to your code and an example run.
- A short reflection on how well the agent achieved the objective, where it struggled, and what should be improved.
- A disclosure of how and why you used AI.
- Aim for 500–800 words, excluding captions and AI disclosure.

**IMPORTANT:** For week 1, we realized that many people used AI for their documentation write-up. Documentation and reflections are THE MOST IMPORTANT part of your learning this course. Going forward, we expect your documentation to be written by yourself rather than an AI. Even rough, informal documentation and reflection is okay. You may use AI for coding assistance as long as you are able to explain what the agent is doing and how it is leveraging this week's course content.

## 3. Talk with classmates about your final project

Find **at least two classmates** via the course agent interface and meet them *in-person* to talk with them about the project ideas you proposed in Week 1. At least one has to be a person you don’t know. A good place to meet up could be for office hours Thursday or Monday at 3-4 PM. Document your HUMAN-HUMAN interaction in your final project documentation (1-2 sentence summary of what you talked about). Here is a [list of everyone taking the class](https://cognitive-agents.media.mit.edu/?q=showfinalprojectistudentideastable) and high-level summaries of their proposed ideas. Feel free to check out their websites for their own accounts.

## 4. Submission and in-class sharing

Publish your Week 2 documentation and code to the private GitHub repository associated with the GitHub ID you provided to the course staff. Test the links and demo media from a signed-out or fresh browser session where possible.

You may be randomly selected to present your work in class. Be ready to walk through your website, explain your design choices, and, if possible, give a live demo from your laptop.  Include an example run or recording on your website so you can still show your work if a live demo is unavailable. In class, you should be able to articulate the (1) objective: what did you build and why? how is it related to cognitive augmentation (2) what is the technical implementation flow and logic? (3) how well did the agent achieve the task and how did you evaluate it? We will provide a Zoom room code for you to connect to during class for your demo.

## Class AI policy and assessment

**AI use is allowed, with transparency.** Clearly document when you use AI to aid or complete an assignment, what you used it for, and why. Because capable AI coding tools are readily available, we have higher expectations for the quality and thoughtfulness of your work.
Assignments will be assessed on:
1. **Engagement with the problem and cognitive-augmentation goal.**
2. **Implementation quality:** How carefully your work is built, tested, and documented. Avoid submitting unchecked AI-generated code or work you cannot explain.
3. **Understanding and communication:** Your ability to explain the important structures, design choices, and limitations of your build during class.
4. **Quality of experimentation and use of evidence.**
5. **Concise, human-authored documentation and transparent AI use.**
