import { describe, expect, it } from "vitest";

import {
  buildCronExpression,
  describeCronExpression,
  INITIAL_CRON_BUILDER,
  isValidCronExpression,
} from "./cronSchedule";

describe("cron schedule builder", () => {
  it("builds hourly, daily, weekly, and monthly expressions", () => {
    expect(
      buildCronExpression({ ...INITIAL_CRON_BUILDER, frequency: "hourly", minute: "15" }),
    ).toBe("15 * * * *");
    expect(
      buildCronExpression({ ...INITIAL_CRON_BUILDER, frequency: "daily", time: "08:30" }),
    ).toBe("30 8 * * *");
    expect(
      buildCronExpression({
        ...INITIAL_CRON_BUILDER,
        frequency: "weekly",
        weekday: "sun",
        time: "21:05",
      }),
    ).toBe("5 21 * * sun");
    expect(
      buildCronExpression({
        ...INITIAL_CRON_BUILDER,
        frequency: "monthly",
        monthDay: "12",
        time: "06:00",
      }),
    ).toBe("0 6 12 * *");
  });

  it("keeps custom cron available as an advanced option", () => {
    expect(
      buildCronExpression({
        ...INITIAL_CRON_BUILDER,
        frequency: "custom",
        customExpression: " 0 */6 * * * ",
      }),
    ).toBe("0 */6 * * *");
    expect(isValidCronExpression("0 */6 * * *")).toBe(true);
    expect(isValidCronExpression("0 */6 * *")).toBe(false);
  });

  it.each([
    "invalid invalid invalid invalid invalid",
    "60 * * * *",
    "0 24 * * *",
    "0 0 0 * *",
    "0 0 32 * *",
    "0 0 * 13 *",
    "0 0 * * 7",
    "*/0 * * * *",
    "10-5 * * * *",
  ])("rejects malformed or out-of-range expression %s", (expression) => {
    expect(isValidCronExpression(expression)).toBe(false);
  });

  it.each(["0,15,30,45 * * * *", "0 9-17/2 * jan-mar mon-fri", "0 0 last * *"])(
    "accepts APScheduler-compatible expression %s",
    (expression) => {
      expect(isValidCronExpression(expression)).toBe(true);
    },
  );

  it("describes generated expressions in plain language", () => {
    expect(describeCronExpression("15 * * * *")).toBe("Every hour at minute 15");
    expect(describeCronExpression("30 8 * * *")).toBe("Every day at 08:30");
    expect(describeCronExpression("5 21 * * sun")).toBe("Every Sunday at 21:05");
    expect(describeCronExpression("0 6 12 * *")).toBe("Every month on day 12 at 06:00");
    expect(describeCronExpression("*/10 * * * *")).toBe("Every 10 minutes");
    expect(describeCronExpression("0 */6 * * *")).toBe("Every 6 hours");
  });
});
