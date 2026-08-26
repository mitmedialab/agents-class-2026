import { DocumentViewer } from "./DocumentViewer.js";

export type DraftFieldStatus = "missing" | "candidate" | "inferred" | "confirmed";
export type DraftDocumentStatus = "draft" | "ready" | "final" | "submitted";

export interface DraftDocumentField {
  id: string;
  label: string;
  value?: string | undefined;
  status: DraftFieldStatus;
  source?: string | undefined;
}

export interface DraftDocumentProps {
  title: string;
  description?: string | undefined;
  status?: DraftDocumentStatus | undefined;
  content?: string | undefined;
  fields?: readonly DraftDocumentField[] | undefined;
}

const FIELD_STATUS_LABELS: Record<DraftFieldStatus, string> = {
  missing: "Missing",
  candidate: "Candidate",
  inferred: "Inferred",
  confirmed: "Confirmed",
};

export function DraftDocument({
  title,
  description,
  status = "draft",
  content,
  fields = [],
}: DraftDocumentProps) {
  const populated = fields.filter(
    (field) => field.status !== "missing" && Boolean(field.value?.trim()),
  ).length;
  const nextMissingIndex = fields.findIndex((field) => field.status === "missing");
  const visibleFields =
    nextMissingIndex < 0 ? fields : fields.slice(0, nextMissingIndex + 1);

  return (
    <article aria-label={title} className="ca-draft-document">
      <header className="ca-draft-document-header">
        <div>
          <span>{status}</span>
          <h2>{title}</h2>
          {description ? <p>{description}</p> : null}
        </div>
        {fields.length ? (
          <strong aria-label={`${populated} of ${fields.length} fields populated`}>
            {populated}/{fields.length}
          </strong>
        ) : (
          <strong>{status}</strong>
        )}
      </header>

      {content?.trim() ? (
        <div className="ca-draft-content">
          <DocumentViewer
            resource={{
              uri: "draft://document",
              title,
              mediaType: "text/markdown",
              data: new TextEncoder().encode(content),
            }}
          />
        </div>
      ) : null}

      {fields.length ? (
        <ol className="ca-draft-fields">
          {visibleFields.map((field) => (
            <li data-status={field.status} key={field.id}>
              <span aria-hidden="true" className="ca-draft-field-node" />
              <header>
                <strong>{field.label}</strong>
                <span>{FIELD_STATUS_LABELS[field.status]}</span>
              </header>
              <p>{field.value?.trim() || "Waiting for information"}</p>
              {field.source ? <small>Source: {field.source}</small> : null}
            </li>
          ))}
        </ol>
      ) : null}

    </article>
  );
}
