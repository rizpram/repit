import os
import unittest
from unittest.mock import patch,AsyncMock,MagicMock
from app.vision import estimate

class VisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_and_unconfigured(self):
        bot=AsyncMock()
        photo=MagicMock(file_size=100)
        with patch.dict(os.environ,{'VISION_ENABLED':'false'}):
            self.assertIn('nonaktif',await estimate(bot,photo))
        with patch.dict(os.environ,{'VISION_ENABLED':'true','OPENAI_API_KEY':''}):
            self.assertIn('belum dikonfigurasi',await estimate(bot,photo))
        bot.download.assert_not_awaited()

    async def test_oversized_and_download_failure(self):
        bot=AsyncMock()
        with patch.dict(os.environ,{'VISION_ENABLED':'true','OPENAI_API_KEY':'test-only'}):
            self.assertIn('terlalu besar',await estimate(bot,MagicMock(file_size=6_000_000)))
            bot.download.assert_not_awaited()
            bot.download.side_effect=RuntimeError('private diagnostic')
            self.assertIn('belum ada data disimpan',await estimate(bot,MagicMock(file_size=100)))

    async def test_provider_estimate_and_invalid_response(self):
        bot=AsyncMock()
        async def download(photo,destination):
            destination.write(b'fake-jpeg')
        bot.download.side_effect=download
        response=MagicMock()
        response.status=200
        response.json=AsyncMock(return_value={'choices':[{'message':{'content':'{"description":"Meal","calories":500,"protein_g":30,"carbs_g":50,"fat_g":15}'}}]})
        response.__aenter__=AsyncMock(return_value=response)
        response.__aexit__=AsyncMock(return_value=False)
        session=MagicMock()
        session.post.return_value=response
        session.__aenter__=AsyncMock(return_value=session)
        session.__aexit__=AsyncMock(return_value=False)
        with patch.dict(os.environ,{'VISION_ENABLED':'true','OPENAI_API_KEY':'test-only'}),patch('aiohttp.ClientSession',return_value=session):
            result=await estimate(bot,MagicMock(file_size=100))
            self.assertEqual(result['calories'],500)
            self.assertEqual(result['description'],'Meal')
            self.assertEqual(session.post.call_args.args[0],'https://api.openai.com/v1/chat/completions')
            response.json.return_value={'choices':[{'message':{'content':'{}'}}]}
            self.assertIn('belum ada data disimpan',await estimate(bot,MagicMock(file_size=100)))
            response.status=429
            self.assertIn('provider gagal',await estimate(bot,MagicMock(file_size=100)))
