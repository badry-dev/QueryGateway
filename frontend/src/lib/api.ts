import axios from "axios";

import { tokenStorage } from "@/lib/auth";
import type {
  Connection,
  ConnectionCreate,
  ConnectionTestResult,
  ConnectionUpdate,
} from "@/types/connection";
import type {
  ApiKeyIssuedResponse,
  AuthMethod,
  AuthMethodCreate,
  AuthMethodUpdate,
  RotateResponse,
  TokenIssuedResponse,
} from "@/types/auth_method";
import type {
  Endpoint,
  EndpointCreate,
  EndpointUpdate,
  SqlPreviewRequest,
  SqlPreviewResponse,
} from "@/types/endpoint";
import type {
  JobRun,
  Schedule,
  ScheduleCreate,
  SchedulePreviewRequest,
  SchedulePreviewResponse,
  ScheduleRunRequest,
  ScheduleUpdate,
  SnapshotSummary,
} from "@/types/schedule";
import type { HealthDashboard, Setting, SettingBulkUpdate } from "@/types/setting";

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();

export const apiBaseUrl =
  configuredApiBaseUrl && configuredApiBaseUrl !== "/"
    ? configuredApiBaseUrl.replace(/\/+$/, "")
    : "";

export function getPublicApiBaseUrl(): string {
  if (apiBaseUrl) return apiBaseUrl;
  if (typeof window !== "undefined") return window.location.origin;
  return "";
}

// Exported for tests so they can install axios-mock-adapter on the same
// instance the production code uses (and exercise the interceptors).
export const http = axios.create({
  baseURL: apiBaseUrl,
  headers: { "Content-Type": "application/json" },
});

// Attach the admin bearer token (if present) to every outgoing request.
http.interceptors.request.use((config) => {
  const token = tokenStorage.read();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

// On 401 from any admin endpoint, clear the stored token and bounce to
// /login. Skips the login route itself so a wrong-password response
// doesn't bury the user in a redirect loop. The current pathname +
// search + hash are passed via ?from=<encoded> so LoginPage can return
// the user to where they were after re-authenticating (the React Router
// guard uses state.from, but a hard navigation can't carry state).
http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      const url = error.config?.url ?? "";
      // Exact match (relative path) or absolute (with baseURL) — never
      // a substring match, so a hypothetical /api/v1/auth/login-history
      // wouldn't accidentally bypass the redirect.
      const isLoginCall = url === "/api/v1/auth/login" || url.endsWith("/api/v1/auth/login");
      if (!isLoginCall) {
        tokenStorage.clear();
        if (typeof window !== "undefined" && window.location.pathname !== "/login") {
          const from = `${window.location.pathname}${window.location.search}${window.location.hash}`;
          const loginUrl = `/login?from=${encodeURIComponent(from)}`;
          window.location.assign(loginUrl);
        }
      }
    }
    return Promise.reject(error);
  },
);

// ── Auth ──────────────────────────────────────────────────────────────────

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
}

export interface MeResponse {
  username: string;
}

export const authApi = {
  login: (username: string, password: string): Promise<LoginResponse> =>
    http.post<LoginResponse>("/api/v1/auth/login", { username, password }).then((r) => r.data),

  me: (): Promise<MeResponse> => http.get<MeResponse>("/api/v1/auth/me").then((r) => r.data),
};

// ── Connections ────────────────────────────────────────────────────────────

export const connectionsApi = {
  list: (activeOnly = false): Promise<Connection[]> =>
    http
      .get<Connection[]>("/api/v1/admin/connections/", {
        params: { active_only: activeOnly },
      })
      .then((r) => r.data),

  get: (id: string): Promise<Connection> =>
    http.get<Connection>(`/api/v1/admin/connections/${id}`).then((r) => r.data),

  create: (payload: ConnectionCreate): Promise<Connection> =>
    http.post<Connection>("/api/v1/admin/connections/", payload).then((r) => r.data),

  update: (id: string, payload: ConnectionUpdate): Promise<Connection> =>
    http.put<Connection>(`/api/v1/admin/connections/${id}`, payload).then((r) => r.data),

  delete: (id: string): Promise<void> =>
    http.delete(`/api/v1/admin/connections/${id}`).then(() => undefined),

  test: (id: string): Promise<ConnectionTestResult> =>
    http.post<ConnectionTestResult>(`/api/v1/admin/connections/${id}/test`).then((r) => r.data),
};

// ── Auth Methods ───────────────────────────────────────────────────────────

export const authMethodsApi = {
  list: (activeOnly = false): Promise<AuthMethod[]> =>
    http
      .get<AuthMethod[]>("/api/v1/admin/auth/", { params: { active_only: activeOnly } })
      .then((r) => r.data),

  get: (id: string): Promise<AuthMethod> =>
    http.get<AuthMethod>(`/api/v1/admin/auth/${id}`).then((r) => r.data),

  create: (payload: AuthMethodCreate): Promise<AuthMethod> =>
    http.post<AuthMethod>("/api/v1/admin/auth/", payload).then((r) => r.data),

  createWithKey: (payload: AuthMethodCreate): Promise<ApiKeyIssuedResponse> =>
    http.post<ApiKeyIssuedResponse>("/api/v1/admin/auth/with-key", payload).then((r) => r.data),

  update: (id: string, payload: AuthMethodUpdate): Promise<AuthMethod> =>
    http.put<AuthMethod>(`/api/v1/admin/auth/${id}`, payload).then((r) => r.data),

  delete: (id: string): Promise<void> =>
    http.delete(`/api/v1/admin/auth/${id}`).then(() => undefined),

  issueToken: (id: string): Promise<TokenIssuedResponse> =>
    http.post<TokenIssuedResponse>(`/api/v1/admin/auth/${id}/issue-token`).then((r) => r.data),

  rotate: (id: string): Promise<RotateResponse | ApiKeyIssuedResponse> =>
    http
      .post<RotateResponse | ApiKeyIssuedResponse>(`/api/v1/admin/auth/${id}/rotate`)
      .then((r) => r.data),
};

