# Week 3: Designing Human–Agent Interfaces

In Week 1 and Week 2, you built an agent loop and expanded it with tools, skills, and MCPs. This week, you will design an interface between an agent and a human and consider: What should the agent know about the human, what should the human know about the agent, and who should control what and when?

## 1. Define a cognitive augmentation objective

Choose a cognitive domain you are interested in, such as learning, memory, reasoning, attention, creativity, reflection, decision-making, communication, or social connection. Identify **three cognitive outcomes within that domain**, and choose **one primary objective** to guide your build. For example, within learning an agent's objective might be to improve retention, transfer, and motivation, while within creativity, idea diversity, idea realization, and authorship/agency. Motivate your objective and proposed approach with examples from relevant literature (1-2 articles). Explain how your agent's interaction with the user could support that objective, what could go wrong, and what evidence would help you determine whether it worked.

## 2. Design and specify the human-agent interface

Before specifying your interface, consider how the agent should relate to the user and the world. Think beyond the classic chat interface. Draw inspiration from the four human–technology relations discussed in class (but feel free to not use them!):

- **Embodiment: the agent as an extension of you.** Could the user experience the agent as an extension of their own perceptual or cognitive apparatus rather than as another actor? Could it change what they notice, perceive, remember, or attend to while largely disappearing from focal attention?
- **Hermeneutic: the agent as something you read or interpret.** Could the agent translate complex or invisible information into a representation the user interprets themselves? Think beyond text and speech: a compass, map, dashboard, warning light, confidence meter, diagram, visualization, or icon.
- **Alterity: the agent as another actor.** Could the agent be experienced as a distinct entity with which the user communicates, collaborates, negotiates, teaches, or disagrees? Does your objective benefit from a separate voice, body, personality, or point of view, or would that unnecessarily anthropomorphize the system?
- **Background / Ambient — the agent as an invisble part of your world.** Could the agent support the user without becoming the focus of interaction? Could it quietly shape the user's environment or communicate through peripheral cues largely unnoticed by the user?

Note: Interfaces may deliberately move between these relations rather than only exist within one. If helpful here are some design provocations to inspire and get you started thinking:

