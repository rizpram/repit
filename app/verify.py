"""Read-only DB/TLS and Telegram preflight. Never polls updates."""
import argparse
import asyncio
import json
import logging
import os
from app.security import database_options, setup_logging

REQUIRED = {
    'users': {'id','telegram_user_id','telegram_chat_id','timezone','is_active','onboarding_completed'},
    'user_profiles': {'user_id','birth_date','sex_for_bmr','height_cm','current_weight_kg','target_weight_kg','activity_level'},
    'nutrition_goals': {'user_id','daily_calories','daily_protein_g','effective_from','effective_to','goal_mode','calculation_method','user_confirmed'},
    'body_weight_logs': {'user_id','measured_at','weight_kg'},
    'bot_events': {'telegram_update_id','event_type','status'},
    'conversation_states': {'user_id','payload'},
    'food_logs': {'user_id','description','calories','protein_g','carbs_g','fat_g','confirmed'},
    'workout_sessions': {'id','user_id','workout_at','title','fingerprint','raw_text'},
    'workout_sets': {'session_id','exercise_name','set_number','weight_kg','reps'},
    'coach_reports': {'user_id','week_start','report_text'},
    'reminder_settings': {'user_id','reminder_type','local_time','day_of_week','enabled'},
    'notification_deliveries': {'user_id','reminder_type','scheduled_for','status'},
}

def check_schema(rows):
    actual = {}
    for row in rows:
        actual.setdefault(row['table_name'], set()).add(row['column_name'])
    return all(columns <= actual.get(table,set()) for table,columns in REQUIRED.items())

async def verify(notify=False):
    import asyncpg
    from aiogram import Bot
    token = os.environ['TELEGRAM_BOT_TOKEN']
    allowed = int(os.environ['TELEGRAM_ALLOWED_USER_ID'])
    if not token or token == 'replace_locally' or allowed <= 0:
        raise ValueError('Private credentials not configured')
    dsn,tls = database_options(os.environ['DATABASE_URL'],os.getenv('DATABASE_CA_FILE'))
    conn = await asyncpg.connect(dsn,ssl=tls,command_timeout=30)
    bot = None
    try:
        await conn.fetchval('select 1')
        rows = await conn.fetch("select table_name,column_name from information_schema.columns where table_schema='fitness'")
        if not check_schema(rows):
            raise ValueError('Schema differs; do not replay historical migrations')
        for table in REQUIRED:
            # has_table_privilege with comma list means ANY; check each separately.
            for privilege in ('SELECT','INSERT','UPDATE','DELETE'):
                if not await conn.fetchval("select has_table_privilege(current_user,$1,$2)",'fitness.'+table,privilege):
                    raise ValueError('Role lacks fitness table privileges')
        role = await conn.fetchrow('select rolsuper,rolbypassrls from pg_roles where rolname=current_user')
        if not role or not (role['rolsuper'] or role['rolbypassrls']):
            # This private backend schema has no public end-user policies.
            raise ValueError('Use the authorized backend database role with RLS bypass')
        sequences = await conn.fetch("""select c.oid from pg_class c join pg_namespace n on n.oid=c.relnamespace
            where n.nspname='fitness' and c.relkind='S'""")
        for sequence in sequences:
            if not await conn.fetchval("select has_sequence_privilege(current_user,$1::oid,'USAGE')",sequence['oid']):
                raise ValueError('Role lacks fitness identity sequence privileges')
        bot = Bot(token)
        identity = await bot.get_me()
        webhook = await bot.get_webhook_info()
        if webhook.url:
            raise ValueError('Existing webhook; polling deployment refused')
        if notify:
            chat = await conn.fetchval('select telegram_chat_id from fitness.users where telegram_user_id=$1',allowed)
            await bot.send_message(chat or allowed,'REPIT DB/TLS and Telegram identity checks passed. Please send /start and /target to verify command processing. Food vision remains optional.')
        return {'database_tls':True,'fitness_schema':True,'telegram_identity':True,
                'webhook_absent':True,'bot_username':identity.username,'command_prompt_sent':notify}
    finally:
        if bot:
            await bot.session.close()
        await conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--notify',action='store_true')
    args = parser.parse_args()
    setup_logging()
    try:
        print(json.dumps(asyncio.run(verify(args.notify))))
    except Exception:
        logging.error('Preflight failed: check private credentials, Supabase CA/permissions, schema and webhook state')
        raise SystemExit(1) from None
