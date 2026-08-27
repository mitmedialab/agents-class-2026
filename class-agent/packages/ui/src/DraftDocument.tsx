import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

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

function resizeToContent(element: HTMLTextAreaElement): void {
  element.style.height = "0px";
  element.style.height = `${element.scrollHeight}px`;
}

interface DraftFieldEditorProps {
  field: DraftDocumentField;
  value: string;
  onChange: (value: string) => void;
  onCommit: (value: string) => void;
}

function DraftFieldEditor({
  field,
  value,
  onChange,
  onCommit,
}: DraftFieldEditorProps) {
  const editorRef = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    if (editorRef.current) resizeToContent(editorRef.current);
  }, [value]);

  return (
    <textarea
      ref={editorRef}
      aria-label={field.label}
      onBlur={(event) => onCommit(event.currentTarget.value)}
      onChange={(event) => {
        resizeToContent(event.currentTarget);
        onChange(event.currentTarget.value);
      }}
      placeholder="Waiting for information"
      rows={1}
      value={value}
    />
  );
}

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
  const nextMissingIndex = fields.findIndex((field) => field.status !== "confirmed");
  const visibleFields =
    nextMissingIndex < 0 ? fields : fields.slice(0, nextMissingIndex + 1);
  const activeFieldId = nextMissingIndex < 0 ? null : fields[nextMissingIndex]?.id;
  const activeFieldRef = useRef<HTMLLIElement>(null);

  useEffect(() => {
    activeFieldRef.current?.scrollIntoView?.({ block: "center", behavior: "auto" });
  }, [activeFieldId]);

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
            <li
              data-active={field.id === activeFieldId}
              data-status={field.status}
              key={field.id}
              ref={field.id === activeFieldId ? activeFieldRef : undefined}
            >
              <span aria-hidden="true" className="ca-draft-field-node" />
              <header>
                <strong>{field.label}</strong>
                <span>{FIELD_STATUS_LABELS[field.status]}</span>
              </header>
              <DraftFieldEditor
                field={field}
                onChange={(value) =>
                  setValues((current) => ({ ...current, [field.id]: value }))
                }
                onCommit={(value) => {
                  if (value !== (field.value ?? "")) onChange?.(field.id, value);
                }}
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
