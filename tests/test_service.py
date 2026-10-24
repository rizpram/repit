import json
import unittest
from unittest.mock import AsyncMock,MagicMock
from tests.test_domain import NOW
from app.service import load_state,command,process

def connection():
    conn=MagicMock()
    conn.fetchval=AsyncMock()
    conn.fetchrow=AsyncMock()
    conn.execute=AsyncMock()
    context=MagicMock()
    context.__aenter__=AsyncMock()
    context.__aexit__=AsyncMock(return_value=False)
    conn.transaction.return_value=context
    return conn

class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_restart(self):
        conn=connection()
        conn.fetchval.return_value='{"kind":"profile","index":1,"data":{"birth_date":"1988-10-11"}}'
        self.assertEqual((await load_state(conn,1))['index'],1)
        await command(conn,1,'/profile',NOW,'Asia/Jakarta')
        conn.execute.assert_not_called()

    async def test_duplicate_no_writes(self):
        conn=connection()
        conn.fetchval.return_value=None
        self.assertIsNone(await process(conn,2,3,3,'/weight 78',NOW))
        conn.execute.assert_not_called()
        self.assertEqual(conn.fetchval.await_count,1)

    async def test_vision_not_logged_before_confirmation(self):
        conn=connection()
        conn.fetchval.side_effect=[1,2,'Asia/Jakarta',None]
        meal=dict(description='Meal',calories=500,protein_g=30,carbs_g=50,fat_g=15)
        self.assertIn('Belum dicatat',await process(conn,3,4,4,'',NOW,meal))
        self.assertFalse(any('insert into fitness.food_logs' in c.args[0] for c in conn.execute.await_args_list))

    async def test_invalid_weight(self):
        conn=connection()
        conn.fetchval.return_value=None
        with self.assertRaises(ValueError):
            await command(conn,1,'/weight nan',NOW,'Asia/Jakarta')
        conn.execute.assert_not_called()

    async def test_confirmfood_clears_state(self):
        conn=connection()
        conn.fetchval.return_value=json.dumps(dict(kind='meal',meal=dict(description='Meal',calories=500,protein_g=30,carbs_g=50,fat_g=15)))
        await command(conn,1,'/confirmfood',NOW,'Asia/Jakarta')
        self.assertTrue(any('insert into fitness.food_logs' in c.args[0] for c in conn.execute.await_args_list))
        self.assertTrue(any('delete from fitness.conversation_states' in c.args[0] for c in conn.execute.await_args_list))
