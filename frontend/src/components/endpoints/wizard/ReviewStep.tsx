import type { AuthMethod } from "@/types/auth_method";
import type { Connection } from "@/types/connection";

import type { WizardState } from "./types";
import { describeParameterDefault } from "./parameterDefaults";

interface ReviewStepProps {
  state: WizardState;
  connections: Connection[];
  authMethods: AuthMethod[];
}

export function ReviewStep({ state, connections, authMethods }: ReviewStepProps) {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Review & Publish</h3>
      <div className="space-y-3 rounded-lg border p-4">
        <div className="grid grid-cols-2 gap-y-2 text-sm">
          <span className="text-muted-foreground">Name:</span>
          <span className="font-medium">{state.name}</span>
          <span className="text-muted-foreground">Path:</span>
          <span className="font-mono">/api/v1/data/{state.path}</span>
          <span className="text-muted-foreground">Connection:</span>
          <span>{connections.find((c) => c.id === state.connection_id)?.name ?? "—"}</span>
          <span className="text-muted-foreground">Auth:</span>
          <span>
            {state.auth_method_id ? (
              (authMethods.find((a) => a.id === state.auth_method_id)?.name ?? "—")
            ) : (
              <span className="font-medium">Platform admin Bearer</span>
            )}
          </span>
          <span className="text-muted-foreground">Strategy:</span>
          <span className="capitalize">{state.data_strategy}</span>
          <span className="text-muted-foreground">Parameters:</span>
          {Object.keys(state.param_schema).length > 0 ? (
            <span className="space-y-1">
              {Object.entries(state.param_schema).map(([name, descriptor]) => (
                <span key={name} className="block">
                  <code>:{name}</code> — {descriptor.type}; default:{" "}
                  {describeParameterDefault(descriptor)}
                  {state.data_strategy === "snapshot" && descriptor.snapshot_filter && (
                    <>
                      ; snapshot: {descriptor.snapshot_filter.column}{" "}
                      {descriptor.snapshot_filter.operator}
                    </>
                  )}
                </span>
              ))}
            </span>
          ) : (
            <span>None</span>
          )}
        </div>
        <div>
          <p className="mb-1 text-sm text-muted-foreground">SQL:</p>
          <pre className="max-h-32 overflow-auto rounded bg-muted p-2 text-xs">
            {state.sql_text}
          </pre>
        </div>
      </div>
    </div>
  );
}
