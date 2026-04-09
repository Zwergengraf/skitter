import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type StateMessageProps = {
  children: ReactNode;
  className?: string;
  tone?: "muted" | "danger";
  compact?: boolean;
};

export function StateMessage({ children, className, tone = "muted", compact = false }: StateMessageProps) {
  return (
    <div
      className={cn(
        "rounded-2xl border text-sm",
        compact ? "px-4 py-4" : "px-4 py-6",
        tone === "danger"
          ? "border-danger/40 bg-danger/10 text-danger"
          : "border-dashed border-border bg-muted/40 text-mutedForeground",
        className,
      )}
    >
      {children}
    </div>
  );
}
