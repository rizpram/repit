# Deployment status — 2026-10-18

**NOT DEPLOYED. NOT VERIFIED LIVE.** No REPIT container has been started on the VPS by this work, and no Telegram reply from the production bot has been observed.

## Verified on 2026-10-18 (from a cloud execution environment)

- PR rizpram/repit#2 is open, not merged; head before this update was 9e7066c. CI runs 38574730559 and 38574718741 on 9e7066c concluded success (GitHub API).
- Issue rizpram/repit#1 is open.
- Repository is publicly readable (unauthenticated API access works), so `scripts/deploy.sh` can fetch the tested commit from codeload. If the repository is made private, the script's download step will fail and needs a different source transfer.
- Locked dependencies install cleanly (`pip check`: no broken requirements).
- 33 application tests pass, including the 7 integration tests against a disposable local PostgreSQL 16 loaded with `tests/fixtures/schema.sql` (Python 3.13 venv; CI uses 3.12).
- 11 deployment guard/rollback simulations pass in an isolated `python:3.12-slim` container without a Docker socket (8 previous + 3 new).
- `bash -n scripts/deploy.sh`, `compileall` and the reachable-history secret scan pass.

## Not verified here

- **Docker image build**: not run in this environment (outbound TLS goes through an intercepting proxy that the image's pip does not trust). CI builds the image on every push; check CI for the new head.
- **pip-audit**: not re-run here; last CI result is from the previous head.
- **Supabase schema compatibility**: `db.lzfrfpokshfrbnbaiuqo.supabase.co` / the pooler and the Supabase API were not reachable from this environment. Compatibility is only established against the contract snapshot in `tests/fixtures/schema.sql` (dated 2026-10-14). `python -m app.verify` checks the live schema, privileges, RLS bypass and webhook state as a preflight before anything is replaced.
- **SSH / VPS state**: TCP to 76.13.21.67:22 is blocked by this environment's egress policy, and no SSH key or agent is available. `api.telegram.org` is also blocked. The earlier "Permission denied" (2026-10-14) was the same kind of egress refusal, not a server-side authentication result. Nothing about the VPS (Docker version, existing containers, `/opt/rizpram-fitness-bot` contents) was observed.

## Deployment script fixes in this update

- `supabase-ca.crt` must now be root-owned, mode 644/444 and contain a PEM certificate. Previously a root-only CA (e.g. mode 600, which `umask 077` habits produce) would pass all checks, then fail TLS inside the non-root container (uid 10001) only after the old REPIT had been stopped. The check now runs before any build or Docker call.
- Existing-container detection ignores Compose one-off containers (`com.docker.compose.oneoff=False`). A leftover `compose run` container from an interrupted preflight previously caused a permanent "Multiple REPIT containers" refusal.
- `docs/RELEASE.md`: CA permission requirement; quoting `.env` values that contain `$` (Compose interpolation).

## How to finish the rollout (owner, in a private SSH session on the VPS)

1. Place secrets privately (never in Git or chat):
   - `/opt/rizpram-fitness-bot/.env` from `.env.example`: bot token, your numeric Telegram user ID, session-pooler URI (port 5432) for `lzfrfpokshfrbnbaiuqo` only, `DATABASE_CA_FILE=/run/secrets/supabase-ca.crt`. `sudo chown root:root .env && sudo chmod 600 .env`.
   - `/opt/rizpram-fitness-bot/supabase-ca.crt` from Supabase Dashboard → Database settings → SSL certificate. `sudo chown root:root supabase-ca.crt && sudo chmod 644 supabase-ca.crt`.
2. Check the CI run for the new PR head is green, then run with that exact 40-character SHA:

       cd /tmp && curl -fsSLO https://raw.githubusercontent.com/rizpram/repit/<SHA>/scripts/deploy.sh
       sudo bash deploy.sh <SHA>

3. When the script prints the prompt, send `/start` and `/target` to the bot from the allowed account within 3 minutes. Only the line `VERIFIED_LIVE:` counts as live; anything ending in `DEPLOYMENT_NOT_LIVE` means REPIT was rolled back or left unchanged.
4. Share the sanitized report path's contents (it contains no secrets) or paste the final lines into PR rizpram/repit#2.

The script touches only `/opt/rizpram-fitness-bot` and the `rizpram-fitness-bot` Compose project: no host ports, migrations, reboot, firewall, Nginx, HestiaCP, PM2 or other containers.

## Remaining limitations (unchanged)

- Weekly coach is a deterministic recap, not AI analysis.
- Food photo vision provider has never been tested live; it is disabled unless `VISION_ENABLED=true`.
- Only `/start` and `/target` are part of the scripted live proof; other commands are covered by automated tests until exercised live.
