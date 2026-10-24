# Deployment status — 2026-10-18

**NOT DEPLOYED. NOT VERIFIED LIVE.** No REPIT container has been started on the VPS by this work, and no Telegram reply from the production bot has been observed.

## Re-check 2026-10-24 (cloud execution environment)

- PR #2 still open and unmerged, head da3239e (doc-only on top of release commit 0d712a7). CI runs 39140241282 and 39140127757 on da3239e: success.
- Re-run locally on da3239e with `requirements.lock` (Python 3.13): all 33 application tests pass, including the 7 integration tests against a disposable PostgreSQL 16; `bash -n scripts/deploy.sh` and the secret-history scan pass. The 11 guard simulations correctly refuse to run outside an isolated container; their evidence remains the CI runs above.
- Egress is unchanged: TCP 76.13.21.67:22, `api.telegram.org` and `*.supabase.co` are refused by this environment's proxy (HTTP 403 on CONNECT). No SSH key/agent and no link to the owner's computer or browser were available, so the VPS was not touched.
- Repository is still public, so the `deploy.sh` codeload download path still works.
- Release commit for rollout is unchanged: `0d712a7e0bc4bb8d90d946660951bfa7fb26f59c`. The owner steps below are still the only route to `VERIFIED_LIVE:`.

## Update 2026-10-24 — multi-provider AI and new release commit

- b8b00d9 routes AI features across providers, each opt-in and with fallback: food photo → Gemini, then OpenAI, then Claude; free-text `/food nasi padang` → OpenAI, then Gemini, then Claude; weekly coach narrative → Claude, then Gemini, then OpenAI (appended and labelled; the stored report stays deterministic). Provider calls run outside DB transactions.
- 1c32e56 bumps transitive `certifi` to 2026.10.19 for PYSEC-2026-4320 (new advisory; it made pip-audit fail CI on b8b00d9).
- CI on 1c32e56: runs 40074705535 and 40074702824 success (pip-audit, 44 app tests incl. PostgreSQL integration, secret scan, Docker build, 11 guard simulations, Compose validation). Locally: 44 app tests pass with a disposable PostgreSQL 16.
- No AI provider was called live: provider hosts are unreachable from this environment. Covered by mocked tests only until exercised on the VPS.
- **New release commit for rollout: `1c32e562fbd3f23019f2155a56346c550375cd49`.** It replaces 0d712a7 in the steps below.

## Update 2026-10-24 (later) — Gemini as primary provider

- a8df90f makes Gemini primary for every AI feature, so a `GEMINI_API_KEY` alone is enough (free tier; Google may use free-tier inputs to improve its products). Defaults: `gemini-3.8-flash` for photos and coach, `gemini-3.5-flash-lite` for typed meals. OpenAI and Claude remain optional paid fallbacks. Retries 429/500/503 once. Adds `python -m app.ai_check` for a live provider check.
- CI on a8df90f: runs 40079338042 and 40079334772 success. Locally: 47 app tests pass with a disposable PostgreSQL 16.
- Gemini has still not been called live from this environment.
- **Release commit for rollout is now `a8df90f94d35c287dacc0a9123e2b132823fd7db`** (replaces 1c32e56 in the steps below). After `VERIFIED_LIVE:`, run `sudo docker compose -p rizpram-fitness-bot exec fitness-bot python -m app.ai_check` to verify Gemini.

## Verified on 2026-10-18 (from a cloud execution environment)

- PR rizpram/repit#2 is open, not merged; head before this update was 9e7066c. CI runs 38574730559 and 38574718741 on 9e7066c concluded success (GitHub API).
- Issue rizpram/repit#1 is open.
- Repository is publicly readable (unauthenticated API access works), so `scripts/deploy.sh` can fetch the tested commit from codeload. If the repository is made private, the script's download step will fail and needs a different source transfer.
- Locked dependencies install cleanly (`pip check`: no broken requirements).
- 33 application tests pass, including the 7 integration tests against a disposable local PostgreSQL 16 loaded with `tests/fixtures/schema.sql` (Python 3.13 venv; CI uses 3.12).
- 11 deployment guard/rollback simulations pass in an isolated `python:3.12-slim` container without a Docker socket (8 previous + 3 new).
- `bash -n scripts/deploy.sh`, `compileall` and the reachable-history secret scan pass.

