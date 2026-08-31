import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScheduleParameterBindings } from "./ScheduleParameterBindings";

describe("ScheduleParameterBindings", () => {
  it("offers dynamic date sources and SQL NULL only for optional parameters", () => {
    render(
      <ScheduleParameterBindings
        paramSchema={{
          run_date: { type: "date", required: true },
          store_id: { type: "string", required: false, default_is_null: true },
        }}
        bindings={{}}
        onBindingsChange={vi.fn()}
        onWindowChange={vi.fn()}
      />,
    );

    const dateSource = screen.getByLabelText("Value source for run_date");
    expect(dateSource).toHaveTextContent("Run date");
    expect(dateSource).toHaveTextContent("Relative to run date");
    expect(dateSource).toHaveTextContent("Window start");
    expect(dateSource).not.toHaveTextContent("SQL NULL");

    expect(screen.getByLabelText("Value source for store_id")).toHaveTextContent("SQL NULL");
  });

  it("emits a relative-date binding with an editable offset", () => {
    const onBindingsChange = vi.fn();
    render(
      <ScheduleParameterBindings
        paramSchema={{ run_date: { type: "date", required: true } }}
        bindings={{}}
        onBindingsChange={onBindingsChange}
        onWindowChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Value source for run_date"), {
      target: { value: "relative_date" },
    });
    expect(onBindingsChange).toHaveBeenLastCalledWith({
      run_date: { source: "relative_date", offset_days: -1 },
    });
  });

  it("shows window presets when a parameter uses a window boundary", () => {
    const onWindowChange = vi.fn();
    render(
      <ScheduleParameterBindings
        paramSchema={{ start_date: { type: "date", required: true } }}
        bindings={{ start_date: { source: "window_start" } }}
        onBindingsChange={vi.fn()}
        onWindowChange={onWindowChange}
      />,
    );

    expect(screen.getByLabelText("Date window preset")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Date window preset"), {
      target: { value: "last_n_complete_days" },
    });
    expect(onWindowChange).toHaveBeenCalledWith({
      preset: "last_n_complete_days",
      days: 7,
    });
  });

  it("emits only valid finite numeric literal values", () => {
    const onBindingsChange = vi.fn();
    render(
      <ScheduleParameterBindings
        paramSchema={{
          limit: { type: "integer", required: true },
          ratio: { type: "float", required: true },
        }}
        bindings={{
          limit: { source: "literal", value: "" },
          ratio: { source: "literal", value: "" },
        }}
        onBindingsChange={onBindingsChange}
        onWindowChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Fixed value for limit"), {
      target: { value: "1.5" },
    });
    expect(onBindingsChange).toHaveBeenLastCalledWith({
      limit: { source: "literal", value: "" },
      ratio: { source: "literal", value: "" },
    });

    fireEvent.change(screen.getByLabelText("Fixed value for ratio"), {
      target: { value: "not-a-number" },
    });
    expect(onBindingsChange).toHaveBeenLastCalledWith({
      limit: { source: "literal", value: "" },
      ratio: { source: "literal", value: "" },
    });

    fireEvent.change(screen.getByLabelText("Fixed value for ratio"), {
      target: { value: "1.5" },
    });
    expect(onBindingsChange).toHaveBeenLastCalledWith({
      limit: { source: "literal", value: "" },
      ratio: { source: "literal", value: 1.5 },
    });
  });
});
