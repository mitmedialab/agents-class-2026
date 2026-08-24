import type { AgentActivity, AgentActivityKind } from "./api.js";

function ActivityIcon({ kind }: { kind: AgentActivityKind }) {
  if (kind === "complete") {
    return (
      <svg aria-hidden="true" className="activity-icon" viewBox="0 0 16 16">
        <circle cx="8" cy="8" r="6.25" />
        <path d="m5 8.1 2 2 4-4.25" />
      </svg>
    );
  }
  if (kind === "resource") {
    return (
      <svg aria-hidden="true" className="activity-icon" viewBox="0 0 16 16">
        <path d="M4 2.25h5l3 3v8.5H4z" />
        <path d="M9 2.25v3h3M6 8h4M6 10.5h4" />
      </svg>
    );
  }
  if (kind === "output") {
    return (
      <svg aria-hidden="true" className="activity-icon" viewBox="0 0 16 16">
        <path d="m3 12.75.65-2.7L10.6 3.1l2.3 2.3-6.95 6.95zM9.7 4l2.3 2.3" />
      </svg>
    );
  }
  if (kind === "error") {
    return (
      <svg aria-hidden="true" className="activity-icon" viewBox="0 0 16 16">
        <path d="M8 2.25 14 13H2zM8 5.7v3.6M8 11.25v.1" />
      </svg>
    );
  }
  if (kind === "tool") {
    return (
      <svg aria-hidden="true" className="activity-icon" viewBox="0 0 16 16">
        <rect height="11.5" rx="1.5" width="13" x="1.5" y="2.25" />
        <path d="m4 6 2 2-2 2M7.5 10H11" />
      </svg>
    );
  }
  return (
    <svg aria-hidden="true" className="activity-icon" viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="5.75" />
      <path d="M8 4.5V8l2.25 1.5" />
    </svg>
  );
}

export interface ActivityTraceProps {
  activities: AgentActivity[];
  currentLabel: string | null;
}

export function ActivityTrace({ activities, currentLabel }: ActivityTraceProps) {
  const latest = activities.at(-1);
  const presenting =
    currentLabel === "Writing final response" || currentLabel === "Presenting response";
  const summaryKind = currentLabel
    ? presenting
      ? "output"
      : (latest?.kind ?? "status")
    : (latest?.kind ?? "complete");
  const summaryLabel = currentLabel ?? latest?.label;

  if (!summaryLabel) return null;

  if (activities.length === 0) {
    return (
      <div className="activity-trace activity-trace-static">
        <div className="activity-trace-summary">
          <ActivityIcon kind={summaryKind} />
          <span aria-live="polite" className="activity-summary-label">
            {summaryLabel}
          </span>
        </div>
      </div>
    );
  }

  return (
    <details className="activity-trace">
      <summary>
        <ActivityIcon kind={summaryKind} />
        <span aria-live="polite" className="activity-summary-label">
          {summaryLabel}
        </span>
        <svg aria-hidden="true" className="activity-chevron" viewBox="0 0 12 12">
          <path d="m3 4.5 3 3 3-3" />
        </svg>
      </summary>
      <ol aria-label="Agent activity" className="activity-list">
        {activities.map((activity, index) => (
          <li key={activity.id ?? `${activity.kind}-${activity.label}-${index}`}>
            <ActivityIcon kind={activity.kind} />
            <div className="activity-entry">
              <span>{activity.label}</span>
              {activity.detail ? (
                <details className="activity-detail">
                  <summary>
                    Details
                    <svg
                      aria-hidden="true"
                      className="activity-detail-chevron"
                      viewBox="0 0 12 12"
                    >
                      <path d="m3 4.5 3 3 3-3" />
                    </svg>
                  </summary>
                  <pre>{activity.detail}</pre>
                </details>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </details>
  );
}
