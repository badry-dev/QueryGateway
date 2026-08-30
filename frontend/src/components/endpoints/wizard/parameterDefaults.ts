import type { ParamDescriptor } from "@/types/endpoint";

export function hasParameterDefault(descriptor: ParamDescriptor): boolean {
  return descriptor.default !== null && descriptor.default !== undefined
    ? true
    : descriptor.default_expression === "today" || descriptor.default_expression === "yesterday";
}

export function missingSnapshotDefaults(
  paramSchema: Record<string, ParamDescriptor>,
): string[] {
  return Object.entries(paramSchema)
    .filter(([, descriptor]) => !hasParameterDefault(descriptor))
    .map(([name]) => name)
    .sort();
}

export function describeParameterDefault(descriptor: ParamDescriptor): string {
  if (descriptor.default_expression === "today") return "Today (server date)";
  if (descriptor.default_expression === "yesterday") return "Yesterday (server date)";
  if (descriptor.default !== null && descriptor.default !== undefined) {
    return String(descriptor.default);
  }
  return "No default";
}
