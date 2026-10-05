import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('guard_review', Path(__file__).resolve().parents[1] / 'scripts/security_guard.py')
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class SecurityReviewFixtureTests(unittest.TestCase):
    def test_review_registry_is_exact_79_objects_81_paths(self):
        self.assertEqual(len(guard.REVIEWED_ACE_SOURCE_PATHS), 79)
        self.assertEqual(sum(len(paths) for paths in guard.REVIEWED_ACE_SOURCE_PATHS.values()), 81)

    def test_review_requires_digest_and_every_exact_path_boundary(self):
        digest, ends = next(iter(guard.REVIEWED_ACE_SOURCE_PATHS.items()))
        end = ends[0]
        self.assertTrue(guard.reviewed_ace_paths(digest, [end, 'snapshot/runtime/plugin/' + end]))
        for paths in [[], ['other.js'], ['prefix' + end], [end, 'private/config.json']]:
            self.assertFalse(guard.reviewed_ace_paths(digest, paths))
        self.assertFalse(guard.reviewed_ace_paths('0' * 64, [end]))

    def test_review_only_covers_literal_lexer_rule_not_strong_keys_or_archives(self):
        self.assertEqual(guard.SOURCE_REVIEW_RULES, {'literal_credential_assignment', 'escaped_literal_credential_assignment'})
        for rule in ['openai_style_key', 'jwt', 'zip_literal_credential_assignment', 'invalid_gzip_payload']:
            self.assertNotIn(rule, guard.SOURCE_REVIEW_RULES)

    def test_malformed_review_registry_fails_closed(self):
        base = {'schema': 1, 'review': 'reviewed_ace_syntax_token_scopes',
                'allowed_rules': sorted(guard.SOURCE_REVIEW_RULES),
                'entries': [{'sha256': 'a' * 64, 'path_ends': ['plugin/ace-builds/mode.js']}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'registry.json'
            for entry in [{'sha256': 'bad', 'path_ends': ['plugin/ace-builds/mode.js']},
                          {'sha256': 'a' * 64, 'path_ends': ['plugin/ace-builds/../mode.js']},
                          {'sha256': 'a' * 64, 'path_ends': ['config.json']},
                          {'sha256': 'a' * 64, 'path_ends': ['plugin/ace-builds/']},
                          {'sha256': 'a' * 64, 'path_ends': []}]:
                data = {**base, 'entries': [entry]}; path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError):
                    guard.load_source_review_file(path)
            path.write_text(json.dumps({**base, 'allowed_rules': ['jwt']}), encoding='utf-8')
            with self.assertRaises(ValueError):
                guard.load_source_review_file(path)


if __name__ == '__main__':
    unittest.main()
