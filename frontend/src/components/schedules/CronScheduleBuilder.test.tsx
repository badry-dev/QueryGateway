import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CronScheduleBuilder } from "./CronScheduleBuilder";
import { INITIAL_CRON_BUILDER } from "./cronSchedule";

describe("CronScheduleBuilder", () => {
  it("starts with a plain-language daily schedule", () => {
    render(<CronScheduleBuilder value={INITIAL_CRON_BUILDER} onChange={vi.fn()} />);

    expect(screen.getByLabelText("Frequency")).toHaveValue("daily");
    expect(screen.getByLabelText("Time")).toHaveValue("00:00");
    expect(screen.getByText("Every day at 00:00")).toBeInTheDocument();
    expect(screen.queryByLabelText("Cron expression")).not.toBeInTheDocument();
  });

  it("offers raw cron only when Custom cron is selected", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <CronScheduleBuilder value={INITIAL_CRON_BUILDER} onChange={onChange} />,
    );

    fireEvent.change(screen.getByLabelText("Frequency"), { target: { value: "custom" } });
    expect(onChange).toHaveBeenCalledWith({ ...INITIAL_CRON_BUILDER, frequency: "custom" });

    rerender(
      <CronScheduleBuilder
        value={{ ...INITIAL_CRON_BUILDER, frequency: "custom" }}
        onChange={onChange}
      />,
    );
    expect(screen.getByLabelText("Cron expression")).toHaveValue("0 */6 * * *");
  });
});
