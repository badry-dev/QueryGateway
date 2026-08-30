import type { ParamDescriptor } from "@/types/endpoint";

export function hasParameterDefault(descriptor: ParamDescriptor): boolean {
  if (descriptor.default_is_null) return true;
  return descriptor.default !== null && descriptor.default !== undefined
    ? true
    : descriptor.default_expression === "today" || descriptor.default_expression === "yesterday";
}

export function missingSnapshotDefaults(paramSchema: Record<string, ParamDescriptor>): string[] {
  return Object.entries(paramSchema)
    .filter(([, descriptor]) => !hasParameterDefault(descriptor))
    .map(([name]) => name)
    .sort();
}

export function describeParameterDefault(descriptor: ParamDescriptor): string {
  if (descriptor.default_is_null) return "NULL";
  if (descriptor.default_expression === "today") return "Today (server date)";
  if (descriptor.default_expression === "yesterday") return "Yesterday (server date)";
  if (descriptor.default !== null && descriptor.default !== undefined) {
    return String(descriptor.default);
  }
  return "No default";
}

export function updateParameterDescriptor(
  current: ParamDescriptor,
  field: keyof ParamDescriptor,
  value: unknown,
): ParamDescriptor {
  const descriptor: ParamDescriptor = { ...current, [field]: value };

  if (field === "default") {
    if (value !== null && value !== undefined) {
      descriptor.default_expression = null;
      descriptor.default_is_null = false;
    } else if (!descriptor.required) {
      descriptor.default_is_null = true;
    }
  }

  if (field === "default_expression" && value !== null && value !== undefined) {
    descriptor.default = null;
    descriptor.default_is_null = false;
  }

  if (field === "default_is_null") {
    descriptor.default_is_null = value === true;
    if (descriptor.default_is_null) {
      descriptor.required = false;
      descriptor.default = null;
      descriptor.default_expression = null;
    }
  }

  if (field === "required") {
    descriptor.required = value === true;
    if (descriptor.required) {
      descriptor.default_is_null = false;
    } else if (descriptor.default == null && descriptor.default_expression == null) {
      descriptor.default_is_null = true;
    }
  }

  if (field === "type" && value !== "date") {
    descriptor.default_expression = null;
    if (!descriptor.required && descriptor.default == null) {
      descriptor.default_is_null = true;
    }
  }

  return descriptor;
}
