# Week 1: Your Website, Project Ideas, and First Agent

This week, you’ll create a home for your work, explore directions for your final project, and implement your first agent from scratch.

## 1. Start your documentation website

Create a personal website to document your work throughout the course. Include a **Week 1 section** and a **final project section**. Your website will grow with your weekly assignments and form part of your final project deliverables.

Be creative! The design and format are up to you. Make your process easy to follow: what you tried, what worked, what didn’t, and what you learned. Use video and other documentation as much as possible.

For inspiration, explore these student websites:

- [Ekaterina Kormilitsyna](https://fab.cba.mit.edu/classes/863.24/people/EkaterinaKormilitsyna/)
- [Vera](https://fab.cba.mit.edu/classes/863.22/CBA/people/Vera/index.html)
- [Char](https://fab.cba.mit.edu/classes/863.23/CBA/people/Char/index.html)
- [Cyrus Clarke](https://fab.cba.mit.edu/classes/863.24/people/CyrusClarke/)

## 2. Propose three final project ideas

Add **three final project ideas** to your website, with **at least 2–3 sentences per idea**. Explain who each idea is for, what problem it addresses, and how an agent could help augment human cognition—for example, learning, reasoning, creativity, memory, or socialization.

Pictures, sketches, and diagrams are strongly encouraged. These are starting points for exploration; you do not need to commit to an idea yet.

## 3. Implement an agent from scratch

Work through the [Building a Minimal Agent Loop From Scratch tutorial notebook](https://colab.research.google.com/drive/1aJDo5ZTXprJjMDg_BTQsT71pILjumnq_?usp=sharing). It demonstrates an agent operating a simulated vending machine and introduces observations, actions, feedback, and stopping conditions. Experiment with the examples and notice how the agent behaves when the environment changes or something goes wrong. There is no requirement to upload this part to your repository, it should only help you get a base understanding before building your simple agent.

Then build a simple agent for a task of your choice. You may use any programming language, although Python is preferred.

Use a downloaded LLM whose inference runs in Google Colab or on your computer. Hosted model APIs such as Anthropic or OpenAI do not satisfy this requirement. Implement the agent loop yourself without agent frameworks or SDKs such as the Claude Agent SDK. The application is open-ended, but the implementation must be LLM-based; an image generator may be a tool or output, but does not replace the LLM-driven agent loop.

Your implementation should let the agent:

- Receive observations from an environment.
- Select and execute an action.
- Use the result to inform its next action.
- Stop when finished or when it reaches an iteration limit.

Keep the scope manageable. The goal is to understand the relationship between the model, its available actions, the environment, and the loop that connects them.

In your Week 1 documentation, include:

- The task your agent addresses and why you chose it.
- Its observations, available actions, and stopping conditions.
- A link to your code and an example run.
- A short reflection on what worked, where it struggled, and what you would improve.
- A disclosure of how and why you used AI.

## Class AI policy

**AI use is allowed, with transparency.** Clearly document when you use AI to aid or complete an assignment, what you used it for, and why.

Because capable AI coding tools are readily available, we have higher expectations for the quality and thoughtfulness of your work. Assignments will be assessed on:

1. **Engagement with the problem:** How clearly you motivate the problem and how thoroughly your solution addresses it.
2. **Implementation quality:** How carefully your work is built, tested, and documented. Avoid submitting unchecked AI-generated code or work you cannot explain.
3. **Understanding and communication:** Your ability to explain the important structures, design choices, and limitations of your build during class.

You do not need to explain every line of code, but you should understand how your system works and take responsibility for what you submit.

In your weekly build documentation, write a few sentences about your AI use for that submission.

## Submission and in-class sharing

Publish your website—with your Week 1 documentation and three final project ideas—to the private GitHub repository associated with the GitHub ID you provided to the course staff.

You may be randomly selected to present your work in class. Be ready to walk through your website, explain your design choices, and, if possible, give a live demo from your laptop. Include an example run or recording on your website so you can still show your work if a live demo is unavailable.
