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
