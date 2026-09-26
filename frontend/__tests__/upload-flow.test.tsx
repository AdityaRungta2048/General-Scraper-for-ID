import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Home from "@/pages/index";
import { setFetch } from "@/services/api";

vi.mock("next/router", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), pathname: "/" }) }));

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const platform = (id: string, label: string, fields: string[], configured: boolean) => ({
  id,
  label,
  fields,
  optional: false,
  keyless: false,
  configured,
  source: configured ? "setup" : null,
});

describe("upload flow", () => {
  afterEach(() => setFetch((...args) => fetch(...args)));

  it("asks for the keys of the chosen platforms before Start", async () => {
    let youtubeConnected = false;
    const f = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/platforms")
        return Promise.resolve(
          json([
            platform("twitch", "Twitch", ["client_id", "client_secret"], true),
            platform("youtube", "YouTube", ["api_key"], youtubeConnected),
          ]),
        );
      if (url === "/api/jobs" && init?.method === "POST")
        return Promise.resolve(
          json({
            id: "j1",
            filename: "s.xlsx",
            status: "UPLOADED",
            detected_platform: "twitch",
            platforms: ["twitch", "youtube"],
            target_platforms: [],
            total_rows: 3,
            sheet_name: "Sheet1",
            header_row: 1,
            warnings_json: [],
            needs_platform_choice: false,
          }),
        );
      if (url === "/api/credentials/youtube") {
        youtubeConnected = true;
        return Promise.resolve(json(platform("youtube", "YouTube", ["api_key"], true)));
      }
      if (url === "/api/jobs") return Promise.resolve(json([]));
      return Promise.resolve(json({}));
    });
    setFetch(f as unknown as typeof fetch);
    render(<Home />);

    const input = (await screen.findByLabelText("Excel file")) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "s.xlsx")] } });
    const summary = await screen.findByTestId("upload-summary");
    const start = within(summary).getByRole("button", { name: "Start Processing" }) as HTMLButtonElement;

    // YouTube (the default destination) has no key yet: its card and guide appear, Start is locked
    const missing = await within(summary).findByTestId("missing-keys");
    expect(within(missing).getByText(/How to get your YouTube API key/)).toBeTruthy();
    expect(start.disabled).toBe(true);

    const card = within(missing).getByTestId("keys-youtube");
    fireEvent.change(card.querySelector("input") as HTMLInputElement, { target: { value: "my-key" } });
    fireEvent.click(card.querySelector("button[type=submit]") as HTMLButtonElement);
    await waitFor(() => expect(start.disabled).toBe(false));
    expect(within(summary).queryByTestId("missing-keys")).toBeNull();
  });
});
