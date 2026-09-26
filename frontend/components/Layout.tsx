import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useState, type ReactNode } from "react";

import { readyCount, setupSeen } from "@/lib/format";
import { api, type AppConfig, type PlatformStatus } from "@/services/api";

/**
 * `gate` (default on): on the first visit, with no platform connected yet, pages open the keys
 * screen first. After that, missing keys are asked for when a job's platforms are chosen.
 */
export default function Layout({ children, gate = true }: { children: ReactNode; gate?: boolean }) {
  const router = useRouter();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [platforms, setPlatforms] = useState<PlatformStatus[] | null>(null);

  useEffect(() => {
    api
      .config()
      .then(setConfig)
      .catch(() => setConfig(null));
    api
      .platforms()
      .then(setPlatforms)
      .catch(() => setPlatforms(null));
  }, []);

  // first visit with nothing connected: show the keys screen first (once)
  const needsSetup = gate && platforms !== null && readyCount(platforms) === 0 && !setupSeen();
  useEffect(() => {
    if (needsSetup) void router.replace("/setup");
  }, [needsSetup, router]);

  const connected = platforms?.filter((p) => !p.optional && p.configured).map((p) => p.label) ?? [];

  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4">
          <Link href="/" className="flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white">
              ID
            </span>
            <span>
              <span className="block text-sm font-bold tracking-wide text-zinc-900">CROSS-PLATFORM ID MATCHER</span>
              <span className="block text-xs text-zinc-500">
                {connected.length ? connected.join(" ⇄ ") : "Streamer identity resolution"}
              </span>
            </span>
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            {config && (
              <span className="hidden text-xs text-zinc-500 md:block">
                engine v{config.matching_engine_version} · match ≥ {config.match_threshold}
              </span>
            )}
            <Link href="/setup" className="font-semibold text-brand-700 hover:underline">
              API keys
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-6 px-6 py-8">{needsSetup ? null : children}</main>
    </div>
  );
}
