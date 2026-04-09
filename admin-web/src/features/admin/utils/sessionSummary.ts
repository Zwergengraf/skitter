import type { SessionDetail } from "@/lib/types";

export const summaryStatusLabel = (detail: SessionDetail): string => {
  const status = detail.summary_status;
  if (!status) {
    return "Not queued";
  }
  if (status === "completed") {
    return "Completed";
  }
  if (status === "failed") {
    return "Failed";
  }
  if (status === "running") {
    return "In progress";
  }
  if (status === "pending" && detail.summary_attempts && detail.summary_attempts > 0) {
    return "Retry scheduled";
  }
  if (status === "pending") {
    return "Queued";
  }
  return status;
};

export const summaryStatusVariant = (detail: SessionDetail): "secondary" | "warning" | "success" | "danger" => {
  const status = detail.summary_status;
  if (status === "completed") {
    return "success";
  }
  if (status === "failed") {
    return "danger";
  }
  if (status === "pending" || status === "running") {
    return "warning";
  }
  return "secondary";
};

export const summaryStatusHint = (detail: SessionDetail): string => {
  const status = detail.summary_status;
  if (!status) {
    return "No background summary was queued for this session.";
  }
  if (status === "completed") {
    return "The archived session summary was generated and embedded successfully.";
  }
  if (status === "failed") {
    return "Automatic retries stopped after repeated failures.";
  }
  if (status === "running") {
    return "The server is currently generating and indexing the archived session summary.";
  }
  if (detail.summary_attempts && detail.summary_attempts > 0) {
    return "A previous attempt failed; the server will retry automatically.";
  }
  return "The archived session summary is queued for background processing.";
};
