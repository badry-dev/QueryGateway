import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listConnectionsMock = vi.fn();
const listAuthMethodsMock = vi.fn();
const previewMock = vi.fn();
const createMock = vi.fn();

vi.mock("@/components/endpoints/SqlEditor", () => ({
  SqlEditor: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => (
    <textarea
      aria-label="SQL query"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));

vi.mock("@/lib/api", () => ({
  authMethodsApi: { list: (...args: unknown[]) => listAuthMethodsMock(...args) },
  connectionsApi: { list: (...args: unknown[]) => listConnectionsMock(...args) },
  endpointsApi: {
    create: (...args: unknown[]) => createMock(...args),
    preview: (...args: unknown[]) => previewMock(...args),
  },
  getApiError: (error: unknown) => (error instanceof Error ? error.message : String(error)),
}));

const { EndpointWizard } = await import("@/components/endpoints/EndpointWizard");

function renderWizard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <EndpointWizard onSuccess={vi.fn()} onCancel={vi.fn()} />
    </QueryClientProvider>,
  );
}

async function advanceToParameters() {
  fireEvent.click(await screen.findByRole("button", { name: /Test Oracle/ }));
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  fireEvent.change(screen.getByLabelText("SQL query"), {
    target: { value: "SELECT * FROM orders WHERE customer_id = :customer_id" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByRole("heading", { name: "Configure Parameters" })).toBeInTheDocument();
}

describe("EndpointWizard preview coordination", () => {
  beforeEach(() => {
    listConnectionsMock.mockReset();
    listAuthMethodsMock.mockReset();
    previewMock.mockReset();
    createMock.mockReset();
    listConnectionsMock.mockResolvedValue([
      {
        id: "connection-id",
        name: "Test Oracle",
        host: "oracle.example.com",
        port: 1521,
        service_name: "ORCLPDB",
        sid: null,
      },
    ]);
    listAuthMethodsMock.mockResolvedValue([]);
    previewMock.mockResolvedValue({
      columns: [],
      rows: [],
      row_count: 0,
      duration_ms: 1,
      bind_params: ["customer_id"],
    });
  });

  it("sends an explicit SQL NULL default in the preview request", async () => {
    renderWizard();
    await advanceToParameters();

    const selectors = screen.getAllByRole("combobox");
    fireEvent.change(selectors[1], { target: { value: "false" } });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Preview Query" }));

    await waitFor(() => expect(previewMock).toHaveBeenCalledOnce());
    expect(previewMock.mock.calls[0][0]).toMatchObject({
      params: { customer_id: null },
      param_schema: {
        customer_id: expect.objectContaining({
          type: "string",
          required: false,
          default_is_null: true,
        }),
      },
    });
  });

  it("sends a resolved date instead of an empty string for a dynamic default", async () => {
    renderWizard();
    await advanceToParameters();

    let selectors = screen.getAllByRole("combobox");
    fireEvent.change(selectors[0], { target: { value: "date" } });
    selectors = screen.getAllByRole("combobox");
    fireEvent.change(selectors[2], { target: { value: "today" } });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: "Preview Query" }));

    await waitFor(() => expect(previewMock).toHaveBeenCalledOnce());
    expect(previewMock.mock.calls[0][0].params.customer_id).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(previewMock.mock.calls[0][0].param_schema.customer_id.type).toBe("date");
  });

  it("sends an inline preview type with the sample value", async () => {
    renderWizard();
    fireEvent.click(await screen.findByRole("button", { name: /Test Oracle/ }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.change(screen.getByLabelText("SQL query"), {
      target: { value: "SELECT * FROM orders WHERE business_date >= :start_date" },
    });
    fireEvent.change(screen.getByLabelText("Preview type for start_date"), {
      target: { value: "date" },
    });
    fireEvent.change(screen.getByLabelText(":start_date"), {
      target: { value: "2026-08-30" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview Query" }));

    await waitFor(() => expect(previewMock).toHaveBeenCalledOnce());
    expect(previewMock.mock.calls[0][0]).toMatchObject({
      params: { start_date: "2026-08-30" },
      param_schema: {
        start_date: expect.objectContaining({ type: "date", required: true }),
      },
    });
  });

  it("requires snapshot row mappings before review", async () => {
    renderWizard();
    await advanceToParameters();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.change(screen.getByPlaceholderText("My API Endpoint"), {
      target: { value: "Orders" },
    });
    fireEvent.change(screen.getByPlaceholderText("employees"), {
      target: { value: "orders" },
    });
    const configSelectors = screen.getAllByRole("combobox");
    fireEvent.change(configSelectors[1], { target: { value: "snapshot" } });
    fireEvent.click(screen.getByRole("checkbox"));

    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Snapshot column for customer_id"), {
      target: { value: "customer_id" },
    });
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
    expect(
      screen.getByText(/Scheduled values are configured with the schedule/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/logical run date/i)).toBeInTheDocument();
  });
});
