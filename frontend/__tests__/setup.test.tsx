import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Setup from "@/pages/setup";
import { setFetch, type PlatformStatus } from "@/services/api";

const push = vi.fn();
vi.mock("next/router", () => ({
  useRouter: () => ({ push, replace: vi.fn(), pathname: "/setup" }),
}));

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const status = (id: string, label: string, fields: string[], configured = false): PlatformStatus => ({
  id,
  label,
  fields,
  optional: id === "brave",
  keyless: false,
  configured,
  source: configured ? "setup" : null,
});

describe("API keys setup screen", () => {
  afterEach(() => setFetch((...args) => fetch(...args)));

  it("shows a guide next to each platform and saves a key", async () => {
    const platforms = [
      status("twitch", "Twitch", ["client_id", "client_secret"], true),
      status("kick", "Kick", ["client_id", "client_secret"]),
      status("youtube", "YouTube", ["api_key"]),
      status("brave", "Brave Search", ["api_key"]),
    ];
    const f = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/platforms") return Promise.resolve(respond(platforms));
      if (url === "/api/config") return Promise.resolve(respond({ matching_engine_version: "2", match_threshold: 90 }));
      if (url === "/api/credentials/youtube" && init?.method === "PUT")
        return Promise.resolve(respond(status("youtube", "YouTube", ["api_key"], true)));
      return Promise.resolve(respond({}, 404));
    });
    setFetch(f as unknown as typeof fetch);
    render(<Setup />);

    expect(await screen.findByText(/How to get your YouTube API key/)).toBeTruthy();
    expect(screen.getByText(/How to get your Twitch Client ID & Secret/)).toBeTruthy();
    // keys can also be added later, per job: continuing is always allowed
    expect((screen.getByRole("button", { name: "Continue to the app" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText("1 of 3 platforms connected")).toBeTruthy();

    const yt = screen.getByTestId("keys-youtube");
    const input = yt.querySelector("input") as HTMLInputElement;
    expect(input.type).toBe("password");
    fireEvent.change(input, { target: { value: "my-key" } });
    fireEvent.click(yt.querySelector("button[type=submit]") as HTMLButtonElement);

    await waitFor(() => expect(screen.getByText("2 of 3 platforms connected")).toBeTruthy());
    const put = f.mock.calls.find(([u, i]) => u === "/api/credentials/youtube" && i?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({
      values: { api_key: "my-key" },
    });
    expect(input.value).toBe(""); // the key is not kept in the page after saving
  });
});
