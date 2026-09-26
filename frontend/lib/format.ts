import type { Job, JobStatus, Platform, PlatformStatus, Row } from "@/services/api";

const SETUP_SEEN = "id-matcher:setup-seen";

/** First visit: the keys screen opens first once; afterwards keys are asked for per job. */
export function setupSeen(): boolean {
  try {
    return window.localStorage.getItem(SETUP_SEEN) === "1";
  } catch {
    return false;
  }
}

export function markSetupSeen(): void {
  try {
    window.localStorage.setItem(SETUP_SEEN, "1");
  } catch {
    /* storage unavailable: the screen may show again, nothing else breaks */
  }
}

export function readyCount(platforms: PlatformStatus[]): number {
  return platforms.filter((p) => !p.optional && p.configured).length;
}

export const ACTIVE_STATUSES: JobStatus[] = ["QUEUED", "PROCESSING"];
export const FINISHED_STATUSES: JobStatus[] = ["COMPLETED", "PARTIAL"];

export function isActive(job: Pick<Job, "status">): boolean {
  return ACTIVE_STATUSES.includes(job.status);
}

const LABELS: Record<string, string> = {
  twitch: "Twitch",
  kick: "Kick",
  youtube: "YouTube",
  chzzk: "CHZZK",
  soop: "SOOP",
  steam: "Steam",
  bigo: "Bigo LIVE",
  nimo: "Nimo TV",
  rumble: "Rumble",
  brave: "Brave Search",
};

export function platformLabel(p: Platform | null | undefined): string {
  if (!p) return "—";
  return LABELS[p] ?? p.charAt(0).toUpperCase() + p.slice(1);
}

export function percent(done: number, total: number): number {
  if (!total) return 0;
  return Math.min(100, Math.round((done / total) * 100));
}

export function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return `${Math.round(value)}%`;
}

export function formatScore(value: unknown): string {
  if (typeof value === "number") return `${Math.round(value * 100)}%`;
  if (typeof value === "boolean") return value ? "MATCH" : "no";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  return value === null || value === undefined ? "n/a" : String(value);
}

export type DisplayDecision = "MATCH" | "REVIEW" | "NO_MATCH" | "NOT_FOUND" | "ERROR" | "SKIPPED" | "PENDING";

/** Collapse the internal row status + decision into what the results table shows. */
export function displayDecision(row: Pick<Row, "status" | "decision" | "manual_verdict">): DisplayDecision {
  const s = row.status;
  if (s === "PENDING" || s === "SOURCE_EXISTS") return "PENDING";
  if (["API_ERROR", "RATE_LIMITED", "TEMPORARY_ERROR", "PROCESSING_ERROR"].includes(s)) return "ERROR";
  if (s === "SKIPPED_EMPTY" || s === "PRESERVED") return "SKIPPED";
  if (s === "MATCH") return "MATCH";
  if (row.decision === "REVIEW" && !row.manual_verdict) return "REVIEW";
  if (s === "SOURCE_NOT_FOUND") return "NOT_FOUND";
  return "NO_MATCH";
}

export function jobStatusTone(status: JobStatus): "neutral" | "info" | "success" | "warning" | "danger" {
  switch (status) {
    case "COMPLETED":
      return "success";
    case "PARTIAL":
      return "warning";
    case "FAILED":
      return "danger";
    case "QUEUED":
    case "PROCESSING":
      return "info";
    default:
      return "neutral";
  }
}

export function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
