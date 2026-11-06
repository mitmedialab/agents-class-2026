export interface WeeklyChecklistItem {
  status: "met" | "unmet" | "unmarked";
  text: string;
}

export interface WeeklyFeedbackSections {
  comments: string;
  checklist: WeeklyChecklistItem[];
}

export function splitWeeklyFeedback(raw: string): WeeklyFeedbackSections {
  const content = raw.replaceAll("\r\n", "\n").trim();
  const marker = /^Grading Checklist:[ \t]*$/im.exec(content);
  const commentsBlock = marker ? content.slice(0, marker.index) : content;
  const checklistBlock = marker ? content.slice(marker.index + marker[0].length) : "";
  const comments = commentsBlock.replace(/^Comments:\*?[ \t]*/i, "").trim();
  const checklist = checklistBlock.split("\n").map((line): WeeklyChecklistItem | null => {
    const text = line.trim();
    if (!text) return null;
    const marked = /^([✓✔☑✗✕xX])[ \t]+(.+)$/.exec(text);
    if (!marked) return { status: "unmarked", text };
    return {
      status: "✓✔☑".includes(marked[1] ?? "") ? "met" : "unmet",
      text: marked[2] ?? "",
    };
  }).filter((item): item is WeeklyChecklistItem => item !== null);
  return { comments, checklist };
}
