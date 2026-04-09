import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

type ApiKeyDialogProps = {
  open: boolean;
  apiReady: boolean;
  apiBase: string;
  apiKeyDraft: string;
  setApiKeyDraft: (value: string) => void;
  apiKeyDialogError: string | null;
  apiKeySaving: boolean;
  openApiKeyDialog: () => void;
  closeApiKeyDialog: () => void;
  saveAdminApiKey: () => void;
};

export function ApiKeyDialog({
  open,
  apiReady,
  apiBase,
  apiKeyDraft,
  setApiKeyDraft,
  apiKeyDialogError,
  apiKeySaving,
  openApiKeyDialog,
  closeApiKeyDialog,
  saveAdminApiKey,
}: ApiKeyDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          closeApiKeyDialog();
          return;
        }
        openApiKeyDialog();
      }}
    >
      <DialogContent
        onEscapeKeyDown={(event) => {
          if (!apiReady) {
            event.preventDefault();
          }
        }}
        onPointerDownOutside={(event) => {
          if (!apiReady) {
            event.preventDefault();
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>{apiReady ? "Edit admin API key" : "Unlock admin UI"}</DialogTitle>
          <DialogDescription>
            Enter the Skitter admin API key for this browser. We validate it before saving it locally.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-2">
            <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">API base</label>
            <Input value={apiBase} readOnly />
          </div>
          <div className="grid gap-2">
            <label className="text-xs font-semibold uppercase tracking-[0.2em] text-mutedForeground">Admin API key</label>
            <Input
              type="password"
              value={apiKeyDraft}
              onChange={(event) => setApiKeyDraft(event.target.value)}
              placeholder="skitter admin key"
              autoFocus
            />
          </div>
          {apiKeyDialogError ? (
            <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-3 text-sm text-mutedForeground">
              {apiKeyDialogError}
            </div>
          ) : (
            <p className="text-sm text-mutedForeground">
              Stored in this browser using local storage. Avoid using this on shared or untrusted machines.
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-3">
            {apiReady ? (
              <Button variant="outline" onClick={closeApiKeyDialog}>
                Cancel
              </Button>
            ) : null}
            <Button onClick={saveAdminApiKey} disabled={apiKeySaving}>
              {apiKeySaving ? "Checking..." : apiReady ? "Save key" : "Unlock admin UI"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
