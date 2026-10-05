import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import security_guard as guard
import technical_archive as archive

TARGET = 'docs/technical/archive/anima_lora_forge/profiles/test_character.json'
SOURCE = TARGET.removeprefix('docs/technical/archive/')


def payload(strong=False):
    value = ('sk-' if strong else 'character') + 'A1b2C3d4E5f6G7h8' * 3
    return json.dumps({'trigger_token': value}).encode()


def registry(data=None, target=TARGET, confirmed=True):
    return {'schema': 1, 'review_type': guard.TRAINING_REVIEW_TYPE, 'entries': [{
        'target': target, 'sha256': hashlib.sha256(data if data is not None else payload()).hexdigest(),
        'allowed_rules': [guard.TRAINING_REVIEW_RULE], 'confirmed': confirmed,
        'reason': guard.TRAINING_REVIEW_REASON}]}


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


class TrainingTriggerReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_exact_digest_full_path_and_only_literal_rule(self):
        data = payload()
        original = guard.patterns(data)
        self.assertEqual(original, {'literal_credential_assignment'})
        reviews = guard.parse_training_trigger_reviews(encoded(registry(data)))
        remaining, removed = guard.apply_training_trigger_review(hashlib.sha256(data).hexdigest(), [TARGET], original, reviews)
        self.assertEqual(remaining, set())
        self.assertEqual(removed, {'literal_credential_assignment'})

    def test_modified_bytes_are_never_approved(self):
        reviews = guard.parse_training_trigger_reviews(encoded(registry()))
        changed = payload() + b'\n'
        remaining, removed = guard.apply_training_trigger_review(hashlib.sha256(changed).hexdigest(), [TARGET], guard.patterns(changed), reviews)
        self.assertIn('literal_credential_assignment', remaining)
        self.assertFalse(removed)

    def test_prefix_suffix_case_slash_and_dot_aliases_are_not_approved(self):
        reviews = guard.parse_training_trigger_reviews(encoded(registry()))
        digest = hashlib.sha256(payload()).hexdigest()
        bad = ['prefix/' + TARGET, TARGET.upper(), TARGET.replace('/', '\\'),
               TARGET.replace('/profiles/', '/profiles/./'), TARGET.replace('/profiles/', '/profiles/other/../'),
               TARGET.removeprefix('docs/technical/archive/'), TARGET + '.copy', '/' + TARGET]
        for path in bad:
            with self.subTest(path=path):
                remaining, removed = guard.apply_training_trigger_review(digest, [path], {guard.TRAINING_REVIEW_RULE}, reviews)
                self.assertEqual(remaining, {guard.TRAINING_REVIEW_RULE})
                self.assertFalse(removed)

    def test_every_blob_alias_must_be_individually_approved(self):
        digest = hashlib.sha256(payload()).hexdigest()
        reviews = guard.parse_training_trigger_reviews(encoded(registry()))
        other = TARGET.replace('test_character', 'other_character')
        remaining, _ = guard.apply_training_trigger_review(digest, [TARGET, other], {guard.TRAINING_REVIEW_RULE}, reviews)
        self.assertEqual(remaining, {guard.TRAINING_REVIEW_RULE})
        value = registry()
        value['entries'].append({**value['entries'][0], 'target': other})
        reviews = guard.parse_training_trigger_reviews(encoded(value))
        remaining, _ = guard.apply_training_trigger_review(digest, [TARGET, other], {guard.TRAINING_REVIEW_RULE}, reviews)
        self.assertFalse(remaining)

    def test_all_other_rules_survive_even_with_approved_identity(self):
        data = payload(strong=True)
        reviews = guard.parse_training_trigger_reviews(encoded(registry(data)))
        rules = guard.patterns(data) | {'jwt', 'escaped_literal_credential_assignment', 'gzip_literal_credential_assignment'}
        remaining, removed = guard.apply_training_trigger_review(hashlib.sha256(data).hexdigest(), [TARGET], rules, reviews)
        self.assertEqual(removed, {'literal_credential_assignment'})
        self.assertEqual(remaining, rules - {'literal_credential_assignment'})
        self.assertIn('openai_style_key', remaining)

    def test_missing_and_unconfirmed_registries_grant_nothing(self):
        for reviews in [guard.parse_training_trigger_reviews(None),
                        guard.parse_training_trigger_reviews(encoded(registry(confirmed=False)))]:
            remaining, removed = guard.apply_training_trigger_review(hashlib.sha256(payload()).hexdigest(), [TARGET], {guard.TRAINING_REVIEW_RULE}, reviews)
            self.assertEqual(remaining, {guard.TRAINING_REVIEW_RULE})
            self.assertFalse(removed)
        self.assertEqual(guard.parse_training_trigger_reviews(encoded(registry(confirmed=False)))['unconfirmed'], 1)

    def test_extra_domain_documents_are_exact_names_not_directory_permissions(self):
        for target in guard.TRAINING_REVIEW_EXTRA_TARGETS:
            self.assertTrue(guard.training_review_target(target))
            self.assertFalse(guard.training_review_target(target.replace('alicia_bell', 'other_character')))
            self.assertFalse(guard.training_review_target(target + '.json'))
        self.assertEqual(len(guard.TRAINING_REVIEW_EXTRA_TARGETS), 3)
        self.assertFalse(guard.training_review_target('docs/technical/archive/character_lora_forge/characters/alicia_bell/01_visual_spec/other.json'))

    def test_bad_registry_schema_rules_and_decisions_fail_closed(self):
        mutations = []
        for key, value in [('schema', True), ('schema', 2), ('review_type', 'generic_exemption'), ('entries', {})]:
            item = registry(); item[key] = value; mutations.append(item)
        for key, value in [('target', 'config.json'), ('target', TARGET.replace('/profiles/', '/profiles/../')),
                           ('target', TARGET + ':stream'), ('sha256', 'invalid'), ('sha256', 'A' * 64),
                           ('allowed_rules', ['jwt']), ('allowed_rules', ['literal_credential_assignment', 'openai_style_key']),
                           ('allowed_rules', ['literal_credential_assignment'] * 2), ('confirmed', 'true'),
                           ('reason', 'arbitrary broad exception')]:
            item = registry(); item['entries'][0][key] = value; mutations.append(item)
        item = registry(); del item['entries'][0]['confirmed']; mutations.append(item)
        item = registry(); item['entries'][0]['path_ends'] = ['profiles/test_character.json']; mutations.append(item)
        item = registry(); item['entries'].append(copy.deepcopy(item['entries'][0])); mutations.append(item)
        for value in mutations:
            with self.subTest(value=list(value)), self.assertRaises(ValueError):
                guard.parse_training_trigger_reviews(encoded(value))

    def test_json_duplicate_keys_and_size_limits_fail_closed(self):
        raw = encoded(registry())
        duplicate = raw.replace(b'"schema": 1', b'"schema": 1, "schema": 1')
        for data in [b'{invalid json', duplicate, raw + b' ' * guard.TRAINING_REVIEW_LIMIT]:
            with self.assertRaises(ValueError):
                guard.parse_training_trigger_reviews(data)

    def test_changed_registry_bytes_change_binding_even_if_semantics_same(self):
        compact = encoded(registry())
        pretty = json.dumps(registry(), indent=2).encode()
        first = guard.parse_training_trigger_reviews(compact)
        second = guard.parse_training_trigger_reviews(pretty)
        self.assertEqual(first['approvals'], second['approvals'])
        self.assertNotEqual(first['sha256'], second['sha256'])

    def test_loader_rejects_symlinks_and_hardlinks(self):
        path = self.base / 'registry.json'
        path.write_bytes(encoded(registry()))
        self.assertEqual(len(guard.load_training_trigger_reviews(path)['approvals']), 1)
        link = self.base / 'link.json'
        try:
            link.symlink_to(path)
        except OSError:
            self.skipTest('Symlink unavailable')
        with self.assertRaises(ValueError):
            guard.load_training_trigger_reviews(link)
        link.unlink()
        os.link(path, link)
        with self.assertRaises(ValueError):
            guard.load_training_trigger_reviews(path)


class TrainingTriggerGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Isolated Trigger Review Test')
        self.git('config', 'user.email', 'test@local.invalid')
        self.write('README.md', b'Isolated fixture\n')
        self.git('add', 'README.md')
        self.git('commit', '-m', 'Initial fixture')

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return result.stdout

    def write(self, name, data):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_staged_review_uses_index_not_unstaged_registry(self):
        self.write(TARGET, payload())
        self.write(guard.TRAINING_REVIEW_FILE, encoded(registry()))
        self.git('add', TARGET)
        self.assertFalse(guard.run(self.repo, staged=True)['pass'])
        self.git('add', guard.TRAINING_REVIEW_FILE)
        self.assertTrue(guard.run(self.repo, staged=True)['pass'])
        self.write(guard.TRAINING_REVIEW_FILE, b'not valid JSON')
        self.assertTrue(guard.run(self.repo, staged=True)['pass'])
        self.assertFalse(guard.git_training_trigger_reviews(self.repo, staged=False)['approvals'])

    def test_all_history_uses_committed_registry_and_blocks_new_unreviewed_bytes(self):
        self.write(TARGET, payload())
        self.write(guard.TRAINING_REVIEW_FILE, encoded(registry()))
        self.git('add', TARGET, guard.TRAINING_REVIEW_FILE)
        self.git('commit', '-m', 'Exact reviewed fixture')
        self.assertTrue(guard.run(self.repo)['pass'])
        self.write(guard.TRAINING_REVIEW_FILE, b'not valid JSON in worktree')
        self.assertTrue(guard.run(self.repo)['pass'])
        self.write(TARGET, payload() + b'\n')
        self.git('add', TARGET)
        self.git('commit', '-m', 'Unreviewed changed bytes')
        report = guard.run(self.repo)
        self.assertFalse(report['pass'])
        self.assertIn('literal_credential_assignment', {row['rule'] for row in report['findings']})

    def test_real_key_signature_is_not_hidden_by_domain_review(self):
        data = payload(strong=True)
        self.write(TARGET, data)
        self.write(guard.TRAINING_REVIEW_FILE, encoded(registry(data)))
        self.git('add', TARGET, guard.TRAINING_REVIEW_FILE)
        report = guard.run(self.repo, staged=True)
        self.assertFalse(report['pass'])
        self.assertIn('openai_style_key', {row['rule'] for row in report['findings']})
        self.assertNotIn(json.loads(data)['trigger_token'], json.dumps(report))

    def test_malformed_staged_registry_blocks_scan(self):
        self.write(guard.TRAINING_REVIEW_FILE, b'{broken')
        self.git('add', guard.TRAINING_REVIEW_FILE)
        with self.assertRaises(ValueError):
            guard.run(self.repo, staged=True)

    def test_unapproved_same_blob_path_alias_remains_blocked(self):
        self.write(TARGET, payload())
        self.write('other.json', payload())
        self.write(guard.TRAINING_REVIEW_FILE, encoded(registry()))
        self.git('add', TARGET, 'other.json', guard.TRAINING_REVIEW_FILE)
        self.assertFalse(guard.run(self.repo, staged=True)['pass'])


class TrainingTriggerArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'
        self.repo = self.root / 'repo'
        self.runtime.mkdir()
        self.repo.mkdir()
        source = self.runtime / SOURCE
        source.parent.mkdir(parents=True)
        source.write_bytes(payload())
        self.selection = {'schema': 1, 'entries': [{'source': SOURCE, 'role': 'configuration'}]}
        self.registry = self.repo / guard.TRAINING_REVIEW_FILE
        self.registry.parent.mkdir()
        self.registry.write_bytes(encoded(registry()))

    def plan(self):
        return archive.plan(self.selection, self.runtime, self.repo)

    def apply(self, review):
        return archive.apply_plan(review, review['review_sha256'], self.repo)

    def test_plan_and_apply_share_exact_guard_and_registry_binding(self):
        review = self.plan()
        row = review['records'][0]
        self.assertEqual(row['status'], 'new_archive')
        self.assertEqual(row['reviewed_rules'], ['literal_credential_assignment'])
        self.assertEqual(review['training_trigger_registry_sha256'], hashlib.sha256(self.registry.read_bytes()).hexdigest())
        result = self.apply(review)
        self.assertEqual((self.repo / TARGET).read_bytes(), payload())
        self.assertEqual((self.runtime / SOURCE).read_bytes(), payload())
        self.assertEqual(result['training_trigger_registry_sha256'], review['training_trigger_registry_sha256'])

    def test_plan_without_registry_rejects_heuristic_trigger(self):
        self.registry.unlink()
        review = self.plan()
        self.assertIsNone(review['training_trigger_registry_sha256'])
        self.assertEqual(review['records'][0]['reason'], 'credential_gate')

    def test_changed_registry_after_plan_rejects_before_copy(self):
        review = self.plan()
        self.registry.write_bytes(json.dumps(registry(), indent=2).encode())
        with self.assertRaises(archive.ArchiveError):
            self.apply(review)
        self.assertFalse((self.repo / archive.ARCHIVE).exists())

    def test_removed_registry_after_plan_rejects_before_copy(self):
        review = self.plan()
        self.registry.unlink()
        with self.assertRaises(archive.ArchiveError):
            self.apply(review)
        self.assertFalse((self.repo / archive.ARCHIVE).exists())

    def test_bad_registry_fails_plan_closed(self):
        self.registry.write_bytes(b'{bad registry')
        with self.assertRaises(ValueError):
            self.plan()
        self.assertFalse((self.repo / archive.ARCHIVE).exists())

    def test_changed_source_bytes_still_rejected_despite_registered_path(self):
        review = self.plan()
        (self.runtime / SOURCE).write_bytes(payload() + b'\n')
        with self.assertRaises(archive.ArchiveError):
            self.apply(review)
        self.assertFalse((self.repo / archive.ARCHIVE).exists())

    def test_other_rule_in_approved_file_remains_quarantined(self):
        data = payload(strong=True)
        (self.runtime / SOURCE).write_bytes(data)
        self.registry.write_bytes(encoded(registry(data)))
        row = self.plan()['records'][0]
        self.assertEqual(row['reason'], 'credential_gate')
        self.assertIn('openai_style_key', row['rules'])
        self.assertNotIn(json.loads(data)['trigger_token'], json.dumps(row))

    def test_registry_change_during_plan_is_detected(self):
        original = guard.load_training_trigger_reviews
        calls = 0

        def changing(*args, **kwargs):
            nonlocal calls
            result = original(*args, **kwargs)
            calls += 1
            if calls == 1:
                self.registry.write_bytes(json.dumps(registry(), indent=2).encode())
            return result

        with patch.object(guard, 'load_training_trigger_reviews', side_effect=changing):
            with self.assertRaises(archive.ArchiveError):
                self.plan()

    def test_registry_change_during_copy_never_claims_completed_provenance(self):
        review = self.plan()
        original = archive.save_new

        def changing(path, data):
            original(path, data)
            if path == self.repo / TARGET:
                self.registry.write_bytes(json.dumps(registry(), indent=2).encode())

        with patch.object(archive, 'save_new', side_effect=changing):
            with self.assertRaises(archive.ArchiveError):
                self.apply(review)
        self.assertFalse((self.repo / archive.PROVENANCE).exists())


if __name__ == '__main__':
    unittest.main()
