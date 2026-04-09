import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ADMIN_THEMES, getThemeOption, type AdminThemeId } from "@/lib/theme";

interface TopbarProps {
  theme: AdminThemeId;
  onThemeChange: (value: AdminThemeId) => void;
}

export function Topbar({ theme, onThemeChange }: TopbarProps) {
  const activeTheme = getThemeOption(theme);

  return (
    <div className="topbar-banner">
      <div className="space-y-4">
        <div className="data-chip topbar-banner__chip text-[10px] text-mutedForeground">Ops command deck</div>
        <div>
          <h2 className="text-3xl font-semibold tracking-tight">Skitter Ops</h2>
          <p className="max-w-2xl text-sm text-mutedForeground">
            Keep the agent fleet aligned, safe, and well-fed.
          </p>
        </div>
      </div>
      <div className="theme-picker">
        <div className="flex flex-col gap-2">
          <Select value={theme} onValueChange={(value) => onThemeChange(value as AdminThemeId)}>
            <SelectTrigger className="theme-picker__trigger">
              <SelectValue className="theme-picker__value" placeholder="Choose theme" />
            </SelectTrigger>
            <SelectContent className="theme-picker__content">
              {ADMIN_THEMES.map((option) => (
                <SelectItem key={option.id} value={option.id}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex items-center gap-2 text-sm">
            <span className="theme-swatch h-3.5 w-3.5 shrink-0" data-theme-swatch={theme} />
            <p className="theme-picker__note">{activeTheme.description}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
