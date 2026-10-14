# Release, restart and rollback

## Gates

1. Review PR; CI unit + PostgreSQL integration + secret scan + Docker build must all pass.
2. Keep repository private if possible. Store Telegram token, allowed user ID and DB URI only in server .env. Never paste them into PR/logs.
3. Download authorized project's Supabase database CA to supabase-ca.crt. Set DATABASE_CA_FILE to container path /run/secrets/supabase-ca.crt.
4. For photo recognition, enabling VISION_ENABLED explicitly consents to sending food photos to OpenAI and potential cost. Fill OPENAI_API_KEY privately; provider failure never saves a meal.
5. Obtain separate authorization for live deployment and acceptance testing. This PR does not deploy, merge, reboot or change VPS settings.

## Isolated deployment (only after gates)

Use /opt/rizpram-fitness-bot exclusively. Inspect existing services read-only first. Do not edit Nginx/HestiaCP/PM2/sites or other Docker stacks. No exposed ports.
Copy reviewed source via approved secure transfer, create .env from .env.example locally, chmod 600 .env. Build a versioned image BEFORE stopping the existing REPIT container. Save old image ID and reviewed Git commit privately for rollback.

    cd /opt/rizpram-fitness-bot
    docker compose -p rizpram-fitness-bot build
    docker compose -p rizpram-fitness-bot up -d --no-build fitness-bot
    docker compose -p rizpram-fitness-bot ps
    docker compose -p rizpram-fitness-bot logs --tail=80 fitness-bot

Do not start a parallel old/new poller. The advisory lock prevents another REPIT process using this protocol, but cannot stop an older poller that lacks the lock. Stop any old REPIT poller before starting the release. Do not use transaction pooler; session pooler reserves a DB connection for the lock.

## Live acceptance (separate evidence)

In private authorized bot: /start, resume /profile after restart, /goal and /confirmgoal twice same day, /target, /weight, /food, /workout and duplicate paste, /reminder on/off, /coach. Use clearly identified test data and remove only those rows if authorized. Verify row counts, profile weight, history and bot_events against the authorized schema. Photo provider requires a real food photo, draft cancellation, explicit confirmation and row verification. Sunday scheduler can be checked with disposable tests; don't alter VPS clock or production schedules just to test it.

Verify TLS connection with the project CA. Inspect container health and lack of host port bindings. Record Telegram evidence and DB checks without credentials or private food/photo contents.

## Restart

    cd /opt/rizpram-fitness-bot
    docker compose -p rizpram-fitness-bot restart fitness-bot

State and dedup history live in Postgres, not container memory. Telegram replies after commit and notification delivery are best effort. Failed/pending notifications are not automatically resent because the original send may already have succeeded. Inspect privately before any manual resend.

Docker HEALTHCHECK reports status; Docker does not automatically restart a running unhealthy container. Fatal DB/lock failures exit so restart policy can recover; investigate sustained unhealthy status.

## Rollback

Stop only REPIT service, restore previously reviewed source/image in this directory, reuse unchanged .env and CA, rebuild/start only this service. No DB migration was applied, so schema rollback isn't required. Preserve bot_events and conversation_states. A baseline poller without dedup can replay a queued update: assess pending updates before rollback and prefer the last tested dedup-capable release. Never restore or truncate the entire Supabase schema.

No system upgrades, reboot, shared service changes or destructive Docker prune commands.


## Single-script rollout and evidence

Use scripts/deploy.sh with the exact tested PR SHA in an authorized root/sudo SSH session. Server .env and Supabase CA remain in /opt/rizpram-fitness-bot, separate from immutable releases. No secret file is copied into source or Docker image. Compose paths/image are supplied through REPIT_ENV_FILE, REPIT_CA_FILE and REPIT_IMAGE.

The script re-runs full tests against disposable localhost PostgreSQL using a container network namespace with no published ports. It refuses unfamiliar REPIT project ownership/config paths, multiple existing REPIT containers, symlink staging paths, or extra services/host ports. It preserves the former image/config and rolls back only REPIT on verification failure. Test containers have a unique deployment label and only those are cleaned up. Old releases/images are retained, not pruned.

At the Telegram prompt, send /start and /target within three minutes. /tmp/repit-runtime.json inside the container records only successful polling/DB timestamps and whitelisted command names (no arguments, messages or secrets). VERIFIED_LIVE requires recent successful getUpdates, DB heartbeat, Docker healthy, and successful real replies to both commands. Other commands remain covered by automated tests until separately exercised live.

See docs/DEPLOYMENT_STATUS.md for the current actual access/deployment status.
