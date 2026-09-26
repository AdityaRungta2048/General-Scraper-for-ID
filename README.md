# Cross-Platform ID Matcher (general edition)

Upload an Excel workbook of creator IDs from one platform (**Twitch, Kick, YouTube, CHZZK, SOOP,
Steam, Bigo LIVE, Nimo TV or Rumble**),
pick **one or more** platforms to search (e.g. Twitch IDs → Kick *and* YouTube in one job), and the
app finds out whether the *same creator* exists on each of them. It
returns **`<your_file>_processed.xlsx`**: your original workbook, same rows, same columns, same
formatting, with only the destination-ID and remarks cells filled in. The output format is the
same for every pair; only the platform names change (`id_youtube`, `no youtube id found`,
`youtube_id_link`, …).

**Bring your own API keys.** On first launch the app opens an **API keys** screen. Each user
creates their own developer credentials (a step-by-step guide sits next to every platform) and
pastes them in. Nobody has to share their keys with anyone.

It is an **identity-resolution** system, not a username search: a name match is only a
*candidate*. An ID is written only when independent evidence (explicit cross-links, shared
unique social accounts, the same non-generic profile picture, …) establishes that both accounts
belong to the same creator. **A missed match is acceptable; a wrong match is not.** Uncertain
rows go to a review queue instead of being guessed.

---

