import asyncio
import unittest
from unittest.mock import AsyncMock,MagicMock,patch
from aiogram import Bot,Dispatcher
from aiogram.types import Update
from app.main import handle_update

def update(uid=123,chat_type='private',photo=False):
    message=dict(message_id=1,date=1791980000,chat=dict(id=uid,type=chat_type),from_user=dict(id=uid,is_bot=False,first_name='Test'),text='/start')
    if photo:
        message.pop('text')
        message['photo']=[dict(file_id='test',file_unique_id='test',width=10,height=10,file_size=100)]
    return Update.model_validate(dict(update_id=1,message=message))

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_dispatcher_routes_and_authorizes(self):
        pool=MagicMock()
        conn=MagicMock()
        conn.fetchval=AsyncMock(return_value=None)
        pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__=AsyncMock(return_value=False)
        bot=Bot('123456789:'+('a'*30))
        dp=Dispatcher()
        failure=asyncio.get_running_loop().create_future()
        @dp.update.outer_middleware()
        async def durable(handler,event,data):
            return await handle_update(bot,pool,123,event,failure)
        with patch('app.main.process',new=AsyncMock(return_value='REPIT')) as process_mock,patch.object(Bot,'__call__',new=AsyncMock()) as send,patch('app.main.mark') as mark:
            await dp.feed_update(bot,update(uid=999))
            await dp.feed_update(bot,update(uid=123,chat_type='group'))
            pool.acquire.assert_not_called()
            await dp.feed_update(bot,update())
            process_mock.assert_awaited_once()
            self.assertEqual(process_mock.await_args.args[1],1)
            send.assert_awaited_once()
            mark.assert_called_once_with('last_reply_success','/start')
            self.assertFalse(failure.done())
        await bot.session.close()

    async def test_db_error_cancels_before_next_offset(self):
        pool=MagicMock()
        pool.acquire.side_effect=RuntimeError('injected')
        failure=asyncio.get_running_loop().create_future()
        with self.assertRaises(asyncio.CancelledError):
            await handle_update(AsyncMock(),pool,123,update(),failure)
        self.assertTrue(failure.done())

    async def test_committed_duplicate_skips_photo_provider(self):
        pool=MagicMock()
        conn=MagicMock()
        conn.fetchval=AsyncMock(return_value=1)
        pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__=AsyncMock(return_value=False)
        failure=asyncio.get_running_loop().create_future()
        with patch('app.main.estimate',new=AsyncMock()) as vision:
            await handle_update(AsyncMock(),pool,123,update(photo=True),failure)
            vision.assert_not_awaited()
