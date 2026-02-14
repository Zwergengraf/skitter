import { cn } from "@/lib/utils";
import { navItems, type NavItemId } from "./navigation";

interface SidebarProps {
  active: NavItemId;
  onSelect: (id: NavItemId) => void;
}

export function Sidebar({ active, onSelect }: SidebarProps) {
  return (
    <aside className="fixed left-0 top-0 z-20 flex h-screen w-[260px] flex-col gap-8 border-r border-border bg-card/80 px-6 py-8 backdrop-blur">
      <div className="space-y-3">
        <div className="data-chip text-[10px] text-mutedForeground">
          Skitter Admin
        </div>
        <div>
          <h1 className="text-2xl font-semibold">Control Room</h1>
          <p className="text-sm text-mutedForeground">
            Monitor sessions, tools, and automation across every transport.
          </p>
        </div>
      </div>
      <nav className="flex flex-col gap-2">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = active === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelect(item.id)}
              className={cn(
                "flex items-center gap-3 rounded-2xl px-4 py-3 text-left text-sm font-semibold transition-colors",
                isActive
                  ? "bg-primary text-primaryForeground shadow-soft"
                  : "text-foreground hover:bg-muted"
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </button>
          );
        })}
      </nav>
      <div className="mt-auto rounded-2xl border border-border bg-background p-4 text-sm">
        <p className="text-xs uppercase tracking-[0.2em] text-mutedForeground">
          Environment
        </p>
        <div className="mt-2 flex items-center justify-between">
          <span className="font-semibold">Local</span>
          <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">
            Healthy
          </span>
        </div>
      </div>
    </aside>
  );
}
