"""Camera metadata fixtures; no mock camera is exposed by the production app."""
import unittest
from unittest.mock import AsyncMock, patch

from app.providers.camera import discover_youtube_id, fetch_camera, infer_provider, safe_url, youtube_id


class CameraParsingTests(unittest.TestCase):
    def test_supported_youtube_urls(self):
        for url in ('https://www.youtube.com/embed/UqrwUKSkMEE?autoplay=1', 'https://youtube.com/watch?v=UqrwUKSkMEE', 'https://youtu.be/UqrwUKSkMEE', 'https://www.youtube-nocookie.com/embed/UqrwUKSkMEE'):
            self.assertEqual(youtube_id(url), 'UqrwUKSkMEE')

    def test_wrong_hosts_and_invalid_ids(self):
        for url in ('https://www.youtube.com.evil.example/embed/UqrwUKSkMEE', 'https://example.com/embed/UqrwUKSkMEE', 'https://youtube.com/embed/short'):
            self.assertIsNone(youtube_id(url))

    def test_lazy_official_embed(self):
        page = '<iframe src="about:blank" data-src="//www.youtube.com/embed/UqrwUKSkMEE?autoplay=1&amp;mute=1"></iframe>'
        self.assertEqual(discover_youtube_id(page), 'UqrwUKSkMEE')
        self.assertIsNone(discover_youtube_id('<h1>No camera available</h1>'))

    def test_unsafe_urls(self):
        for url in ('javascript:alert(1)', 'file:///etc/passwd', 'https://secret@example.com/stream', '/relative'):
            with self.assertRaises(ValueError):
                safe_url(url)

    def test_alternative_detection(self):
        self.assertEqual(infer_provider('https://example.com/lake.jpg?version=1'), 'image')
        self.assertEqual(infer_provider('https://youtu.be/UqrwUKSkMEE'), 'youtube')
        self.assertEqual(infer_provider('https://example.com/player'), 'iframe')


class CameraFetchTests(unittest.IsolatedAsyncioTestCase):
    def config(self):
        return {'camera': {'provider': 'youtube', 'source_page': 'https://lakeconroe.com/camera/', 'url': 'https://www.youtube.com/embed/UqrwUKSkMEE'}}

    async def test_discovery_does_not_claim_playback(self):
        with patch('app.providers.camera.get_text', AsyncMock(return_value='<iframe src="https://www.youtube.com/embed/abcdefghijk"></iframe>')):
            result = await fetch_camera(self.config(), None)
        self.assertEqual(result['video_id'], 'abcdefghijk')
        self.assertEqual(result['status'], 'discovered')
        self.assertFalse(result['playback_verified'])

    async def test_discovery_failure_keeps_honest_configured_source(self):
        with patch('app.providers.camera.get_text', AsyncMock(side_effect=RuntimeError('secret-not-to-expose'))):
            result = await fetch_camera(self.config(), None)
        self.assertEqual(result['video_id'], 'UqrwUKSkMEE')
        self.assertEqual(result['status'], 'configured')
        self.assertFalse(result['playback_verified'])
        self.assertTrue(result['limitations'])
        self.assertNotIn('secret-not-to-expose', ' '.join(result['limitations']))

    async def test_disabled_source_never_fetches(self):
        with patch('app.providers.camera.get_text', AsyncMock()) as mock:
            result = await fetch_camera({'camera': {'provider': 'disabled'}}, None)
        mock.assert_not_awaited()
        self.assertEqual(result['provider'], 'disabled')
