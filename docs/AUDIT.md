# Phase 1.2 audit — 2026-10-14

Baseline main: 6bee74f152572b8e4b4203054a74ace9c27e469c. Issue #1.
Only lzfrfpokshfrbnbaiuqo fitness inspected. No live DB or VPS writes.

## Findings fixed

| Finding | Change |
| --- | --- |
| asyncpg JSONB returned text; state.get fails | Explicit JSON decoding, JSON-safe dates |
| First profile completion converts date twice | Parse/store ISO string; convert only for SQL |
| Telegram retries duplicate writes | bot_events unique update ID in same transaction as writes |
| Profile/weight and session/sets may partially persist | One transaction, validation savepoint |
| Weight update before profile silently loses sync | Profile upsert with weight |
| Height accepts 20 cm despite DB minimum 50 | Validation matches actual limits; finite-only numbers |
| Formula target can exceed DB protein limit | Reject outside schema bounds, manual target option |
| Same-day goal validity undefined | Half-open date intervals, zero-length history retained |
| Date headers and quoted notes corrupt Hevy exercise names | Parse header, skip notes/links, reject unsupported sets |
| Workout duplicate hash depends on exact text | Normalize parsed sets and workout time/local day |
| Weekly reminder only sends /coach link | Generate, persist and send actual deterministic report |
| Fixed timezone for all reminders | Daily IANA profile timezone; weekly fixed Jakarta |
| Healthcheck tests process existence only | Recent DB/session/scheduler heartbeat |
| SSL require without certificate validation | Verified TLS context and project/session guard |
| Missing .env ignore files | Git/Docker exclusion and history scan in CI |
| No single poller ownership | Dedicated PostgreSQL session advisory lock |
| Exception logs can expose credentials | Sanitized formatter; no raw provider/body logging |

## Actual schema contract

Tables: users, user_profiles, nutrition_goals, body_weight_logs, bot_events, conversation_states, food_logs, workout_sessions, workout_sets, coach_reports, reminder_settings, notification_deliveries.

Verified uniqueness: telegram_user_id; telegram_update_id; one current nutrition goal per user; workout (user_id,fingerprint); coach (user_id,week_start); reminder (user_id,reminder_type); delivery (user_id,reminder_type,scheduled_for).

Verified goal date check permits effective_to=effective_from. Formula/food/weight validation aligns with inspected constraints. All 12 tables have RLS enabled; anon/authenticated have no USAGE on fitness or SELECT on these tables. No migrations required.

## Secret audit

Two existing commits were found. Initial commit tree contains only README; Phase 1.2 tree contains source, SQL, Docker, tests and README, with no .env. Retrieved baseline files contain no apparent real Telegram tokens, API keys or DB passwords. This is a heuristic review, not proof that credentials were never shared elsewhere. CI scans all reachable commit versions, printing paths only.

## Remaining live verification

No production Telegram polling, provider call or TLS connection was performed here. Unit mocks and disposable PostgreSQL are distinct from live acceptance checks. See RELEASE.md. CI result must be attached to PR; failures block release.
