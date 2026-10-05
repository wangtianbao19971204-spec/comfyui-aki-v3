"""Read local JSON as data; never interpolate credentials into a shell command.

The two historical helpers keep their wake/SSH/heartbeat behavior. Only this
entry point owns configuration loading and the original BAT orchestration.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

ENVIRONMENT_KEYS = {
    'AUTODL_TOKEN', 'AUTODL_INSTANCE_UUID', 'AUTODL_START_COMMAND',
    'COMFY_URL', 'LEASE_HEALTH_URL', 'LEASE_HEARTBEAT_URL', 'LEASE_SECRET',
    'CHECK_INTERVAL_SECONDS', 'LOCAL_HEARTBEAT_LOG_PATH',
    'AUTODL_MAX_WAIT_SECONDS', 'AUTODL_RETRY_SECONDS', 'AUTODL_SSH_HOST',
    'AUTODL_SSH_PORT', 'AUTODL_SSH_USER', 'AUTODL_SSH_KEY',
    'AUTODL_SSH_START_COMMAND', 'AUTODL_SSH_FALLBACK_AFTER_ATTEMPTS',
}
WAKE_KEYS = {key for key in ENVIRONMENT_KEYS if key.startswith('AUTODL_')} | {'LEASE_HEALTH_URL'}
HEARTBEAT_KEYS = {'COMFY_URL', 'LEASE_HEARTBEAT_URL', 'LEASE_SECRET',
                  'CHECK_INTERVAL_SECONDS', 'LOCAL_HEARTBEAT_LOG_PATH'}
PATH_KEYS = {'python', 'pythonw', 'launcher'}


class ConfigurationError(ValueError):
    """Messages are fixed rule names, never a private value or remote response."""


def no_links(path):
    for candidate in [*reversed(path.parents), path]:
        try:
            item = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(item.st_mode) or getattr(item, 'st_file_attributes', 0) & 0x400:
            raise ConfigurationError('linked_configuration_path')


def external_root(runtime, environment):
    value = environment.get('COMFYUI_EXTERNAL_ROOT')
    path = Path(value) if value else runtime.parent / 'ComfyUI-local'
    if not path.is_absolute() or '..' in path.parts or str(path).startswith(('\\\\', '//')):
        raise ConfigurationError('external_root_must_be_local_absolute')
    no_links(path)
    path = path.resolve()
    if path == Path(path.anchor) or path == runtime or path.is_relative_to(runtime):
        raise ConfigurationError('external_root_must_be_outside_runtime')
    return path


def relative_executable(runtime, value):
    if not isinstance(value, str) or not value or re.search(r'[\\:*?"<>|\x00-\x1f]', value):
        raise ConfigurationError('invalid_relative_executable')
    parts = value.split('/')
    if any(p in {'', '.', '..'} or p.rstrip(' .') != p for p in parts):
        raise ConfigurationError('invalid_relative_executable')
    path = runtime.joinpath(*parts)
    no_links(path)
    if not path.resolve().is_relative_to(runtime) or path.suffix.lower() != '.exe':
        raise ConfigurationError('executable_outside_runtime_or_wrong_type')
    return path


def load_config(runtime, environment=None):
    runtime = Path(runtime).resolve()
    environment = os.environ if environment is None else environment
    file = external_root(runtime, environment) / 'private-config/remote-llm/config.json'
    no_links(file)
    if not file.is_file() or file.stat().st_size > 256 * 1024 or file.stat().st_nlink != 1:
        raise ConfigurationError('private_configuration_missing_or_invalid')
    try:
        config = json.loads(file.read_bytes())
    except (ValueError, UnicodeError):
        raise ConfigurationError('private_configuration_not_json') from None
    if not isinstance(config, dict) or set(config) != {'schema', 'paths', 'environment'} or type(config['schema']) is not int or config['schema'] != 1:
        raise ConfigurationError('invalid_configuration_schema')
    values, paths = config['environment'], config['paths']
    if not isinstance(values, dict) or set(values) - ENVIRONMENT_KEYS or not isinstance(paths, dict) or set(paths) != PATH_KEYS:
        raise ConfigurationError('unrecognized_configuration_fields')
    if any(not isinstance(v, str) or len(v) > 16384 or any(c in v for c in '\x00\r\n') for v in values.values()):
        raise ConfigurationError('configuration_values_must_be_single_line_strings')
    for key in ['AUTODL_TOKEN', 'AUTODL_INSTANCE_UUID', 'LEASE_HEALTH_URL', 'LEASE_HEARTBEAT_URL', 'LEASE_SECRET']:
        if not values.get(key, '').strip() or values[key].startswith('<'):
            raise ConfigurationError('required_configuration_value_missing')
    for key in ['CHECK_INTERVAL_SECONDS', 'AUTODL_MAX_WAIT_SECONDS', 'AUTODL_RETRY_SECONDS',
                'AUTODL_SSH_FALLBACK_AFTER_ATTEMPTS']:
        if key in values and (not values[key].isascii() or not values[key].isdigit() or not 1 <= int(values[key]) <= 86400):
            raise ConfigurationError('invalid_numeric_configuration')
    executables = {key: relative_executable(runtime, value) for key, value in paths.items()}
    return values, executables


def child_environment(values, keys, inherited=None):
    # Never mutate the launcher process or hand unrelated wake keys to heartbeat.
    inherited = os.environ if inherited is None else inherited
    result = {key: value for key, value in inherited.items() if key not in ENVIRONMENT_KEYS}
    result.update({key: value for key, value in values.items() if key in keys})
    return result


def required_file(path):
    no_links(path)
    if not path.is_file():
        raise ConfigurationError('required_runtime_executable_or_helper_missing')
    return str(path)


def command(paths, helper, background=False):
    return [required_file(paths['pythonw' if background else 'python']), '-X', 'utf8', '-B', required_file(helper)]


def local_comfy_alive():
    # Match the old launcher: the launch guard always checks local port 8188.
    try:
        with urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=5) as response:
            return 200 <= response.status < 400
    except Exception:
        return False


def run(mode, runtime=None, environment=None):
    runtime = Path(runtime).resolve() if runtime else Path(__file__).resolve().parent.parent
    values, paths = load_config(runtime, environment)
    heartbeat = runtime / 'remote_llm_guard/local_heartbeat_client.py'
    inherited = os.environ if environment is None else environment
    heartbeat_env = child_environment(values, HEARTBEAT_KEYS, inherited)
    if mode == 'heartbeat':
        return subprocess.run(command(paths, heartbeat), cwd=runtime, env=heartbeat_env, shell=False).returncode
    if mode != 'start':
        raise ConfigurationError('unknown_launch_mode')
    # Check all local dependencies before starting the remote machine.
    wake_command = command(paths, runtime / 'remote_llm_guard/autodl_power_on.py')
    heartbeat_command = command(paths, heartbeat, background=True)
    required_file(paths['launcher'])
    print('[1/3] Waking the configured remote LLM...', flush=True)
    result = subprocess.run(wake_command, cwd=runtime,
                            env=child_environment(values, WAKE_KEYS, inherited), shell=False)
    if result.returncode:
        return result.returncode
    print('[2/3] Starting the background heartbeat client...', flush=True)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    subprocess.Popen(heartbeat_command, cwd=runtime, env=heartbeat_env, shell=False,
                     creationflags=flags, close_fds=True)
    print('[3/3] Checking local ComfyUI...', flush=True)
    if not local_comfy_alive():
        # No private configuration values are placed in the GUI process env.
        subprocess.Popen([str(paths['launcher'])], cwd=runtime, shell=False,
                         env=child_environment({}, set(), inherited))
    else:
        print('ComfyUI is already running; GUI launch skipped.', flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['start', 'heartbeat'])
    args = parser.parse_args()
    try:
        return run(args.mode)
    except Exception as exc:
        rule = str(exc) if isinstance(exc, ConfigurationError) else type(exc).__name__
        print('Remote LLM launcher failed: ' + rule, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
