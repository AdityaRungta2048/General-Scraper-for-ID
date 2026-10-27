import Link from "next/link";
import { useRouter } from "next/router";
import { useCallback, useEffect, useState } from "react";

import Layout from "@/components/Layout";
import { Alert, Badge, Button, Card, LinkButton } from "@/components/ui";
import { isActive, platformLabel } from "@/lib/format";
import { api, type Job, type RenameItem } from "@/services/api";

/** Rows with no result: look each channel up on streamscharts.com (free, in your own browser),
 * type its current name, and the row is re-checked through the official API. */
export default function RenamesPage() {
  const router = useRouter();
  const id = typeof router.query.id === "string" ? router.query.id : null;
  const [job, setJob] = useState<Job | null>(null);
  const [items, setItems] = useState<RenameItem[]>([]);
  const [names, setNames] = useState<Record<number, string>>({});
  const [onlyOpen, setOnlyOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(0);

  const load = useCallback(async () => {
    if (!id) return;
    const [j, r] = await Promise.all([api.getJob(id), api.renames(id)]);
    setJob(j);
    setItems(r);
  }, [id]);

  useEffect(() => {
    const t = setTimeout(() => load().catch((e: Error) => setError(e.message)), 0);
    return () => clearTimeout(t);
  }, [load]);

  useEffect(() => {
    if (!job || !isActive(job)) return;
    const t = setInterval(() => load().catch((e: Error) => setError(e.message)), 1500);
    return () => clearInterval(t);
  }, [job, load]);

  const value = (item: RenameItem) => names[item.original_row] ?? item.renamed_to ?? "";
  const changed = items.filter((i) => value(i).trim() !== (i.renamed_to ?? ""));
  const shown = items.filter((i) => !onlyOpen || !i.renamed_to || changed.includes(i));
  const source = job?.source_platform ?? null;

  const save = async () => {
    if (!id || !changed.length) return;
    setBusy(true);
    setError(null);
    try {
      await api.saveRenames(
        id,
        changed.map((i) => ({ original_row: i.original_row, renamed_to: value(i).trim() || null })),
      );
      setSaved(changed.length);
      setNames({});
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Layout>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          {id && (
            <Link href={`/jobs/${id}`} className="text-sm text-brand-600 hover:underline">
              ← Back to job
            </Link>
          )}
          <h1 className="mt-1 text-xl font-semibold">Renamed channels</h1>
          <p className="text-sm text-zinc-500">
            {job?.filename} · {items.filter((i) => !i.renamed_to).length} to check
          </p>
        </div>
        {id && (
          <LinkButton variant="primary" href={api.downloadUrl(id)} download={job?.output_filename ?? undefined}>
            ⬇ Download updated Excel
          </LinkButton>
        )}
      </div>

      <Alert tone="info" title="Free: you look it up, the app checks it">
        These rows got no result, often because a channel was renamed. Click <b>Streams Charts</b>: it opens the
        channel&apos;s page in your browser (if it says &quot;not found&quot;, paste the ID into the search bar
        there, wait a few seconds and click the result). Type the channel&apos;s <b>current {platformLabel(source)}{" "}
        name</b> and click <b>Save &amp; re-check</b>. The app checks it through the official API and fills in the
        row. Nothing is paid; the app itself never contacts streamscharts.com.
      </Alert>
      {error && <Alert tone="danger">{error}</Alert>}
      {saved > 0 && job && isActive(job) && <Alert tone="info">Re-checking {saved} row(s)…</Alert>}

      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-zinc-200 px-4 py-2">
          <label className="flex items-center gap-2 text-sm text-zinc-600">
            <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />
            Hide rows that already have a name
          </label>
          <span className="ml-auto" />
          <Button variant="primary" disabled={busy || !changed.length || (job ? isActive(job) : true)} onClick={save}>
            Save &amp; re-check {changed.length ? `${changed.length} row(s)` : ""}
          </Button>
        </div>
        {shown.length === 0 ? (
          <p className="p-8 text-center text-zinc-600">Nothing to check.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-left text-xs uppercase text-zinc-500">
              <tr>
                <th className="px-4 py-2">Row</th>
                <th className="px-4 py-2">{platformLabel(source)} ID</th>
                <th className="px-4 py-2">Result</th>
                <th className="px-4 py-2">Look it up</th>
                <th className="px-4 py-2">Current name</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((item) => (
                <tr key={item.original_row} className="border-t border-zinc-100" data-testid="rename-row">
                  <td className="px-4 py-2 tabular-nums text-zinc-500">{item.original_row}</td>
                  <td className="px-4 py-2 font-medium">
                    {item.source_value}
                    {item.country && <span className="ml-2 text-xs text-zinc-500">{item.country}</span>}
                  </td>
                  <td className="px-4 py-2">
                    {item.pending ? (
                      <Badge>checking…</Badge>
                    ) : (
                      Object.entries(item.results).map(([p, matched]) => (
                        <div key={p}>
                          {matched ? (
                            <Badge tone="success">
                              {platformLabel(p)}: {matched}
                            </Badge>
                          ) : (
                            <span className="text-zinc-500">{item.remarks || `no ${platformLabel(p)} result`}</span>
                          )}
                        </div>
                      ))
                    )}
                  </td>
                  <td className="px-4 py-2">
                    <a
                      href={item.streams_charts_url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium text-brand-700 underline"
                    >
                      Streams Charts ↗
                    </a>
                  </td>
                  <td className="px-4 py-2">
                    <input
                      aria-label={`Current name for row ${item.original_row}`}
                      className="w-48 rounded-md border border-zinc-300 px-2 py-1"
                      placeholder="new name"
                      value={value(item)}
                      onChange={(e) => setNames({ ...names, [item.original_row]: e.target.value })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </Layout>
  );
}
