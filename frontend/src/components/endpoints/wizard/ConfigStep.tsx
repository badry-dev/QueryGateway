import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { AuthMethod } from "@/types/auth_method";
import type { DataStrategy } from "@/types/endpoint";

import type { WizardState, WizardUpdate } from "./types";
import { missingSnapshotDefaults } from "./parameterDefaults";

interface ConfigStepProps {
  state: WizardState;
  update: WizardUpdate;
  authMethods: AuthMethod[];
}

export function ConfigStep({ state, update, authMethods }: ConfigStepProps) {
  const missingDefaults = missingSnapshotDefaults(state.param_schema);

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Endpoint Configuration</h3>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label>Endpoint Name *</Label>
          <Input
            className="mt-1"
            value={state.name}
            onChange={(e) => update({ name: e.target.value })}
            placeholder="My API Endpoint"
          />
        </div>
        <div>
          <Label>URL Path *</Label>
          <div className="mt-1 flex items-center gap-0">
            <span className="rounded-l-md border border-r-0 bg-muted px-2 py-2 text-sm text-muted-foreground">
              /api/v1/data/
            </span>
            <Input
              className="rounded-l-none"
              value={state.path}
              onChange={(e) => update({ path: e.target.value })}
              placeholder="employees"
            />
          </div>
        </div>
      </div>

      <div>
        <Label>Description</Label>
        <Textarea
          className="mt-1"
          value={state.description}
          onChange={(e) => update({ description: e.target.value })}
          placeholder="What does this endpoint return?"
          rows={2}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label>Authentication</Label>
          <Select
            className="mt-1"
            value={state.auth_method_id}
            onChange={(e) =>
              update({
                auth_method_id: e.target.value,
                // Selecting an auth method clears the public opt-in so a
                // stale "public" flag can't linger on a protected endpoint.
                allow_unauthenticated: e.target.value ? false : state.allow_unauthenticated,
              })
            }
          >
            <option value="">None (public)</option>
            {authMethods.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.method_type})
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label>Data Strategy</Label>
          <Select
            className="mt-1"
            value={state.data_strategy}
            onChange={(e) => update({ data_strategy: e.target.value as DataStrategy })}
          >
            <option value="live">Live (query on each request)</option>
            <option value="snapshot">Snapshot (cached, scheduled refresh)</option>
          </Select>
        </div>
      </div>

      {state.data_strategy === "snapshot" && missingDefaults.length > 0 && (
        <Alert variant="destructive">
          <AlertTitle>Snapshot defaults required</AlertTitle>
          <AlertDescription>
            Add a fixed or dynamic default for {missingDefaults.map((name) => `:${name}`).join(", ")}
            {" "}in the Parameters step. Scheduled snapshots have no request values to bind.
          </AlertDescription>
        </Alert>
      )}

      {!state.auth_method_id && (
        <Alert variant="destructive">
          <AlertTitle>⚠ This endpoint is PUBLIC</AlertTitle>
          <AlertDescription>
            <p className="mb-2">
              With no authentication method attached, anyone who knows the URL can read this
              endpoint&apos;s data without credentials. Attach an auth method above unless this data
              is meant to be public.
            </p>
            <label className="flex items-center gap-2 font-medium">
              <input
                type="checkbox"
                checked={state.allow_unauthenticated}
                onChange={(e) => update({ allow_unauthenticated: e.target.checked })}
              />
              Yes, serve this endpoint publicly without authentication.
            </label>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
