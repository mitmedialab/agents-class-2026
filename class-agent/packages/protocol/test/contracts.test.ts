import { readFileSync } from "node:fs";

import Ajv2020Package from "ajv/dist/2020.js";
import addFormatsPackage from "ajv-formats";
import type { Ajv2020 as Ajv2020Type } from "ajv/dist/2020.js";
import type { FormatsPlugin } from "ajv-formats";
import { describe, expect, it } from "vitest";

import { SCHEMA_VERSION } from "../src/index.js";
import type {
  AgentContext,
  AgentInput,
  AgentResult,
  Capability,
  Conversation,
  ContractMap,
  ContractName,
  Event,
  Memory,
  Node,
  Permission,
  PrincipalContext,
} from "../src/index.js";

const schemaPath = new URL(
  "../../../shared/schemas/v1/agent-core.schema.json",
  import.meta.url,
);
const examplesPath = new URL(
  "../../../shared/schemas/v1/examples/contracts.json",
  import.meta.url,
);

const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as {
  $id: string;
  [key: string]: unknown;
};
const examples = JSON.parse(readFileSync(examplesPath, "utf8")) as Record<
  ContractName,
  unknown
>;

const contractNames = [
  "PrincipalContext",
  "Event",
  "Conversation",
  "Memory",
  "Capability",
  "Permission",
  "Node",
  "AgentContext",
  "AgentInput",
  "AgentResult",
] as const satisfies readonly ContractName[];

const Ajv2020 = Ajv2020Package as unknown as typeof Ajv2020Type;
const addFormats = addFormatsPackage as unknown as FormatsPlugin;

function createAjv(): Ajv2020Type {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(ajv);
  ajv.addSchema(schema);
  return ajv;
}

describe("canonical JSON Schema", () => {
  it("is a valid draft 2020-12 schema", () => {
    expect(createAjv().validateSchema(schema)).toBe(true);
  });

  it.each(contractNames)("validates the shared %s example", (contractName) => {
    const ajv = createAjv();
    const validate = ajv.getSchema(`${schema.$id}#/$defs/${contractName}`);

    expect(validate, `missing schema definition for ${contractName}`).toBeDefined();
    const valid = validate?.(examples[contractName]);
    expect(valid, JSON.stringify(validate?.errors)).toBe(true);
  });

  it("rejects unknown event fields", () => {
    const ajv = createAjv();
    const validate = ajv.getSchema(`${schema.$id}#/$defs/Event`);
    const invalidEvent = {
      ...(examples.Event as Record<string, unknown>),
      unexpected: true,
    };

    expect(validate?.(invalidEvent)).toBe(false);
  });
});

describe("TypeScript bindings", () => {
  it("represent every shared contract", () => {
    const typedExamples = examples as unknown as ContractMap;

    const principal: PrincipalContext = typedExamples.PrincipalContext;
    const event: Event = typedExamples.Event;
    const conversation: Conversation = typedExamples.Conversation;
    const memory: Memory = typedExamples.Memory;
    const capability: Capability = typedExamples.Capability;
    const permission: Permission = typedExamples.Permission;
    const node: Node = typedExamples.Node;
    const context: AgentContext = typedExamples.AgentContext;
    const input: AgentInput = typedExamples.AgentInput;
    const result: AgentResult = typedExamples.AgentResult;

    expect(principal.roles).toContain("student");
    expect(event.schema_version).toBe(SCHEMA_VERSION);
    expect(conversation.user_id).toBe(principal.user_id);
    expect(memory.privacy).toBe("personal");
    expect(capability.status).toBe("obtainable");
    expect(permission.capability).toBe("filesystem.read");
    expect(node.type).toBe("local_bridge");
    expect(context.permitted_tool_ids).toContain("grades.get_mine");
    expect(input.text).toBeTruthy();
    expect(result.input_id).toBe(input.id);
  });
});
