# RIZPRAM Fitness & Calorie Bot — Phase 1.1

Private Telegram bot foundation. **Implemented**: `/start`, `/profile` conversational setup, `/goal cutting|bulking|maintenance`, `/confirmgoal`, `/target`, `/weight 77.5`, `/today` (weight + Phase 2 placeholder), `/reminder` (schedule placeholder), `/cancel`.

**Not implemented**: food image logging, Hevy imports, weekly coach scheduler, automated daily reminders, meal data, workout data. Never claim these are live.

## Database

The existing Supabase project `lzfrfpokshfrbnbaiuqo` already has the `fitness` private schema and goal columns applied. Do not re-run `migrations/001_initial.sql`: it was an early draft with mismatched tables. `migrations/README.md` explains live schema ownership.

Use the Supabase **Session Pooler** or direct PostgreSQL connection URI from the project dashboard. Ensure the role has permissions for the `fitness` schema. TLS is required. Do not put DB password or Telegram token in Git.

## BotFather

1. In https://t.me/BotFather use `/newbot`, pick a display name and available username.
2. Keep the token private. To find your numeric Telegram user ID use a trusted Telegram ID helper or Telegram API `getUpdates` locally, never share token or paste it in chat.
3. Create `.env` **only on your server**, based on `.env.example`; chmod 600.

## Deploy (after reviewing existing VPS services)

```bash
# First inspect existing workloads; do not change their ports or proxies
sudo docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}'
sudo ss -lntp
sudo mkdir -p /opt/rizpram-fitness-bot
# Copy the project there by an approved secure transfer method.
cd /opt/rizpram-fitness-bot
cp .env.example .env
chmod 600 .env
# edit .env locally on VPS and fill secrets; never paste secrets in chat
sudo docker compose -p rizpram-fitness-bot up -d --build
sudo docker compose -p rizpram-fitness-bot logs --tail=80
```

Long polling needs no inbound port or Nginx change. One bot instance only. Never run `docker compose down` on unrelated stacks.

## Tests

```bash
python -m unittest discover -s tests -v
python -m compileall -q app
```

**Caution**: BMR estimates use Mifflin-St Jeor and simple activity multipliers. Not a medical prescription. Calories are proposed and only saved on `/confirmgoal`. The formula requires an adult profile and a binary formula reference; future UX should support manual targets when formula reference is not appropriate. Weekly trends should guide later adjustments.

## Phase 1.2 additions
- /food 550 35 60 18 Nasi ayam (manual kcal/protein/carbs/fat)
- /workout followed by pasted Hevy text; best-effort set extraction, exact duplicate detection
- /coach weekly statistical recap (not AI-generated)
- /reminder on and /reminder off (opt-in; timezone Asia/Jakarta)
- Persistent onboarding and goal draft in fitness.conversation_states
- /weight also updates current weight in user profile
- Same-day goal switches supported by closing old current goal on current date
- Telegram update deduplication is not yet implemented; avoid running multiple pollers.
- Food photo vision and provider-backed AI coach are NOT implemented.
- Docker healthcheck only checks that process namespace is present, NOT Telegram/DB reachability.
- DB migrations 001 and 003 are already applied to the live rizpram-fitness project; DO NOT re-run them.
- .env contains secrets: keep out of Git, do not share logs with credentials.
