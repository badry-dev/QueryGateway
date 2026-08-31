import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConfigStep } from "@/components/endpoints/wizard/ConfigStep";
import type { WizardState } from "@/components/endpoints/wizard/types";

function makeState(overrides: Partial<WizardState> = {}): WizardState {
  return {
    name: "",
    description: "",
    path: "",
    connection_id: "",
    sql_text: "",
    param_schema: {},
    column_map: {},
    auth_method_id: "",
    allow_unauthenticated: false,
    data_strategy: "live",
    ...overrides,
  };
}

describe("ConfigStep platform authentication fallback", () => {
  it("explains that platform Bearer authentication is required without an endpoint method", () => {
    render(<ConfigStep state={makeState()} update={vi.fn()} authMethods={[]} />);
    expect(screen.getByText(/Platform authentication required/i)).toBeInTheDocument();
    expect(screen.queryByText(/This endpoint is PUBLIC/i)).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("checking the confirmation opts into the platform Bearer fallback", () => {
    const update = vi.fn();
    render(<ConfigStep state={makeState()} update={update} authMethods={[]} />);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(update).toHaveBeenCalledWith({ allow_unauthenticated: true });
  });

  it("hides the fallback notice once an endpoint auth method is selected", () => {
    render(
      <ConfigStep
        state={makeState({ auth_method_id: "auth-1" })}
        update={vi.fn()}
        authMethods={[]}
      />,
    );
    expect(screen.queryByText(/Platform authentication required/i)).not.toBeInTheDocument();
  });
});

describe("ConfigStep snapshot scheduling guidance", () => {
  it("explains that scheduled values are configured separately", () => {
    render(
      <ConfigStep
        state={makeState({
          data_strategy: "snapshot",
          param_schema: {
            start_date: { type: "date", required: true, default_expression: "yesterday" },
            end_date: { type: "date", required: true, default: null },
          },
        })}
        update={vi.fn()}
        authMethods={[]}
      />,
    );

    expect(
      screen.getByText(/Scheduled values are configured with the schedule/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/logical run date/i)).toBeInTheDocument();
  });

  it("shows the guidance even when endpoint defaults exist", () => {
    render(
      <ConfigStep
        state={makeState({
          data_strategy: "snapshot",
          param_schema: {
            enabled: { type: "boolean", required: true, default: false },
            offset: { type: "integer", required: true, default: 0 },
          },
        })}
        update={vi.fn()}
        authMethods={[]}
      />,
    );

    expect(
      screen.getByText(/Scheduled values are configured with the schedule/i),
    ).toBeInTheDocument();
  });

  it("configures an explicit cached column and operator for every parameter", () => {
    const update = vi.fn();
    render(
      <ConfigStep
        state={makeState({
          data_strategy: "snapshot",
          param_schema: {
            start_date: { type: "date", required: true, default: null },
          },
        })}
        update={update}
        authMethods={[]}
        previewColumns={["business_date", "store_id"]}
      />,
    );

    expect(screen.getByText(/Snapshot request filters/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Snapshot column for start_date"), {
      target: { value: "business_date" },
    });

    expect(update).toHaveBeenCalledWith({
      param_schema: {
        start_date: {
          type: "date",
          required: true,
          default: null,
          snapshot_filter: {
            column: "business_date",
            operator: "eq",
            null_means_all: false,
          },
        },
      },
    });
  });

  it("allows an optional equality filter to declare scheduled NULL as all values", () => {
    const update = vi.fn();
    render(
      <ConfigStep
        state={makeState({
          data_strategy: "snapshot",
          param_schema: {
            store_id: {
              type: "integer",
              required: false,
              default_is_null: true,
              snapshot_filter: {
                column: "store_id",
                operator: "eq",
                null_means_all: false,
              },
            },
          },
        })}
        update={update}
        authMethods={[]}
      />,
    );

    fireEvent.click(screen.getByLabelText("Scheduled NULL covers all store_id values"));

    expect(update).toHaveBeenCalledWith({
      param_schema: {
        store_id: expect.objectContaining({
          snapshot_filter: {
            column: "store_id",
            operator: "eq",
            null_means_all: true,
          },
        }),
      },
    });
  });
});
