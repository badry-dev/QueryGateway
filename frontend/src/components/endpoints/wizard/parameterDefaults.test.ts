import { describe, expect, it } from "vitest";

import {
  describeParameterDefault,
  hasParameterDefault,
  missingSnapshotDefaults,
} from "./parameterDefaults";

describe("parameter default helpers", () => {
  it("counts false, zero, empty strings, and dynamic expressions as defaults", () => {
    expect(hasParameterDefault({ type: "boolean", required: true, default: false })).toBe(true);
    expect(hasParameterDefault({ type: "integer", required: true, default: 0 })).toBe(true);
    expect(hasParameterDefault({ type: "string", required: true, default: "" })).toBe(true);
    expect(
      hasParameterDefault({
        type: "date",
        required: true,
        default_expression: "today",
      }),
    ).toBe(true);
  });

  it("returns only parameter names with no default", () => {
    expect(
      missingSnapshotDefaults({
        start_date: { type: "date", required: true, default_expression: "yesterday" },
        end_date: { type: "date", required: true, default: null },
      }),
    ).toEqual(["end_date"]);
  });

  it("describes dynamic defaults in server-date terms", () => {
    expect(
      describeParameterDefault({
        type: "date",
        required: true,
        default_expression: "today",
      }),
    ).toBe("Today (server date)");
  });
});
