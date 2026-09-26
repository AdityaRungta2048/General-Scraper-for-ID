import { useRouter } from "next/router";
import { useEffect, useState } from "react";

import Layout from "@/components/Layout";
import PlatformKeys from "@/components/PlatformKeys";
import { Alert, Button, Card } from "@/components/ui";
import { markSetupSeen, readyCount } from "@/lib/format";
import { api, type PlatformStatus } from "@/services/api";

export default function Setup() {
  const router = useRouter();
  const [platforms, setPlatforms] = useState<PlatformStatus[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showOptional, setShowOptional] = useState(false);

  useEffect(() => {
    api
      .platforms()
      .then(setPlatforms)
      .catch((e: Error) => setError(e.message));
  }, []);

  const ready = platforms ? readyCount(platforms) : 0;
  const all = platforms ?? [];
  const groups: [string, PlatformStatus[]][] = [
    ["Official APIs: your keys", all.filter((p) => !p.keyless && !p.optional)],
    ["No official API: switch on to use public pages", all.filter((p) => p.keyless)],
  ];
  const update = (s: PlatformStatus) => setPlatforms((ps) => (ps ?? []).map((p) => (p.id === s.id ? s : p)));

  return (
    <Layout gate={false}>
      <Card className="p-6">
        <h1 className="text-lg font-semibold">Your platform keys</h1>
        <p className="mt-1 text-sm text-zinc-600">
          This app looks people up with <b>your own</b> developer keys. You only need keys for the platforms you use:
          the one your sheet&apos;s IDs come from and the ones you search. You can add them here now, or later: when
          you pick platforms for a job, the app asks for any key that&apos;s missing before it starts. Each key is
          tested before it&apos;s saved, stays on this app&apos;s server, and is never shown again or sent to the
          browser. Platforms without an official API have no key: they&apos;re just switched on.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            variant="primary"
            onClick={() => {
              markSetupSeen();
              void router.push("/");
            }}
          >
            Continue to the app
          </Button>
          <span className="text-sm text-zinc-500">
            {ready} of {platforms?.filter((p) => !p.optional).length ?? "…"} platforms connected
          </span>
        </div>
      </Card>
      {error && (
        <Alert tone="danger" title="Could not load platforms">
          {error}
        </Alert>
      )}
      {groups.map(([title, group]) =>
        group.length ? (
          <section key={title} className="space-y-4">
            <h2 className="px-1 text-sm font-semibold uppercase tracking-wide text-zinc-500">{title}</h2>
            {group.map((p) => (
              <PlatformKeys key={p.id} status={p} onChange={update} />
            ))}
          </section>
        ) : null,
      )}
      {all
        .filter((p) => p.optional)
        .map((p) =>
          showOptional || p.configured ? (
            <PlatformKeys key={p.id} status={p} onChange={update} />
          ) : (
            <div key={p.id} className="px-1">
              <Button variant="secondary" onClick={() => setShowOptional(true)} data-testid="show-brave">
                Optional: add a Brave Search API key
              </Button>
              <p className="mt-1 text-xs text-zinc-500">
                Not about the Brave browser (any browser works). Brave Search is an extra search engine the app can
                use to find hard-to-find accounts; it needs its own API key.
              </p>
            </div>
          ),
        )}
    </Layout>
  );
}
