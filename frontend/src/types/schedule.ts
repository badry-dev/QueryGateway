export type ScheduleType = "cron" | "interval";

export interface Schedule {
  id: string;
  endpoint_id: string;
  schedule_type: ScheduleType;
  cron_expression: string | null;
  interval_seconds: number | null;
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
  is_active?: boolean;
}

export interface ScheduleUpdate {
  schedule_type?: ScheduleType;
  cron_expression?: string;
  interval_seconds?: number;
  is_active?: boolean;
}

export interface JobRun {
  id: string;
  schedule_id: string | null;
  endpoint_id: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "success" | "failed" | "timeout";
  row_count: number | null;
  error_detail: string | null;
  created_at: string;
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
