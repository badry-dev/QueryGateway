import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { ParamDescriptor, SnapshotFilter, SnapshotFilterOperator } from "@/types/endpoint";

interface SnapshotFilterMappingsProps {
  paramSchema: Record<string, ParamDescriptor>;
  onChange: (paramSchema: Record<string, ParamDescriptor>) => void;
  previewColumns?: string[];
}

export function SnapshotFilterMappings({
  paramSchema,
  onChange,
  previewColumns = [],
}: SnapshotFilterMappingsProps) {
  const updateSnapshotFilter = (
    name: string,
    patch: Partial<SnapshotFilter> & { operator?: SnapshotFilterOperator },
  ) => {
    const descriptor = paramSchema[name];
    const current = descriptor.snapshot_filter;
    const next: SnapshotFilter = {
      column: current?.column ?? "",
      operator: current?.operator ?? "eq",
      null_means_all: current?.null_means_all ?? false,
      ...patch,
    };
    if (next.operator !== "eq") next.null_means_all = false;
    onChange({
      ...paramSchema,
      [name]: { ...descriptor, snapshot_filter: next },
    });
  };

  if (Object.keys(paramSchema).length === 0) return null;

  return (
    <section className="space-y-3 rounded-lg border p-4">
      <div>
        <h4 className="font-medium">Snapshot request filters</h4>
        <p className="mt-1 text-sm text-muted-foreground">
          Map every request parameter to a cached output column. These mappings select rows; they do
          not grant tenant access.
        </p>
      </div>
      {Object.entries(paramSchema).map(([name, descriptor]) => {
        const mapping = descriptor.snapshot_filter;
        const columnInputId = `snapshot-column-${name}`;
        const columnListId = `snapshot-columns-${name}`;
        const operatorInputId = `snapshot-operator-${name}`;
        return (
          <div key={name} className="rounded-md bg-muted/40 p-3">
            <p className="mb-2 font-mono text-sm font-medium">:{name}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label htmlFor={columnInputId} className="text-xs">
                  Cached output column *
                </Label>
                <Input
                  id={columnInputId}
                  aria-label={`Snapshot column for ${name}`}
                  list={columnListId}
                  className="mt-1 h-9"
                  value={mapping?.column ?? ""}
                  onChange={(event) => updateSnapshotFilter(name, { column: event.target.value })}
                  placeholder="business_date"
                />
                <datalist id={columnListId}>
                  {previewColumns.map((column) => (
                    <option key={column} value={column} />
                  ))}
                </datalist>
              </div>
              <div>
                <Label htmlFor={operatorInputId} className="text-xs">
                  Request comparison *
                </Label>
                <Select
                  id={operatorInputId}
                  aria-label={`Snapshot operator for ${name}`}
                  className="mt-1 h-9"
                  value={mapping?.operator ?? "eq"}
                  onChange={(event) =>
                    updateSnapshotFilter(name, {
                      operator: event.target.value as SnapshotFilterOperator,
                    })
                  }
                >
                  <option value="eq">Equals</option>
                  <option value="gte">From / minimum</option>
                  <option value="lte">To / maximum</option>
                </Select>
              </div>
            </div>
            {!descriptor.required && (mapping?.operator ?? "eq") === "eq" && (
              <label className="mt-3 flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  aria-label={`Scheduled NULL covers all ${name} values`}
                  checked={mapping?.null_means_all ?? false}
                  onChange={(event) =>
                    updateSnapshotFilter(name, { null_means_all: event.target.checked })
                  }
                />
                Scheduled SQL NULL means this snapshot covers all values.
              </label>
            )}
          </div>
        );
      })}
    </section>
  );
}
