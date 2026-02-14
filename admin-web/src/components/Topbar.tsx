import { Moon, Sun } from "lucide-react";

import { Switch } from "@/components/ui/switch";

interface TopbarProps {
  isDark: boolean;
  onToggleTheme: (value: boolean) => void;
}

export function Topbar({ isDark, onToggleTheme }: TopbarProps) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <h2 className="text-3xl font-semibold">Skitter Ops</h2>
        <p className="text-sm text-mutedForeground">
          Keep the agent fleet aligned, safe, and well-fed.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-semibold text-mutedForeground">
          {isDark ? <Moon className="h-3.5 w-3.5 text-primary" /> : <Sun className="h-3.5 w-3.5 text-amber-500" />}
          <span>{isDark ? "Dark" : "Light"} mode</span>
          <Switch checked={isDark} onCheckedChange={onToggleTheme} />
        </div>
      </div>
    </div>
  );
}
