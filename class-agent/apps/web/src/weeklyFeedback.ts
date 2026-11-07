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
  const commentLines: string[] = [];
  const checklistLines: string[] = [];
  let section: "comments" | "checklist" = "comments";
  for (const line of content.split("\n")) {
    if (/^Grading Checklist:[ \t]*$/i.test(line)) {
      section = "checklist";
      continue;
    }
    const commentHeading = /^Comments?:\*?[ \t]?(.*)$/i.exec(line);
    if (commentHeading) {
      section = "comments";
      commentLines.push(commentHeading[1] ?? "");
      continue;
    }
    if (section === "checklist" && /^(?:Unclear or missing|Reviewer follow-up):[ \t]*$/i.test(line)) {
      section = "comments";
    }
    (section === "checklist" ? checklistLines : commentLines).push(line);
  }
  const comments = commentLines.join("\n").trim();
  const checklist = checklistLines.map((line): WeeklyChecklistItem | null => {
    const text = line.trim();
    if (!text) return null;
    const marked = /^(?:[•*-][ \t]*)?([✓✔☑✗✕xX])[ \t]+(.+)$/.exec(text);
    if (!marked) return { status: "unmarked", text: text.replace(/^[•*-][ \t]*/, "") };
    return {
      status: "✓✔☑".includes(marked[1] ?? "") ? "met" : "unmet",
      text: marked[2] ?? "",
    };
  }).filter((item): item is WeeklyChecklistItem => item !== null);
  return { comments, checklist };
}
