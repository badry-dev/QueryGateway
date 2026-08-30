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

describe("ConfigStep public-endpoint warning (M1)", () => {
  it("warns that the endpoint is PUBLIC when no auth method is selected", () => {
    render(<ConfigStep state={makeState()} update={vi.fn()} authMethods={[]} />);
    expect(screen.getByText(/This endpoint is PUBLIC/i)).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("checking the confirmation sets allow_unauthenticated", () => {
    const update = vi.fn();
    render(<ConfigStep state={makeState()} update={update} authMethods={[]} />);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(update).toHaveBeenCalledWith({ allow_unauthenticated: true });
  });

  it("hides the public warning once an auth method is selected", () => {
    render(
      <ConfigStep
        state={makeState({ auth_method_id: "auth-1" })}
        update={vi.fn()}
        authMethods={[]}
      />,
    );
    expect(screen.queryByText(/This endpoint is PUBLIC/i)).not.toBeInTheDocument();
  });
});

describe("ConfigStep snapshot defaults", () => {
  it("lists snapshot parameters that have no default", () => {
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

    expect(screen.getByText(/Snapshot defaults required/i)).toBeInTheDocument();
    expect(screen.getByText(/:end_date/)).toBeInTheDocument();
    expect(screen.queryByText(/:start_date/)).not.toBeInTheDocument();
  });

  it("accepts false and zero as configured snapshot defaults", () => {
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

    expect(screen.queryByText(/Snapshot defaults required/i)).not.toBeInTheDocument();
  });
});
