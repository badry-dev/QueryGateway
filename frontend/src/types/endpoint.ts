/** TypeScript interfaces for API endpoint management (Phase 4). */

export type DataStrategy = "live" | "snapshot";
export type DateDefaultExpression = "today" | "yesterday";
export type SnapshotFilterOperator = "eq" | "gte" | "lte";

export interface SnapshotFilter {
  column: string;
  operator: SnapshotFilterOperator;
  null_means_all?: boolean;
}

export interface ParamDescriptor {
  type: "string" | "integer" | "float" | "date" | "boolean";
  required: boolean;
  default?: string | number | boolean | null;
  default_is_null?: boolean;
  default_expression?: DateDefaultExpression | null;
  description?: string;
  snapshot_filter?: SnapshotFilter | null;
}

export interface Endpoint {
  id: string;
  name: string;
  description: string | null;
  path: string;
  connection_id: string;
  sql_text: string;
  param_schema: Record<string, ParamDescriptor>;
  column_map: Record<string, string>;
  auth_method_id: string | null;
  allow_unauthenticated: boolean;
  data_strategy: DataStrategy;
  version: string;
  is_active: boolean;
  is_deprecated: boolean;
  deprecation_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface EndpointCreate {
  name: string;
  description?: string;
  path: string;
  connection_id: string;
  sql_text: string;
  param_schema?: Record<string, ParamDescriptor>;
  column_map?: Record<string, string>;
  auth_method_id?: string | null;
  /** Legacy-named opt-in to platform-admin Bearer fallback when auth_method_id is null. */
  allow_unauthenticated?: boolean;
  data_strategy?: DataStrategy;
  is_active?: boolean;
}

export interface EndpointUpdate {
  name?: string;
  description?: string | null;
  path?: string;
  connection_id?: string;
  sql_text?: string;
  param_schema?: Record<string, ParamDescriptor>;
  column_map?: Record<string, string>;
  auth_method_id?: string | null;
  allow_unauthenticated?: boolean;
  data_strategy?: DataStrategy;
  is_active?: boolean;
  is_deprecated?: boolean;
  deprecation_note?: string | null;
}

export interface SqlPreviewRequest {
  connection_id: string;
  sql_text: string;
  params?: Record<string, string | number | boolean | null>;
  param_schema?: Record<string, ParamDescriptor>;
  max_rows?: number;
}

export interface SqlPreviewResponse {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  bind_params: string[];
  duration_ms: number;
}
