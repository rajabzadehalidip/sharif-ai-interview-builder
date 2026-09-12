"""Regression checks for immediate, version-safe protocol publication."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import server
import shared_engine as engine


def usable_settings(first_question: str) -> dict:
    settings = engine.default_settings()
    settings['questionnaire'] = [
        {
            'id': 'Q1', 'text': first_question, 'goal': 'ثبت تعریف یا برداشت اولیهٔ فرد.',
            'kind': 'open', 'options': [], 'probe_limit': 1, 'probe_hints': [], 'branches': {},
        },
        {
            'id': 'Q2', 'text': 'نکتهٔ دیگری هست که مایل باشید اضافه کنید؟',
            'goal': 'دعوت پایانی اختیاری.', 'kind': 'open', 'options': [],
            'probe_limit': 0, 'probe_hints': [], 'branches': {},
        },
    ]
    return settings


class PublishActivationTests(unittest.TestCase):
    def test_publish_is_immediate_for_new_sessions_and_pins_existing_ones(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'DB_PATH', str(Path(folder) / 'test.sqlite')):
            server.init_db()
            staff = {'username': 'owner', 'role': 'admin'}
            with patch.object(server, '_current_staff', return_value=staff):
                first = usable_settings('نسخهٔ نخستِ پرسش چیست؟')
                version_one = server.publish_settings(server.InterviewSettings(**first), 'token')['version']
                original = server.create_session(server.CreateSession(expected_settings_version=version_one))
                self.assertEqual(original['settings_version'], version_one)
                self.assertIn('نسخهٔ نخست', original['messages'][0]['content'])

                second = usable_settings('نسخهٔ منتشرشدهٔ جدید چیست؟')
                second['based_on'] = version_one
                version_two = server.publish_settings(server.InterviewSettings(**second), 'token')['version']

                with self.assertRaises(HTTPException) as stale:
                    server.create_session(server.CreateSession(expected_settings_version=version_one))
                self.assertEqual(stale.exception.status_code, 409)

                current = server.create_session(server.CreateSession(expected_settings_version=version_two))
                self.assertEqual(current['settings_version'], version_two)
                self.assertIn('نسخهٔ منتشرشدهٔ جدید', current['messages'][0]['content'])
                # The session already underway preserves its scientific record.
                self.assertIn('نسخهٔ نخست', server.load(original['id']).messages[0]['content'])


if __name__ == '__main__':
    unittest.main()
