"""Regression checks for the configurable Interview Builder editor."""
import unittest
from unittest.mock import patch
from pathlib import Path

import server
import shared_engine as engine


class BuilderEditorTests(unittest.TestCase):
    def test_team_is_an_editor_but_not_an_export_admin(self):
        with patch.object(server, '_current_staff', return_value={'username': 'researcher', 'role': 'team'}):
            self.assertEqual(server.require_editor('token')['role'], 'team')
            with self.assertRaises(Exception):
                server.require_admin('token')

    def test_question_probe_hints_are_validated_and_preserved(self):
        settings = engine.default_settings()
        for index, question in enumerate(settings['questionnaire'], start=1):
            question['text'] = f'پرسش پژوهشگر {index}'
            question['goal'] = f'هدف پژوهشی {index}'
        settings['questionnaire'][0]['probe_hints'] = ['اگر مایلید، یک نمونه را توضیح دهید؟']
        payload = server.settings_payload(server.InterviewSettings(**settings))
        self.assertEqual(payload['questionnaire'][0]['probe_hints'], ['اگر مایلید، یک نمونه را توضیح دهید؟'])
        self.assertEqual(engine.question_probe_hints('Q1'), [])

    def test_editor_collection_is_scoped_away_from_pre_interview_rows(self):
        script = Path(__file__).parents[1] / 'static' / 'research-tools.js'
        source = script.read_text(encoding='utf-8')
        self.assertIn("#questionnaire-editor .question-edit[data-index]", source)
        self.assertIn("probe_hints", source)


if __name__ == '__main__':
    unittest.main()
