import { describe, expect, it } from "vitest";

import {
  describeParameterDefault,
  resolvePreviewParameterDefault,
  updateParameterDescriptor,
} from "./parameterDefaults";

describe("parameter default helpers", () => {
  it("describes dynamic defaults in server-date terms", () => {
    expect(
      describeParameterDefault({
        type: "date",
        required: true,
        default_expression: "today",
      }),
    ).toBe("Today (server date)");
  });

  it("describes an explicit null default", () => {
    expect(
      describeParameterDefault({
        type: "string",
        required: false,
        default_is_null: true,
      }),
    ).toBe("NULL");
  });

  it("turns an empty optional default into an explicit null bind", () => {
    const descriptor = updateParameterDescriptor(
      { type: "string", required: true, default: null },
      "required",
      false,
    );

    expect(descriptor).toMatchObject({
      required: false,
      default: null,
      default_is_null: true,
    });
  });

  it("resolves dynamic preview dates from the supplied local date", () => {
    const runDate = new Date(2026, 7, 30, 12, 0, 0);

    expect(
      resolvePreviewParameterDefault(
        { type: "date", required: true, default_expression: "today" },
        runDate,
      ),
    ).toBe("2026-08-30");
    expect(
      resolvePreviewParameterDefault(
        { type: "date", required: true, default_expression: "yesterday" },
        runDate,
      ),
    ).toBe("2026-08-29");
  });

  it("preserves explicit SQL NULL and distinguishes a missing default", () => {
    expect(
      resolvePreviewParameterDefault({
        type: "string",
        required: false,
        default_is_null: true,
      }),
    ).toBeNull();
    expect(
      resolvePreviewParameterDefault({ type: "string", required: true, default: null }),
    ).toBeUndefined();
  });
});
