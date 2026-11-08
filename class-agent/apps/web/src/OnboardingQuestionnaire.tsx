import { Button } from "@class-agent/ui";
import {
  ONBOARDING_ANSWER_MAX_LENGTH,
  ONBOARDING_SECTIONS,
  onboardingMessage,
  type OnboardingAnswers,
} from "./onboardingQuestions.js";

export function OnboardingQuestionnaire({
  answers,
  busy,
  onAnswersChange,
  onBack,
  onSubmit,
}: {
  answers: OnboardingAnswers;
  busy: boolean;
  onAnswersChange: (answers: OnboardingAnswers) => void;
  onBack: () => void;
  onSubmit: (message: string) => void;
}) {
  const message = onboardingMessage(answers);

  return (
    <main className="syllabus-page">
      <form
        className="syllabus-document"
        onSubmit={(event) => {
          event.preventDefault();
          if (message) onSubmit(message);
        }}
      >
        <h1>Onboarding questionnaire</h1>
        <div className="syllabus-sections">
          <p>
            Every question is optional. Your answers go to the Course Agent as one chat
            message, and the agent decides what to remember.
          </p>
          {ONBOARDING_SECTIONS.map(({ heading, questions }) => (
            <section key={heading}>
              <h2>{heading}</h2>
              {questions.map((question) => (
                <label className="ca-field onboarding-question" key={question}>
                  {question}
                  <textarea
                    className="ca-input"
                    maxLength={ONBOARDING_ANSWER_MAX_LENGTH}
                    onChange={(event) =>
                      onAnswersChange({ ...answers, [question]: event.target.value })
                    }
                    rows={3}
                    value={answers[question] ?? ""}
                  />
                </label>
              ))}
            </section>
          ))}
          <div className="onboarding-actions">
            <Button disabled={!message || busy} type="submit" variant="outline">
              Send to the agent
            </Button>
            <Button onClick={onBack}>Back to conversation</Button>
          </div>
        </div>
      </form>
    </main>
  );
}
