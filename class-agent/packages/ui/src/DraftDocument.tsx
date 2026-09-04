import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { DocumentViewer } from "./DocumentViewer.js";

export type DraftFieldStatus = "missing" | "candidate" | "inferred" | "confirmed";
export type DraftDocumentStatus = "draft" | "ready" | "final" | "submitted";
export type DraftFieldInputType =
  | "text"
  | "email"
  | "url"
  | "year"
  | "multiline"
  | "attachment";

export interface DraftDocumentField {
  id: string;
  label: string;
  value?: string | undefined;
  status: DraftFieldStatus;
  source?: string | undefined;
  options?: readonly string[] | undefined;
  inputType?: DraftFieldInputType | undefined;
  helpText?: string | undefined;
  validationError?: string | undefined;
}

export interface DraftDocumentProps {
  title: string;
  description?: string | undefined;
  status?: DraftDocumentStatus | undefined;
  content?: string | undefined;
  fields?: readonly DraftDocumentField[] | undefined;
  onChange?: ((id: string, value: string) => void | Promise<void>) | undefined;
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
  error?: string | undefined;
  helpText?: string | undefined;
  onChange: (value: string) => void;
  onCommit: (value: string) => Promise<void>;
}

function DraftFieldEditor({
  field,
  value,
  error,
  helpText,
  onChange,
  onCommit,
}: DraftFieldEditorProps) {
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const options = field.options ?? [];
  const inputType = field.inputType ?? "multiline";
  const helpId = helpText ? `draft-${field.id}-help` : undefined;
  const errorId = error ? `draft-${field.id}-error` : undefined;
  const describedBy = [helpId, errorId].filter(Boolean).join(" ") || undefined;

  useLayoutEffect(() => {
    if (editorRef.current) resizeToContent(editorRef.current);
  }, [value]);

  if (options.length > 0) {
    const hasLegacyValue = Boolean(value) && !options.includes(value);
    return (
      <select
        aria-label={field.label}
        onChange={(event) => {
          const nextValue = event.currentTarget.value;
          onChange(nextValue);
          void onCommit(nextValue);
        }}
        aria-describedby={describedBy}
        aria-invalid={Boolean(error)}
        value={value}
      >
        <option disabled value="">
          Choose an option
        </option>
        {hasLegacyValue ? (
          <option disabled value={value}>
            {value} — choose a current option
          </option>
        ) : null}
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }

  if (inputType === "attachment") {
    const attached = Boolean(value.trim()) && !error;
    return (
      <div
        aria-describedby={describedBy}
        aria-label={field.label}
        className="ca-draft-attachment"
        data-attached={attached}
        role="status"
      >
        {attached ? "Picture attached" : "No picture attached yet"}
      </div>
    );
  }

  if (inputType !== "multiline") {
    const type = inputType === "year" ? "text" : inputType;
    return (
      <input
        aria-describedby={describedBy}
        aria-invalid={Boolean(error)}
        aria-label={field.label}
        autoComplete={inputType === "email" ? "email" : inputType === "url" ? "url" : undefined}
        inputMode={inputType === "year" ? "numeric" : undefined}
        maxLength={4_000}
        onBlur={(event) => void onCommit(event.currentTarget.value)}
        onChange={(event) => onChange(event.currentTarget.value)}
        pattern={inputType === "year" ? "[0-9]{4}" : undefined}
        placeholder="Waiting for information"
        type={type}
        value={value}
      />
    );
  }

  return (
    <textarea
      ref={editorRef}
      aria-describedby={describedBy}
      aria-invalid={Boolean(error)}
      aria-label={field.label}
      maxLength={4_000}
      onBlur={(event) => void onCommit(event.currentTarget.value)}
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
  const [commitErrors, setCommitErrors] = useState<Record<string, string>>({});
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
                error={commitErrors[field.id] ?? field.validationError}
                field={field}
                helpText={field.helpText}
                onChange={(value) => {
                  setValues((current) => ({ ...current, [field.id]: value }));
                  setCommitErrors((current) => {
                    if (!(field.id in current)) return current;
                    const next = { ...current };
                    delete next[field.id];
                    return next;
                  });
                }}
                onCommit={async (value) => {
                  if (value === (field.value ?? "") || !onChange) return;
                  setCommitErrors((current) => {
                    const next = { ...current };
                    delete next[field.id];
                    return next;
                  });
                  try {
                    await onChange(field.id, value);
                  } catch (commitError) {
                    const message =
                      commitError instanceof Error && commitError.message !== "request failed"
                        ? commitError.message
                        : "This change could not be saved. Please try again.";
                    setCommitErrors((current) => ({ ...current, [field.id]: message }));
                  }
                }}
                value={values[field.id] ?? ""}
              />
              {field.helpText ? (
                <small className="ca-draft-field-help" id={`draft-${field.id}-help`}>
                  {field.helpText}
                </small>
              ) : null}
              {commitErrors[field.id] ?? field.validationError ? (
                <p
                  className="ca-draft-field-error"
                  id={`draft-${field.id}-error`}
                  role="alert"
                >
                  {commitErrors[field.id] ?? field.validationError}
                </p>
              ) : null}
              {field.inputType === "multiline" && field.status !== "confirmed" ? (
                <small className="ca-draft-field-count">
                  {(values[field.id] ?? "").length.toLocaleString()}/4,000
                </small>
              ) : null}
              {field.source ? <small>Source: {field.source}</small> : null}
            </li>
          ))}
        </ol>
      ) : null}
    </article>
  );
}
