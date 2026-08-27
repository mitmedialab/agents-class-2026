import type { ComponentManifest } from "./types.js";

export const DOCUMENT_VIEWER_MANIFEST: ComponentManifest = {
  id: "document-viewer",
  version: "1.0.0",
  title: "Document Viewer",
  description:
    "Opens a specific Markdown, plain-text, or PDF artifact for close reading, navigation, search, and focused discussion. Do not use it for synthesized knowledge overviews.",
  propsSchema: {
    type: "object",
    properties: {
      page: { type: "integer", minimum: 1 },
      find_text: { type: "string", maxLength: 500 },
      highlight: {
        type: "object",
        properties: {
          resource_uri: { type: "string", minLength: 1, maxLength: 500 },
          page: { type: "integer", minimum: 1 },
          quote: { type: "string", minLength: 1, maxLength: 2_000 },
          prefix: { type: "string", maxLength: 500 },
          suffix: { type: "string", maxLength: 500 },
        },
        required: ["resource_uri", "page", "quote"],
        additionalProperties: false,
      },
    },
    additionalProperties: false,
  },
  supportedOperations: ["open", "update", "focus", "close"],
  defaultSize: { width: 720, height: 640 },
};

export const CALENDAR_MANIFEST: ComponentManifest = {
  id: "calendar",
  version: "1.0.0",
  title: "Calendar",
  description: "Displays normalized course events in month or agenda views.",
  propsSchema: {
    type: "object",
    properties: {
      view: { type: "string", enum: ["month", "agenda"] },
      focus_date: { type: "string", format: "date" },
      selected_event_id: { type: "string", minLength: 1, maxLength: 200 },
    },
    additionalProperties: false,
  },
  supportedOperations: ["open", "update", "focus", "close"],
  defaultSize: { width: 760, height: 620 },
};

export const WEBPAGE_VIEWER_MANIFEST: ComponentManifest = {
  id: "webpage-viewer",
  version: "1.0.0",
  title: "Web Page",
  description: "Displays an agent-read page or an optional live sandboxed iframe.",
  propsSchema: {
    type: "object",
    properties: {
      url: {
        type: "string",
        format: "uri",
        pattern: "^https://[^\\s]+$",
        maxLength: 2_048,
      },
      mode: { type: "string", enum: ["reader", "live"] },
      content: { type: "string", maxLength: 20_000 },
    },
    required: ["url"],
    additionalProperties: false,
  },
  supportedOperations: ["open", "update", "focus", "close"],
  defaultSize: { width: 900, height: 680 },
};

export const BROWSER_VIEWER_MANIFEST: ComponentManifest = {
  id: "browser-viewer",
  version: "1.0.0",
  title: "Remote Browser",
  description:
    "Displays an isolated server-side browser session. Open it with browser.open; session IDs are platform-issued.",
  propsSchema: {
    type: "object",
    properties: {
      session_id: { type: "string", format: "uuid" },
      url: {
        type: "string",
        format: "uri",
        pattern: "^https://[^\\s]+$",
        maxLength: 2_048,
      },
      title: { type: "string", minLength: 1, maxLength: 500 },
      revision: { type: "integer", minimum: 1 },
      viewport_width: { type: "integer", minimum: 320, maximum: 4_096 },
      viewport_height: { type: "integer", minimum: 240, maximum: 4_096 },
      scroll_y: { type: "integer", minimum: 0 },
      document_height: { type: "integer", minimum: 0 },
    },
    required: [
      "session_id",
      "url",
      "title",
      "revision",
      "viewport_width",
      "viewport_height",
    ],
    additionalProperties: false,
  },
  supportedOperations: ["open", "update", "focus", "close"],
  defaultSize: { width: 960, height: 720 },
};

export const PAGE_CARDS_MANIFEST: ComponentManifest = {
  id: "page-cards",
  version: "1.0.0",
  title: "Page Cards",
  description:
    "Compares several website candidates in adjacent, independently scrollable preview columns.",
  propsSchema: {
    type: "object",
    properties: {
      heading: { type: "string", minLength: 1, maxLength: 200 },
      description: { type: "string", maxLength: 2_000 },
      selected_id: { type: "string", minLength: 1, maxLength: 100 },
      items: {
        type: "array",
        minItems: 2,
        maxItems: 6,
        items: {
          type: "object",
          properties: {
            id: {
              type: "string",
              pattern: "^[a-z][a-z0-9_-]*$",
              maxLength: 100,
            },
            url: {
              type: "string",
              format: "uri",
              pattern: "^https://[^\\s]+$",
              maxLength: 2_048,
            },
            title: { type: "string", minLength: 1, maxLength: 500 },
            description: { type: "string", maxLength: 2_000 },
            preview_id: { type: "string", format: "uuid" },
            revision: { type: "integer", minimum: 1 },
          },
          required: ["id", "url", "title"],
          additionalProperties: false,
        },
      },
    },
    required: ["items"],
    additionalProperties: false,
  },
  supportedOperations: ["open", "update", "focus", "close"],
  defaultSize: { width: 1100, height: 720 },
};

