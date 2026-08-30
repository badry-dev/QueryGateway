/**
 * Five-step wizard for authoring a new API endpoint.
 *
 * The wizard owns shared state (form values, server preview result,
 * step index, error message) and the data-fetching for connections /
 * auth methods. Each step's UI lives in its own file under
 * ``./wizard/`` — this module is the shell that decides which step is
 * visible and renders the indicator + nav buttons.
 */

import { useCallback, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { authMethodsApi, connectionsApi, endpointsApi, getApiError } from "@/lib/api";
import { queryKeys } from "@/lib/queryClient";
import type { EndpointCreate, ParamDescriptor, SqlPreviewResponse } from "@/types/endpoint";

import { ConfigStep } from "./wizard/ConfigStep";
import { ConnectionStep } from "./wizard/ConnectionStep";
import { ParamsStep } from "./wizard/ParamsStep";
import { ReviewStep } from "./wizard/ReviewStep";
import { SqlStep } from "./wizard/SqlStep";
import { extractBindParams, reconcileParamSchema } from "./wizard/bindParams";
import {
  INITIAL_WIZARD_STATE,
  WIZARD_STEPS,
  type WizardState,
  type WizardStepName,
} from "./wizard/types";

interface EndpointWizardProps {
  onSuccess: () => void;
  onCancel: () => void;
}

export function EndpointWizard({ onSuccess, onCancel }: EndpointWizardProps) {
  const [step, setStep] = useState(0);
  const [state, setState] = useState<WizardState>(INITIAL_WIZARD_STATE);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<SqlPreviewResponse | null>(null);
  const [previewParams, setPreviewParams] = useState<Record<string, string>>({});

  const { data: connections = [] } = useQuery({
    queryKey: queryKeys.connections.list(true),
    queryFn: () => connectionsApi.list(true),
  });

  const { data: authMethods = [] } = useQuery({
    queryKey: queryKeys.authMethods.list(true),
    queryFn: () => authMethodsApi.list(true),
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      endpointsApi.preview({
        connection_id: state.connection_id,
        sql_text: state.sql_text,
        params: Object.fromEntries(
          Object.entries(state.param_schema).map(([name, descriptor]) => [
            name,
            previewParams[name] ?? descriptor.default ?? "",
          ]),
        ),
        max_rows: 10,
      }),
    onSuccess: (data) => {
      setPreview(data);
      // Auto-populate param_schema from detected bind params, preserving
      // any descriptors the user already configured for the same names.
      // Read from the *current* state inside the updater rather than the
      // closure-captured ``state`` — otherwise edits made while the
      // preview request is in-flight get clobbered when the response
      // lands.
      setState((s) => {
        const newSchema: Record<string, ParamDescriptor> = {};
        for (const p of data.bind_params) {
          newSchema[p] = s.param_schema[p] ?? {
            type: "string",
            required: true,
            default: null,
          };
        }
        return { ...s, param_schema: newSchema };
      });
      setError("");
    },
    onError: (err) => setError(getApiError(err)),
  });

  const createMutation = useMutation({
    mutationFn: (payload: EndpointCreate) => endpointsApi.create(payload),
    onSuccess: () => onSuccess(),
    onError: (err) => setError(getApiError(err)),
  });

  const update = useCallback((patch: Partial<WizardState>) => {
    if (patch.sql_text !== undefined) {
      const bindParams = extractBindParams(patch.sql_text);

      setState((s) => ({
        ...s,
        ...patch,
        param_schema: reconcileParamSchema(patch.sql_text ?? "", s.param_schema),
      }));
      setPreviewParams((current) =>
        Object.fromEntries(
          bindParams
            .filter((name) => current[name] !== undefined)
            .map((name) => [name, current[name]]),
        ),
      );
      setPreview(null);
      return;
    }

    if (patch.connection_id !== undefined) setPreview(null);
    setState((s) => ({ ...s, ...patch }));
  }, []);

  const updateParam = useCallback((name: string, field: keyof ParamDescriptor, value: unknown) => {
    setState((s) => ({
      ...s,
      param_schema: {
        ...s.param_schema,
        [name]: { ...s.param_schema[name], [field]: value },
      },
    }));
  }, []);

  const canNext = (): boolean => {
    if (step === 0) return !!state.connection_id;
    if (step === 1) return !!state.sql_text.trim();
    if (step === 3) {
      // A public endpoint (no auth method) requires an explicit opt-in,
      // mirroring the server-side 422 so the admin can't reach Review with
      // an invalid configuration.
      const authOk = !!state.auth_method_id || state.allow_unauthenticated;
      return !!state.name.trim() && !!state.path.trim() && authOk;
    }
    return true;
  };

  const handleSubmit = () => {
    setError("");
    const payload: EndpointCreate = {
      name: state.name,
      description: state.description || undefined,
      path: state.path,
      connection_id: state.connection_id,
      sql_text: state.sql_text,
      param_schema: state.param_schema,
      column_map: state.column_map,
      auth_method_id: state.auth_method_id || null,
      allow_unauthenticated: state.allow_unauthenticated,
      data_strategy: state.data_strategy,
    };
    createMutation.mutate(payload);
  };

  const currentStep: WizardStepName = WIZARD_STEPS[step];

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Step indicator */}
      <div className="flex items-center gap-1">
        {WIZARD_STEPS.map((s, i) => (
          <div key={s} className="flex items-center gap-1">
            <button
              onClick={() => i < step && setStep(i)}
              disabled={i > step}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                i === step
                  ? "bg-primary text-primary-foreground"
                  : i < step
                    ? "cursor-pointer bg-primary/20 text-primary hover:bg-primary/30"
                    : "bg-muted text-muted-foreground"
              }`}
            >
              {i + 1}. {s}
            </button>
            {i < WIZARD_STEPS.length - 1 && <div className="h-px w-4 bg-border" />}
          </div>
        ))}
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {currentStep === "Connection" && (
        <ConnectionStep state={state} update={update} connections={connections} />
      )}
      {currentStep === "SQL Query" && (
        <SqlStep
          state={state}
          update={update}
          preview={preview}
          previewParams={previewParams}
          isPreviewing={previewMutation.isPending}
          onPreview={() => previewMutation.mutate()}
          onUpdatePreviewParam={(name, value) =>
            setPreviewParams((current) => ({ ...current, [name]: value }))
          }
        />
      )}
      {currentStep === "Parameters" && <ParamsStep state={state} onUpdateParam={updateParam} />}
      {currentStep === "Auth & Config" && (
        <ConfigStep state={state} update={update} authMethods={authMethods} />
      )}
      {currentStep === "Review" && (
        <ReviewStep state={state} connections={connections} authMethods={authMethods} />
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between border-t pt-4">
        <Button variant="outline" onClick={step === 0 ? onCancel : () => setStep(step - 1)}>
          {step === 0 ? "Cancel" : "Back"}
        </Button>
        <div className="flex gap-2">
          {step < WIZARD_STEPS.length - 1 ? (
            <Button onClick={() => setStep(step + 1)} disabled={!canNext()}>
              Next
            </Button>
          ) : (
            <Button onClick={handleSubmit} disabled={createMutation.isPending}>
              {createMutation.isPending ? "Publishing..." : "Publish Endpoint"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
