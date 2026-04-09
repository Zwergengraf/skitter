export const THEME_STORAGE_KEY = "theme";

export const getStoredTheme = (): "dark" | "light" => {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
};

export const applyTheme = (isDark: boolean): void => {
  document.documentElement.classList.toggle("dark", isDark);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, isDark ? "dark" : "light");
  } catch {
    // Ignore storage failures and keep the in-memory theme.
  }
};

export const initializeTheme = (): boolean => {
  const isDark = getStoredTheme() === "dark";
  document.documentElement.classList.toggle("dark", isDark);
  return isDark;
};