## CI on release commit 0d712a7 (GitHub Actions)

- Push run https://github.com/rizpram/repit/actions/runs/39139979401 and pull_request run 39139982770: success.
- Steps passed: locked install, pip-audit of runtime requirements, Bash syntax, all unit + PostgreSQL integration tests, compileall, secret scan, **Docker image build**, 11 isolated guard/rollback simulations, image import / absent-secret checks, Compose validation with placeholders.
- The Docker build was not run in the cloud session itself (intercepting egress proxy); the CI build above is the build evidence.

## Not verified here

- **Supabase schema compatibility**: `db.lzfrfpokshfrbnbaiuqo.supabase.co` / the pooler and the Supabase API were not reachable from this environment. Compatibility is only established against the contract snapshot in `tests/fixtures/schema.sql` (dated 2026-10-14). `python -m app.verify` checks the live schema, privileges, RLS bypass and webhook state as a preflight before anything is replaced.
- **SSH / VPS state**: TCP to 76.13.21.67:22 is blocked by this environment's egress policy, and no SSH key or agent is available. `api.telegram.org` is also blocked. The earlier "Permission denied" (2026-10-14) was the same kind of egress refusal, not a server-side authentication result. Nothing about the VPS (Docker version, existing containers, `/opt/rizpram-fitness-bot` contents) was observed.

## Deployment script fixes in this update

- `supabase-ca.crt` must now be root-owned, mode 644/444 and contain a PEM certificate. Previously a root-only CA (e.g. mode 600, which `umask 077` habits produce) would pass all checks, then fail TLS inside the non-root container (uid 10001) only after the old REPIT had been stopped. The check now runs before any build or Docker call.
- Existing-container detection ignores Compose one-off containers (`com.docker.compose.oneoff=False`). A leftover `compose run` container from an interrupted preflight previously caused a permanent "Multiple REPIT containers" refusal.
- `docs/RELEASE.md`: CA permission requirement; quoting `.env` values that contain `$` (Compose interpolation).

## How to finish the rollout (owner, in a private SSH session on the VPS)

1. Place secrets privately (never in Git or chat):
   - `/opt/rizpram-fitness-bot/.env` from `.env.example`: bot token, your numeric Telegram user ID, session-pooler URI (port 5432) for `lzfrfpokshfrbnbaiuqo` only, `DATABASE_CA_FILE=/run/secrets/supabase-ca.crt`. Optional AI: `GEMINI_API_KEY` (enough on its own), optionally `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`, and the per-feature `AI_*_ENABLED` flags (see `.env.example`). `sudo chown root:root .env && sudo chmod 600 .env`.
   - `/opt/rizpram-fitness-bot/supabase-ca.crt` from Supabase Dashboard → Database settings → SSL certificate. `sudo chown root:root supabase-ca.crt && sudo chmod 644 supabase-ca.crt`.
2. Run with the CI-verified code commit a8df90f94d35c287dacc0a9123e2b132823fd7db (later doc-only commits are fine if their CI is green):

       cd /tmp && curl -fsSLO https://raw.githubusercontent.com/rizpram/repit/a8df90f94d35c287dacc0a9123e2b132823fd7db/scripts/deploy.sh
       sudo bash deploy.sh a8df90f94d35c287dacc0a9123e2b132823fd7db

3. When the script prints the prompt, send `/start` and `/target` to the bot from the allowed account within 3 minutes. Only the line `VERIFIED_LIVE:` counts as live; anything ending in `DEPLOYMENT_NOT_LIVE` means REPIT was rolled back or left unchanged.
4. Share the sanitized report path's contents (it contains no secrets) or paste the final lines into PR rizpram/repit#2.

The script touches only `/opt/rizpram-fitness-bot` and the `rizpram-fitness-bot` Compose project: no host ports, migrations, reboot, firewall, Nginx, HestiaCP, PM2 or other containers.

## Remaining limitations (unchanged)

- Weekly coach is a deterministic recap, not AI analysis.
- Food photo vision provider has never been tested live; it is disabled unless `VISION_ENABLED=true`.
- Only `/start` and `/target` are part of the scripted live proof; other commands are covered by automated tests until exercised live.