const VISUAL_ELEMENT_ID_SCHEMA = {
  type: "string",
  pattern: "^[a-z][a-z0-9_-]*$",
  maxLength: 100,
};
const VISUAL_WIDTH_SCHEMA = {
  type: "string",
  enum: ["auto", "full", "half", "third"],
};
const VISUAL_ELEMENT_SCHEMA = {
  oneOf: [
    {
      type: "object",
      properties: {
        id: VISUAL_ELEMENT_ID_SCHEMA,
        type: { const: "group" },
        children: {
          type: "array",
          minItems: 1,
          maxItems: 24,
          uniqueItems: true,
          items: VISUAL_ELEMENT_ID_SCHEMA,
        },
        layout: { type: "string", enum: ["stack", "row", "grid"] },
        columns: { type: "integer", minimum: 1, maximum: 4 },
        gap: { type: "string", enum: ["compact", "normal", "loose"] },
        align: { type: "string", enum: ["start", "center", "end", "stretch"] },
        justify: {
          type: "string",
          enum: ["start", "center", "end", "between"],
        },
        wrap: { type: "boolean" },
        surface: { type: "string", enum: ["plain", "subtle", "raised", "accent"] },
        padding: { type: "string", enum: ["none", "small", "medium", "large"] },
        radius: { type: "string", enum: ["none", "small", "medium", "large"] },
        width: VISUAL_WIDTH_SCHEMA,
      },
      required: ["id", "type", "children"],
      additionalProperties: false,
    },
    {
      type: "object",
      properties: {
        id: VISUAL_ELEMENT_ID_SCHEMA,
        type: { const: "image" },
        url: {
          type: "string",
          format: "uri",
          pattern: "^https://[^\\s]+$",
          maxLength: 2_048,
        },
        alt: { type: "string", maxLength: 500 },
        caption: { type: "string", maxLength: 1_000 },
        aspect: {
          type: "string",
          enum: ["auto", "square", "portrait", "landscape", "wide"],
        },
        fit: { type: "string", enum: ["cover", "contain"] },
        radius: {
          type: "string",
          enum: ["none", "small", "medium", "large", "round"],
        },
        width: VISUAL_WIDTH_SCHEMA,
      },
      required: ["id", "type", "url", "alt"],
      additionalProperties: false,
    },
    {
      type: "object",
      properties: {
        id: VISUAL_ELEMENT_ID_SCHEMA,
        type: { const: "heading" },
        text: { type: "string", minLength: 1, maxLength: 1_000 },
        level: { type: "integer", minimum: 1, maximum: 4 },
        size: { type: "string", enum: ["small", "medium", "large", "display"] },
        tone: { type: "string", enum: ["default", "muted", "accent"] },
        align: { type: "string", enum: ["left", "center", "right"] },
        width: VISUAL_WIDTH_SCHEMA,
      },
      required: ["id", "type", "text"],
      additionalProperties: false,
    },
    {
      type: "object",
      properties: {
        id: VISUAL_ELEMENT_ID_SCHEMA,
        type: { const: "text" },
        text: { type: "string", maxLength: 8_000 },
        variant: { type: "string", enum: ["body", "lead", "caption", "quote"] },
        tone: { type: "string", enum: ["default", "muted", "accent"] },
        align: { type: "string", enum: ["left", "center", "right"] },
        width: VISUAL_WIDTH_SCHEMA,
      },
      required: ["id", "type", "text"],
      additionalProperties: false,
    },
    {
      type: "object",
      properties: {
        id: VISUAL_ELEMENT_ID_SCHEMA,
        type: { const: "badge" },
        label: { type: "string", minLength: 1, maxLength: 200 },
        tone: { type: "string", enum: ["neutral", "accent", "success", "warning"] },
        width: VISUAL_WIDTH_SCHEMA,
      },
      required: ["id", "type", "label"],
      additionalProperties: false,
    },
    {
      type: "object",
      properties: {
        id: VISUAL_ELEMENT_ID_SCHEMA,
        type: { const: "link" },
        label: { type: "string", minLength: 1, maxLength: 300 },
        url: {
          type: "string",
          format: "uri",
          pattern: "^https://[^\\s]+$",
          maxLength: 2_048,
        },
        style: { type: "string", enum: ["text", "button", "quiet"] },
        width: VISUAL_WIDTH_SCHEMA,
      },
      required: ["id", "type", "label", "url"],
      additionalProperties: false,
    },
    {
      type: "object",
      properties: {
        id: VISUAL_ELEMENT_ID_SCHEMA,
        type: { const: "facts" },
        items: {
          type: "array",
          minItems: 1,
          maxItems: 20,
          items: {
            type: "object",
            properties: {
              label: { type: "string", minLength: 1, maxLength: 200 },
              value: { type: "string", maxLength: 1_000 },
            },
            required: ["label", "value"],
            additionalProperties: false,
          },
        },
        width: VISUAL_WIDTH_SCHEMA,
      },
      required: ["id", "type", "items"],
      additionalProperties: false,
    },
    {
      type: "object",
      properties: {
        id: VISUAL_ELEMENT_ID_SCHEMA,
        type: { const: "input" },
        label: { type: "string", minLength: 1, maxLength: 200 },
        value: { type: "string", maxLength: 2_000 },
        placeholder: { type: "string", maxLength: 300 },
        input_type: { type: "string", enum: ["text", "email", "url"] },
        read_only: { type: "boolean" },
        width: VISUAL_WIDTH_SCHEMA,
      },
      required: ["id", "type", "label"],
      additionalProperties: false,
    },
    {
      type: "object",
      properties: {
        id: VISUAL_ELEMENT_ID_SCHEMA,
        type: { const: "textarea" },
        label: { type: "string", minLength: 1, maxLength: 200 },
        value: { type: "string", maxLength: 8_000 },
        placeholder: { type: "string", maxLength: 300 },
        rows: { type: "integer", minimum: 2, maximum: 12 },
        read_only: { type: "boolean" },
        width: VISUAL_WIDTH_SCHEMA,
      },
      required: ["id", "type", "label"],
      additionalProperties: false,
    },
    {
      type: "object",
      properties: {
        id: VISUAL_ELEMENT_ID_SCHEMA,
        type: { const: "divider" },
        width: VISUAL_WIDTH_SCHEMA,
      },
      required: ["id", "type"],
      additionalProperties: false,
    },
    {
      type: "object",
      properties: {
        id: VISUAL_ELEMENT_ID_SCHEMA,
        type: { const: "spacer" },
        size: { type: "string", enum: ["small", "medium", "large"] },
        width: VISUAL_WIDTH_SCHEMA,
      },
      required: ["id", "type"],
      additionalProperties: false,
    },
  ],
};

