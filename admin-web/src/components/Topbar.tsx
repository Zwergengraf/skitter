import { Bell, Moon, Search, Sun } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

interface TopbarProps {
  isDark: boolean;
  onToggleTheme: (value: boolean) => void;
}

export function Topbar({ isDark, onToggleTheme }: TopbarProps) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <h2 className="text-3xl font-semibold">Skittermander Ops</h2>
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
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-mutedForeground" />
          <Input className="w-[220px] pl-9" placeholder="Search sessions" />
        </div>
        <Button variant="outline" size="icon">
          <Bell className="h-4 w-4" />
        </Button>
        <Avatar>
          <AvatarFallback>GM</AvatarFallback>
        </Avatar>
      </div>
    </div>
  );
}
