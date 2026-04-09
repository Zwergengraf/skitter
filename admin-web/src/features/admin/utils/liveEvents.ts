export const liveEventLevelVariant = (level: string): "secondary" | "warning" | "success" | "danger" => {
  if (level === "error") {
    return "danger";
  }
  if (level === "warning") {
    return "warning";
  }
  if (level === "success") {
    return "success";
  }
  return "secondary";
};

export const liveEventKindLabel = (kind: string): string =>
  kind
    .split(".")
    .map((segment) => segment.replace(/_/g, " "))
    .join(" / ");
