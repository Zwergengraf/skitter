export const THEME_STORAGE_KEY = "theme";

export type AdminThemeId = "light" | "dark" | "catppuccin-mocha";

interface AdminThemeOption {
  id: AdminThemeId;
  label: string;
  description: string;
  appearance: "light" | "dark";
}

export const ADMIN_THEMES: readonly AdminThemeOption[] = [
  {
    id: "light",
    label: "Solar Dune",
    description: "Warm parchment panels with copper telemetry accents.",
    appearance: "light",
  },
  {
    id: "dark",
    label: "Night Shift",
    description: "A moody control-room palette with electric depth.",
    appearance: "dark",
  },
  {
    id: "catppuccin-mocha",
    label: "Catppuccin Mocha",
    description: "Pastel midnight surfaces inspired by the official Mocha flavor.",
    appearance: "dark",
  },
];

const DEFAULT_THEME: AdminThemeId = "dark";

const isAdminThemeId = (value: string | null): value is AdminThemeId =>
  ADMIN_THEMES.some((theme) => theme.id === value);

export const getStoredTheme = (): AdminThemeId => {
  try {
    const storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    return isAdminThemeId(storedTheme) ? storedTheme : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
};

export const getThemeOption = (themeId: AdminThemeId): AdminThemeOption =>
  ADMIN_THEMES.find((theme) => theme.id === themeId) ?? ADMIN_THEMES[1];

export const isDarkTheme = (themeId: AdminThemeId): boolean =>
  getThemeOption(themeId).appearance === "dark";

export const applyTheme = (themeId: AdminThemeId): void => {
  const root = document.documentElement;
  root.dataset.theme = themeId;
  root.classList.toggle("dark", isDarkTheme(themeId));
  root.style.colorScheme = isDarkTheme(themeId) ? "dark" : "light";

  try {
    localStorage.setItem(THEME_STORAGE_KEY, themeId);
  } catch {
    // Ignore storage failures and keep the in-memory theme.
  }
};

export const initializeTheme = (): AdminThemeId => {
  const themeId = getStoredTheme();
  applyTheme(themeId);
  return themeId;
};
