export type CronFrequency = "hourly" | "daily" | "weekly" | "monthly" | "custom";

export type CronWeekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

export interface CronBuilderValue {
  frequency: CronFrequency;
  minute: string;
  time: string;
  weekday: CronWeekday;
  monthDay: string;
  customExpression: string;
}

export const INITIAL_CRON_BUILDER: CronBuilderValue = {
  frequency: "daily",
  minute: "0",
  time: "00:00",
  weekday: "mon",
  monthDay: "1",
  customExpression: "0 */6 * * *",
};

export const WEEKDAYS: Array<{ value: CronWeekday; label: string }> = [
  { value: "mon", label: "Monday" },
  { value: "tue", label: "Tuesday" },
  { value: "wed", label: "Wednesday" },
  { value: "thu", label: "Thursday" },
  { value: "fri", label: "Friday" },
  { value: "sat", label: "Saturday" },
  { value: "sun", label: "Sunday" },
];

function normalizeInteger(value: string, min: number, max: number): string {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) return String(min);
  return String(Math.min(max, Math.max(min, parsed)));
}

function parseTime(value: string): [string, string] {
  const match = /^(\d{2}):(\d{2})$/.exec(value);
  if (!match) return ["0", "0"];
  return [normalizeInteger(match[2], 0, 59), normalizeInteger(match[1], 0, 23)];
}

export function buildCronExpression(value: CronBuilderValue): string {
  const [minute, hour] = parseTime(value.time);

  switch (value.frequency) {
    case "hourly":
      return `${normalizeInteger(value.minute, 0, 59)} * * * *`;
    case "daily":
      return `${minute} ${hour} * * *`;
    case "weekly":
      return `${minute} ${hour} * * ${value.weekday}`;
    case "monthly":
      return `${minute} ${hour} ${normalizeInteger(value.monthDay, 1, 31)} * *`;
    case "custom":
      return value.customExpression.trim();
  }
}

interface CronFieldRules {
  min: number;
  max: number;
  names?: Record<string, number>;
  allowLast?: boolean;
}

const MONTH_NAMES: Record<string, number> = {
  jan: 1,
  feb: 2,
  mar: 3,
  apr: 4,
  may: 5,
  jun: 6,
  jul: 7,
  aug: 8,
  sep: 9,
  oct: 10,
  nov: 11,
  dec: 12,
};

const WEEKDAY_NAMES: Record<string, number> = {
  mon: 0,
  tue: 1,
  wed: 2,
  thu: 3,
  fri: 4,
  sat: 5,
  sun: 6,
};

const CRON_FIELD_RULES: CronFieldRules[] = [
  { min: 0, max: 59 },
  { min: 0, max: 23 },
  { min: 1, max: 31, allowLast: true },
  { min: 1, max: 12, names: MONTH_NAMES },
  { min: 0, max: 6, names: WEEKDAY_NAMES },
];

function parseCronValue(value: string, rules: CronFieldRules): number | null {
  const namedValue = rules.names?.[value.toLowerCase()];
  if (namedValue !== undefined) return namedValue;
  if (!/^\d+$/.test(value)) return null;
  const parsed = Number.parseInt(value, 10);
  return parsed >= rules.min && parsed <= rules.max ? parsed : null;
}

function isValidCronPart(part: string, rules: CronFieldRules): boolean {
  const stepParts = part.split("/");
  if (stepParts.length > 2) return false;
  const [base, step] = stepParts;
  if (step !== undefined) {
    if (!/^\d+$/.test(step)) return false;
    const parsedStep = Number.parseInt(step, 10);
    if (parsedStep < 1 || parsedStep > rules.max - rules.min + 1) return false;
  }

  if (base === "*") return true;
  if (rules.allowLast && base.toLowerCase() === "last" && step === undefined) return true;

  const range = base.split("-");
  if (range.length === 1) return parseCronValue(base, rules) !== null;
  if (range.length !== 2) return false;
  const start = parseCronValue(range[0], rules);
  const end = parseCronValue(range[1], rules);
  return start !== null && end !== null && start <= end;
}

function isValidCronField(field: string, rules: CronFieldRules): boolean {
  const parts = field.split(",");
  return parts.length > 0 && parts.every((part) => part.length > 0 && isValidCronPart(part, rules));
}

export function isValidCronExpression(expression: string): boolean {
  const fields = expression.trim().split(/\s+/);
  return (
    fields.length === CRON_FIELD_RULES.length &&
    fields.every((field, index) => isValidCronField(field, CRON_FIELD_RULES[index]))
  );
}

function formatTime(hour: string, minute: string): string {
  return `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
}

export function describeCronExpression(expression: string | null | undefined): string {
  if (!expression) return "Calendar schedule";

  const [minute, hour, day, month, weekday] = expression.trim().split(/\s+/);
  if (!minute || !hour || !day || !month || !weekday) return "Custom calendar schedule";

  const minuteInterval = /^\*\/(\d+)$/.exec(minute);
  if (minuteInterval && hour === "*" && day === "*" && month === "*" && weekday === "*") {
    return `Every ${minuteInterval[1]} minutes`;
  }

  const hourInterval = /^\*\/(\d+)$/.exec(hour);
  if (hourInterval && /^\d+$/.test(minute) && day === "*" && month === "*" && weekday === "*") {
    return minute === "0"
      ? `Every ${hourInterval[1]} hours`
      : `Every ${hourInterval[1]} hours at minute ${minute}`;
  }

  if (/^\d+$/.test(minute) && hour === "*" && day === "*" && month === "*" && weekday === "*") {
    return `Every hour at minute ${minute}`;
  }

  if (/^\d+$/.test(minute) && /^\d+$/.test(hour) && day === "*" && month === "*") {
    const time = formatTime(hour, minute);
    if (weekday === "*") return `Every day at ${time}`;

    const weekdayLabel = WEEKDAYS.find((item) => item.value === weekday)?.label;
    if (weekdayLabel) return `Every ${weekdayLabel} at ${time}`;
  }

  if (
    /^\d+$/.test(minute) &&
    /^\d+$/.test(hour) &&
    /^\d+$/.test(day) &&
    month === "*" &&
    weekday === "*"
  ) {
    return `Every month on day ${day} at ${formatTime(hour, minute)}`;
  }

  return "Custom calendar schedule";
}

export function describeCronBuilder(value: CronBuilderValue): string {
  if (value.frequency === "custom") {
    return isValidCronExpression(value.customExpression)
      ? describeCronExpression(value.customExpression)
      : "Enter a complete five-field cron expression.";
  }
  return describeCronExpression(buildCronExpression(value));
}