- **What is the future user interface for AI agents? Will there be a CSS for agents?** For inspiration see [VibeOS](https://www.youtube.com/watch?v=7NfyZhV1dKM), [OpenUI](http://openui.com), or [json-render](https://json-render.dev).
- **How could the interface of agents change based on form factors**, such as an agent running on a computer, smartphone, smartwatch, smart glasses, brain–computer interface, etc.?
- **What could a non-chat agent look like? How about a non-language agent?** Inspiration: agents [acting on the human](https://www.youtube.com/watch?v=fCLxENGs7CY), [RT-2](https://robotics-transformer2.github.io/).
- **How could an agent help with information overload?** For example, could an agent go over all the data about you that is available to advertisers through cookies and flag things you might not want to share? Could an agent notice consent documents and read them before you agree, identifying things that might affect you? See [“Agents that Reduce Work and Information Overload”](https://dl.acm.org/doi/pdf/10.1145/176789.176792).
- **How could an agent help with decision-making?** For example, could it negotiate prices on your behalf by teaming up with other agents to buy in bulk?
- **How could an agent integrate into existing interfaces?** Inspiration: [Harry Potter diary](https://www.instagram.com/p/Dcs7D_6ADQB/?img_index=2), or [pseudocode](https://medium.com/@danielur1995/why-you-should-pseudocode-f6c5cd44cd40) used to visualize and edit code structure that is not normally visible when working with coding agents.
- **Can we learn from agent interfaces in the 1990s?**. For example, [Bradshaw's "Software Agents" book](https://cognitive-agents.media.mit.edu/?q=openbradshaw).

Explain your choice of form factor and interaction modality, and why they suit your cognitive augmentation objective.

Then specify your **human–agent interaction space**, using the following characterizations:

| Component | What to specify |
| --- | --- |
| **Human state** | For example: Goals, knowledge, beliefs, attention, cognitive capabilities, cognitive load or other human state relevant to the task. Distinguish what can be observed from what is inferred or unknown. |
| **Agent state** | For example: Interpreted goal, plan, progress, uncertainty, pending actions, commitments, memories, interaction history, procedures. |
| **Human observations** | What information about the agent state can the user perceive, through which interface, and when? |
| **Agent observations** | What information about the human state can the agent receive, through which inputs, and when? |
| **Human interaction action space** | For example: natural language input, approve, reject, correct, constrain, interrupt, delegate, undo, or demonstrate |
| **Agent interaction action space** | For example: Ask, propose, notify, explain, execute, defer, wait, hand back control |
| **Authority** | Who is permitted to select or execute which classes of actions? For example, only the user might be able to send emails or delete files. |
| **Initiative policy** | Under what conditions should the agent act, ask, suggest, wait, or defer? State the observations or inferred variables that trigger these choices. |
| **Interaction transitions** | What interaction states exist, and which human, agent, or environmental events cause transitions between them? |
| **Recovery** | What happens if the user disagrees, interrupts, changes their mind, or the agent makes an error? What can be stopped, undone, or resumed? |


## 3. Build an agent with a novel user interface

Based on your reflection and specification, build a novel interface for a cognitive-support agent. Focus on how the interface supports the cognitive objective and makes the information and control flows in your interaction specification work.

Digital and physical interfaces are welcome. Real in-the-wild and self-testing is encouraged! If your proposed form factor involves hardware or materials you do not have access to—such as a wearable system, robot arm, 3D printer, or bacterial culture—you may simulate it realistically. Clearly identify what is implemented and what is simulated.

Your prototype must:

- Connect the interface to a working LLM-based agent loop, preferably using smolagents.
- Implement a user interface with the relevant observations, actions, and interaction rules from your human-agent interaction space specification.
- Demonstrate **at least two distinct interaction states** and a meaningful transition between them.
- Show an example run in which human input or a change in the user's context affects what the agent does next.


## 4. Form your final project group

Form your final project group and add the group members' names and your proposed project direction to the final project section of your website. Explain briefly which cognitive augmentation objective you want to pursue together.

## 5. Reflect as a cognitive agent user

Plot twist! For the last few weeks, **you have been the human in a human-agent interaction** intended to help you manage the course, find materials, work through assignments, connect with peers, and learn about AI agents. Did it do any of these things well? Could any changes or new features greatly improve such *cognitive outcomes*??

Based on your experience using the [course agent](https://cognitive-agents.media.mit.edu/), identify **one human-agent interaction problem, opportunity or feature** that could better support your learning. Feel free to be creative. Report it [as an issue in the course agent's GitHub repository](https://github.com/mitmedialab/agents-class-2026/issues). Include a concrete interaction example or screenshot where useful, and link to your issue in your Week 3 documentation.

## 6. Document your progress

In your Week 3 documentation of the above, include:

- **Objective:** Your cognitive domain, three cognitive outcomes, primary objective, target user, and motivation from 1–2 articles. Explain the intended cognitive benefit, potential risks, and evidence needed to assess success.
- **Interface design:** Your choosen form factor, modalities, and human–technology relation(s), and why they suit your cognitive objective. Include your interaction specification covering all components in Section 2.
- **Technical overview and flow:** A diagram showing the agent architecture (similar to the week 2 agent diagram): interface, model, harness or runtime, tools, state, environment, and any approval or sandbox boundary. Include human–agent information and control flows and interaction-state transitions. Rough diagrams are fine.
- A link to your code and an example run demonstrating the required states, transition, and response to human input or context. Identify what is implemented and what is simulated. Please images or ideally videos of your build running.
- A short reflection on what worked interface wise, where the interface struggled, what should improve, and what your observations establish about how the interface affected the cognitive objective.
- Your final project group, proposed direction (you can still iterate on this), and shared cognitive objective in your website's final project section; link to it here.
- A link to your course-agent GitHub issue, briefly explaining the interaction problem, opportunity, or feature and how it could support your learning. Include an example or screenshot where useful (about 2-3 sentences).
- A disclosure of how and why you used AI.
**IMPORTANT:** For week 1, we realized that many people used AI for their documentation write-up. Documentation and reflections are THE MOST IMPORTANT part of your learning this course. Going forward, we expect your documentation to be written by yourself rather than an AI. Even rough, informal documentation and reflection is okay. You may use AI for coding assistance as long as you are able to explain what the agent is doing and how it is leveraging this week's course content.

## 7. Submission

Publish your Week 3 documentation and code to the private GitHub repository associated with the GitHub ID you provided to the course staff. Test the links and demo media from a signed-out or fresh browser session where possible.

## 8. In-class sharing (UPDATED)

If you are selected in the class for presentation, please prepare the following:

1. The problem (20s)
 "Don't you hate it when…" One concrete motivation you had for your build. State the concrete agent objective the agent tries to achieve (success criteria). Remember, the objective needs to be augmentation of some cognitive outcome.
2. The solution (60s)
 "To address this, I built ___." Briefly describe what the agent does in a diagram: what are the (1) evironment and agent states, (2) action space, (3) observation space, (4) decision policy (LLM, policy, rules, planner), (4) the reward or criteria telling it whether it's doing well
3. Live interaction (1:25) (required)
 Show your cool agent live and interact with it in real time.
4. What I learned (15s)
 What went well, one surprise, failure mode, or limitation.


## Class AI policy and assessment

**AI use is allowed, with transparency.** Clearly document when you use AI to aid or complete an assignment, what you used it for, and why. Because capable AI coding tools are readily available, we have higher expectations for the quality and thoughtfulness of your work.
Assignments will be assessed on:
1. **Engagement with the problem and cognitive-augmentation goal.**
2. **Implementation quality:** How carefully your work is built, tested, and documented. Avoid submitting unchecked AI-generated code or work you cannot explain.
3. **Understanding and communication:** Your ability to explain the important structures, design choices, and limitations of your build during class.
4. **Quality of experimentation and use of evidence.**
5. **Concise, human-authored documentation and transparent AI use.**
