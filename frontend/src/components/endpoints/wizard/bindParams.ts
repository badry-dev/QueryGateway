import type { ParamDescriptor } from "@/types/endpoint";

const BIND_PARAM_RE = /:([A-Za-z_]\w*)/g;
const SINGLE_QUOTED_STRING_RE = /'[^']*'/g;

/**
 * Detect named Oracle bind parameters using the same rules as the backend.
 * Matches inside single-quoted string literals are intentionally ignored.
 */
export function extractBindParams(sql: string): string[] {
  const cleaned = sql.replace(SINGLE_QUOTED_STRING_RE, "");
  const names = Array.from(cleaned.matchAll(BIND_PARAM_RE), (match) => match[1]);
  return [...new Set(names)];
}

/** Keep configured descriptors for existing binds and add/remove entries as SQL changes. */
export function reconcileParamSchema(
  sql: string,
  current: Record<string, ParamDescriptor>,
): Record<string, ParamDescriptor> {
  return Object.fromEntries(
    extractBindParams(sql).map((name) => [
      name,
      current[name] ?? {
        type: "string",
        required: true,
        default: null,
      },
    ]),
  );
}
