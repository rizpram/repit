"""Contract tests: disposable localhost PostgreSQL, never Supabase."""
import os
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from app.service import process,load_state
from app.main import notify
from app.security import LOCK_ID
DSN=os.getenv('TEST_DATABASE_URL')

@unittest.skipUnless(DSN,'Disposable local DB required; CI runs these tests')
class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncpg
        if urlsplit(DSN).hostname not in ('localhost','127.0.0.1'):
            raise RuntimeError('Tests refuse non-local DB')
        self.conn=await asyncpg.connect(DSN)
        await self.conn.execute('drop schema if exists fitness cascade')
        await self.conn.execute(Path('tests/fixtures/schema.sql').read_text())
        self.counter=100
        self.now=datetime.now(timezone.utc)

    async def asyncTearDown(self):
        await self.conn.close()

    async def send(self,text,vision=None,update=None):
        self.counter+=1
        return await process(self.conn,update or self.counter,123,123,text,self.now,vision)

    async def test_commands_and_restart(self):
        self.assertIn('/profile',await self.send('/start'))
        await self.send('/profile')
        await self.send('1988-10-11')
        self.assertEqual((await load_state(self.conn,1))['index'],1)
        self.assertIn('male',await self.send('/profile'))
        import asyncpg
        await self.conn.close()
        self.conn=await asyncpg.connect(DSN)
        for value in ('male','170','78','65','moderate'):
            await self.send(value)
        self.assertTrue(await self.conn.fetchval('select onboarding_completed from fitness.users'))
        await self.send('/goal cutting')
        await self.send('/confirmgoal')
        self.assertIn('cutting',await self.send('/target'))
        await self.send('/goal bulking')
        await self.send('/confirmgoal')
        self.assertIn('bulking',await self.send('/target'))
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.nutrition_goals'),2)
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.nutrition_goals where effective_to is null'),1)
        self.assertTrue(await self.conn.fetchval('select effective_to=effective_from from fitness.nutrition_goals where effective_to is not null'))
        await self.send('/weight 77.5')
        self.assertEqual(float(await self.conn.fetchval('select current_weight_kg from fitness.user_profiles')),77.5)
        self.assertIn('tercatat',await self.send('/food 550 35 60 18 Nasi ayam'))
        self.assertIn('550',await self.send('/today'))
        raw='/workout Workout\nBench\nSet 1: 20 kg x 8'
        self.assertIn('1 set',await self.send(raw))
        self.assertIn('duplikat',await self.send(raw))
        self.assertIn('bukan AI',await self.send('/coach'))
        await self.send('/reminder on')
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.reminder_settings where enabled'),5)
        await self.send('/reminder off')
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.reminder_settings where enabled'),0)

    async def test_atomic_retry(self):
        await self.send('/weight 78',update=900)
        self.assertIsNone(await self.send('/weight 78',update=900))
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.body_weight_logs'),1)
        await self.conn.execute("create function fitness.fail() returns trigger language plpgsql as $$ begin raise exception 'injected'; end $$")
        await self.conn.execute('create trigger fail before insert on fitness.body_weight_logs for each row execute function fitness.fail()')
        with self.assertRaises(Exception):
            await self.send('/weight 79',update=901)
        self.assertIsNone(await self.conn.fetchval('select id from fitness.bot_events where telegram_update_id=901'))
        await self.conn.execute('drop trigger fail on fitness.body_weight_logs')
        await self.send('/weight 79',update=901)
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.body_weight_logs'),2)

    async def test_manual_goal_photo_confirmation(self):
        await self.send('/goal manual 2000 140')
        await self.send('/confirmgoal')
        self.assertIn('2000',await self.send('/target'))
        meal=dict(description='Meal',calories=500,protein_g=30,carbs_g=50,fat_g=15)
        await self.send('',vision=meal)
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.food_logs'),0)
        await self.send('/cancel')
        await self.send('/confirmfood')
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.food_logs'),0)
        await self.send('',vision=meal)
        await self.send('/confirmfood')
        await self.send('/confirmfood')
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.food_logs'),1)
        text_meal=dict(meal,description='Nasi padang',ai_provider='OpenAI',origin='text')
        reply=await self.send('/food nasi padang',vision=text_meal)
        self.assertIn('Estimasi AI teks (OpenAI)',reply)
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.food_logs'),1)
        await self.send('/confirmfood')
        sources=await self.conn.fetch('select source from fitness.food_logs order by id')
        self.assertEqual([r['source'] for r in sources],['photo_estimate','text_estimate'])

    async def test_scheduler_and_poller_lock(self):
        await self.send('/reminder on')
        row=dict(await self.conn.fetchrow("select r.*,u.timezone,u.telegram_user_id,u.telegram_chat_id from fitness.reminder_settings r join fitness.users u on u.id=r.user_id where reminder_type='weekly_coach'"))
        bot=AsyncMock()
        sunday=datetime(2026,10,18,13,0,tzinfo=timezone.utc)
        await notify(self.conn,bot,row,sunday)
        await notify(self.conn,bot,row,sunday)
        bot.send_message.assert_awaited_once()
        self.assertIn('Weekly Review',bot.send_message.await_args.args[1])
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.coach_reports'),1)
        import asyncpg
        second=await asyncpg.connect(DSN)
        try:
            self.assertTrue(await self.conn.fetchval('select pg_try_advisory_lock($1)',LOCK_ID))
            self.assertFalse(await second.fetchval('select pg_try_advisory_lock($1)',LOCK_ID))
            await self.conn.fetchval('select pg_advisory_unlock($1)',LOCK_ID)
            self.assertTrue(await second.fetchval('select pg_try_advisory_lock($1)',LOCK_ID))
        finally:
            await second.close()

    async def test_invalid_no_partial_rows(self):
        for text in ('/weight nan','/food 550 nan 1 1 meal','/workout Workout\nBench\nSet 1: 10 kg x 8\nSet 2: 30s'):
            self.assertIn('tidak valid',await self.send(text))
        for table in ('body_weight_logs','food_logs','workout_sessions','workout_sets'):
            self.assertEqual(await self.conn.fetchval(f'select count(*) from fitness.{table}'),0)

    async def test_concurrent_duplicate_and_workout_rollback(self):
        import asyncpg
        import asyncio
        other=await asyncpg.connect(DSN)
        try:
            replies=await asyncio.gather(
                process(self.conn,990,123,123,'/weight 78',self.now),
                process(other,990,123,123,'/weight 78',self.now))
            self.assertEqual(sum(r is None for r in replies),1)
            self.assertEqual(await self.conn.fetchval('select count(*) from fitness.body_weight_logs'),1)
        finally:
            await other.close()
        await self.conn.execute("create function fitness.fail_set() returns trigger language plpgsql as $$ begin raise exception 'injected'; end $$")
        await self.conn.execute('create trigger fail before insert on fitness.workout_sets for each row execute function fitness.fail_set()')
        with self.assertRaises(Exception):
            await self.send('/workout Workout\nBench\nSet 1: 20 kg x 8',update=991)
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.workout_sessions'),0)
        self.assertIsNone(await self.conn.fetchval('select id from fitness.bot_events where telegram_update_id=991'))
        await self.conn.execute('drop trigger fail on fitness.workout_sets')
        await self.send('/workout Workout\nBench\nSet 1: 20 kg x 8',update=991)
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.workout_sets'),1)

    async def test_weight_draft_and_timezone(self):
        await self.send('/weight 78')
        self.assertEqual(float(await self.conn.fetchval('select current_weight_kg from fitness.user_profiles')),78)
        await self.send('/goal manual 2000 140')
        await self.send('/weight 79')
        self.assertEqual(await load_state(self.conn,1),{})
        await self.send('/confirmgoal')
        self.assertEqual(await self.conn.fetchval('select count(*) from fitness.nutrition_goals'),0)
        await self.send('/timezone Asia/Tokyo')
        self.assertEqual(await self.conn.fetchval('select timezone from fitness.users'),'Asia/Tokyo')
        await self.send('/reminder on')
        row=dict(await self.conn.fetchrow("select r.*,u.timezone,u.telegram_user_id,u.telegram_chat_id from fitness.reminder_settings r join fitness.users u on u.id=r.user_id where reminder_type='weekly_coach'"))
        bot=AsyncMock()
        # Still 20:00 Jakarta, not 20:00 Tokyo.
        await notify(self.conn,bot,row,datetime(2026,10,18,11,0,tzinfo=timezone.utc))
        bot.send_message.assert_not_awaited()
        await notify(self.conn,bot,row,datetime(2026,10,18,13,0,tzinfo=timezone.utc))
        bot.send_message.assert_awaited_once()
