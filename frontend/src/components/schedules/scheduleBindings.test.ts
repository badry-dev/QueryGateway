import { describe, expect, it } from "vitest";

import type { ParamDescriptor } from "@/types/endpoint";
import type { ScheduleParameterBinding } from "@/types/schedule";

import { scheduleBindingsComplete, suggestScheduleBindings } from "./scheduleBindings";

describe("schedule binding helpers", () => {
  it("translates endpoint defaults into editable schedule-owned suggestions", () => {
    const schema: Record<string, ParamDescriptor> = {
      start_date: { type: "date", required: true, default_expression: "yesterday" },
      end_date: { type: "date", required: true, default_expression: "today" },
      store_id: { type: "string", required: false, default_is_null: true },
      limit: { type: "integer", required: true, default: 100 },
      region: { type: "string", required: true },
    };

    expect(suggestScheduleBindings(schema)).toEqual({
      start_date: { source: "relative_date", offset_days: -1 },
      end_date: { source: "run_date" },
      store_id: { source: "null" },
      limit: { source: "literal", value: 100 },
    });
  });

  it("requires one binding per endpoint parameter", () => {
    const schema: Record<string, ParamDescriptor> = {
      run_date: { type: "date", required: true },
      store_id: { type: "string", required: true },
    };
    const incomplete: Record<string, ScheduleParameterBinding> = {
      run_date: { source: "run_date" },
    };

    expect(scheduleBindingsComplete(schema, incomplete, undefined)).toBe(false);
    expect(
      scheduleBindingsComplete(
        schema,
        { ...incomplete, store_id: { source: "literal", value: "101" } },
        undefined,
      ),
    ).toBe(true);
  });

  it("requires a window preset when a binding reads a window boundary", () => {
    const schema: Record<string, ParamDescriptor> = {
      start_date: { type: "date", required: true },
    };
    const bindings: Record<string, ScheduleParameterBinding> = {
      start_date: { source: "window_start" },
    };

    expect(scheduleBindingsComplete(schema, bindings, undefined)).toBe(false);
    expect(scheduleBindingsComplete(schema, bindings, { preset: "previous_day" })).toBe(true);
  });
});