export const VISUAL_COMPOSITION_MANIFEST: ComponentManifest = {
  id: "visual-composition",
  version: "1.0.0",
  title: "Visual Composition",
  description:
    "Composes trusted image, text, profile, form, and layout primitives into one visual surface. Use groups and element IDs instead of HTML or CSS.",
  propsSchema: {
    type: "object",
    properties: {
      title: { type: "string", minLength: 1, maxLength: 200 },
      description: { type: "string", maxLength: 2_000 },
      root_id: VISUAL_ELEMENT_ID_SCHEMA,
      elements: {
        type: "array",
        minItems: 1,
        maxItems: 80,
        items: VISUAL_ELEMENT_SCHEMA,
      },
    },
    required: ["root_id", "elements"],
    additionalProperties: false,
  },
  supportedOperations: ["open", "update", "focus", "close"],
  defaultSize: { width: 960, height: 720 },
};

export const DRAFT_DOCUMENT_MANIFEST: ComponentManifest = {
  id: "draft-document",
  version: "1.0.0",
  title: "Draft Document",
  description: "Builds a structured document progressively from confirmed and draft fields.",
  propsSchema: {
    type: "object",
    properties: {
      title: { type: "string", minLength: 1, maxLength: 200 },
      description: { type: "string", maxLength: 2_000 },
      status: { type: "string", enum: ["draft", "ready", "final", "submitted"] },
      content: { type: "string", minLength: 1, maxLength: 30_000 },
      fields: {
        type: "array",
        minItems: 1,
        maxItems: 50,
        items: {
          type: "object",
          properties: {
            id: {
              type: "string",
              pattern: "^[a-z][a-z0-9_-]*$",
              maxLength: 100,
            },
            label: { type: "string", minLength: 1, maxLength: 200 },
            value: { type: "string", maxLength: 4_000 },
            status: {
              type: "string",
              enum: ["missing", "candidate", "inferred", "confirmed"],
            },
            source: { type: "string", maxLength: 500 },
          },
          required: ["id", "label", "status"],
          additionalProperties: false,
        },
      },
    },
    required: ["title"],
    anyOf: [
      { properties: { content: {} }, required: ["content"] },
      { properties: { fields: {} }, required: ["fields"] },
    ],
    additionalProperties: false,
  },
  supportedOperations: ["open", "update", "focus", "close"],
  defaultSize: { width: 760, height: 720 },
};

export const BUILT_IN_COMPONENT_MANIFESTS: readonly ComponentManifest[] = [
  DOCUMENT_VIEWER_MANIFEST,
  CALENDAR_MANIFEST,
  WEBPAGE_VIEWER_MANIFEST,
  BROWSER_VIEWER_MANIFEST,
  PAGE_CARDS_MANIFEST,
  VISUAL_COMPOSITION_MANIFEST,
  DRAFT_DOCUMENT_MANIFEST,
];
