import { cn } from "@/lib/utils";
import type { HealthStatus } from "@/lib/types";

interface StatusPillProps {
  status: HealthStatus;
  label: string;
  detail?: string;
}

export function StatusPill({ status, label, detail }: StatusPillProps) {
  const styles = {
    healthy: "bg-emerald-100 text-emerald-700",
    warning: "bg-amber-100 text-amber-700",
    degraded: "bg-rose-100 text-rose-700",
  };

  return (
    <div className="flex items-center justify-between rounded-2xl border border-border bg-card px-4 py-3">
      <div>
        <p className="text-sm font-semibold">{label}</p>
        {detail ? <p className="text-xs text-mutedForeground">{detail}</p> : null}
      </div>
      <span className={cn("rounded-full px-3 py-1 text-xs font-semibold", styles[status])}>
        {status}
      </span>
    </div>
  );
}
