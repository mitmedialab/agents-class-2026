import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { OnboardingQuestionnaire } from "./OnboardingQuestionnaire.js";
import {
  ONBOARDING_ANSWER_MAX_LENGTH,
  ONBOARDING_SECTIONS,
  onboardingMessage,
  type OnboardingAnswers,
} from "./onboardingQuestions.js";

const QUESTIONS = ONBOARDING_SECTIONS.flatMap(({ questions }) => questions);
const FIRST = QUESTIONS[0] as string;
const LAST = QUESTIONS[12] as string;

function renderForm(busy = false) {
  const onBack = vi.fn();
  const onSubmit = vi.fn();
  function Harness() {
    const [answers, setAnswers] = useState<OnboardingAnswers>({});
    return (
      <OnboardingQuestionnaire
        answers={answers}
        busy={busy}
        onAnswersChange={setAnswers}
        onBack={onBack}
        onSubmit={onSubmit}
      />
    );
  }
  render(<Harness />);
  return { onBack, onSubmit, submit: screen.getByRole("button", { name: "Send to the agent" }) };
}

function answer(question: string, value: string) {
  fireEvent.change(screen.getByRole("textbox", { name: question }), { target: { value } });
}

describe("OnboardingQuestionnaire", () => {
  it("renders four sections and all 13 labeled questions", () => {
    renderForm();
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(4);
    expect(QUESTIONS).toHaveLength(13);
    for (const question of QUESTIONS) {
      expect(screen.getByRole("textbox", { name: question })).toHaveAttribute(
        "maxlength",
        String(ONBOARDING_ANSWER_MAX_LENGTH),
      );
    }
  });

  it("disables submit until an answer has text", () => {
    const { submit } = renderForm();
    expect(submit).toBeDisabled();
    answer(FIRST, "   ");
    expect(submit).toBeDisabled();
    answer(FIRST, "Physics");
    expect(submit).toBeEnabled();
  });

  it("disables submit while the composer is busy", () => {
    const { submit } = renderForm(true);
    answer(FIRST, "Physics");
    expect(submit).toBeDisabled();
  });

  it("submits one labeled message without blank answers", () => {
    const { onSubmit, submit } = renderForm();
    answer(FIRST, " Physics ");
    answer(QUESTIONS[1] as string, "  ");
    answer(LAST, "My age");
    fireEvent.click(submit);
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith(
      `Onboarding questionnaire responses:\n\n${FIRST}\nPhysics\n\n${LAST}\nMy age`,
    );
  });

  it("goes back without submitting", () => {
    const { onBack, onSubmit } = renderForm();
    answer(FIRST, "Physics");
    fireEvent.click(screen.getByRole("button", { name: "Back to conversation" }));
    expect(onBack).toHaveBeenCalledOnce();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps 13 full answers within the API's message limit", () => {
    const full = Object.fromEntries(
      QUESTIONS.map((question) => [question, "x".repeat(ONBOARDING_ANSWER_MAX_LENGTH)]),
    );
    expect(onboardingMessage(full)?.length).toBeLessThanOrEqual(20_000);
  });
});
