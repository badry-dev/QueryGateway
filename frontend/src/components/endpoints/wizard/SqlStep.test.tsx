import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SqlStep } from "./SqlStep";
import type { WizardState } from "./types";

vi.mock("@/components/endpoints/SqlEditor", () => ({
  SqlEditor: ({ value }: { value: string }) => (
    <textarea aria-label="SQL query" value={value} readOnly />
  ),
}));

function makeState(): WizardState {
  return {
    name: "",
    description: "",
    path: "",
    connection_id: "connection-id",
    sql_text: "SELECT * FROM orders WHERE customer_id = :customer_id",
    param_schema: {
      customer_id: { type: "string", required: true, default: null },
    },
    column_map: {},
    auth_method_id: "",
    allow_unauthenticated: false,
    data_strategy: "live",
  };
}

describe("SqlStep preview parameters", () => {
  it("shows detected bind parameters and requires a sample value before preview", () => {
    render(
      <SqlStep
        state={makeState()}
        update={vi.fn()}
        preview={null}
        previewParams={{}}
        isPreviewing={false}
        onPreview={vi.fn()}
        onUpdatePreviewParam={vi.fn()}
      />,
    );

    expect(screen.getByLabelText(":customer_id")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview Query" })).toBeDisabled();
  });

  it("passes preview-only values to the wizard and enables preview", () => {
    const onPreview = vi.fn();
    const onUpdatePreviewParam = vi.fn();
    const { rerender } = render(
      <SqlStep
        state={makeState()}
        update={vi.fn()}
        preview={null}
        previewParams={{}}
        isPreviewing={false}
        onPreview={onPreview}
        onUpdatePreviewParam={onUpdatePreviewParam}
      />,
    );

    fireEvent.change(screen.getByLabelText(":customer_id"), { target: { value: "42" } });
    expect(onUpdatePreviewParam).toHaveBeenCalledWith("customer_id", "42");

    rerender(
      <SqlStep
        state={makeState()}
        update={vi.fn()}
        preview={null}
        previewParams={{ customer_id: "42" }}
        isPreviewing={false}
        onPreview={onPreview}
        onUpdatePreviewParam={onUpdatePreviewParam}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Preview Query" }));
    expect(onPreview).toHaveBeenCalledOnce();
  });

  it("allows preview when an optional parameter has an explicit NULL default", () => {
    const state = makeState();
    state.param_schema.customer_id = {
      type: "string",
      required: false,
      default: null,
      default_is_null: true,
    };

    render(
      <SqlStep
        state={state}
        update={vi.fn()}
        preview={null}
        previewParams={{}}
        isPreviewing={false}
        onPreview={vi.fn()}
        onUpdatePreviewParam={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Preview Query" })).toBeEnabled();
  });

  it("allows preview when a date parameter has a dynamic default", () => {
    const state = makeState();
    state.param_schema.customer_id = {
      type: "date",
      required: true,
      default: null,
      default_expression: "today",
    };

    render(
      <SqlStep
        state={state}
        update={vi.fn()}
        preview={null}
        previewParams={{}}
        isPreviewing={false}
        onPreview={vi.fn()}
        onUpdatePreviewParam={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Preview Query" })).toBeEnabled();
  });
});
