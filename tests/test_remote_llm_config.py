"""Offline tests: every process and local HTTP probe is mocked."""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import extract_remote_llm as migration

launcher = migration.launcher


class RemoteLLMConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime space & harmless'
        self.repo = self.root / 'public'
        self.runtime.mkdir(); self.repo.mkdir()
        self.external = self.root / 'ComfyUI-local'
        for name in ['python/python.exe', 'python/pythonw.exe', 'launcher.exe',
                     'remote_llm_guard/autodl_power_on.py', 'remote_llm_guard/local_heartbeat_client.py']:
            file = self.runtime / name; file.parent.mkdir(exist_ok=True)
            file.write_text('fixture; never executed', encoding='utf-8')
        self.values = {
            'AUTODL_TOKEN': 'fixture-' + 'wake-private-value',
            'AUTODL_INSTANCE_UUID': 'fixture-instance',
            'LEASE_HEALTH_URL': 'https://example.invalid/health',
            'LEASE_HEARTBEAT_URL': 'https://example.invalid/heartbeat',
            'LEASE_SECRET': 'fixture-' + 'heartbeat-private-value & harmless',
            'COMFY_URL': 'http://127.0.0.1:8188', 'CHECK_INTERVAL_SECONDS': '30',
        }
        self.config = {'schema': 1, 'paths': {'python': 'python/python.exe',
                        'pythonw': 'python/pythonw.exe', 'launcher': 'launcher.exe'},
                       'environment': dict(self.values)}
        self.env = {'COMFYUI_EXTERNAL_ROOT': str(self.external), 'PATH': 'fixture-path'}

    def write_config(self, config=None):
        file = self.external / 'private-config/remote-llm/config.json'
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(config or self.config), encoding='utf-8')
        return file

    def write_legacy(self):
        paths = {'ROOT': str(self.runtime), 'PY': '%ROOT%/python/python.exe',
                 'PYW': '%ROOT%/python/pythonw.exe', 'LAUNCHER': '%ROOT%/launcher.exe'}
        for name in migration.FILES:
            text = '@echo off\r\n' + ''.join(f'set "{key}={value}"\r\n' for key, value in {**paths, **self.values}.items())
            (self.runtime / name).write_bytes(text.encode('utf-8'))

    def test_config_is_data_without_parent_environment_mutation(self):
        self.write_config()
        original = dict(self.env)
        values, paths = launcher.load_config(self.runtime, self.env)
        self.assertEqual(values, self.values)
        self.assertEqual(self.env, original)
        self.assertEqual(paths['python'], self.runtime / 'python/python.exe')

    def test_external_root_defaults_to_runtime_sibling(self):
        self.assertEqual(launcher.external_root(self.runtime, {}), self.runtime.parent / 'ComfyUI-local')
        for value in [str(self.runtime), str(self.runtime / 'private'), '.', str(Path(self.runtime.anchor))]:
            with self.assertRaises(launcher.ConfigurationError):
                launcher.external_root(self.runtime, {'COMFYUI_EXTERNAL_ROOT': value})

    def test_child_environment_only_contains_its_own_keys(self):
        child = launcher.child_environment(self.values, launcher.HEARTBEAT_KEYS,
                                          {'AUTODL_TOKEN': 'stale', 'PATH': 'path-value'})
        self.assertNotIn('AUTODL_TOKEN', child)
        self.assertEqual(child['LEASE_SECRET'], self.values['LEASE_SECRET'])
        self.assertEqual(child['PATH'], 'path-value')

    def test_unknown_fields_non_strings_and_multiline_rejected(self):
        for key, value in [('PYTHONPATH', 'untrusted'), ('LEASE_SECRET', ['bad']),
                           ('LEASE_SECRET', 'first\nsecond'), ('CHECK_INTERVAL_SECONDS', '0')]:
            with self.subTest(key=key):
                config = copy.deepcopy(self.config); config['environment'][key] = value
                self.write_config(config)
                with self.assertRaises(launcher.ConfigurationError):
                    launcher.load_config(self.runtime, self.env)

    def test_executable_escape_drive_and_nonexe_rejected(self):
        for value in ['../outside.exe', 'C:/outside.exe', 'python/python.exe:stream',
                      'python/python.bat', 'python\\python.exe', 'a//python.exe']:
            with self.subTest(value=value), self.assertRaises(launcher.ConfigurationError):
                launcher.relative_executable(self.runtime, value)

    def test_config_symlink_or_hardlink_rejected(self):
        file = self.write_config()
        other = self.root / 'hard-config.json'; os.link(file, other)
        with self.assertRaises(launcher.ConfigurationError):
            launcher.load_config(self.runtime, self.env)

    def test_heartbeat_uses_argv_and_env_never_shell_interpolation(self):
        self.write_config()
        with patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
             patch.object(launcher.subprocess, 'Popen') as background, \
             patch.object(launcher.urllib.request, 'urlopen') as http:
            self.assertEqual(launcher.run('heartbeat', self.runtime, self.env), 0)
        args, kwargs = run.call_args
        self.assertIsInstance(args[0], list)
        self.assertFalse(kwargs['shell'])
        self.assertNotIn(self.values['LEASE_SECRET'], str(args))
        self.assertNotIn('AUTODL_TOKEN', kwargs['env'])
        self.assertEqual(kwargs['env']['LEASE_SECRET'], self.values['LEASE_SECRET'])
        background.assert_not_called(); http.assert_not_called()

    def test_start_sequence_online_skips_gui_and_hides_background(self):
        self.write_config()
        with patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as wake, \
             patch.object(launcher.subprocess, 'Popen') as spawned, \
             patch.object(launcher, 'local_comfy_alive', return_value=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.run('start', self.runtime, self.env), 0)
        self.assertEqual(spawned.call_count, 1)
        self.assertNotIn('LEASE_SECRET', wake.call_args.kwargs['env'])
        self.assertEqual(spawned.call_args.kwargs['creationflags'], getattr(launcher.subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertFalse(spawned.call_args.kwargs['shell'])

    def test_start_sequence_offline_launches_gui_without_secrets(self):
        self.write_config()
        with patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
             patch.object(launcher.subprocess, 'Popen') as spawned, \
             patch.object(launcher, 'local_comfy_alive', return_value=False), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.run('start', self.runtime, self.env), 0)
        self.assertEqual(spawned.call_count, 2)
        self.assertEqual(spawned.call_args.args[0], [str(self.runtime / 'launcher.exe')])
        self.assertFalse(set(spawned.call_args.kwargs['env']) & launcher.ENVIRONMENT_KEYS)

    def test_wake_failure_stops_without_heartbeat_gui_or_http(self):
        self.write_config()
        with patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=7)), \
             patch.object(launcher.subprocess, 'Popen') as spawned, \
             patch.object(launcher, 'local_comfy_alive') as health, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.run('start', self.runtime, self.env), 7)
        spawned.assert_not_called(); health.assert_not_called()

    def test_legacy_dry_run_does_not_write_execute_or_log_values(self):
        self.write_legacy()
        with patch.object(launcher.subprocess, 'run') as run, patch.object(launcher.urllib.request, 'urlopen') as http:
            receipt = migration.extract(self.runtime, self.external, repo=self.repo)
        self.assertFalse(self.external.exists())
        self.assertFalse(receipt['production_modified'])
        self.assertNotIn(self.values['AUTODL_TOKEN'], json.dumps(receipt))
        run.assert_not_called(); http.assert_not_called()

    def test_legacy_write_preserves_exact_backups_and_runtime(self):
        self.write_legacy()
        originals = {name: (self.runtime / name).read_bytes() for name in migration.FILES}
        receipt = migration.extract(self.runtime, self.external, write=True, repo=self.repo)
        self.assertTrue(receipt['pass'])
        for name, raw in originals.items():
            self.assertEqual((self.runtime / name).read_bytes(), raw)
            self.assertEqual((self.external / 'private-config/remote-llm/originals' / name).read_bytes(), raw)
        loaded, paths = launcher.load_config(self.runtime, self.env)
        self.assertEqual(loaded, self.values)
        self.assertNotIn(self.values['LEASE_SECRET'], json.dumps(receipt))
        with self.assertRaises(migration.ContractError):
            migration.extract(self.runtime, self.external, write=True, repo=self.repo)

    def test_legacy_conflicting_values_and_unknown_assignments_rejected(self):
        self.write_legacy()
        file = self.runtime / migration.FILES[1]
        file.write_text(file.read_text().replace('fixture-instance', 'different-instance'), encoding='utf-8')
        with self.assertRaises(migration.ContractError):
            migration.extract(self.runtime, self.external, repo=self.repo)
        for text in ['set "UNKNOWN=anything"', 'set LEASE_SECRET=unquoted', 'set "ROOT=%UNKNOWN%"',
                     'set "ROOT=first"\nset "ROOT=second"']:
            with self.subTest(text=text), self.assertRaises(migration.ContractError):
                values = migration.parse_assignments(text.encode())
                migration.resolve_assignments(values, self.runtime)


if __name__ == '__main__':
    unittest.main()
