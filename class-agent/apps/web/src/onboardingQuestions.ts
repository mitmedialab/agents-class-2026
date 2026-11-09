export type OnboardingAnswers = Record<string, string>;

export const ONBOARDING_SECTIONS = [
  {
    heading: "A. Background and Prior Knowledge",
    questions: [
      "What is your academic or professional background? In which areas do you have experience or knowledge that could help connect new concepts to what you already know?",
      "How familiar are you with artificial intelligence, programming, and technical concepts? Would you consider yourself a beginner, intermediate, or advanced learner in these areas?",
      "Why are you taking this course? What would you most like to learn or accomplish?",
    ],
  },
  {
    heading: "B. Cultural Context and Communication",
    questions: [
      "Which languages do you prefer for learning and participating in discussions? Would you find it helpful to have technical terminology clarified in another language when needed?",
      "Are there cultural, educational, or professional experiences that influence how you prefer to communicate or receive feedback?",
      "How would you like the agent to handle disagreement or ambiguity? Would you prefer it to challenge your assumptions directly, ask reflective questions, present alternative interpretations, or combine these approaches?",
    ],
  },
  {
    heading: "C. Learning and Interaction",
    questions: [
      "How do you prefer to learn unfamiliar concepts: concise explanations, analogies, practical examples, diagrams, spoken explanations, or exercises?",
      "What level of detail do you prefer: a brief answer first, a comprehensive explanation, or progressive depth?",
      "When you struggle to understand something, how should the agent respond? Should it rephrase the explanation, offer another example, change the format, or ask what specifically remains unclear?",
      "Which interaction modalities would be most useful to you: text, voice, images, diagrams, interactive visualizations, or a combination?",
    ],
  },
  {
    heading: "D. The Agent's Role, Memory, and Personalization",
    questions: [
      "What would you like the agent to do for you beyond answering questions? Would you like it to act as a tutor, a critical thinking partner, a research collaborator, a project advisor, or a combination of these roles?",
      "What information would you like the agent to remember across conversations? How should it use that information: adapting its responses automatically, asking for permission, or allowing you to control the level of personalization?",
      "What should the agent avoid assuming about you?",
    ],
  },
];

// The API rejects run text over 20,000 characters (PromptText in course_server/api.py).
// This bound keeps 13 full answers plus their questions and label under that limit.
export const ONBOARDING_ANSWER_MAX_LENGTH = 1_300;

/** The chat message for these answers, or null when every answer is blank. */
export function onboardingMessage(answers: OnboardingAnswers): string | null {
  const answered = ONBOARDING_SECTIONS.flatMap(({ questions }) => questions).flatMap(
    (question) => {
      const answer = answers[question]?.trim();
      return answer ? [`${question}\n${answer}`] : [];
    },
  );
  return answered.length > 0
    ? ["Onboarding questionnaire responses:", ...answered].join("\n\n")
    : null;
}
