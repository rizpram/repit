import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from app import diagnostics
from app.verify import REQUIRED,check_schema

class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        diagnostics.STATE.clear()

    def test_live_requires_poll_and_actual_replies(self):
        value={'started_at':100,'last_db_success':110}
        self.assertFalse(diagnostics.evidence(value,now=120,require_commands=True)['verified'])
        value['last_poll_success']=115
        self.assertTrue(diagnostics.evidence(value,now=120)['verified'])
        self.assertFalse(diagnostics.evidence(value,now=120,require_commands=True)['verified'])
        value['command_replies']={'/start':116,'/target':117}
        self.assertTrue(diagnostics.evidence(value,now=120,require_commands=True)['verified'])
        self.assertFalse(diagnostics.evidence(value,now=300,require_commands=True)['verified'])
        value['started_at']=118
        self.assertFalse(diagnostics.evidence(value,now=120,require_commands=True)['verified'])

    def test_only_safe_command_names_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'runtime.json'
            diagnostics.mark('started_at',path=path,now=100)
            diagnostics.mark('last_reply_success','/start',path=path,now=110)
            diagnostics.mark('last_reply_success','private food description',path=path,now=111)
            value=json.loads(path.read_text())
            self.assertEqual(value['command_replies'],{'/start':110})
            self.assertNotIn('private food',path.read_text())

    async def test_poll_marker_only_after_success(self):
        from aiogram.methods import GetUpdates,GetMe
        request=AsyncMock(return_value=[])
        with patch('app.diagnostics.mark') as mark:
            await diagnostics.record_request(request,None,GetUpdates())
            mark.assert_called_once_with('last_poll_success')
            mark.reset_mock()
            await diagnostics.record_request(request,None,GetMe())
            mark.assert_not_called()
            request.side_effect=RuntimeError('network failure')
            with self.assertRaises(RuntimeError):
                await diagnostics.record_request(request,None,GetUpdates())
            mark.assert_not_called()

    def test_schema_contract_missing_column(self):
        rows=[{'table_name':table,'column_name':column} for table,columns in REQUIRED.items() for column in columns]
        self.assertTrue(check_schema(rows))
        rows=[r for r in rows if r!=dict(table_name='bot_events',column_name='telegram_update_id')]
        self.assertFalse(check_schema(rows))
