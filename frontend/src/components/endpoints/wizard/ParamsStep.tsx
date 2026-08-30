import type { ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { ParamDescriptor } from "@/types/endpoint";

import type { WizardState } from "./types";

interface ParamsStepProps {
  state: WizardState;
  onUpdateParam: (name: string, field: keyof ParamDescriptor, value: unknown) => void;
}

interface DefaultValueControlProps {
  desc: ParamDescriptor;
  name: string;
  onUpdateParam: (name: string, field: keyof ParamDescriptor, value: unknown) => void;
}

interface ScalarDefaultControlProps extends DefaultValueControlProps {
  children: ReactNode;
}

function ScalarDefaultControl({ desc, name, onUpdateParam, children }: ScalarDefaultControlProps) {
  if (desc.required) return <div className="mt-1">{children}</div>;

  return (
    <div className="mt-1 space-y-1.5">
      <Select
        aria-label={`Default mode for ${name}`}
        className="h-8 px-2 py-1.5"
        value={desc.default_is_null ? "null" : "fixed"}
        onChange={(e) => onUpdateParam(name, "default_is_null", e.target.value === "null")}
      >
        <option value="fixed">Fixed value</option>
        <option value="null">Null</option>
      </Select>
      {desc.default_is_null ? (
        <p className="text-xs text-muted-foreground">Passes SQL NULL when omitted.</p>
      ) : (
        children
      )}
    </div>
  );
}

function DefaultValueControl({ desc, name, onUpdateParam }: DefaultValueControlProps) {
  switch (desc.type) {
    case "boolean":
      return (
        <Select
          aria-label={`Default value for ${name}`}
          className="mt-1 h-8 px-2 py-1.5"
          value={
            desc.default_is_null
              ? "null"
              : desc.default === true
                ? "true"
                : desc.default === false
                  ? "false"
                  : "none"
          }
          onChange={(e) => {
            if (e.target.value === "null") {
              onUpdateParam(name, "default_is_null", true);
            } else if (e.target.value === "none") {
              onUpdateParam(name, "default_is_null", false);
            } else {
              onUpdateParam(name, "default", e.target.value === "true");
            }
          }}
        >
          <option value="none">No default</option>
          {!desc.required && <option value="null">Null</option>}
          <option value="true">True</option>
          <option value="false">False</option>
        </Select>
      );
    case "integer":
      return (
        <ScalarDefaultControl desc={desc} name={name} onUpdateParam={onUpdateParam}>
          <Input
            className="h-8 text-sm"
            type="number"
            value={desc.default != null ? String(desc.default) : ""}
            onChange={(e) => {
              const parsed = parseInt(e.target.value, 10);
              onUpdateParam(name, "default", e.target.value && !isNaN(parsed) ? parsed : null);
            }}
            placeholder="(none)"
          />
        </ScalarDefaultControl>
      );
    case "float":
      return (
        <ScalarDefaultControl desc={desc} name={name} onUpdateParam={onUpdateParam}>
          <Input
            className="h-8 text-sm"
            type="number"
            step="any"
            value={desc.default != null ? String(desc.default) : ""}
            onChange={(e) => {
              const parsed = parseFloat(e.target.value);
              onUpdateParam(name, "default", e.target.value && !isNaN(parsed) ? parsed : null);
            }}
            placeholder="(none)"
          />
        </ScalarDefaultControl>
      );
    case "date":
      return (
        <div className="mt-1 space-y-1.5">
          <Select
            aria-label={`Default mode for ${name}`}
            className="h-8 px-2 py-1.5"
            value={desc.default_is_null ? "null" : (desc.default_expression ?? "fixed")}
            onChange={(e) => {
              const mode = e.target.value;
              if (mode === "null") {
                onUpdateParam(name, "default_is_null", true);
              } else if (mode === "today" || mode === "yesterday") {
                onUpdateParam(name, "default_expression", mode);
              } else if (desc.default_is_null) {
                onUpdateParam(name, "default_is_null", false);
              } else {
                onUpdateParam(name, "default_expression", null);
              }
            }}
          >
            <option value="fixed">Fixed date</option>
            {!desc.required && <option value="null">Null</option>}
            <option value="today">Today</option>
            <option value="yesterday">Yesterday</option>
          </Select>
          {desc.default_is_null ? (
            <p className="text-xs text-muted-foreground">Passes SQL NULL when omitted.</p>
          ) : desc.default_expression == null ? (
            <Input
              aria-label={`Fixed default date for ${name}`}
              className="h-8 text-sm"
              type="date"
              value={desc.default != null ? String(desc.default) : ""}
              onChange={(e) => onUpdateParam(name, "default", e.target.value || null)}
            />
          ) : null}
        </div>
      );
    default:
      return (
        <ScalarDefaultControl desc={desc} name={name} onUpdateParam={onUpdateParam}>
          <Input
            className="h-8 text-sm"
            value={String(desc.default ?? "")}
            onChange={(e) => onUpdateParam(name, "default", e.target.value || null)}
            placeholder="(none)"
          />
        </ScalarDefaultControl>
      );
  }
}

export function ParamsStep({ state, onUpdateParam }: ParamsStepProps) {
  const entries = Object.entries(state.param_schema);

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Configure Parameters</h3>
      <p className="text-sm text-muted-foreground">
        Define types and defaults for bind parameters detected in your query.
      </p>
      {state.data_strategy === "snapshot" && entries.length > 0 && (
        <p className="text-sm text-amber-700">
          Snapshot endpoints require a fixed, NULL, or dynamic default for every parameter. Dynamic
          dates are evaluated from the application server date whenever the snapshot runs.
        </p>
      )}
      {entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No bind parameters detected. You can proceed or go back to modify your query.
        </p>
      ) : (
        <div className="space-y-3">
          {entries.map(([name, desc]) => (
            <div key={name} className="rounded-lg border p-3">
              <p className="mb-2 font-mono text-sm font-medium">:{name}</p>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <Label className="text-xs">Type</Label>
                  <Select
                    className="mt-1 h-8 px-2 py-1.5"
                    value={desc.type}
                    onChange={(e) => onUpdateParam(name, "type", e.target.value)}
                  >
                    <option value="string">String</option>
                    <option value="integer">Integer</option>
                    <option value="float">Float</option>
                    <option value="boolean">Boolean</option>
                    <option value="date">Date</option>
                  </Select>
                </div>
                <div>
                  <Label className="text-xs">Required</Label>
                  <Select
                    className="mt-1 h-8 px-2 py-1.5"
                    value={desc.required ? "true" : "false"}
                    onChange={(e) => onUpdateParam(name, "required", e.target.value === "true")}
                  >
                    <option value="true">Yes</option>
                    <option value="false">No</option>
                  </Select>
                </div>
                <div>
                  <Label className="text-xs">Default</Label>
                  <DefaultValueControl desc={desc} name={name} onUpdateParam={onUpdateParam} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
