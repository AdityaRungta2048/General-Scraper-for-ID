import type { ReactNode } from "react";

export interface Guide {
  fieldLabels: Record<string, string>;
  consoleUrl: string;
  consoleName: string;
  steps: ReactNode[];
  note?: ReactNode;
}

const A = ({ href, children }: { href: string; children: ReactNode }) => (
  <a href={href} target="_blank" rel="noreferrer" className="font-medium text-brand-700 underline">
    {children}
  </a>
);

/** Step-by-step instructions shown next to each platform on the API keys screen. */
export const GUIDES: Record<string, Guide> = {
  twitch: {
    fieldLabels: { client_id: "Client ID", client_secret: "Client Secret" },
    consoleUrl: "https://dev.twitch.tv/console/apps",
    consoleName: "Twitch Developer Console",
    steps: [
      <>
        Turn on two-factor authentication for your Twitch account (Twitch requires it for developer tools):{" "}
        <A href="https://www.twitch.tv/settings/security">Settings → Security</A>.
      </>,
      <>
        Open the <A href="https://dev.twitch.tv/console/apps">Twitch Developer Console</A> and click{" "}
        <b>Register Your Application</b>.
      </>,
      <>
        Name: anything unique (e.g. <code>my-id-matcher</code>). OAuth Redirect URL: <code>http://localhost</code>.
        Category: <b>Analytics Tool</b>. Client Type: <b>Confidential</b>. Click <b>Create</b>.
      </>,
      <>
        Click <b>Manage</b> on the new app and copy the <b>Client ID</b>.
      </>,
      <>
        Click <b>New Secret</b> and copy the <b>Client Secret</b>. Twitch only shows it once.
      </>,
    ],
    note: "The app only reads public channel data with an app token. No Twitch login or permissions are requested.",
  },
  kick: {
    fieldLabels: { client_id: "Client ID", client_secret: "Client Secret" },
    consoleUrl: "https://kick.com/settings/developer",
    consoleName: "Kick Developer settings",
    steps: [
      <>
        Log in at <A href="https://kick.com">kick.com</A> and turn on two-factor authentication (Kick requires it for
        developer apps): <b>Settings → Security</b>.
      </>,
      <>
        Go to <A href="https://kick.com/settings/developer">Settings → Developer</A> and click <b>Create App</b>.
      </>,
      <>
        App name: anything. Redirect URL: <code>http://localhost</code>. You don&apos;t need to tick any scopes.
      </>,
      <>
        Save, then copy the <b>Client ID</b> and <b>Client Secret</b> shown for the app.
      </>,
    ],
    note: "Kick's official API has no search, so accounts are found by exact name, name variants and links.",
  },
  youtube: {
    fieldLabels: { api_key: "API key" },
    consoleUrl: "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
    consoleName: "Google Cloud Console",
    steps: [
      <>
        Open the <A href="https://console.cloud.google.com/projectcreate">Google Cloud Console</A> and create a project
        (any name). No billing account is needed.
      </>,
      <>
        With that project selected, open{" "}
        <A href="https://console.cloud.google.com/apis/library/youtube.googleapis.com">YouTube Data API v3</A> and click{" "}
        <b>Enable</b>.
      </>,
      <>
        Go to <A href="https://console.cloud.google.com/apis/credentials">APIs &amp; Services → Credentials</A>, click{" "}
        <b>Create credentials → API key</b> and copy the key.
      </>,
      <>
        Recommended: click <b>Edit API key</b>, choose <b>Restrict key</b> under API restrictions, pick{" "}
        <b>YouTube Data API v3</b> and save.
      </>,
    ],
    note: (
      <>
        YouTube uses one <b>API key</b> instead of a client id and secret. The free quota is 10,000 units a day. A row
        usually costs 1–15 units, or about 100 more when a channel search is needed. When the quota runs out, rows are
        marked as errors (not &quot;no match&quot;) so you can retry them the next day.
      </>
    ),
  },
  chzzk: {
    fieldLabels: { client_id: "Client ID", client_secret: "Client Secret" },
    consoleUrl: "https://developers.chzzk.naver.com/",
    consoleName: "CHZZK Developers",
    steps: [
      <>
        Log in with your Naver account at <A href="https://developers.chzzk.naver.com/">CHZZK Developers</A>.
      </>,
      <>
        Open <b>Application</b> (애플리케이션) and register a new application. Name: anything. Redirect URL:{" "}
        <code>http://localhost</code>. You don&apos;t need any user scopes.
      </>,
      <>
        Copy the <b>Client ID</b> and <b>Client Secret</b> shown for the application. Naver may review a new app
        before it can call the API.
      </>,
    ],
    note: (
      <>
        CHZZK channels are identified by a 32-character channel id (the part after <code>chzzk.naver.com/</code>),
        and that id is what&apos;s written to the sheet. The official API has no search, so channels are found through
        CHZZK&apos;s public channel search.
      </>
    ),
  },
  steam: {
    fieldLabels: { api_key: "Web API key" },
    consoleUrl: "https://steamcommunity.com/dev/apikey",
    consoleName: "Steam Web API key page",
    steps: [
      <>
        Log in to Steam and open <A href="https://steamcommunity.com/dev/apikey">steamcommunity.com/dev/apikey</A>.
      </>,
      <>
        Domain name: <code>localhost</code>. Accept the terms and click <b>Register</b>.
      </>,
      <>Copy the key that appears.</>,
    ],
    note: (
      <>
        SteamTV broadcasts belong to Steam community profiles, so this looks up profiles by custom URL name
        (steamcommunity.com/id/<b>name</b>) or 64-bit SteamID. Steam only gives keys to accounts that have spent at
        least $5 in the store. The API has no search and no bio, so matches rely on links in other profiles and the
        profile picture.
      </>
    ),
  },
  soop: {
    fieldLabels: {},
    consoleUrl: "https://www.sooplive.co.kr/",
    consoleName: "SOOP",
    steps: [
      <>SOOP&apos;s official Open API can&apos;t look up other streamers&apos; channels, so there is no key to create.</>,
      <>
        Turning this on reads the public channel data SOOP&apos;s own website shows to visitors (
        <code>ch.sooplive.co.kr/&lt;id&gt;</code>): nickname, profile text, picture.
      </>,
    ],
  },
  bigo: {
    fieldLabels: {},
    consoleUrl: "https://www.bigo.tv/",
    consoleName: "Bigo LIVE",
    steps: [
      <>Bigo LIVE has no public developer API, so there is no key to create.</>,
      <>
        Turning this on reads the public profile data bigo.tv shows to visitors, by Bigo ID (
        <code>bigo.tv/&lt;id&gt;</code>).
      </>,
    ],
  },
  nimo: {
    fieldLabels: {},
    consoleUrl: "https://www.nimo.tv/",
    consoleName: "Nimo TV",
    steps: [
      <>Nimo TV has no public developer API, so there is no key to create.</>,
      <>
        Turning this on reads the public channel pages on nimo.tv (<code>nimo.tv/&lt;name&gt;</code>).
      </>,
    ],
  },
  rumble: {
    fieldLabels: {},
    consoleUrl: "https://rumble.com/",
    consoleName: "Rumble",
    steps: [
      <>
        Rumble&apos;s API keys only give access to your own live stream, not to looking up other channels, so there
        is no key to create.
      </>,
      <>
        Turning this on reads the public channel pages on rumble.com (<code>rumble.com/c/&lt;name&gt;</code>).
      </>,
    ],
  },
  brave: {
    fieldLabels: { api_key: "API key" },
    consoleUrl: "https://api-dashboard.search.brave.com/",
    consoleName: "Brave Search API dashboard",
    steps: [
      <>
        Sign up at the <A href="https://api-dashboard.search.brave.com/">Brave Search API dashboard</A>.
      </>,
      <>Subscribe to a plan (a free tier is available).</>,
      <>
        Open <b>API Keys</b>, click <b>Add API key</b> and copy it.
      </>,
    ],
    note: "Optional. Used only to discover candidate accounts when the platform APIs find nothing plausible.",
  },
};
