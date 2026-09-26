import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useState } from "react";

import Layout from "@/components/Layout";
import PlatformKeys from "@/components/PlatformKeys";
import UploadDropzone from "@/components/UploadDropzone";
import { Alert, Badge, Button, Card } from "@/components/ui";
import { jobStatusTone, percent, platformLabel } from "@/lib/format";
import { api, type Job, type Platform, type PlatformStatus } from "@/services/api";

function PlatformPicker({
  title,
  options,
  selected,
  onPick,
  keys,
}: {
  title: string;
  options: Platform[];
  selected: Platform[];
  onPick: (p: Platform) => void;
  keys: PlatformStatus[];
}) {
  return (
    <div>
      <div className="mb-2 text-sm font-medium">{title}</div>
      <div className="flex flex-wrap gap-2">
        {options.map((p) => {
          const info = keys.find((k) => k.id === p);
          const ok = info?.configured ?? false;
          return (
            <Button
              key={p}
              variant={selected.includes(p) ? "primary" : "secondary"}
              aria-pressed={selected.includes(p)}
              onClick={() => onPick(p)}
            >
              {platformLabel(p)}
              {!ok && (
                <span className="text-xs font-normal opacity-80">{info?.keyless ? "(off)" : "(no API key)"}</span>
              )}
            </Button>
          );
        })}
      </div>
    </div>
  );
}

export default function Home() {
  const router = useRouter();
  const [job, setJob] = useState<Job | null>(null);
  const [choice, setChoice] = useState<Platform | null>(null);
  const [targets, setTargets] = useState<Platform[]>([]);
  const [keys, setKeys] = useState<PlatformStatus[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<Job[]>([]);

  useEffect(() => {
    api
      .listJobs()
      .then(setRecent)
      .catch(() => setRecent([]));
    api
      .platforms()
      .then(setKeys)
      .catch(() => setKeys([]));
  }, []);

  const pickSource = (p: Platform) => {
    setChoice(p);
    const others = (job?.platforms ?? []).filter((x) => x !== p);
    setTargets((ts) => {
      const kept = ts.filter((t) => t !== p);
      return kept.length ? kept : others;
    });
  };
  const searchable = keys.filter((k) => !k.optional && k.id !== choice).map((k) => k.id);
  const toggleTarget = (p: Platform) =>
    setTargets((ts) => (ts.includes(p) ? ts.filter((t) => t !== p) : [...ts, p]));
  const missingKeys = [choice, ...targets].filter((p): p is Platform => !!p && !keys.find((k) => k.id === p)?.configured);

  const onFile = async (file: File) => {
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const created = await api.upload(file);
      setJob(created);
      setChoice(created.detected_platform);
      const others = created.platforms.filter((p) => p !== created.detected_platform);
      setTargets(created.detected_platform ? others : []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      await api.start(job.id, choice, targets);
      await router.push(`/jobs/${job.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <Layout>
      <Card className="p-6">
        <h1 className="text-lg font-semibold">Upload a streamer workbook</h1>
        <p className="mb-4 mt-1 text-sm text-zinc-500">
          The processed workbook keeps your exact rows, columns and formatting. Only the destination ID and remarks
          cells are filled in, plus one channel-link column per platform.
        </p>
        <UploadDropzone onFile={onFile} disabled={busy} />
        {busy && !job && <p className="mt-3 text-sm text-zinc-500">Validating workbook…</p>}
        {error && (
          <div className="mt-4">
            <Alert tone="danger" title="Upload problem">
              {error}
            </Alert>
          </div>
        )}

        {job && (
          <div className="mt-6 space-y-4 rounded-lg border border-zinc-200 p-4" data-testid="upload-summary">
            <div className="grid gap-4 sm:grid-cols-4">
              <div>
                <div className="text-xs uppercase text-zinc-500">File</div>
                <div className="font-medium">{job.filename}</div>
              </div>
              <div>
                <div className="text-xs uppercase text-zinc-500">Detected platform</div>
                <div className="font-semibold">
                  {job.detected_platform ? platformLabel(job.detected_platform).toUpperCase() : "Choose below"}
                </div>
              </div>
              <div>
                <div className="text-xs uppercase text-zinc-500">Rows</div>
                <div className="font-semibold tabular-nums">{job.total_rows}</div>
              </div>
              <div>
                <div className="text-xs uppercase text-zinc-500">Sheet</div>
                <div className="font-medium">
                  {job.sheet_name} (header row {job.header_row})
                </div>
              </div>
            </div>
            {job.detection_note && <p className="text-sm text-zinc-600">{job.detection_note}</p>}
            {job.warnings_json && job.warnings_json.length > 0 && (
              <Alert tone="warning" title="Warnings">
                <ul className="list-disc pl-5">
                  {job.warnings_json.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </Alert>
            )}
            <PlatformPicker
              title="Source: the platform your sheet's IDs come from"
              options={job.platforms}
              selected={choice ? [choice] : []}
              onPick={pickSource}
              keys={keys}
            />
            <PlatformPicker
              title="Search on: pick one or more platforms (a missing id_<platform> column is added to the output)"
              options={searchable}
              selected={targets}
              onPick={toggleTarget}
              keys={keys}
            />
            {missingKeys.length > 0 && (
              <div className="space-y-3" data-testid="missing-keys">
                <Alert tone="warning" title={`Connect ${missingKeys.map(platformLabel).join(", ")} to start`}>
                  These platforms are part of this job but have no key yet. Follow the guide next to each one,
                  paste your key below, and Start unlocks once they&apos;re all connected.
                </Alert>
                {keys
                  .filter((k) => missingKeys.includes(k.id))
                  .map((k) => (
                    <PlatformKeys
                      key={k.id}
                      status={k}
                      onChange={(s) => setKeys((ks) => ks.map((x) => (x.id === s.id ? s : x)))}
                    />
                  ))}
              </div>
            )}
            <Button variant="primary" onClick={start} disabled={busy || !choice || targets.length === 0 || missingKeys.length > 0}>
              Start Processing
            </Button>
          </div>
        )}
      </Card>

      <Card>
        <div className="border-b border-zinc-200 px-6 py-3 text-sm font-semibold">Recent jobs</div>
        {recent.length === 0 ? (
          <p className="px-6 py-6 text-sm text-zinc-500">No jobs yet.</p>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {recent.map((j) => (
              <li key={j.id}>
                <Link href={`/jobs/${j.id}`} className="flex items-center justify-between px-6 py-3 hover:bg-zinc-50">
                  <span>
                    <span className="font-medium">{j.filename}</span>{" "}
                    <span className="text-sm text-zinc-500">
                      · {platformLabel(j.source_platform ?? j.detected_platform)}
                      {j.target_platforms.length ? ` → ${j.target_platforms.map(platformLabel).join(", ")}` : ""} · {j.total_rows} rows
                    </span>
                  </span>
                  <span className="flex items-center gap-3 text-sm">
                    <span className="tabular-nums text-zinc-500">{percent(j.processed_rows, j.total_rows)}%</span>
                    <Badge tone={jobStatusTone(j.status)}>{j.status}</Badge>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </Layout>
  );
}
