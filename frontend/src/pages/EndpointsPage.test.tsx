import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listMock = vi.fn();
const deleteMock = vi.fn();
const updateMock = vi.fn();

vi.mock("@/components/endpoints/EndpointWizard", () => ({
  EndpointWizard: () => <div>Endpoint wizard</div>,
}));

vi.mock("@/lib/api", () => ({
  endpointsApi: {
    list: (...args: unknown[]) => listMock(...args),
    delete: (...args: unknown[]) => deleteMock(...args),
    update: (...args: unknown[]) => updateMock(...args),
  },
  getApiError: (error: unknown) => (error instanceof Error ? error.message : String(error)),
  getPublicApiBaseUrl: () => "http://localhost:8000",
}));

const { EndpointsPage } = await import("@/pages/EndpointsPage");

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <EndpointsPage />
    </QueryClientProvider>,
  );
}

describe("EndpointsPage", () => {
  beforeEach(() => {
    listMock.mockReset();
    deleteMock.mockReset();
    updateMock.mockReset();
    listMock.mockResolvedValue([
      {
        id: "0ff4f30e-6799-48af-9ba7-bb31471de215",
        name: "store_orders",
        description: null,
        path: "store-orders",
        connection_id: "fd421223-0866-45fd-8937-7a374ba8eb06",
        sql_text: "SELECT 1 FROM dual",
        param_schema: {},
        column_map: {},
        auth_method_id: null,
        allow_unauthenticated: true,
        data_strategy: "snapshot",
        version: "v1",
        is_active: true,
        is_deprecated: false,
        deprecation_note: null,
        created_at: "2026-08-30T00:00:00Z",
        updated_at: "2026-08-30T00:00:00Z",
      },
    ]);
  });

  it("keeps the delete dialog open and displays an API failure", async () => {
    deleteMock.mockRejectedValueOnce(new Error("Endpoint could not be deleted."));
    renderPage();

    expect(await screen.findByText("store_orders")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Delete endpoint"));

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(deleteMock).toHaveBeenCalledWith("0ff4f30e-6799-48af-9ba7-bb31471de215"),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Endpoint could not be deleted.");
    expect(screen.getByRole("heading", { name: "Delete Endpoint" })).toBeInTheDocument();
  });

  it("lets an existing snapshot endpoint add missing request filter mappings", async () => {
    listMock.mockResolvedValueOnce([
      {
        id: "0ff4f30e-6799-48af-9ba7-bb31471de215",
        name: "store_orders",
        description: null,
        path: "store-orders",
        connection_id: "fd421223-0866-45fd-8937-7a374ba8eb06",
        sql_text: "SELECT * FROM orders WHERE store_id = :store_id",
        param_schema: {
          store_id: { type: "integer", required: true },
        },
        column_map: {},
        auth_method_id: null,
        allow_unauthenticated: true,
        data_strategy: "snapshot",
        version: "v1",
        is_active: true,
        is_deprecated: false,
        deprecation_note: null,
        created_at: "2026-08-30T00:00:00Z",
        updated_at: "2026-08-30T00:00:00Z",
      },
    ]);
    updateMock.mockResolvedValue({});
    renderPage();

    expect(await screen.findByText("store_orders")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Edit endpoint"));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Snapshot column for store_id"), {
      target: { value: "store_id" },
    });
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith(
        "0ff4f30e-6799-48af-9ba7-bb31471de215",
        expect.objectContaining({
          param_schema: {
            store_id: expect.objectContaining({
              snapshot_filter: {
                column: "store_id",
                operator: "eq",
                null_means_all: false,
              },
            }),
          },
        }),
      ),
    );
  });
});