## Contents
1. [Project overview](#1-project-overview) · 2. [Architecture](#2-architecture) · 3. [Setup](#3-setup) ·
4. [Twitch API setup](#4-twitch-api-setup) · 5. [Kick API setup](#5-kick-api-setup) ·
6. [OAuth configuration](#6-oauth-configuration) · 7. [Environment variables](#7-environment-variables) ·
8. [Database](#8-database-setup) · 9. [Redis / queue](#9-redis--queue-setup) ·
10. [Local development](#10-local-development) · 11. [Docker](#11-docker-development) ·
12. [Excel format](#12-excel-format) · 13. [Matching methodology](#13-matching-methodology) ·
14. [Confidence scoring](#14-confidence-scoring) · 15. [Review process](#15-review-process) ·
16. [API limitations](#16-api-limitations) · 17. [Rate limits](#17-rate-limits) · 18. [Security](#18-security) ·
19. [Known limitations](#19-known-limitations) · 20. [Troubleshooting](#20-troubleshooting) ·
21. [Tuning thresholds](#21-how-to-tune-thresholds) · 22. [Updating API adapters](#22-how-to-update-api-adapters) ·
[Testing](#testing)

Design notes with the verified API capabilities, the exact row state machine and the
false-positive strategy: [`docs/DESIGN.md`](docs/DESIGN.md).

---

## 1. Project overview

```
ADD YOUR API KEYS → UPLOAD EXCEL → CHOOSE SOURCE + DESTINATION → READ ROWS → VERIFY SOURCE ACCOUNTS → GENERATE CANDIDATES
→ CROSS-PLATFORM IDENTITY ANALYSIS → MATCH / REVIEW / NO_MATCH → WRITE TO ORIGINAL ROW POSITIONS
→ GENERATE <name>_processed.xlsx → VERIFY XLSX (cell-by-cell) → DOWNLOAD
```

* **Primary deliverable:** `<name>_processed.xlsx` (download button in the UI).
* **Secondary:** `<name>_review.xlsx` — per-row decision, confidence, evidence and reasons.
* Web UI: API keys screen with per-platform guides, drag-and-drop upload, source/destination
  pickers, live progress, results table with per-row evidence,
  review dashboard (confirm / reject / skip), retry of failed rows.

## 2. Architecture

```
frontend/ (Next.js, TS, Tailwind) ──/api proxy──► backend/ (FastAPI)
                                                     │  jobs + rows persisted (PostgreSQL / SQLite)
                                                     ▼
                                   queue: Redis + RQ worker  (or in-process for local dev)
                                                     ▼
       JobProcessor ── per unique source id ──► IdentityResolver
                                                     ├─ PlatformAdapter: TwitchAdapter / KickAdapter
                                                     │     (token mgmt, rate limit, retry, cache)
                                                     ├─ CandidateGenerator   (discovery only)
                                                     └─ IdentityVerifier     (decides)
                                                          ├─ SocialLinkMatcher  ├─ ProfileImageMatcher
                                                          ├─ Username/DisplayNameMatcher
                                                          ├─ BioMatcher  ├─ ContentMatcher  ├─ CountryMatcher
                                                          └─ ConfidenceScorer + DecisionEngine
                                                     ▼
                             Row state machine → ExcelExporter → OutputVerifier → download
```

| Path | Responsibility |
|---|---|
| `backend/app/platforms/` | `base.py` (Profile, `PlatformAdapter`), `catalog.py` (the platform list), `twitch.py`, `kick.py`, `youtube.py`, `search_engine.py`, `http.py` (retries/rate limit/OAuth/API keys), `errors.py` |
| `backend/app/credentials.py` | the user's API keys (setup screen → `DATA_DIR/credentials.json`, env fallback) |
| `backend/app/matching/` | `candidates.py`, `verifier.py`, `names.py`, `social.py`, `image.py`, `text.py`, `decision.py`, `config.py` |
| `backend/app/services/` | `resolver.py` (one source id → auditable resolution), `jobs.py`, `stores.py`, `context.py` |
| `backend/app/excel/` | `importer.py`, `state_machine.py`, `exporter.py`, `verifier.py`, `review_report.py` |
| `backend/app/workers/` | `processor.py` (async, resumable), `queue.py` (RQ / inline) |
| `backend/app/reviews/` | manual review service |
| `backend/app/models/` | SQLAlchemy models; migrations in `backend/alembic/` |
| `frontend/pages`, `components`, `services`, `lib` | UI |
| `docker/`, `docker-compose.yml`, `scripts/` | deployment and tooling |

## 3. Setup

Requirements: Python ≥ 3.11, Node ≥ 20 (for the UI), optionally Docker, PostgreSQL, Redis.

```bash
cp .env.example .env                  # optional: keys are normally entered in the app itself
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cd ../frontend && npm ci
```

Sample inputs built from the brief's examples: `python scripts/make_sample_workbooks.py`
→ `samples/kick_streamers.xlsx`, `samples/twitch_streamers.xlsx`.

### How a job runs

1. Upload the sheet. The input platform is detected from its `id_<platform>` column (you can change it).
2. Pick the platform(s) to find each person on.
3. If any of those platforms (or the input platform) has no key yet, their key forms appear right
   there, each with its step-by-step guide. **Start** unlocks once they're all connected.
4. The processed workbook comes back with the found IDs, remarks and channel links.

### API keys screen

On the first visit the app opens the **API keys** screen (all platforms, with guides). Keys can be
added there, or skipped and added per job as above. Each card
has the fields for that platform and a numbered guide with direct links to the right console.
**Save & test** makes one cheap authenticated call first, so a wrong key is caught right away. Saved
keys go to `DATA_DIR/credentials.json` (file mode 600, shared by the API and the worker). They are
never returned to the browser; the UI only sees "connected / not connected". You can change them
any time from the **API keys** link in the header. Environment variables (below) still work as a
fallback for server deployments.

> Run your own copy (locally or on your own server). If you host one instance for other people,
> they would all share (and be able to replace) the keys saved on it, so put it behind a login
> or give each person their own instance.

## 4. Twitch API setup

1. Log in at <https://dev.twitch.tv/console/apps> → **Register Your Application**.
2. OAuth Redirect URL: `http://localhost` (not used — the app only uses app access tokens).
   Category: *Analytics Tool* (or similar). Client type: **Confidential**.
3. Copy the **Client ID**, click **New Secret**, copy the **Client Secret**.
4. Put them in `.env` as `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET`.

Endpoints used (Helix, app token): `GET /helix/users?login=` (existence + profile, 100/call),
`GET /helix/channels?broadcaster_id=` (category, title, tags, language),
`GET /helix/search/channels` (candidate discovery only).

## 5. Kick API setup

1. Log in at kick.com, enable **2FA** (required for developer tools).
2. **Settings → Developer** → **Create App**. Redirect URL: `http://localhost` (unused).
   No scopes are needed for the public data this app reads.
3. Copy the **Client ID** and **Client Secret** into `.env` as `KICK_CLIENT_ID` / `KICK_CLIENT_SECRET`.

Endpoints used (Kick Public API, app token): `GET /public/v1/channels?slug=` (existence +
channel, 50/call), `GET /public/v1/users?id=` (name + profile picture). The official Kick API has
**no search** and **no social-link fields** — see [API limitations](#16-api-limitations).

## 5b. YouTube API setup

1. [Google Cloud Console](https://console.cloud.google.com/projectcreate): create a project (no billing needed).
2. Enable **YouTube Data API v3** for it (APIs & Services → Library).
3. APIs & Services → Credentials → **Create credentials → API key**. Optionally restrict it to the
   YouTube Data API v3.
4. Paste it on the API keys screen (or `YOUTUBE_API_KEY` in `.env`).

Endpoints used: `GET /channels?forHandle=@h` (one handle per call, 1 quota unit),
`GET /channels?id=…` (50 ids per call, 1 unit), `GET /search?type=channel` (100 units, discovery
only). The free quota is **10,000 units/day**, so the app probes at most 12 handles per row
(`variant_budget`) and only searches when those found nothing plausible. When the quota is used up,
rows are marked `RATE_LIMITED` (never "no match"); use **Retry failed rows** the next day. YouTube
IDs are written as `@handle`; the sheet may contain `@handle`, `handle`, a channel URL or a
`UC…` channel id.

## 5c. The other platforms

| Platform | Access | What the user provides | Lookup key written to the sheet |
|---|---|---|---|
| CHZZK | Official Open API (`openapi.chzzk.naver.com`) + CHZZK's public channel search for discovery | Client ID + Secret from [CHZZK Developers](https://developers.chzzk.naver.com/) | 32-hex channel id |
| Steam (SteamTV) | Official Steam Web API (`ResolveVanityURL`, `GetPlayerSummaries`) | Web API key from [steamcommunity.com/dev/apikey](https://steamcommunity.com/dev/apikey) | custom URL name or SteamID64 |
| SOOP | No official lookup API: public station data (`chapi.sooplive.co.kr/api/<id>/station`) | nothing, switch it on | SOOP id |
| Bigo LIVE | No public API: public studio info (`ta.bigo.tv/.../getInternalStudioInfo`) | nothing, switch it on | Bigo ID |
| Nimo TV | No public API: public channel page (`nimo.tv/<name>`) | nothing, switch it on | channel name |
| Rumble | No lookup API: public channel page (`rumble.com/c/<name>`) | nothing, switch it on | channel name |

The four keyless platforms are **unofficial** and opt-in on the API keys screen (or
`PUBLIC_LOOKUP_PLATFORMS=soop,bigo,nimo,rumble`). They read the same data the sites show to anonymous
visitors, rate-limited (`<PLATFORM>_REQUESTS_PER_MINUTE`), never get around bot protection, and turn a
block or an unexpected page into a retryable row error — never "no match". They were built from the
formats used by open-source tools (e.g. Streamlink) and are covered by tests against a fake of those
responses, but were not tested against the live sites; if a site changes, only that adapter
(`backend/app/platforms/public_sites.py`) needs updating. None of the six has a usable search (except
CHZZK), so accounts are found by exact name, name variants (a small per-row budget) and links in bios.

## 6. OAuth configuration

Both platforms use the **OAuth 2 client-credentials** flow (server-to-server *app access tokens*):

| Platform | Token endpoint | Grant |
|---|---|---|
| Twitch | `POST https://id.twitch.tv/oauth2/token` | `client_credentials` |
| Kick | `POST https://id.kick.com/oauth/token` | `client_credentials` |

Tokens are fetched lazily, cached in memory until shortly before `expires_in`, refreshed once
automatically on a 401, and never logged or sent to the browser. No user login is needed and
no user data beyond public profiles is requested.

## 7. Environment variables

All settings live in `.env` (template: [`.env.example`](.env.example)). Key groups:

| Group | Variables |
|---|---|
| Credentials (fallback; normally entered on the API keys screen) | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `KICK_CLIENT_ID`, `KICK_CLIENT_SECRET`, `YOUTUBE_API_KEY`, `BRAVE_SEARCH_API_KEY` (optional) |
| Infrastructure | `DATABASE_URL`, `REDIS_URL`, `QUEUE_BACKEND` (`inline`/`rq`), `DATA_DIR`, `MAX_UPLOAD_MB`, `CORS_ORIGINS`, `LOG_LEVEL`, `LOG_JSON` |
| Behaviour | `EXISTING_DESTINATION_POLICY` (`preserve`/`overwrite`), `KICK_PUBLIC_PROFILE_ENRICHMENT`, `SEARCH_ENGINE_FALLBACK` |
| HTTP | `API_CONCURRENCY`, `ROW_CONCURRENCY`, `TWITCH_REQUESTS_PER_MINUTE`, `KICK_REQUESTS_PER_MINUTE`, `RETRY_COUNT`, `RETRY_BASE_DELAY`, `HTTP_TIMEOUT` |
| Cache | `CACHE_TTL`, `NEGATIVE_CACHE_TTL`, `RESOLUTION_CACHE_TTL`, `IMAGE_CACHE_TTL` |
| Candidates | `MAX_CANDIDATES`, `SEARCH_RESULTS_PER_QUERY`, `IMAGE_MAX_CANDIDATES` |
| Scoring | `MATCH_THRESHOLD`, `REVIEW_THRESHOLD`, `CONFIDENCE_SCALE`, `CROSS_LINK_WEIGHT`, `SOCIAL_LINK_WEIGHT`, `IMAGE_WEIGHT`, `USERNAME_WEIGHT`, `DISPLAY_NAME_WEIGHT`, `BIO_WEIGHT`, `CONTENT_WEIGHT`, `COUNTRY_WEIGHT`, `IMAGE_SIMILARITY_THRESHOLD`, … (see `backend/app/config.py`) |

## 8. Database setup

* **Local:** SQLite by default (`DATABASE_URL=sqlite:///./data/matcher.db`) — nothing to install.
* **Production:** PostgreSQL, e.g. `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/matcher`.
* Schema: `cd backend && alembic upgrade head` (the Docker image does this on start).
  Tables: `processing_jobs`, `processing_rows`, `platform_accounts`, `social_links`,
  `profile_images`, `match_candidates`, `match_decisions`, `manual_reviews`, `api_cache`.
* New migration after a model change: `alembic revision --autogenerate -m "…"`.

## 9. Redis / queue setup

* `QUEUE_BACKEND=inline` (default): jobs run in a background thread of the API process —
  ideal for local use. Interrupted jobs resume automatically when the API restarts.
* `QUEUE_BACKEND=rq`: jobs are enqueued in Redis (`REDIS_URL`) and executed by
  `rq worker matcher --url $REDIS_URL` (the `worker` service in Docker Compose). Scale by
  running more workers. API and workers must share `DATA_DIR` and the database.

## 10. Local development

```bash
./scripts/dev.sh            # API on :8000 (uvicorn --reload), UI on :3000
# or separately:
cd backend && uvicorn app.main:app --reload --port 8000
cd frontend && BACKEND_URL=http://localhost:8000 npm run dev
```

Open <http://localhost:3000>. The UI proxies `/api/*` to the backend, so the browser never
needs the backend URL or any secret.

## 11. Docker development

```bash
docker compose up --build   # then add your API keys on the setup screen   # postgres, redis, backend (runs migrations), worker, frontend
open http://localhost:3000
```

Uploaded files and generated workbooks live in the `appdata` volume (shared by API and worker).

## 12. Excel format

The header row (anywhere in the first 20 rows, case/space/hyphen-insensitive) needs at least the
source `id_<platform>` column: `id_twitch`, `id_kick`, `id_youtube`, `id_chzzk`, `id_soop`,
`id_steam`, `id_bigo`, `id_nimo` or `id_rumble` (aliases like `twitch_id`, `yt` work). Values can
be plain IDs or channel URLs.

| Example workbook | Headers | Job |
|---|---|---|
| Kick source | `id_kick \| country \| id_twitch \| remarks` | Kick → Twitch |
| Twitch → YouTube | `id_twitch \| country \| id_youtube \| remarks` | Twitch → YouTube |
| Several at once | `id_twitch \| country \| remarks` + choose Kick and YouTube | Twitch → Kick, YouTube (`id_kick`, `id_youtube` columns are added) |

The source is the **first** ID column unless another one is clearly fuller (then the UI asks). You
then choose which platforms to **search on**: any connected platform, one or several. A
destination without an `id_<platform>` column in the sheet gets one, appended after your last
used column. Internally every Excel row becomes one result per destination (a 5-row sheet
searched on 2 platforms shows 10 results), all merged back into the same Excel row.
`.xlsx` and `.xlsm` are supported (`.xls` must be re-saved as `.xlsx`).

**Output rules.** The destination ID (`id_twitch` for a Kick sheet, `id_kick` for a Twitch
sheet, `id_<destination>` in general) is written **only for a confirmed match** (or one you confirm on the Review page).

The remark follows the two link columns described below. The phrases below use the Kick/Twitch
names; for other pairs the platform names change (`no youtube id found`,
`nearest possible youtube channel`). When several platforms are searched, the phrases for each
destination are joined with `; ` in the destination order you chose (a confirmed match adds
nothing), e.g. `nearest possible kick channel; no youtube id found`. If the source account
doesn't exist, the remark is `no <source> id` plus `no <p> id found` for each destination with
nothing, or `no Id on any platform` when none of them has anything. If one destination hits an
API error, that row's remark is left untouched until **Retry failed rows** completes it:

| Kick link | Twitch link | remarks |
|---|---|---|
| ✓ | ✓ confirmed match | *(empty)* |
| ✓ | ✓ closest Twitch account only (Kick sheet) | `nearest possible twitch channel` |
| ✓ closest Kick account only (Twitch sheet) | ✓ | `nearest possible kick channel` |
| ✓ | — | `no twitch id found` |
| — | ✓ | `no kick id` |
| — | — | `no Id on both platforms` |

When the source ID itself doesn't exist, the `no … id` remark is used even if the other
platform's link is only the closest account.

API/network errors leave the row **untouched** (reported as an error, retryable), and an
empty source cell is left untouched.

**Channel-link columns.** Two columns are appended after your last used column,
`<platform>_id_link` for the source and every searched platform, in the same order as their ID columns
(reused if the sheet already has them), with **one
clickable link each**:

* the source platform's column: the row's own channel (empty if that account doesn't exist);
* the other platform's column: the single best account — the confirmed match; otherwise the
  review candidate; otherwise the closest account found (same name first, then confidence).
  Accounts you rejected in review are never linked.

The ID column is still filled only for verified matches, so **a link next to an empty ID is
an unconfirmed suggestion** — check it before relying on it.

Guarantees: rows are never sorted, inserted, deleted or de-duplicated; results are written by
the original Excel row number; source IDs, countries, other sheets, formatting, widths, filters,
freeze panes, merged cells, hyperlinks and formulas are preserved. Placeholder text such as
`None` in the destination column becomes a genuinely empty cell. A destination value you typed
yourself is **preserved** by default (`EXISTING_DESTINATION_POLICY=overwrite` replaces it only
with a verified ID). Your own remarks are never erased. Before download, the output is re-opened
and diffed cell-by-cell against the original; any unexpected difference blocks the download.

## 13. Matching methodology

1. **Verify the source account** by exact lookup (offline ≠ nonexistent; API failure ≠ not found).
2. **Generate candidates** (`CandidateGenerator`, never decides): explicit links in the source
   profile → exact handle → deterministic variants (case, `_`↔`-`, separators, `tv/ttv/live/
   official/yt/gaming/gg` suffixes and prefixes, trailing digits — batched lookups) → Twitch
   channel search → optional Brave Search fallback. Deduplicated, capped at `MAX_CANDIDATES`.
3. **Verify identity** (`IdentityVerifier`), cheap signals first, image hashing only for the
   most promising candidates:
   * **Explicit cross-link** (Kick bio → `twitch.tv/x`, or the reverse) — strongest; a link to a
     *different* account is a hard conflict.
   * **Shared unique social accounts** — Instagram/YouTube/X/TikTok/Linktree/Beacons/personal
     website URLs *and* mentions (`IG: @name`) are normalised to `(network, handle)`. Discord
     invites, shorteners, sponsor/affiliate domains, platform brand accounts, team sites and any
     identity shared by ≥ 3 stored accounts are treated as generic.
   * **Profile image** — downloaded (allow-listed CDNs only), normalised, pHash/dHash/aHash over
     untrimmed/trimmed/centre-crop variants. Default avatars, low-complexity logos and images used
     by several unrelated accounts carry almost no weight.
   * **Username / display name** — accent-folded, separator-insensitive fuzzy similarity
     (Levenshtein, Jaro-Winkler, bigrams), affix stripping as a *feature* (`abc` ≠ `abcgaming`),
     scaled by how distinctive the name is. Never sufficient on its own.
   * **Bio** — URLs/boilerplate/generic gaming words removed (en/fr/de/es/it); token and
     char-n-gram similarity, plus optional multilingual embeddings (`BIO_EMBEDDINGS_ENABLED`,
     `pip install ".[ml]"`). Identical long passages count as strong.
   * **Content** — category (generic ones like *Just Chatting* down-weighted), tags, language, title.
   * **Country** — support only: +2 when the candidate's broadcast language fits; never a penalty.
4. **Decide** per candidate, then aggregate: exactly one MATCH → MATCH; several → REVIEW
   (never "pick the best"); otherwise the best REVIEW or NO_MATCH.

Every decision stores its full evidence, reason text and `matching_engine_version`
(`backend/app/version.py`) — visible in the UI (click a row) and the review workbook.

LLMs are intentionally **not** used to decide identity; the deterministic scorer is authoritative.
The optional embedding model only produces a similarity feature.

## 14. Confidence scoring

Each signal contributes evidence points (negative for contradictions):

| Signal | Max points (default) |
|---|---|
| Explicit cross-platform link | 30 (+5 if mutual) |
| Shared unique social account | 25 (+8 per extra, max 2) |
| Strong profile-image match | 20 (moderate: 10; generic × 0.15; clearly different: −6) |
| Username similarity | 15 × distinctiveness |
| Display-name similarity | 10 (× 0.3 if it just restates the login); name family capped at 20 |
| Bio similarity | 10 |
| Content / category | 5 |
| Country | 2 |
| Link to a *different* account | −40 (conflict) |

`confidence = 100 · (1 − e^(−points / CONFIDENCE_SCALE))`, scale 16. **MATCH requires all of:**
confidence ≥ `MATCH_THRESHOLD` (90); at least one *strong* signal (link / unique social /
non-generic image / identical long bio) **plus** corroboration from a different family (or two
strong families, or a mutual link); no conflict; no contradicting image evidence without
link/social proof; and no second candidate that also qualifies. Name/content/country-only
evidence is capped below the match threshold. `REVIEW_THRESHOLD` (70) or any strong-but-
uncorroborated evidence → REVIEW. Otherwise NO_MATCH.

## 15. Review process

Rows marked REVIEW (and "source missing but a same-name account exists") appear on the job's
**Review** page: source vs candidate profile side by side (avatar, names, bio, category, language,
social links, URLs), the evidence scores, each signal with its points and explanation.

* **Confirm Match** writes the candidate's ID into the processed workbook (for every row with the
  same source ID), **Reject Match** stores a negative decision, **Skip** leaves it for later.
* Only accounts the engine actually discovered can be confirmed — you can't type an arbitrary ID.
* Verdicts are stored in `manual_reviews` and applied as explicit overrides in future jobs too.
  They never change weights or thresholds (no self-modifying learning).
* After reviewing, **Download** regenerates and re-verifies the workbook automatically.

## 16. API limitations

Verified against the official documentation (see `docs/DESIGN.md` §A/§B):

* **YouTube quota:** 10,000 units/day by default (see §5b). Channel "About" links are not in the API;
  links are read from the channel description.
* **Instagram, TikTok and X have no free official API for looking up public profiles**, so they are
  not selectable platforms. Their handles are still used as evidence when they appear in bios.
* **SOOP, Bigo LIVE, Nimo TV and Rumble** rely on public pages (see §5c) and can break without notice.
* **Kick has no official search endpoint.** Twitch→Kick discovery relies on deterministic slug
  variants (cheap: 50 per request), explicit links in Twitch bios, and the optional search-engine
  fallback. A Kick account with an unrelated name and no link can't be discovered.
* **Neither official API exposes social links.** Social identities are parsed from bios
  (Twitch `description`, Kick `channel_description`). Twitch *About panels* are not in Helix.
* Optional `KICK_PUBLIC_PROFILE_ENRICHMENT=true` reads the public, **undocumented** channel JSON
  kick.com serves anonymously (bio + social handles). Off by default; it never bypasses bot
  protection — any non-JSON/403 response simply means "unavailable".
* Twitch search is fuzzy and recency-weighted; absence from search never implies non-existence.
* Kick deprecated `GET /public/v1/livestreams` and v1 categories (2026); this app uses neither.

## 17. Rate limits

* Twitch: token bucket (~800 points/min per app token); `Ratelimit-*` headers and 429s are honoured.
* Kick: limits are not published — conservative default `KICK_REQUESTS_PER_MINUTE=120`.
* Client side: per-platform token bucket + concurrency semaphore, batching (Twitch 100 logins,
  Kick 50 slugs per call), exponential backoff with jitter on 429/5xx/timeouts/connection errors,
  `Retry-After` support, no retry on 400/409/422, one token refresh on 401, clear configuration
  error on repeated 401/403. Persistent failures mark rows `API_ERROR` / `RATE_LIMITED` /
  `TEMPORARY_ERROR` — never "no match" — and **Retry Failed Rows** re-runs only those.
* Caching (DB + memory): profiles 24 h, negative lookups 6 h, image hashes 7 d, whole resolutions
  3 d (keyed by engine version). Duplicate IDs in a workbook are resolved once.

## 18. Security

* Each user's own keys, saved from the API keys screen to `DATA_DIR/credentials.json` (mode 600),
  or environment variables; never sent back to the frontend (it only sees connected/not connected),
  never logged (structured logs scrub token/secret/authorization keys).
* Image downloads: HTTPS only, allow-listed platform CDN hosts (`IMAGE_ALLOWED_HOSTS`), size-capped —
  no SSRF via crafted profile URLs.
* Uploads: extension + ZIP validation, size limit, sanitised filenames, stored per job.
* The exporter refuses to write formula-like values or into merged/header cells.
* Only public profile/channel data is used; no emails, private data, CAPTCHA or bot-protection
  bypass.

## 19. Known limitations

* Recall is bounded by what's publicly and officially exposed (see §16). Expect REVIEW rows for
  creators who use different names and no cross-links.
* Perceptual hashes detect the *same* picture (resized, recompressed, bordered, lightly cropped);
  they intentionally don't treat "similar-looking" pictures as a match. Heavily re-cropped or
  redrawn avatars fall back to other evidence.
* openpyxl preserves values, styles, widths, filters, merges, hyperlinks, formulas, data
  validation and conditional formatting, but drops embedded **charts/images/pivot caches**
  from the copy. The original upload is never modified.
* The verifier compares cell values *as stored*; cached formula results are recomputed by Excel
  on open.

## 20. Troubleshooting

| Symptom | Fix |
|---|---|
| Banner "API credentials are not configured" | Set `TWITCH_*` / `KICK_*` in `.env`, restart the backend. |
| Job FAILED: "rejected the client credentials (HTTP 401/403)" | Wrong id/secret, or a proxy/firewall blocks `id.twitch.tv` / `id.kick.com`. |
| Job PARTIAL with errors | Temporary API/network failures. Rows are untouched; click **Retry Failed Rows**. |
| "Required headers not found" | Header row must contain `id_kick` and `id_twitch` within the first 20 rows. |
| "Please choose the source platform" | Column order and fill rates disagree; pick Kick or Twitch. |
| Download returns an error | Output verification failed (details in the job's verification list). The file is withheld on purpose. |
| Job stuck in PROCESSING after a crash | Inline mode resumes on restart; otherwise click **Resume** (allowed after 10 min of inactivity). |
| Many REVIEW rows | Expected when profiles lack links/avatars; use the Review page or enable the optional enrichment/search fallback. |

## 21. How to tune thresholds

1. Change values in `.env` (`MATCH_THRESHOLD`, `REVIEW_THRESHOLD`, weights, `CONFIDENCE_SCALE`,
   `IMAGE_SIMILARITY_THRESHOLD`, …). Restart the backend/worker.
2. Run the scenario suite: `cd backend && pytest tests/integration/test_end_to_end.py` — it
   encodes the difficult cases (same name/different person, suffixes, generic avatars, conflicts,
   ambiguity…) and must stay green. Add a scenario to `tests/scenarios.py` for any real-world
   case you care about before changing weights.
3. Bump `MATCHING_ENGINE_VERSION` in `backend/app/version.py` whenever behaviour changes; cached
   resolutions are keyed by it and every stored decision records it, so results can be compared.
4. Prefer lowering weights / raising thresholds: precision beats recall.

## 22. How to add a platform or update an adapter

To add a platform: write `backend/app/platforms/<name>.py` implementing `PlatformAdapter`, then add
one `PlatformInfo` line in `platforms/catalog.py` (label + credential fields), build it in
`platforms/registry.py`, add a key check in `services/context.py::check_credentials`, and add a
guide in `frontend/lib/guides.tsx`. The importer, state machine, remarks, link columns and UI
pick it up from the catalog.


* Each platform is isolated behind `PlatformAdapter` (`backend/app/platforms/base.py`):
  `find_exact_accounts`, `search_accounts`, `get_image`, `normalize_handle`, `to_handle`,
  `existence_variants`. Changing Twitch never touches Kick and vice versa.
* Base URLs and token URLs are settings (`TWITCH_API_BASE`, `KICK_API_BASE`, …).
* Response parsing lives in one place per adapter; an unexpected response shape (or a 404 on a
  lookup endpoint) raises `UnexpectedResponseError` instead of silently becoming "not found".
* Update the fake API in `backend/tests/fakes.py` to the new shape, then run the suite. Live smoke
  tests against the real APIs: `pytest -m live tests/integration/test_live_apis.py` (needs creds).

## Testing

```bash
./scripts/check.sh          # everything below
cd backend && pytest        # 234 tests: unit, adapters (mocked HTTP), end-to-end, API, row integrity
cd frontend && npm test && npm run lint && npm run typecheck && npm run build
```

Normal tests never hit live APIs: a stateful fake Twitch/Kick/CDN is plugged in at the HTTP
transport layer, so the real adapters, OAuth, retry and cache code run. Highlights:
`test_async_completion_order_does_not_change_output` (rows finish B, D, A, C → output stays
A, B, C, D), the 25-scenario Kick and 10-scenario Twitch end-to-end workbooks, duplicate
handling, resume after a crash, retry after an outage, verifier tamper detection, and the full
upload → review → re-download API flow.

`python -m tests.demo_server` (from `backend/`, `PYTHONPATH=.`) runs the real app against that
fake world for UI demos without network access — **test/demo only**.
