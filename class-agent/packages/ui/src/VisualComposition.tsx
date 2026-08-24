import { createElement, useEffect, useMemo, useState } from "react";

type VisualWidth = "auto" | "full" | "half" | "third";

interface VisualBase {
  id: string;
  type: string;
  width?: VisualWidth;
}

export interface VisualGroup extends VisualBase {
  type: "group";
  children: string[];
  layout?: "stack" | "row" | "grid";
  columns?: 1 | 2 | 3 | 4;
  gap?: "compact" | "normal" | "loose";
  align?: "start" | "center" | "end" | "stretch";
  justify?: "start" | "center" | "end" | "between";
  wrap?: boolean;
  surface?: "plain" | "subtle" | "raised" | "accent";
  padding?: "none" | "small" | "medium" | "large";
  radius?: "none" | "small" | "medium" | "large";
}

export interface VisualImage extends VisualBase {
  type: "image";
  url: string;
  alt: string;
  caption?: string;
  aspect?: "auto" | "square" | "portrait" | "landscape" | "wide";
  fit?: "cover" | "contain";
  radius?: "none" | "small" | "medium" | "large" | "round";
}

export interface VisualHeading extends VisualBase {
  type: "heading";
  text: string;
  level?: 1 | 2 | 3 | 4;
  size?: "small" | "medium" | "large" | "display";
  tone?: "default" | "muted" | "accent";
  align?: "left" | "center" | "right";
}

export interface VisualText extends VisualBase {
  type: "text";
  text: string;
  variant?: "body" | "lead" | "caption" | "quote";
  tone?: "default" | "muted" | "accent";
  align?: "left" | "center" | "right";
}

export interface VisualBadge extends VisualBase {
  type: "badge";
  label: string;
  tone?: "neutral" | "accent" | "success" | "warning";
}

export interface VisualLink extends VisualBase {
  type: "link";
  label: string;
  url: string;
  style?: "text" | "button" | "quiet";
}

export interface VisualFacts extends VisualBase {
  type: "facts";
  items: Array<{ label: string; value: string }>;
}

export interface VisualInput extends VisualBase {
  type: "input";
  label: string;
  value?: string;
  placeholder?: string;
  input_type?: "text" | "email" | "url";
  read_only?: boolean;
}

export interface VisualTextarea extends VisualBase {
  type: "textarea";
  label: string;
  value?: string;
  placeholder?: string;
  rows?: number;
  read_only?: boolean;
}

export interface VisualDivider extends VisualBase {
  type: "divider";
}

export interface VisualSpacer extends VisualBase {
  type: "spacer";
  size?: "small" | "medium" | "large";
}

export type VisualElement =
  | VisualGroup
  | VisualImage
  | VisualHeading
  | VisualText
  | VisualBadge
  | VisualLink
  | VisualFacts
  | VisualInput
  | VisualTextarea
  | VisualDivider
  | VisualSpacer;

export interface VisualCompositionProps {
  rootId: string;
  elements: VisualElement[];
  title?: string;
  description?: string;
  onChange?: (id: string, value: string) => void;
}

const VISUAL_TYPES = new Set([
  "group",
  "image",
  "heading",
  "text",
  "badge",
  "link",
  "facts",
  "input",
  "textarea",
  "divider",
  "spacer",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function normalizeVisualElements(
  value: unknown,
  rootId: string,
): VisualElement[] | null {
  if (!Array.isArray(value) || value.length === 0 || value.length > 80) return null;
  const elements: VisualElement[] = [];
  const byId = new Map<string, VisualElement>();
  for (const raw of value) {
    if (
      !isRecord(raw) ||
      typeof raw.id !== "string" ||
      typeof raw.type !== "string" ||
      !VISUAL_TYPES.has(raw.type) ||
      byId.has(raw.id)
    ) {
      return null;
    }
    if (
      raw.type === "group" &&
      (!Array.isArray(raw.children) || !raw.children.every((id) => typeof id === "string"))
    ) {
      return null;
    }
    const element = raw as unknown as VisualElement;
    elements.push(element);
    byId.set(element.id, element);
  }
  if (!byId.has(rootId)) return null;

  const parents = new Map<string, number>();
  for (const element of elements) {
    if (element.type !== "group") continue;
    for (const childId of element.children) {
      if (!byId.has(childId)) return null;
      const count = (parents.get(childId) ?? 0) + 1;
      if (count > 1) return null;
      parents.set(childId, count);
    }
  }
  if (parents.has(rootId)) return null;

  const visited = new Set<string>();
  const active = new Set<string>();
  function visit(id: string): boolean {
    if (active.has(id)) return false;
    if (visited.has(id)) return true;
    active.add(id);
    const element = byId.get(id);
    if (!element) return false;
    if (element.type === "group" && !element.children.every(visit)) return false;
    active.delete(id);
    visited.add(id);
    return true;
  }
  if (!visit(rootId) || visited.size !== elements.length) return null;
  return elements;
}

function safeHttpsUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password) return null;
    return parsed.href;
  } catch {
    return null;
  }
}

