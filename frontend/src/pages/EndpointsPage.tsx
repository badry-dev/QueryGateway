import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DeleteConfirmDialog } from "@/components/ui/delete-confirm-dialog";
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
import { Textarea } from "@/components/ui/textarea";
import { EndpointWizard } from "@/components/endpoints/EndpointWizard";
import { endpointsApi, getApiError, getPublicApiBaseUrl } from "@/lib/api";
import { queryKeys } from "@/lib/queryClient";
import type { Endpoint, EndpointUpdate } from "@/types/endpoint";

export function EndpointsPage() {
  const qc = useQueryClient();

  const [showWizard, setShowWizard] = useState(false);
  const [editEndpoint, setEditEndpoint] = useState<Endpoint | null>(null);
  const [deleteEndpoint, setDeleteEndpoint] = useState<Endpoint | null>(null);
  const [editForm, setEditForm] = useState<EndpointUpdate>({});
  const [editError, setEditError] = useState("");
  const [deleteError, setDeleteError] = useState("");

  const {
    data: endpoints = [],
    isLoading,
    error: listError,
  } = useQuery({
    queryKey: queryKeys.endpoints.list(false),
    queryFn: () => endpointsApi.list(false),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => endpointsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.endpoints.all });
      setDeleteEndpoint(null);
      setDeleteError("");
    },
    onError: (err) => setDeleteError(getApiError(err)),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: EndpointUpdate }) =>
      endpointsApi.update(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.endpoints.all });
      setEditEndpoint(null);
      setEditError("");
    },
    onError: (err) => setEditError(getApiError(err)),
  });

  const openEdit = (ep: Endpoint) => {
    setEditEndpoint(ep);
    setEditForm({
      name: ep.name,
      description: ep.description ?? "",
      path: ep.path,
      is_active: ep.is_active,
      is_deprecated: ep.is_deprecated,
      deprecation_note: ep.deprecation_note ?? "",
    });
    setEditError("");
  };

  const baseUrl = getPublicApiBaseUrl();

  if (showWizard) {
    return (
      <div className="p-6">
        <h1 className="mb-6 text-2xl font-bold">Create API Endpoint</h1>
        <EndpointWizard
          onSuccess={() => {
            setShowWizard(false);
            qc.invalidateQueries({ queryKey: queryKeys.endpoints.all });
          }}
          onCancel={() => setShowWizard(false)}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">API Endpoints</h1>
          <p className="text-sm text-muted-foreground">
            Manage dynamic REST endpoints backed by Oracle queries.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => qc.invalidateQueries({ queryKey: queryKeys.endpoints.all })}
          >
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Refresh
          </Button>
          <Button size="sm" onClick={() => setShowWizard(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" /> New endpoint
          </Button>
        </div>
      </div>

      {listError && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load endpoints: {getApiError(listError)}
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : endpoints.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="mb-2 text-sm text-muted-foreground">No endpoints created yet.</p>
          <Button size="sm" onClick={() => setShowWizard(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" /> Create your first endpoint
          </Button>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-3 text-left font-medium">Name</th>
                <th className="px-4 py-3 text-left font-medium">Path</th>
                <th className="px-4 py-3 text-left font-medium">Strategy</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {endpoints.map((ep) => (
                <tr key={ep.id} className="border-b last:border-0">
                  <td className="px-4 py-3">
                    <p className="font-medium">{ep.name}</p>
                    {ep.description && (
                      <p className="text-xs text-muted-foreground">{ep.description}</p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                      /api/v1/data/{ep.path}
                    </code>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="outline" className="capitalize">
                      {ep.data_strategy}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      <Badge variant={ep.is_active ? "default" : "secondary"}>
                        {ep.is_active ? "Active" : "Inactive"}
                      </Badge>
                      {ep.is_deprecated && <Badge variant="destructive">Deprecated</Badge>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        title="Copy URL"
                        onClick={() => {
                          navigator.clipboard.writeText(`${baseUrl}/api/v1/data/${ep.path}`);
                        }}
                      >
                        <Copy className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        title="Open in new tab"
                        onClick={() => {
                          window.open(`${baseUrl}/api/v1/data/${ep.path}`, "_blank");
                        }}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => openEdit(ep)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        title="Delete endpoint"
                        onClick={() => {
                          setDeleteEndpoint(ep);
                          setDeleteError("");
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Edit Dialog */}
      <Dialog open={!!editEndpoint} onOpenChange={() => setEditEndpoint(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Endpoint</DialogTitle>
            <DialogDescription>
              Update endpoint settings. SQL and connection cannot be changed after creation.
            </DialogDescription>
          </DialogHeader>
          {editError && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {editError}
            </div>
          )}
          <div className="space-y-3">
            <div>
              <Label>Name</Label>
              <Input
                className="mt-1"
                value={editForm.name ?? ""}
                onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div>
              <Label>Description</Label>
              <Textarea
                className="mt-1"
                value={editForm.description ?? ""}
                onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))}
                rows={2}
              />
            </div>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={editForm.is_active ?? true}
                  onChange={(e) => setEditForm((f) => ({ ...f, is_active: e.target.checked }))}
                />
                Active
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={editForm.is_deprecated ?? false}
                  onChange={(e) => setEditForm((f) => ({ ...f, is_deprecated: e.target.checked }))}
                />
                Deprecated
              </label>
            </div>
            {editForm.is_deprecated && (
              <div>
                <Label>Deprecation Note</Label>
                <Input
                  className="mt-1"
                  value={editForm.deprecation_note ?? ""}
                  onChange={(e) => setEditForm((f) => ({ ...f, deprecation_note: e.target.value }))}
                  placeholder="Sunset date or migration instructions"
                />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditEndpoint(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (editEndpoint) {
                  updateMutation.mutate({ id: editEndpoint.id, payload: editForm });
                }
              }}
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <DeleteConfirmDialog
        open={!!deleteEndpoint}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteEndpoint(null);
            setDeleteError("");
          }
        }}
        title="Delete Endpoint"
        description={
          <>
            This will permanently delete <strong>{deleteEndpoint?.name}</strong>. The URL{" "}
            <code>/api/v1/data/{deleteEndpoint?.path}</code> will stop serving data. Its schedule
            and cached snapshots will also be removed; historical job-run audit records are
            retained.
          </>
        }
        isDeleting={deleteMutation.isPending}
        onConfirm={() => deleteEndpoint && deleteMutation.mutate(deleteEndpoint.id)}
        error={deleteError}
      />
    </div>
  );
}
