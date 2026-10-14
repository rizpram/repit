"""Private single poller; long polling needs no inbound ports."""
import asyncio
import contextlib
import logging
import os
from datetime import datetime, timezone
from app.domain import reminder_due
from app.security import HEARTBEAT, LOCK_ID, database_options, setup_logging
from app.service import coach, process
from app.vision import estimate

async def notify(conn,bot,row,now):
    if row['reminder_type']=='weekly_coach':
        row=dict(row,timezone='Asia/Jakarta')
    scheduled=reminder_due(row,now)
    if scheduled is None:
        return
    delivery=await conn.fetchval('''insert into fitness.notification_deliveries(user_id,reminder_type,scheduled_for)
        values($1,$2,$3) on conflict do nothing returning id''',row['user_id'],row['reminder_type'],scheduled)
    if delivery is None:
        return
    try:
        if row['reminder_type']=='weekly_coach':
            text=await coach(conn,row['user_id'],now,'Asia/Jakarta')
        else:
            text={'morning_goal':'Target hari ini: /target','lunch':'Catat makan: /food','evening_check':'Cek progres: /today','daily_recap':'Rekap: /today'}[row['reminder_type']]
        await bot.send_message(row['telegram_chat_id'] or row['telegram_user_id'],text)
        await conn.execute("update fitness.notification_deliveries set status='sent',delivered_at=now() where id=$1",delivery)
    except Exception:
        logging.error('Notification delivery failed; inspect status')
        await conn.execute("update fitness.notification_deliveries set status='failed' where id=$1",delivery)

async def handle_update(bot,pool,allowed,event,failure):
    message=event.message
    if not message or not message.from_user or message.from_user.id!=allowed or message.chat.type!='private':
        return
    try:
        async with pool.acquire() as conn:
            if await conn.fetchval('select 1 from fitness.bot_events where telegram_update_id=$1',event.update_id):
                return
            vision=await estimate(bot,message.photo[-1]) if message.photo else None
            reply=await process(conn,event.update_id,allowed,message.chat.id,(message.text or '').strip(),datetime.now(timezone.utc),vision)
    except Exception:
        # aiogram catches ordinary handler errors. Cancel this polling task
        # and signal supervisor so no next batch acknowledges failed writes.
        if not failure.done():
            failure.set_result(True)
        raise asyncio.CancelledError()
    if reply:
        try:
            await message.answer(reply)
        except Exception:
            logging.error('Reply failed; committed writes will not replay')


async def run():
    import asyncpg
    from aiogram import Bot, Dispatcher
    token=os.environ['TELEGRAM_BOT_TOKEN']
    allowed=int(os.environ['TELEGRAM_ALLOWED_USER_ID'])
    if token=='replace_locally' or not token or allowed<=0:
        raise ValueError('Configure credentials privately')
    dsn,tls=database_options(os.environ['DATABASE_URL'],os.getenv('DATABASE_CA_FILE'))
    lock=await asyncpg.connect(dsn,ssl=tls,command_timeout=30)
    pool=bot=task=None
    failure=asyncio.get_running_loop().create_future()
    def lock_lost(connection):
        if not failure.done():
            failure.set_result(True)
    lock.add_termination_listener(lock_lost)
    try:
        if not await lock.fetchval('select pg_try_advisory_lock($1)',LOCK_ID):
            raise RuntimeError('Another REPIT poller owns lock')
        pool=await asyncpg.create_pool(dsn,ssl=tls,min_size=1,max_size=3,command_timeout=30)
        bot,dp=Bot(token),Dispatcher()

        @dp.update.outer_middleware()
        async def durable(handler,event,data):
            return await handle_update(bot,pool,allowed,event,failure)

        async def maintenance():
            while True:
                # Session disconnect is fatal; another process may acquire the lock.
                await lock.fetchval('select 1')
                async with pool.acquire() as conn:
                    rows=await conn.fetch('''select r.*,u.timezone,u.telegram_user_id,u.telegram_chat_id
                        from fitness.reminder_settings r join fitness.users u on u.id=r.user_id
                        where r.enabled and u.is_active and u.telegram_user_id=$1''',allowed)
                    for row in rows:
                        await notify(conn,bot,row,datetime.now(timezone.utc))
                HEARTBEAT.touch()
                await asyncio.sleep(30)

        task=asyncio.create_task(maintenance())
        poller=asyncio.create_task(dp.start_polling(bot,handle_as_tasks=False,allowed_updates=['message'],close_bot_session=False,handle_signals=True))
        try:
            done,_=await asyncio.wait([task,poller,failure],return_when=asyncio.FIRST_COMPLETED)
            if failure in done:
                raise RuntimeError('Update transaction failed')
            for item in done:
                item.result()
        finally:
            # stop_polling cancels its child polling task; cancelling only the
            # start_polling wrapper could leave a child fetching updates.
            if not poller.done():
                with contextlib.suppress(RuntimeError):
                    await dp.stop_polling()
            with contextlib.suppress(asyncio.CancelledError):
                await poller
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if bot:
            await bot.session.close()
        if pool:
            await pool.close()
        await lock.close()
        HEARTBEAT.unlink(missing_ok=True)

if __name__=='__main__':
    setup_logging()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.error('REPIT stopped; check configuration/connectivity privately')
        raise SystemExit(1) from None
