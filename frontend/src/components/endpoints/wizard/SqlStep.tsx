import { Button } from "@/components/ui/button";
import { SqlEditor } from "@/components/endpoints/SqlEditor";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { SqlPreviewResponse } from "@/types/endpoint";

import type { WizardState, WizardUpdate } from "./types";

interface SqlStepProps {
  state: WizardState;
  update: WizardUpdate;
  preview: SqlPreviewResponse | null;
  previewParams: Record<string, string>;
  isPreviewing: boolean;
  onPreview: () => void;
  onUpdatePreviewParam: (name: string, value: string) => void;
}

export function SqlStep({
  state,
  update,
  preview,
  previewParams,
  isPreviewing,
  onPreview,
  onUpdatePreviewParam,
}: SqlStepProps) {
  const bindParams = Object.entries(state.param_schema);
  const hasPreviewValues = bindParams.every(([name, descriptor]) => {
    const value = previewParams[name];
    return value !== undefined && value.trim().length > 0
      ? true
      : descriptor.default_is_null === true || descriptor.default != null;
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
              Enter a sample value for each bind parameter. These values are used only for this
              preview and are not saved as endpoint defaults.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {bindParams.map(([name, descriptor]) => (
              <div key={name}>
                <Label htmlFor={`preview-param-${name}`} className="text-xs">
                  :{name}
                </Label>
                <Input
                  id={`preview-param-${name}`}
                  className="mt-1 h-8 text-sm"
                  value={
                    previewParams[name] ??
                    (descriptor.default != null ? String(descriptor.default) : "")
                  }
                  onChange={(event) => onUpdatePreviewParam(name, event.target.value)}
                  placeholder="Sample value"
                />
              </div>
            ))}
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
