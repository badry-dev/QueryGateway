import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { ParamDescriptor } from "@/types/endpoint";
import type {
  ScheduleBindingSource,
  ScheduleParameterBinding,
  ScheduleWindow,
  ScheduleWindowPreset,
} from "@/types/schedule";

import { bindingsUseWindow, parseScheduleNumericLiteral } from "./scheduleBindings";

interface ScheduleParameterBindingsProps {
  paramSchema: Record<string, ParamDescriptor>;
  bindings: Record<string, ScheduleParameterBinding>;
  window?: ScheduleWindow | null;
  onBindingsChange: (bindings: Record<string, ScheduleParameterBinding>) => void;
  onWindowChange: (window: ScheduleWindow | null) => void;
}

function initialBinding(source: ScheduleBindingSource, descriptor: ParamDescriptor) {
  if (source === "literal") {
    if (descriptor.type === "boolean") return { source, value: true } as const;
    return { source, value: descriptor.default ?? "" } as const;
  }
  if (source === "relative_date") return { source, offset_days: -1 } as const;
  return { source } as ScheduleParameterBinding;
}

function WindowEditor({
  window,
  onChange,
}: {
  window?: ScheduleWindow | null;
  onChange: (window: ScheduleWindow) => void;
}) {
  const current = window ?? { preset: "previous_day" as const };
  return (
    <div className="rounded-md border bg-muted/30 p-3">
      <Label htmlFor="schedule-window-preset">Date window</Label>
      <Select
        id="schedule-window-preset"
        aria-label="Date window preset"
        className="mt-1"
        value={current.preset}
        onChange={(event) => {
          const preset = event.target.value as ScheduleWindowPreset;
          onChange(preset === "last_n_complete_days" ? { preset, days: 7 } : { preset });
        }}
      >
        <option value="previous_day">Previous day</option>
        <option value="last_n_complete_days">Last N complete days</option>
        <option value="week_to_date">Week to date</option>
        <option value="previous_week">Previous week</option>
        <option value="month_to_date">Month to date</option>
        <option value="previous_month">Previous month</option>
      </Select>
      {current.preset === "last_n_complete_days" && (
        <div className="mt-2">
          <Label htmlFor="schedule-window-days">Number of complete days</Label>
          <Input
            id="schedule-window-days"
            className="mt-1"
            type="number"
            min={1}
            max={3660}
            value={current.days ?? 7}
            onChange={(event) =>
              onChange({
                preset: "last_n_complete_days",
                days: Math.max(1, Number.parseInt(event.target.value, 10) || 1),
              })
            }
          />
        </div>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        Window start and end are inclusive and are evaluated from each logical run date.
      </p>
    </div>
  );
}

export function ScheduleParameterBindings({
  paramSchema,
  bindings,
  window,
  onBindingsChange,
  onWindowChange,
}: ScheduleParameterBindingsProps) {
  const updateBinding = (name: string, binding: ScheduleParameterBinding) =>
    onBindingsChange({ ...bindings, [name]: binding });

  if (Object.keys(paramSchema).length === 0) {
    return (
      <div className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
        This endpoint has no SQL parameters. Each run will execute the same query.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-medium">Scheduled parameter values</h4>
        <p className="text-xs text-muted-foreground">
          Values are owned by this schedule and resolved from its logical run date.
        </p>
      </div>
      {Object.entries(paramSchema).map(([name, descriptor]) => {
        const binding = bindings[name];
        return (
          <div key={name} className="grid gap-2 rounded-md border p-3 sm:grid-cols-2">
            <div>
              <Label htmlFor={`binding-source-${name}`}>
                :{name} <span className="text-xs text-muted-foreground">({descriptor.type})</span>
              </Label>
              <Select
                id={`binding-source-${name}`}
                aria-label={`Value source for ${name}`}
                className="mt-1"
                value={binding?.source ?? ""}
                onChange={(event) =>
                  updateBinding(
                    name,
                    initialBinding(event.target.value as ScheduleBindingSource, descriptor),
                  )
                }
              >
                <option value="">Choose a value source...</option>
                <option value="literal">Fixed value</option>
                {descriptor.type === "date" && (
                  <>
                    <option value="run_date">Run date</option>
                    <option value="relative_date">Relative to run date</option>
                    <option value="window_start">Window start</option>
                    <option value="window_end">Window end</option>
                  </>
                )}
                {!descriptor.required && <option value="null">SQL NULL</option>}
              </Select>
            </div>
            <div>
              {binding?.source === "literal" && descriptor.type === "boolean" && (
                <>
                  <Label htmlFor={`binding-value-${name}`}>Fixed value</Label>
                  <Select
                    id={`binding-value-${name}`}
                    aria-label={`Fixed value for ${name}`}
                    className="mt-1"
                    value={String(binding.value ?? true)}
                    onChange={(event) =>
                      updateBinding(name, {
                        source: "literal",
                        value: event.target.value === "true",
                      })
                    }
                  >
                    <option value="true">True</option>
                    <option value="false">False</option>
                  </Select>
                </>
              )}
              {binding?.source === "literal" && descriptor.type !== "boolean" && (
                <>
                  <Label htmlFor={`binding-value-${name}`}>Fixed value</Label>
                  <Input
                    id={`binding-value-${name}`}
                    aria-label={`Fixed value for ${name}`}
                    className="mt-1"
                    type={descriptor.type === "date" ? "date" : "text"}
                    inputMode={
                      descriptor.type === "integer" || descriptor.type === "float"
                        ? "decimal"
                        : undefined
                    }
                    value={String(binding.value ?? "")}
                    onChange={(event) => {
                      const raw = event.target.value;
                      const value =
                        descriptor.type === "integer" || descriptor.type === "float"
                          ? parseScheduleNumericLiteral(raw, descriptor.type)
                          : raw;
                      updateBinding(name, { source: "literal", value });
                    }}
                  />
                </>
              )}
              {binding?.source === "relative_date" && (
                <>
                  <Label htmlFor={`binding-offset-${name}`}>Day offset</Label>
                  <Input
                    id={`binding-offset-${name}`}
                    aria-label={`Day offset for ${name}`}
                    className="mt-1"
                    type="number"
                    min={-36500}
                    max={36500}
                    value={binding.offset_days ?? -1}
                    onChange={(event) =>
                      updateBinding(name, {
                        source: "relative_date",
                        offset_days: Number.parseInt(event.target.value, 10) || 0,
                      })
                    }
                  />
                </>
              )}
              {binding && !["literal", "relative_date"].includes(binding.source) && (
                <p className="mt-6 text-xs text-muted-foreground">
                  {binding.source === "null"
                    ? "Oracle receives an explicit SQL NULL bind."
                    : "Resolved separately for every logical run."}
                </p>
              )}
            </div>
          </div>
        );
      })}
      {bindingsUseWindow(bindings) && <WindowEditor window={window} onChange={onWindowChange} />}
    </div>
  );
}
