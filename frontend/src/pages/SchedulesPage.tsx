import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Plus, RefreshCw, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CronScheduleBuilder } from "@/components/schedules/CronScheduleBuilder";
import { ScheduleParameterBindings } from "@/components/schedules/ScheduleParameterBindings";
import {
  buildCronExpression,
  describeCronExpression,
  INITIAL_CRON_BUILDER,
  isValidCronExpression,
  type CronBuilderValue,
} from "@/components/schedules/cronSchedule";
import {
  bindingsUseWindow,
  scheduleBindingsComplete,
  suggestScheduleBindings,
} from "@/components/schedules/scheduleBindings";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { endpointsApi, getApiError, schedulesApi } from "@/lib/api";
import { queryKeys } from "@/lib/queryClient";
import type { Endpoint } from "@/types/endpoint";
import type { JobRun, Schedule, ScheduleCreate, SchedulePreviewRequest } from "@/types/schedule";

const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const commonTimezones = Array.from(
  new Set([
    "UTC",
    browserTimezone,
    "Asia/Riyadh",
    "Asia/Dubai",
    "Europe/London",
    "America/New_York",
  ]),
);

function initialCreateForm(): ScheduleCreate {
  return {
    endpoint_id: "",
    schedule_type: "interval",
    interval_seconds: 300,
    timezone: browserTimezone,
    parameter_bindings: {},
  };
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function formatDuration(started: string, finished: string | null): string {
  if (!finished) return "running...";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function SchedulesPage() {
  const qc = useQueryClient();

  const [showCreate, setShowCreate] = useState(false);
  const [deleteSchedule, setDeleteSchedule] = useState<Schedule | null>(null);
  const [viewJobsFor, setViewJobsFor] = useState<Schedule | null>(null);
  const [createForm, setCreateForm] = useState<ScheduleCreate>(initialCreateForm);
  const [cronBuilder, setCronBuilder] = useState<CronBuilderValue>(INITIAL_CRON_BUILDER);
  const [createError, setCreateError] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [deleteError, setDeleteError] = useState("");

  const {
    data: schedules = [],
    isLoading,
    error: listError,
  } = useQuery({
    queryKey: queryKeys.schedules.list(false),
    queryFn: () => schedulesApi.list(false),
  });

  const { data: endpoints = [] } = useQuery({
    queryKey: queryKeys.endpoints.list(false),
    queryFn: () => endpointsApi.list(false),
  });

  const { data: jobRuns = [] } = useQuery({
    queryKey: queryKeys.schedules.jobRuns(viewJobsFor?.id),
    queryFn: () => schedulesApi.listJobRuns({ schedule_id: viewJobsFor!.id, limit: 20 }),
    enabled: !!viewJobsFor,
  });

  const endpointMap = new Map<string, Endpoint>(endpoints.map((e) => [e.id, e]));

  const createMutation = useMutation({
    mutationFn: (payload: ScheduleCreate) => schedulesApi.create(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.schedules.all });
      setShowCreate(false);
      setCreateError("");
      setCreateForm(initialCreateForm());
      setCronBuilder(INITIAL_CRON_BUILDER);
      setPreviewError("");
    },
    onError: (err) => setCreateError(getApiError(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => schedulesApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.schedules.all });
      setDeleteSchedule(null);
      setDeleteError("");
    },
    onError: (err) => setDeleteError(getApiError(err)),
  });

  const previewMutation = useMutation({
    mutationFn: (payload: SchedulePreviewRequest) => schedulesApi.preview(payload),
    onSuccess: () => setPreviewError(""),
    onError: (err) => setPreviewError(getApiError(err)),
  });

  const runNowMutation = useMutation({
    mutationFn: (id: string) => schedulesApi.runNow(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.schedules.all });
    },
  });

  const pauseMutation = useMutation({
    mutationFn: (id: string) => schedulesApi.pause(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.schedules.all }),
  });

  const resumeMutation = useMutation({
    mutationFn: (id: string) => schedulesApi.resume(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.schedules.all }),
  });

  // Filter endpoints that don't already have a schedule
  const scheduledEndpointIds = new Set(schedules.map((s) => s.endpoint_id));
  const availableEndpoints = endpoints.filter(
    (e) => e.is_active && e.data_strategy === "snapshot" && !scheduledEndpointIds.has(e.id),
  );
  const selectedEndpoint = endpointMap.get(createForm.endpoint_id);
  const parameterBindings = createForm.parameter_bindings ?? {};
  const bindingsComplete = selectedEndpoint
    ? scheduleBindingsComplete(selectedEndpoint.param_schema, parameterBindings, createForm.window)
    : false;
  const timingComplete =
    createForm.schedule_type === "interval"
      ? (createForm.interval_seconds ?? 0) >= 10
      : isValidCronExpression(createForm.cron_expression ?? "");

  const previewPayload = (): SchedulePreviewRequest => ({
    endpoint_id: createForm.endpoint_id,
    schedule_type: createForm.schedule_type,
    cron_expression: createForm.cron_expression,
    interval_seconds: createForm.interval_seconds,
    timezone: createForm.timezone ?? "UTC",
    parameter_bindings: parameterBindings,
    window: createForm.window,
    count: 3,
  });

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Schedules</h1>
          <p className="text-sm text-muted-foreground">
            Manage scheduled snapshot refresh jobs for your endpoints.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => qc.invalidateQueries({ queryKey: queryKeys.schedules.all })}
          >
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Refresh
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" /> New schedule
          </Button>
        </div>
      </div>

      {listError && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load schedules: {getApiError(listError)}
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : schedules.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="mb-2 text-sm text-muted-foreground">No schedules created yet.</p>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" /> Create your first schedule
          </Button>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-3 text-left font-medium">Endpoint</th>
                <th className="px-4 py-3 text-left font-medium">Type</th>
                <th className="px-4 py-3 text-left font-medium">Config</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
                <th className="px-4 py-3 text-left font-medium">Last Run</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((s) => {
                const ep = endpointMap.get(s.endpoint_id);
                return (
                  <tr key={s.id} className="border-b last:border-0">
                    <td className="px-4 py-3">
                      <p className="font-medium">{ep?.name ?? "Unknown"}</p>
                      {ep && (
                        <code className="text-xs text-muted-foreground">
                          /api/v1/data/{ep.path}
                        </code>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="outline" className="capitalize">
                        {s.schedule_type}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {s.schedule_type === "cron" ? (
                        <div>
                          <p>{describeCronExpression(s.cron_expression)}</p>
                          <code className="text-[11px] text-muted-foreground">
                            {s.cron_expression}
                          </code>
                          <p className="text-[11px] text-muted-foreground">{s.timezone}</p>
                        </div>
                      ) : (
                        `Every ${s.interval_seconds}s`
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={s.is_active ? "default" : "secondary"}>
                        {s.is_active ? "Active" : "Paused"}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {formatDate(s.last_run_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          title="Run now"
                          onClick={() => runNowMutation.mutate(s.id)}
                          disabled={runNowMutation.isPending}
                        >
                          <Play className="h-3.5 w-3.5" />
                        </Button>
                        {s.is_active ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            title="Pause"
                            onClick={() => pauseMutation.mutate(s.id)}
                          >
                            <Pause className="h-3.5 w-3.5" />
                          </Button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            title="Resume"
                            onClick={() => resumeMutation.mutate(s.id)}
                          >
                            <Play className="h-3.5 w-3.5 text-green-600" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          title="View job runs"
                          onClick={() => setViewJobsFor(s)}
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setDeleteError("");
                            setDeleteSchedule(s);
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={showCreate} onOpenChange={() => setShowCreate(false)}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Create Schedule</DialogTitle>
            <DialogDescription>
              Set up a recurring snapshot refresh for an endpoint.
            </DialogDescription>
          </DialogHeader>
          {createError && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {createError}
            </div>
          )}
          <div className="space-y-3">
            <div>
              <Label>Endpoint</Label>
              <Select
                className="mt-1"
                value={createForm.endpoint_id}
                onChange={(e) => {
                  const endpointId = e.target.value;
                  const endpoint = endpointMap.get(endpointId);
                  setCreateForm((form) => ({
                    ...form,
                    endpoint_id: endpointId,
                    parameter_bindings: suggestScheduleBindings(endpoint?.param_schema ?? {}),
                    window: undefined,
                  }));
                  previewMutation.reset();
                  setPreviewError("");
                }}
              >
                <option value="">Select endpoint...</option>
                {availableEndpoints.map((ep) => (
                  <option key={ep.id} value={ep.id}>
                    {ep.name}
                  </option>
                ))}
              </Select>
              <p className="mt-1 text-xs text-muted-foreground">
                Only active snapshot endpoints without an existing schedule are shown.
              </p>
            </div>
            <div>
              <Label htmlFor="schedule-type">Timing method</Label>
              <Select
                id="schedule-type"
                className="mt-1"
                value={createForm.schedule_type}
                onChange={(e) => {
                  const v = e.target.value;
                  setCreateForm((f) => ({
                    ...f,
                    schedule_type: v as "cron" | "interval",
                    cron_expression: v === "cron" ? buildCronExpression(cronBuilder) : undefined,
                    interval_seconds: v === "interval" ? 300 : undefined,
                  }));
                }}
              >
                <option value="interval">Repeat at an interval</option>
                <option value="cron">Calendar schedule</option>
              </Select>
            </div>
            {createForm.schedule_type === "interval" && (
              <div>
                <Label>Interval (seconds)</Label>
                <Input
                  className="mt-1"
                  type="number"
                  min={10}
                  value={createForm.interval_seconds ?? 300}
                  onChange={(e) =>
                    setCreateForm((f) => ({
                      ...f,
                      interval_seconds: parseInt(e.target.value, 10) || 10,
                    }))
                  }
                />
                <p className="mt-1 text-xs text-muted-foreground">Minimum 10 seconds.</p>
              </div>
            )}
            {createForm.schedule_type === "cron" && (
              <CronScheduleBuilder
                value={cronBuilder}
                onChange={(value) => {
                  setCronBuilder(value);
                  setCreateForm((form) => ({
                    ...form,
                    cron_expression: buildCronExpression(value),
                  }));
                }}
              />
            )}
            <div>
              <Label htmlFor="schedule-timezone">Schedule timezone</Label>
              <Select
                id="schedule-timezone"
                className="mt-1"
                value={createForm.timezone ?? "UTC"}
                onChange={(event) => {
                  setCreateForm((form) => ({ ...form, timezone: event.target.value }));
                  previewMutation.reset();
                }}
              >
                {commonTimezones.map((timezone) => (
                  <option key={timezone} value={timezone}>
                    {timezone}
                  </option>
                ))}
              </Select>
              <p className="mt-1 text-xs text-muted-foreground">
                Cron times and logical dates are evaluated in this timezone.
              </p>
            </div>
            {selectedEndpoint && (
              <ScheduleParameterBindings
                paramSchema={selectedEndpoint.param_schema}
                bindings={parameterBindings}
                window={createForm.window}
                onBindingsChange={(bindings) => {
                  setCreateForm((form) => ({
                    ...form,
                    parameter_bindings: bindings,
                    window: bindingsUseWindow(bindings)
                      ? (form.window ?? { preset: "previous_day" })
                      : undefined,
                  }));
                  previewMutation.reset();
                }}
                onWindowChange={(window) => {
                  setCreateForm((form) => ({ ...form, window }));
                  previewMutation.reset();
                }}
              />
            )}
            {previewError && (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {previewError}
              </div>
            )}
            {selectedEndpoint && (
              <div className="space-y-2 rounded-md border p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-medium">Resolved run preview</h4>
                    <p className="text-xs text-muted-foreground">
                      Verify the next three logical dates and bound values before creating.
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => previewMutation.mutate(previewPayload())}
                    disabled={!bindingsComplete || !timingComplete || previewMutation.isPending}
                  >
                    {previewMutation.isPending ? "Resolving..." : "Preview runs"}
                  </Button>
                </div>
                {previewMutation.data && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b">
                          <th className="px-2 py-1.5 text-left">Scheduled for</th>
                          <th className="px-2 py-1.5 text-left">Logical date</th>
                          <th className="px-2 py-1.5 text-left">Resolved parameters</th>
                        </tr>
                      </thead>
                      <tbody>
                        {previewMutation.data.runs.map((run) => (
                          <tr key={run.scheduled_for} className="border-b last:border-0">
                            <td className="px-2 py-1.5">{formatDate(run.scheduled_for)}</td>
                            <td className="px-2 py-1.5">{run.logical_date}</td>
                            <td className="px-2 py-1.5 font-mono">
                              {JSON.stringify(run.resolved_parameters)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createMutation.mutate(createForm)}
              disabled={
                createMutation.isPending ||
                !createForm.endpoint_id ||
                !timingComplete ||
                !bindingsComplete
              }
            >
              {createMutation.isPending ? "Creating..." : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Dialog */}
      <Dialog
        open={!!deleteSchedule}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteSchedule(null);
            setDeleteError("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Schedule</DialogTitle>
            <DialogDescription>
              This will permanently delete the schedule for{" "}
              <strong>
                {endpointMap.get(deleteSchedule?.endpoint_id ?? "")?.name ?? "this endpoint"}
              </strong>
              . Existing snapshots will be preserved.
            </DialogDescription>
          </DialogHeader>
          {deleteError && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {deleteError}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteSchedule(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteSchedule && deleteMutation.mutate(deleteSchedule.id)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Job Runs Dialog */}
      <Dialog open={!!viewJobsFor} onOpenChange={() => setViewJobsFor(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Job Runs</DialogTitle>
            <DialogDescription>
              Execution history for{" "}
              {endpointMap.get(viewJobsFor?.endpoint_id ?? "")?.name ?? "this schedule"}.
            </DialogDescription>
          </DialogHeader>
          {jobRuns.length === 0 ? (
            <p className="text-sm text-muted-foreground">No job runs yet.</p>
          ) : (
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b">
                    <th className="px-2 py-1.5 text-left font-medium">Started</th>
                    <th className="px-2 py-1.5 text-left font-medium">Logical date</th>
                    <th className="px-2 py-1.5 text-left font-medium">Duration</th>
                    <th className="px-2 py-1.5 text-left font-medium">Status</th>
                    <th className="px-2 py-1.5 text-left font-medium">Rows</th>
                    <th className="px-2 py-1.5 text-left font-medium">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {jobRuns.map((jr: JobRun) => (
                    <tr key={jr.id} className="border-b last:border-0">
                      <td className="px-2 py-1.5">{formatDate(jr.started_at)}</td>
                      <td className="px-2 py-1.5">{jr.logical_date ?? "—"}</td>
                      <td className="px-2 py-1.5">
                        {formatDuration(jr.started_at, jr.finished_at)}
                      </td>
                      <td className="px-2 py-1.5">
                        <Badge
                          variant={
                            jr.status === "success"
                              ? "default"
                              : jr.status === "running"
                                ? "outline"
                                : "destructive"
                          }
                          className="text-xs"
                        >
                          {jr.status}
                        </Badge>
                      </td>
                      <td className="px-2 py-1.5">{jr.row_count ?? "—"}</td>
                      <td className="max-w-[200px] truncate px-2 py-1.5 text-muted-foreground">
                        {jr.error_detail ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setViewJobsFor(null)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