function elementAttributes(element: VisualElement) {
  return {
    className: "ca-visual-element",
    "data-element-id": element.id,
    "data-width": element.width ?? "auto",
  };
}

export function VisualComposition({
  rootId,
  elements,
  title,
  description,
  onChange,
}: VisualCompositionProps) {
  const elementMap = useMemo(
    () => new Map(elements.map((element) => [element.id, element])),
    [elements],
  );
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => {
    setValues(
      Object.fromEntries(
        elements
          .filter(
            (element): element is VisualInput | VisualTextarea =>
              element.type === "input" || element.type === "textarea",
          )
          .map((element) => [element.id, element.value ?? ""]),
      ),
    );
  }, [elements]);

  function renderElement(id: string): React.ReactNode {
    const element = elementMap.get(id);
    if (!element) return null;
    const attributes = elementAttributes(element);
    if (element.type === "group") {
      return (
        <div
          {...attributes}
          data-align={element.align ?? "stretch"}
          data-columns={element.columns ?? 2}
          data-gap={element.gap ?? "normal"}
          data-justify={element.justify ?? "start"}
          data-layout={element.layout ?? "stack"}
          data-padding={element.padding ?? "none"}
          data-radius={element.radius ?? "medium"}
          data-surface={element.surface ?? "plain"}
          data-wrap={element.wrap || undefined}
        >
          {element.children.map((childId) => (
            <div className="ca-visual-child" key={childId}>
              {renderElement(childId)}
            </div>
          ))}
        </div>
      );
    }
    if (element.type === "image") {
      const url = safeHttpsUrl(element.url);
      return (
        <figure
          {...attributes}
          className={`${attributes.className} ca-visual-image`}
          data-aspect={element.aspect ?? "auto"}
          data-fit={element.fit ?? "cover"}
          data-radius={element.radius ?? "medium"}
        >
          {url ? (
            <img
              alt={element.alt}
              loading="lazy"
              referrerPolicy="no-referrer"
              src={url}
            />
          ) : (
            <span>Image unavailable</span>
          )}
          {element.caption ? <figcaption>{element.caption}</figcaption> : null}
        </figure>
      );
    }
    if (element.type === "heading") {
      return createElement(
        `h${element.level ?? 2}`,
        {
          ...attributes,
          className: `${attributes.className} ca-visual-heading`,
          "data-align": element.align ?? "left",
          "data-size": element.size ?? "medium",
          "data-tone": element.tone ?? "default",
        },
        element.text,
      );
    }
    if (element.type === "text") {
      return (
        <p
          {...attributes}
          className={`${attributes.className} ca-visual-text`}
          data-align={element.align ?? "left"}
          data-tone={element.tone ?? "default"}
          data-variant={element.variant ?? "body"}
        >
          {element.text}
        </p>
      );
    }
    if (element.type === "badge") {
      return (
        <span
          {...attributes}
          className={`${attributes.className} ca-visual-badge`}
          data-tone={element.tone ?? "neutral"}
        >
          {element.label}
        </span>
      );
    }
    if (element.type === "link") {
      const url = safeHttpsUrl(element.url);
      return url ? (
        <a
          {...attributes}
          className={`${attributes.className} ca-visual-link`}
          data-style={element.style ?? "text"}
          href={url}
          rel="noreferrer"
          target="_blank"
        >
          {element.label} <span aria-hidden="true">↗</span>
        </a>
      ) : null;
    }
    if (element.type === "facts") {
      return (
        <dl {...attributes} className={`${attributes.className} ca-visual-facts`}>
          {element.items.map((item, index) => (
            <div key={`${item.label}-${index}`}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      );
    }
    if (element.type === "input" || element.type === "textarea") {
      const value = values[element.id] ?? "";
      const fieldProps = {
        id: `visual-${element.id}`,
        onBlur: () => onChange?.(element.id, value),
        onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
          setValues((current) => ({ ...current, [element.id]: event.target.value })),
        placeholder: element.placeholder,
        readOnly: element.read_only,
        value,
      };
      return (
        <label {...attributes} className={`${attributes.className} ca-visual-field`}>
          <span>{element.label}</span>
          {element.type === "textarea" ? (
            <textarea {...fieldProps} rows={element.rows ?? 4} />
          ) : (
            <input {...fieldProps} type={element.input_type ?? "text"} />
          )}
        </label>
      );
    }
    if (element.type === "divider") {
      return <hr {...attributes} className={`${attributes.className} ca-visual-divider`} />;
    }
    return (
      <span
        {...attributes}
        aria-hidden="true"
        className={`${attributes.className} ca-visual-spacer`}
        data-size={element.size ?? "medium"}
      />
    );
  }

  return (
    <section aria-label={title ?? "Visual composition"} className="ca-visual-composition">
      {title || description ? (
        <header>
          {title ? <strong>{title}</strong> : null}
          {description ? <p>{description}</p> : null}
        </header>
      ) : null}
      <div className="ca-visual-canvas">{renderElement(rootId)}</div>
      <p className="ca-visual-status">Trusted composable interface</p>
    </section>
  );
}
