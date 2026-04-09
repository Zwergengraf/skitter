import type { TableRange } from "@/features/admin/types";

export const rangeStart = (range: TableRange): number | null => {
  const now = new Date();
  if (range === "all") {
    return null;
  }
  if (range === "today") {
    const start = new Date(now);
    start.setHours(0, 0, 0, 0);
    return start.getTime();
  }
  if (range === "week") {
    const start = new Date(now);
    const day = (start.getDay() + 6) % 7;
    start.setDate(start.getDate() - day);
    start.setHours(0, 0, 0, 0);
    return start.getTime();
  }
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  start.setHours(0, 0, 0, 0);
  return start.getTime();
};

export const inRange = (value: string | null | undefined, range: TableRange): boolean => {
  const start = rangeStart(range);
  if (start == null) {
    return true;
  }
  if (!value) {
    return false;
  }
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) {
    return false;
  }
  return ts >= start;
};