// ── Endpoints ─────────────────────────────────────────────────────────────

export const endpointsApi = {
  list: (activeOnly = false): Promise<Endpoint[]> =>
    http
      .get<Endpoint[]>("/api/v1/admin/endpoints/", { params: { active_only: activeOnly } })
      .then((r) => r.data),

  get: (id: string): Promise<Endpoint> =>
    http.get<Endpoint>(`/api/v1/admin/endpoints/${id}`).then((r) => r.data),

  create: (payload: EndpointCreate): Promise<Endpoint> =>
    http.post<Endpoint>("/api/v1/admin/endpoints/", payload).then((r) => r.data),

  update: (id: string, payload: EndpointUpdate): Promise<Endpoint> =>
    http.put<Endpoint>(`/api/v1/admin/endpoints/${id}`, payload).then((r) => r.data),

  delete: (id: string): Promise<void> =>
    http.delete(`/api/v1/admin/endpoints/${id}`).then(() => undefined),

  preview: (payload: SqlPreviewRequest): Promise<SqlPreviewResponse> =>
    http.post<SqlPreviewResponse>("/api/v1/admin/endpoints/preview", payload).then((r) => r.data),
};

// ── Schedules ─────────────────────────────────────────────────────────────

export const schedulesApi = {
  list: (activeOnly = false): Promise<Schedule[]> =>
    http
      .get<Schedule[]>("/api/v1/admin/schedules/", { params: { active_only: activeOnly } })
      .then((r) => r.data),

  get: (id: string): Promise<Schedule> =>
    http.get<Schedule>(`/api/v1/admin/schedules/${id}`).then((r) => r.data),

  create: (payload: ScheduleCreate): Promise<Schedule> =>
    http.post<Schedule>("/api/v1/admin/schedules/", payload).then((r) => r.data),

  preview: (payload: SchedulePreviewRequest): Promise<SchedulePreviewResponse> =>
    http
      .post<SchedulePreviewResponse>("/api/v1/admin/schedules/preview", payload)
      .then((r) => r.data),

  update: (id: string, payload: ScheduleUpdate): Promise<Schedule> =>
    http.put<Schedule>(`/api/v1/admin/schedules/${id}`, payload).then((r) => r.data),

  delete: (id: string): Promise<void> =>
    http.delete(`/api/v1/admin/schedules/${id}`).then(() => undefined),

  runNow: (id: string, payload?: ScheduleRunRequest): Promise<{ status: string }> =>
    http.post<{ status: string }>(`/api/v1/admin/schedules/${id}/run`, payload).then((r) => r.data),

  pause: (id: string): Promise<Schedule> =>
    http.post<Schedule>(`/api/v1/admin/schedules/${id}/pause`).then((r) => r.data),

  resume: (id: string): Promise<Schedule> =>
    http.post<Schedule>(`/api/v1/admin/schedules/${id}/resume`).then((r) => r.data),

  listJobRuns: (params?: {
    schedule_id?: string;
    endpoint_id?: string;
    limit?: number;
  }): Promise<JobRun[]> =>
    http.get<JobRun[]>("/api/v1/admin/schedules/jobs/", { params }).then((r) => r.data),

  listSnapshots: (endpointId: string, limit = 10): Promise<SnapshotSummary[]> =>
    http
      .get<SnapshotSummary[]>(`/api/v1/admin/schedules/snapshots/${endpointId}`, {
        params: { limit },
      })
      .then((r) => r.data),
};

// ── Settings ──────────────────────────────────────────────────────────────

export const settingsApi = {
  list: (): Promise<Setting[]> =>
    http.get<Setting[]>("/api/v1/admin/settings/").then((r) => r.data),

  get: (key: string): Promise<Setting> =>
    http.get<Setting>(`/api/v1/admin/settings/${key}`).then((r) => r.data),

  update: (key: string, value: string): Promise<Setting> =>
    http.put<Setting>(`/api/v1/admin/settings/${key}`, { value }).then((r) => r.data),

  bulkUpdate: (payload: SettingBulkUpdate): Promise<Setting[]> =>
    http.put<Setting[]>("/api/v1/admin/settings/", payload).then((r) => r.data),

  restartKeys: (): Promise<string[]> =>
    http.get<string[]>("/api/v1/admin/settings/restart-keys").then((r) => r.data),
};

// ── Health ────────────────────────────────────────────────────────────────

export const healthApi = {
  live: (): Promise<{ status: string }> =>
    http.get<{ status: string }>("/api/v1/admin/health/live").then((r) => r.data),

  ready: (): Promise<{ status: string; checks: Record<string, string> }> =>
    http
      .get<{ status: string; checks: Record<string, string> }>("/api/v1/admin/health/ready")
      .then((r) => r.data),

  dashboard: (): Promise<HealthDashboard> =>
    http.get<HealthDashboard>("/api/v1/admin/health/dashboard").then((r) => r.data),
};

// ── Error helpers ──────────────────────────────────────────────────────────

export function getApiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join("; ");
    }
    return error.message;
  }
  return String(error);
}
