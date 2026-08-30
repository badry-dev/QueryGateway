import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listEndpointsMock = vi.fn();
const listSchedulesMock = vi.fn();
const previewMock = vi.fn();

vi.mock("@/lib/api", () => ({
  endpointsApi: { list: (...args: unknown[]) => listEndpointsMock(...args) },
  schedulesApi: {
    list: (...args: unknown[]) => listSchedulesMock(...args),
    listJobRuns: vi.fn(),
    create: vi.fn(),
    delete: vi.fn(),
    preview: (...args: unknown[]) => previewMock(...args),
    runNow: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
  },
  getApiError: (error: unknown) => (error instanceof Error ? error.message : String(error)),
}));

const { SchedulesPage } = await import("@/pages/SchedulesPage");

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SchedulesPage />
    </QueryClientProvider>,
  );
}

describe("SchedulesPage run preview", () => {
  beforeEach(() => {
    listEndpointsMock.mockReset();
    listSchedulesMock.mockReset();
    previewMock.mockReset();
    listSchedulesMock.mockResolvedValue([]);
    listEndpointsMock.mockResolvedValue([
      {
        id: "endpoint-1",
        name: "Orders snapshot",
        path: "orders",
        param_schema: {},
        data_strategy: "snapshot",
        is_active: true,
      },
    ]);
    previewMock.mockResolvedValue({
      runs: [
        {
          scheduled_for: "2026-08-31T03:00:00Z",
          logical_date: "2026-08-31",
          window_start: null,
          window_end: null,
          resolved_parameters: {},
        },
      ],
    });
  });

  it("clears a resolved preview when interval timing changes", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "New schedule" }));
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Endpoint" }),
      "endpoint-1",
    );
    await user.click(await screen.findByRole("button", { name: "Preview runs" }));

    expect(await screen.findByText("2026-08-31")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("spinbutton", { name: "Interval (seconds)" }), {
      target: { value: "600" },
    });

    await waitFor(() => expect(screen.queryByText("2026-08-31")).not.toBeInTheDocument());
  });
});
