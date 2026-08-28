import { createElement, useEffect, useMemo, useState } from "react";

import {
  Chart,
  type ChartDataKind,
  type ChartSeries,
  type ChartTone,
  type ChartType,
} from "./Chart.js";

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
  source_width?: number;
  source_height?: number;
  presentation?: "standard" | "banner" | "feature" | "card" | "avatar";
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

export interface VisualChart extends VisualBase {
  type: "chart";
  title: string;
  chart_type: ChartType;
  labels: string[];
  series: Array<ChartSeries & { tone?: ChartTone }>;
  comparison_basis?: string;
  data_kind?: ChartDataKind;
  data_source?: string;
  description?: string;
  unit?: string;
  value_suffix?: string;
  y_min?: number;
  y_max?: number;
  show_legend?: boolean;
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
  | VisualChart
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
  "chart",
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
    if (
      raw.type === "image" &&
      ((raw.source_width === undefined) !== (raw.source_height === undefined) ||
        (raw.source_width !== undefined &&
          (typeof raw.source_width !== "number" ||
            !Number.isInteger(raw.source_width) ||
            raw.source_width <= 0)) ||
        (raw.source_height !== undefined &&
          (typeof raw.source_height !== "number" ||
            !Number.isInteger(raw.source_height) ||
            raw.source_height <= 0)))
    ) {
      return null;
    }
    if (raw.type === "chart") {
      const labels = raw.labels;
      const series = raw.series;
      if (
        typeof raw.title !== "string" ||
        !["bar", "line", "area"].includes(String(raw.chart_type)) ||
        !Array.isArray(labels) ||
        labels.length < 2 ||
        labels.length > 16 ||
        !labels.every((label) => typeof label === "string") ||
        !Array.isArray(series) ||
        series.length < 1 ||
        series.length > 4 ||
        !series.every(
          (item) =>
            isRecord(item) &&
            typeof item.label === "string" &&
            Array.isArray(item.values) &&
            item.values.length === labels.length &&
            item.values.every((itemValue) =>
              typeof itemValue === "number" && Number.isFinite(itemValue)
            ) &&
            (item.tone === undefined ||
              ["accent", "coral", "secondary", "success", "warning", "violet"].includes(
                String(item.tone),
              )) &&
            (item.tones === undefined ||
              (Array.isArray(item.tones) &&
                item.tones.length === labels.length &&
                item.tones.every((tone) =>
                  ["accent", "coral", "secondary", "success", "warning", "violet"].includes(
                    String(tone),
                  ),
                ))),
        ) ||
        (raw.y_min !== undefined &&
          (typeof raw.y_min !== "number" || !Number.isFinite(raw.y_min))) ||
        (raw.y_max !== undefined &&
          (typeof raw.y_max !== "number" || !Number.isFinite(raw.y_max))) ||
        (typeof raw.y_min === "number" &&
          typeof raw.y_max === "number" &&
          raw.y_max <= raw.y_min)
      ) {
        return null;
      }
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

function safeImageUrl(value: string): string | null {
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  return safeHttpsUrl(value);
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
      const isRoot = id === rootId;
      return (
        <div
          {...attributes}
          data-align={element.align ?? "stretch"}
          data-columns={element.columns ?? 2}
          data-gap={element.gap ?? (isRoot ? "loose" : "normal")}
          data-justify={element.justify ?? "start"}
          data-layout={element.layout ?? "stack"}
          data-padding={element.padding ?? (isRoot ? "large" : "none")}
          data-radius={element.radius ?? (isRoot ? "large" : "medium")}
          data-root={isRoot || undefined}
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
      const url = safeImageUrl(element.url);
      const hasSourceDimensions =
        element.source_width !== undefined && element.source_height !== undefined;
      return (
        <figure
          {...attributes}
          className={`${attributes.className} ca-visual-image`}
          data-aspect={element.aspect ?? "auto"}
          data-fit={element.fit ?? "cover"}
          data-presentation={element.presentation ?? "standard"}
          data-radius={element.radius ?? "medium"}
          data-source-dimensions={hasSourceDimensions ? "known" : "unknown"}
          data-source-height={element.source_height}
          data-source-width={element.source_width}
        >
          {url ? (
            <img
              alt={element.alt}
              {...(element.source_height === undefined
                ? {}
                : { height: element.source_height })}
              loading="lazy"
              referrerPolicy="no-referrer"
              src={url}
              {...(element.source_width === undefined
                ? {}
                : { width: element.source_width })}
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
    if (element.type === "chart") {
      return (
        <div {...attributes} className={`${attributes.className} ca-visual-chart`}>
          <Chart
            chartType={element.chart_type}
            labels={element.labels}
            series={element.series}
            title={element.title}
            {...(element.comparison_basis === undefined
              ? {}
              : { comparisonBasis: element.comparison_basis })}
            {...(element.data_kind === undefined ? {} : { dataKind: element.data_kind })}
            {...(element.data_source === undefined
              ? {}
              : { dataSource: element.data_source })}
            {...(element.description === undefined
              ? {}
              : { description: element.description })}
            {...(element.unit === undefined ? {} : { unit: element.unit })}
            {...(element.value_suffix === undefined
              ? {}
              : { valueSuffix: element.value_suffix })}
            {...(element.y_min === undefined ? {} : { yMin: element.y_min })}
            {...(element.y_max === undefined ? {} : { yMax: element.y_max })}
            {...(element.show_legend === undefined
              ? {}
              : { showLegend: element.show_legend })}
          />
        </div>
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
