import { useEffect, useMemo, useState } from "react";

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
  onChange?: ((id: string, value: string) => void) | undefined;
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
  onChange,
}: DraftDocumentProps) {
  const fieldSignature = useMemo(
    () => JSON.stringify(fields.map((field) => [field.id, field.value ?? ""])),
    [fields],
  );
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => {
    setValues(Object.fromEntries(fields.map((field) => [field.id, field.value ?? ""])));
  }, [fieldSignature]);
  const populated = fields.filter(
    (field) => Boolean((values[field.id] ?? field.value)?.trim()),
  ).length;

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
          {fields.map((field) => (
            <li data-status={field.status} key={field.id}>
              <header>
                <strong>{field.label}</strong>
                <span>{FIELD_STATUS_LABELS[field.status]}</span>
              </header>
              <textarea
                aria-label={field.label}
                onBlur={(event) => {
                  if (event.currentTarget.value !== (field.value ?? "")) {
                    onChange?.(field.id, event.currentTarget.value);
                  }
                }}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.id]: event.target.value,
                  }))
                }
                placeholder="Waiting for information"
                rows={Math.max(2, Math.min(8, (values[field.id] ?? "").split("\n").length))}
                value={values[field.id] ?? ""}
              />
              {field.source ? <small>Source: {field.source}</small> : null}
            </li>
          ))}
        </ol>
      ) : null}
    </article>
  );
}
