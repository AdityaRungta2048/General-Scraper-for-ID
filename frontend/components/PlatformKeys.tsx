import { useState } from "react";

import { Alert, Badge, Button, Card } from "@/components/ui";
import { GUIDES } from "@/lib/guides";
import { api, type PlatformStatus } from "@/services/api";

/** One platform's key form (or on/off switch) with its step-by-step guide beside it. */
export default function PlatformKeys({ status, onChange }: { status: PlatformStatus; onChange: (s: PlatformStatus) => void }) {
  const guide = GUIDES[status.id];
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const complete = status.fields.every((f) => (values[f] ?? "").trim());

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      onChange(await api.saveCredentials(status.id, values));
      setValues({});
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      onChange(await api.deleteCredentials(status.id));
      setSaved(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="grid gap-6 p-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]" data-testid={`keys-${status.id}`}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (complete && !busy) void save();
        }}
      >
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-base font-semibold">
            {status.label}
            {status.optional && <span className="ml-2 text-xs font-normal text-zinc-500">optional</span>}
            {status.keyless && <span className="ml-2 text-xs font-normal text-zinc-500">no API key needed</span>}
          </h2>
          {status.configured ? (
            <Badge tone="success">
              {status.keyless ? "On" : "Connected"}
              {status.source === "environment" ? " (server config)" : ""}
            </Badge>
          ) : (
            <Badge tone="neutral">{status.keyless ? "Off" : "Not connected"}</Badge>
          )}
        </div>
        {status.fields.map((f) => (
          <label key={f} className="block">
            <span className="text-sm font-medium text-zinc-700">{guide?.fieldLabels[f] ?? f}</span>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={values[f] ?? ""}
              onChange={(e) => setValues({ ...values, [f]: e.target.value })}
              placeholder={status.configured ? "•••••••• (saved — enter a new value to replace)" : ""}
              className="mt-1 block w-full rounded-lg border border-zinc-300 px-3 py-2 font-mono text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100"
            />
          </label>
        ))}
        {status.keyless && (
          <p className="text-sm text-zinc-600">
            Unofficial: reads the platform&apos;s public pages, the same data its website shows to anyone. It can stop
            working if the site changes, and lookups are slow on purpose. When a lookup is blocked, the row is marked as
            an error to retry, never as &quot;no match&quot;.
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {!(status.keyless && status.configured) && (
            <Button type="submit" variant="primary" disabled={!complete || busy}>
              {busy ? "Checking…" : status.keyless ? "Turn on" : "Save & test"}
            </Button>
          )}
          {status.source === "setup" && (
            <Button type="button" variant={status.keyless ? "secondary" : "ghost"} onClick={remove} disabled={busy}>
              {status.keyless ? "Turn off" : "Remove"}
            </Button>
          )}
        </div>
        {saved && (
          <p className="text-sm text-emerald-700">{status.keyless ? "Turned on." : "Keys work and were saved."}</p>
        )}
        {error && (
          <Alert tone="danger" title="Not saved">
            {error}
          </Alert>
        )}
      </form>

      {guide && (
        <div className="rounded-lg bg-zinc-50 p-4 text-sm leading-relaxed text-zinc-700">
          <div className="mb-2 font-semibold text-zinc-900">
            {status.keyless
              ? `Why ${status.label} has no key`
              : `How to get your ${status.label} ${status.fields.length > 1 ? "Client ID & Secret" : "API key"}`}
          </div>
          <ol className="list-decimal space-y-1.5 pl-5">
            {guide.steps.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
          {guide.note && <p className="mt-3 text-xs text-zinc-500">{guide.note}</p>}
        </div>
      )}
    </Card>
  );
}
