import { Clock3 } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  buildCronExpression,
  describeCronBuilder,
  isValidCronExpression,
  WEEKDAYS,
  type CronBuilderValue,
  type CronFrequency,
  type CronWeekday,
} from "./cronSchedule";

interface CronScheduleBuilderProps {
  value: CronBuilderValue;
  onChange: (value: CronBuilderValue) => void;
}

export function CronScheduleBuilder({ value, onChange }: CronScheduleBuilderProps) {
  const update = (patch: Partial<CronBuilderValue>) => onChange({ ...value, ...patch });
  const expression = buildCronExpression(value);
  const customIsInvalid =
    value.frequency === "custom" && !isValidCronExpression(value.customExpression);

  return (
    <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
      <div>
        <Label htmlFor="cron-frequency">Frequency</Label>
        <Select
          id="cron-frequency"
          className="mt-1"
          value={value.frequency}
          onChange={(event) => update({ frequency: event.target.value as CronFrequency })}
        >
          <option value="hourly">Hourly</option>
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
          <option value="custom">Custom cron</option>
        </Select>
      </div>

      {value.frequency === "hourly" && (
        <div>
          <Label htmlFor="cron-minute">At minute</Label>
          <Input
            id="cron-minute"
            className="mt-1"
            type="number"
            min={0}
            max={59}
            value={value.minute}
            onChange={(event) => update({ minute: event.target.value })}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            For example, 15 runs at 09:15, 10:15, and so on.
          </p>
        </div>
      )}

      {value.frequency === "daily" && (
        <div>
          <Label htmlFor="cron-time">Time</Label>
          <Input
            id="cron-time"
            className="mt-1"
            type="time"
            value={value.time}
            onChange={(event) => update({ time: event.target.value })}
          />
        </div>
      )}

      {value.frequency === "weekly" && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="cron-weekday">Day</Label>
            <Select
              id="cron-weekday"
              className="mt-1"
              value={value.weekday}
              onChange={(event) => update({ weekday: event.target.value as CronWeekday })}
            >
              {WEEKDAYS.map((weekday) => (
                <option key={weekday.value} value={weekday.value}>
                  {weekday.label}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="cron-weekly-time">Time</Label>
            <Input
              id="cron-weekly-time"
              className="mt-1"
              type="time"
              value={value.time}
              onChange={(event) => update({ time: event.target.value })}
            />
          </div>
        </div>
      )}

      {value.frequency === "monthly" && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="cron-month-day">Day of month</Label>
            <Input
              id="cron-month-day"
              className="mt-1"
              type="number"
              min={1}
              max={31}
              value={value.monthDay}
              onChange={(event) => update({ monthDay: event.target.value })}
            />
          </div>
          <div>
            <Label htmlFor="cron-monthly-time">Time</Label>
            <Input
              id="cron-monthly-time"
              className="mt-1"
              type="time"
              value={value.time}
              onChange={(event) => update({ time: event.target.value })}
            />
          </div>
          <p className="col-span-2 text-xs text-muted-foreground">
            Months without the selected date are skipped.
          </p>
        </div>
      )}

      {value.frequency === "custom" && (
        <div>
          <Label htmlFor="custom-cron">Cron expression</Label>
          <Input
            id="custom-cron"
            className="mt-1 font-mono"
            value={value.customExpression}
            onChange={(event) => update({ customExpression: event.target.value })}
            placeholder="0 */6 * * *"
            aria-invalid={customIsInvalid}
          />
          <p
            className={
              customIsInvalid
                ? "mt-1 text-xs text-destructive"
                : "mt-1 text-xs text-muted-foreground"
            }
          >
            {customIsInvalid
              ? "Enter exactly five fields: minute hour day month weekday."
              : "Advanced: minute hour day month weekday."}
          </p>
        </div>
      )}

      <div
        className="flex gap-2 rounded-md border bg-background px-3 py-2.5"
        role="status"
        aria-live="polite"
      >
        <Clock3 className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-sm font-medium">{describeCronBuilder(value)}</p>
          <p className="text-xs text-muted-foreground">
            Server time · <code>{expression || "Incomplete expression"}</code>
          </p>
        </div>
      </div>
    </div>
  );
}
