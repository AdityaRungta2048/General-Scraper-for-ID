import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RenamesPage from "@/pages/jobs/[id]/renames";
import { setFetch } from "@/services/api";

vi.mock("next/router", () => ({
  useRouter: () => ({ query: { id: "j1" }, push: vi.fn(), replace: vi.fn(), pathname: "/jobs/[id]/renames" }),
}));

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const job = {
  id: "j1",
  filename: "s.xlsx",
  status: "COMPLETED",
  source_platform: "twitch",
  output_filename: "s_processed.xlsx",
};
const item = (row: number, value: string, renamed_to: string | null = null) => ({
  original_row: row,
  source_value: value,
  country: "Germany",
  remarks: "no Id on both platforms",
  renamed_to,
  pending: false,
  streams_charts_url: `https://streamscharts.com/channels/${value}?platform=twitch`,
  results: { kick: null },
  reason: null,
});

describe("renamed channels page", () => {
  afterEach(() => setFetch((...args) => fetch(...args)));

  it("links each row to Streams Charts and saves only the names that changed", async () => {
    const posted: unknown[] = [];
    const f = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/platforms")
        return Promise.resolve(
          json([{ id: "twitch", label: "Twitch", fields: [], optional: false, keyless: false, configured: true }]),
        );
      if (url === "/api/jobs/j1") return Promise.resolve(json(job));
      if (url === "/api/jobs/j1/renames" && init?.method === "POST") {
        posted.push(JSON.parse(String(init.body)));
        return Promise.resolve(json(job));
      }
      if (url === "/api/jobs/j1/renames")
        return Promise.resolve(json([item(2, "oldtwitch"), item(3, "other"), item(4, "done", "donenow")]));
      return Promise.resolve(json({}));
    });
    setFetch(f as unknown as typeof fetch);
    render(<RenamesPage />);

    const links = await screen.findAllByText("Streams Charts ↗");
    expect(links).toHaveLength(2); // the row that already has a name is hidden
    expect(links[0]).toHaveAttribute("href", "https://streamscharts.com/channels/oldtwitch?platform=twitch");
    expect(links[0]).toHaveAttribute("target", "_blank");

    fireEvent.change(screen.getByLabelText("Current name for row 2"), { target: { value: " newtwitch " } });
    fireEvent.click(screen.getByRole("button", { name: /Save & re-check/ }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ items: [{ original_row: 2, renamed_to: "newtwitch" }] });
  });
});
