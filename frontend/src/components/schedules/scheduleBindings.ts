import type { ParamDescriptor } from "@/types/endpoint";
import type { ScheduleParameterBinding, ScheduleWindow } from "@/types/schedule";

export function suggestScheduleBindings(
  paramSchema: Record<string, ParamDescriptor>,
): Record<string, ScheduleParameterBinding> {
  const bindings: Record<string, ScheduleParameterBinding> = {};
  for (const [name, descriptor] of Object.entries(paramSchema)) {
    if (descriptor.default_is_null) {
      bindings[name] = { source: "null" };
    } else if (descriptor.default_expression === "today") {
      bindings[name] = { source: "run_date" };
    } else if (descriptor.default_expression === "yesterday") {
      bindings[name] = { source: "relative_date", offset_days: -1 };
    } else if (descriptor.default !== null && descriptor.default !== undefined) {
      bindings[name] = { source: "literal", value: descriptor.default };
    }
  }
  return bindings;
}

export function bindingsUseWindow(bindings: Record<string, ScheduleParameterBinding>): boolean {
  return Object.values(bindings).some(
    (binding) => binding.source === "window_start" || binding.source === "window_end",
  );
}

export function scheduleBindingsComplete(
  paramSchema: Record<string, ParamDescriptor>,
  bindings: Record<string, ScheduleParameterBinding>,
  window: ScheduleWindow | null | undefined,
): boolean {
  const parameterNames = Object.keys(paramSchema);
  if (parameterNames.some((name) => !bindings[name])) return false;
  if (Object.keys(bindings).some((name) => !paramSchema[name])) return false;
  if (bindingsUseWindow(bindings) && !window) return false;

  return parameterNames.every((name) => {
    const binding = bindings[name];
    const descriptor = paramSchema[name];
    if (binding.source === "null") return !descriptor.required;
    if (binding.source === "literal") {
      if (binding.value === null || binding.value === undefined) return false;
      if (descriptor.type !== "string" && binding.value === "") return false;
    }
    if (binding.source === "relative_date" && binding.offset_days == null) return false;
    return true;
  });
}
