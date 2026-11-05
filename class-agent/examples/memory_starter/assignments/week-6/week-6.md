# Week 6: Building a Device-Use Agent

Reminder: complete these forms:
- Complete the [class feedback form](https://forms.gle/k4FQb9F3uxhPeXRs5) as soon as possible (5–10 minutes).
- Submit the [final-project team registration form](https://forms.gle/w9hFuZQhY6kvfQm58) **before class tomorrow (Tuesday, October 27)**. Use the same form if you are still looking for teammates.

The tutorial code example from Yasith can be found [here](https://drive.google.com/file/d/18db_gTZHp0pdcSBtnaTAYotNO_FsM5sr/view?usp=sharing).

This week, make an LLM agent operate a **real device with an existing operating system or firmware** that is not a conventional desktop or browser, such as a smartphone, smartwatch, smart TV, printer, robot, smart-home device, vending machine, 3D printer or something unexpected. If you have a compelling computer-use idea that uses a computer OS or browser (MacOS, Windows, Google Chrome), reach out to the instructors first. But otherwise, the requirement is to work with a non-computer OS this week.

The goal is to explore how an agent can **observe and act through an interface designed originally for another purpose like a human user**. You may need to investigate or reverse-engineer how your device can be controlled. Choose a scope you can pursue in roughly **10 hours**, but feel free to go further if you're excited about it. You may work **individually or in pairs (maximum two students)** for this week.

## 1. Specify your device and objective

Choose a useful task or set of tasks that an agent might be able to pursue when controlling this device. A cognitive augmentation task here can mean supporting memory, learning, or attention, but also **reducing cognitive workload** by helping someone operate a device or complete a tedious task. For instance, one of the many tasks a printer use agent could enable could be looking at the user's calendar and print meeting agendas right before meetings.

Briefly specify:

| Component | What to describe |
| --- | --- |
| **Device and OS** | What device are you using, and what runs on it? |
| **Control interface / protocol** | How can software communicate with the device (e.g., an API, ADB, Bluetooth, network protocol, accessibility interface, or device-specific commands)? What did you have to discover? |
| **Objective** | What could an agent accomplish using the device, and for whom? Which cognitive augmentation objectives could be possible with the device use? Write down some examples of objectives that you find interesting.  |
| **State \(S\)** | What relevant states can the device be in? |
| **Observations \(O\)** | What can your agent observe? What remains inaccessible? |
| **Actions \(A\)** | What can your agent do through your interface? |
| **Transitions** | How do actions or other events change device state? |
| **Completion and control** | How do you know a task is done? What needs human approval? |


## 2. Build an MCP interface and agent

Build an **MCP server** that exposes at least one way to observe the device and one way to act on it, so that other MCP-compatible agent frameworks could use your interface. Consider how a human normally operates the device and whether an agent can interact more efficiently through an API, protocol, or other interface instead of imitating human button presses (see the Week 6 lecture). Explain your choice. Connect it to an LLM-based agent and demonstrate a **multi-step task** in which an observation or action result influences the agent's next action.

You can use existing APIs, device protocols, accessibility services, shell commands, screenshots, or other mechanisms. Simulation-only alternatives require instructor approval.

## 3. Evaluate your agent

Define **three small task instances or starting conditions** and a clear success criterion for each. Run your agent, check the **actual device state** rather than relying on the agent's self-report, and summarize the outcomes in a small table. Examine at least one failure or limitation. You may reuse evaluation tools from Week 5, but Langfuse is not required.

## 4. Document your progress

In your Week 6 website documentation, include:

- Your **device/objective specification** from Section 1 and a brief technical overview of the MCP interface flow that an agent may connect to.
- A **link to your code**, including the MCP server and instructions for connecting to it.
- Your **three task evaluations**, results, and an interesting failure or limitation.
- A **demo video** showing the physical device, the agent interacting with it, and at least one task execution and outcome. Show real operation, not just a polished result.
- A short reflection on what you learned, what you would improve. If working in a pair, identify both students and their contributions.

As in previous weeks, write your documentation and reflection **yourself**, rather than generating them with AI. AI coding assistance is allowed if you can explain your implementation.

## 5. Submission and in-class sharing

Publish your Week 6 documentation, code, and video to the private GitHub repository associated with the GitHub ID you provided to the course staff. Test the links and demo media from a signed-out or fresh browser session where possible.

You may be randomly selected to present your work in class. Be ready to walk through your website, explain your design choices, and, if possible, give a live demo from your device. Bring it if practical (STRONGLY ENCOURAGED!) but otherwise, show your video. In class, you should be able to articulate (1) **the objective:** what device use MCP did you build and why? (2) **the implementation:** how does the agent observe and operate the device through MCP? Preferably a short demo. (3) **the evaluation:** how well did it achieve the tasks? and (4) **what you learned:** an interesting failure, limitation, or result.

## Class AI policy and assessment

**AI use is allowed, with transparency.** Clearly document when you use AI to aid or complete an assignment, what you used it for, and why. Because capable AI coding tools are readily available, we have higher expectations for the quality and thoughtfulness of your work.

Assignments will be assessed on:
1. **Engagement with the problem and cognitive-augmentation goal.**
2. **Implementation quality:** How carefully your work is built, tested, and documented. Avoid submitting unchecked AI-generated code or work you cannot explain.
3. **Understanding and communication:** Your ability to explain the important structures, design choices, and limitations of your build during class.
4. **Quality of experimentation and use of evidence.**
5. **Concise, human-authored documentation and transparent AI use.**
