import type { ReactNode } from "react";

type ProfileMetricCardProps = {
  icon?: ReactNode;
  label: string;
  value: string | number;
  hint: string;
};

export function ProfileMetricCard({ icon, label, value, hint }: ProfileMetricCardProps) {
  return (
    <div className="rounded-2xl border border-border bg-muted/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-mutedForeground">{label}</p>
          <p className="mt-3 text-2xl font-semibold tracking-tight text-foreground">{value}</p>
        </div>
        {icon ? (
          <div className="rounded-2xl border border-border bg-card p-2 text-mutedForeground shadow-sm">{icon}</div>
        ) : null}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-mutedForeground">{hint}</p>
    </div>
  );
}
