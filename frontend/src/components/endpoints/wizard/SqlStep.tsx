import { Button } from "@/components/ui/button";
import { SqlEditor } from "@/components/endpoints/SqlEditor";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { ParamDescriptor, SqlPreviewResponse } from "@/types/endpoint";

import { hasParameterDefault, resolvePreviewParameterDefault } from "./parameterDefaults";
import type { WizardState, WizardUpdate } from "./types";

interface SqlStepProps {
  state: WizardState;
  update: WizardUpdate;
  preview: SqlPreviewResponse | null;
  previewParams: Record<string, string>;
  isPreviewing: boolean;
  onPreview: () => void;
  onUpdateParam: (name: string, field: keyof ParamDescriptor, value: unknown) => void;
  onUpdatePreviewParam: (name: string, value: string) => void;
}

export function SqlStep({
  state,
  update,
  preview,
  previewParams,
  isPreviewing,
  onPreview,
  onUpdateParam,
  onUpdatePreviewParam,
}: SqlStepProps) {
  const bindParams = Object.entries(state.param_schema);
  const hasPreviewValues = bindParams.every(([name, descriptor]) => {
    const value = previewParams[name];
    return value !== undefined && value.trim().length > 0 ? true : hasParameterDefault(descriptor);
  });

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Write SQL Query</h3>
      <p className="text-sm text-muted-foreground">
        Use named bind parameters like <code className="rounded bg-muted px-1">:param_name</code>.
        String interpolation is rejected.
      </p>
      <SqlEditor value={state.sql_text} onChange={(v) => update({ sql_text: v })} height="250px" />
      {bindParams.length > 0 && (
        <div className="space-y-3 rounded-lg border p-3">
          <div>
            <h4 className="text-sm font-medium">Preview parameters</h4>
            <p className="text-xs text-muted-foreground">
              Choose the Oracle bind type and enter a sample value for each parameter. Values are
              validated and typed before execution, used only for this preview, and not saved as
              endpoint defaults.
            </p>
          </div>
          <div className="space-y-3">
            {bindParams.map(([name, descriptor]) => {
              const typeInputId = `preview-param-type-${name}`;
              const valueInputId = `preview-param-${name}`;
              const resolvedDefault = resolvePreviewParameterDefault(descriptor);
              const value =
                previewParams[name] ??
                (resolvedDefault !== null && resolvedDefault !== undefined
                  ? String(resolvedDefault)
                  : "");

              return (
                <div key={name} className="rounded-md bg-muted/40 p-3">
                  <p className="mb-2 font-mono text-sm font-medium">:{name}</p>
                  <div className="grid gap-3 sm:grid-cols-[10rem_minmax(0,1fr)]">
                    <div>
                      <Label htmlFor={typeInputId} className="text-xs">
                        Parameter type
                      </Label>
                      <Select
                        id={typeInputId}
                        aria-label={`Preview type for ${name}`}
                        className="mt-1 h-9"
                        value={descriptor.type}
                        onChange={(event) => onUpdateParam(name, "type", event.target.value)}
                      >
                        <option value="string">String</option>
                        <option value="integer">Integer</option>
                        <option value="float">Float</option>
                        <option value="boolean">Boolean</option>
                        <option value="date">Date</option>
                      </Select>
                    </div>
                    <div>
                      <Label htmlFor={valueInputId} className="text-xs">
                        Sample value
                      </Label>
                      {descriptor.type === "boolean" ? (
                        <Select
                          id={valueInputId}
                          aria-label={`:${name}`}
                          className="mt-1 h-9"
                          value={value}
                          onChange={(event) => onUpdatePreviewParam(name, event.target.value)}
                        >
                          <option value="">Select true or false</option>
                          <option value="true">True</option>
                          <option value="false">False</option>
                        </Select>
                      ) : (
                        <Input
                          id={valueInputId}
                          aria-label={`:${name}`}
                          className="mt-1 h-9 text-sm"
                          type={
                            descriptor.type === "date"
                              ? "date"
                              : descriptor.type === "integer" || descriptor.type === "float"
                                ? "number"
                                : "text"
                          }
                          step={descriptor.type === "float" ? "any" : undefined}
                          value={value}
                          onChange={(event) => onUpdatePreviewParam(name, event.target.value)}
                          placeholder="Sample value"
                        />
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <Button
        variant="outline"
        size="sm"
        onClick={onPreview}
        disabled={!state.sql_text.trim() || !hasPreviewValues || isPreviewing}
      >
        {isPreviewing ? "Running..." : "Preview Query"}
      </Button>
      {preview && (
        <div className="space-y-2">
          <p className="text-sm font-medium">
            Preview: {preview.row_count} rows in {preview.duration_ms}ms
          </p>
          {preview.bind_params.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Detected params: {preview.bind_params.join(", ")}
            </p>
          )}
          {preview.rows.length > 0 && (
            <div className="max-h-48 overflow-auto rounded border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/50">
                    {preview.columns.map((col) => (
                      <th key={col} className="px-2 py-1 text-left font-medium">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row, i) => (
                    <tr key={i} className="border-b">
                      {preview.columns.map((col) => (
                        <td key={col} className="px-2 py-1">
                          {String(row[col] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
