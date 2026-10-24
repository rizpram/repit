# REPIT — Phase 1.2 production preparation

Private Telegram fitness logger. Release requires review and passing CI. **No live deployment is claimed.**

Implemented: persistent /profile onboarding (including skip/manual targets), /goal cutting|bulking|maintenance, /goal manual 2000 140, /confirmgoal, /target, /weight, /food, /workout Hevy strength imports, /today, /coach, /reminder on|off, /timezone, /cancel, optional photo estimation and /confirmfood.

The weekly coach is a **deterministic statistical report**; when `AI_COACH_ENABLED=true` a clearly labelled AI narrative is appended (only weekly aggregates are sent) and the stored report stays deterministic. Photo and free-text meal estimates (`/food nasi padang rendang`) are AI-backed only when configured and enabled, and remain drafts until /confirmfood. /cancel discards drafts; to correct an estimate, cancel and enter /food with correct values. No TKPI/USDA matching is claimed.

### AI providers per feature

Gemini is primary everywhere because its API has a free tier; a `GEMINI_API_KEY` alone runs all three features. OpenAI and Claude are optional paid fallbacks.

| Feature | Primary (default model) | Optional fallbacks |
|---|---|---|
| Food photo estimate | Gemini `gemini-3.8-flash` | OpenAI → Claude |
| Free-text meal estimate | Gemini `gemini-3.5-flash-lite` | OpenAI → Claude |
| Weekly coach narrative | Gemini `gemini-3.8-flash` | Claude → OpenAI |

A provider without a key is skipped. Rate limits (429) and transient 500/503 errors are retried once after 2 s, then the next provider is tried. Blocked or truncated Gemini answers count as failures. Routes and models can be overridden with `AI_ROUTE_<FEATURE>` and `AI_MODEL_<PROVIDER>[_<FEATURE>]` (see `.env.example`). Each reply names the provider that answered. On the Gemini free tier, Google may use inputs to improve its products.

Check providers live inside the running container (prints only OK/failure per feature and provider, never keys or output):

    sudo docker compose -p rizpram-fitness-bot exec fitness-bot python -m app.ai_check

## Authorized database

Only Supabase project **lzfrfpokshfrbnbaiuqo**, private schema fitness. Runtime rejects another project and transaction pooler port 6543. Use direct connection or **session pooler port 5432** with a dedicated session for the poller advisory lock. TLS verifies hostname and certificate, using the project's CA downloaded privately from the dashboard. URI SSL flags cannot weaken verification.

Live schema was inspected read-only on 2026-10-14. No schema migration is needed for this release. migrations/001_initial.sql is an incompatible historical draft: **do not run it**. migrations/003_repit_features.sql is historical, not a deployment script. tests/fixtures/schema.sql is solely for disposable local PostgreSQL, never Supabase. See docs/AUDIT.md.

## Behavior and boundaries

- User must match TELEGRAM_ALLOWED_USER_ID and private chat. Reminders query only that user.
- Update ID, domain writes and state changes commit together. A failed DB transaction is retried after poller restart. Committed duplicates never repeat writes.
- Telegram reply delivery is best effort after commit; Telegram has no idempotency key. A lost response may require /target or /today to check saved data.
- Sequential update handling protects polling offsets. DB failure stops polling. Lock-session loss stops the process.
- Same-day goals use half-open date intervals [effective_from,effective_to). Replaced same-day rows remain zero-length history. /target selects exactly the current valid row.
- Weight and profile update atomically. Changing weight invalidates a goal draft; active confirmed targets remain unchanged.
- Hevy parser supports English export dates, decimal comma, kg/lb, strength reps and bodyweight. Notes and links are ignored. Unsupported duration/distance sets reject the entire import; no partial sets are saved. Dated duplicates ignore title/spacing/notes/link; undated duplicates are scoped to local day.
- Reminders require /reminder on. Daily times follow /timezone (default Asia/Jakarta). Weekly **report** is sent Sunday 20:00 Asia/Jakarta, not a link to /coach. Five-minute scheduling grace; older missed runs are not backfilled. Uncertain sends aren't retried automatically; pending/failed deliveries need inspection.
- Healthcheck proves a recent DB/lock/scheduler heartbeat. It does not prove Telegram reachability, delivery, or successful AI provider calls.
- Logs redact known credentials, token patterns and DB URIs. Raw meals, photos and provider responses aren't logged.

## Tests

CI installs requirements.lock, audits dependencies, and runs unit/command tests, real PostgreSQL integration tests, 8 isolated deployment guard/rollback simulations, secret-history scan, compilation, Bash syntax, Docker build/import checks and Compose validation. Tests use localhost PostgreSQL only; no other Supabase project is used or created.

Local pure tests:
    python -m unittest tests.test_goals tests.test_domain tests.test_service -v

All tests with disposable localhost PostgreSQL:
    TEST_DATABASE_URL=<private localhost test URI> python -m unittest discover -s tests -v

Without TEST_DATABASE_URL integration tests explicitly skip. A skipped integration suite is not full release validation.

## Deployment

Use scripts/deploy.sh with an exact tested SHA in an authorized SSH session. Read docs/RELEASE.md and docs/DEPLOYMENT_STATUS.md for actual rollout status. Do not deploy until CI passes and review is complete. No auto-deploy workflow exists. Production Telegram and DB verification is a separate authorized step; never run a second poller using the production token for CI.

Keep .env private and chmod 600. .gitignore and .dockerignore exclude .env. Repository is public; private visibility is recommended. If any real credential was ever published, rotate it before release even if the file was deleted.
