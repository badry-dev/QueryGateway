export type ScheduleType = "cron" | "interval";
export type ScheduleBindingSource =
  | "literal"
  | "null"
  | "run_date"
  | "relative_date"
  | "window_start"
  | "window_end";
export type ScheduleWindowPreset =
  | "previous_day"
  | "last_n_complete_days"
  | "week_to_date"
  | "previous_week"
  | "month_to_date"
  | "previous_month";

export interface ScheduleParameterBinding {
  source: ScheduleBindingSource;
  value?: string | number | boolean | null;
  offset_days?: number | null;
}

export interface ScheduleWindow {
  preset: ScheduleWindowPreset;
  days?: number | null;
}

export interface Schedule {
  id: string;
  endpoint_id: string;
  schedule_type: ScheduleType;
  cron_expression: string | null;
  interval_seconds: number | null;
  timezone: string;
  parameter_bindings: Record<string, ScheduleParameterBinding>;
  window: ScheduleWindow | null;
  is_active: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleCreate {
  endpoint_id: string;
  schedule_type: ScheduleType;
  cron_expression?: string;
  interval_seconds?: number;
  timezone?: string;
  parameter_bindings?: Record<string, ScheduleParameterBinding>;
  window?: ScheduleWindow | null;
  is_active?: boolean;
}

export interface ScheduleUpdate {
  schedule_type?: ScheduleType;
  cron_expression?: string;
  interval_seconds?: number;
  timezone?: string;
  parameter_bindings?: Record<string, ScheduleParameterBinding>;
  window?: ScheduleWindow | null;
  is_active?: boolean;
}

export interface JobRun {
  id: string;
  schedule_id: string | null;
  endpoint_id: string | null;
  started_at: string;
  finished_at: string | null;
  status: "running" | "success" | "failed" | "timeout";
  row_count: number | null;
  error_detail: string | null;
  scheduled_for: string | null;
  logical_date: string | null;
  window_start: string | null;
  window_end: string | null;
  resolved_parameters: Record<string, unknown> | null;
  trigger_source: string | null;
  binding_hash: string | null;
  created_at: string;
}

export interface SchedulePreviewRequest {
  endpoint_id: string;
  schedule_type: ScheduleType;
  cron_expression?: string;
  interval_seconds?: number;
  timezone: string;
  parameter_bindings: Record<string, ScheduleParameterBinding>;
  window?: ScheduleWindow | null;
  count?: number;
}

export interface ScheduleRunPreview {
  scheduled_for: string;
  logical_date: string;
  window_start: string | null;
  window_end: string | null;
  resolved_parameters: Record<string, unknown>;
}

export interface SchedulePreviewResponse {
  runs: ScheduleRunPreview[];
}

export interface ScheduleRunRequest {
  logical_date?: string;
}

export interface SnapshotSummary {
  id: string;
  endpoint_id: string;
  job_run_id: string | null;
  row_count: number;
  created_at: string;
}

export interface SnapshotDetail extends SnapshotSummary {
  data: Record<string, unknown>[];
}
