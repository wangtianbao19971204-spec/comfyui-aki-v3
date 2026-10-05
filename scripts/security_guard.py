"""Offline Git-object credential and payload gate. Never prints matched values.

Scan the staged index before commit, and every reachable blob before publication.
Git history and gzip payloads are read without checkout or network access.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import math
import re
import subprocess
import sys
import zlib
import zipfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
CHUNK = 1024 * 1024
OVERLAP = 32768
MAX_BLOB = 50 * 1024 * 1024
MAX_INFLATED = 1024 * 1024 * 1024
WEIGHTS = {'.safetensors', '.ckpt', '.pt', '.pth', '.onnx', '.gguf', '.bin', '.engine'}
DATABASES = {'.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm', '.sqlite-wal', '.sqlite-shm'}
PRIVATE_NAMES = re.compile(r'(?i)^(?:\.env(?:\..*)?|(?:.*[_-])?(?:credentials|secrets|cookies|accounts|auth|tokens|providers)(?:\.(?:json|yaml|yml|ini|toml))|(?:id_rsa|id_ed25519|id_ecdsa)(?:\.pub)?)$')
PRIVATE_SEGMENTS = {'.git', '.cache', '.venv', 'node_modules', '__pycache__'}
PRIVATE_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.keystore'}
KNOWN_PRIVATE_ENDS = (
    '/WeiLin-Comfyui-Tools-V52-FullPromptSelector/init.json',
    '/TB_Multi_API_Caption_ConfigPage_V17_ProviderAdapters/models_cache.json',
    '/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/config.json',
    '/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/py/character_feature_swap/llm_settings.json',
    '/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/py/multi_character_editor/settings/editor_settings.json',
)
RUNTIME_PAYLOAD_PREFIXES = tuple('snapshot/runtime/comfyui/' + name + '/' for name in ('input', 'output', 'temp', 'models'))
UNSUPPORTED_ARCHIVE_SUFFIXES = ('.bz2', '.bzip2', '.xz', '.zst', '.zstd', '.7z', '.rar', '.tar', '.lz4', '.lzma', '.z', '.tbz', '.tbz2', '.txz')

# These exact bytes were manually reviewed as deliberately synthetic SSRF tests.
# A directory or filename alone never exempts its content.
REVIEWED_FIXTURES = {
    '06d5f2680138c9fa4919fc13afd362fe3c969fe58c1c54d635380fe80181e7a1': 'synthetic_ssrf_redaction_test',
    '32a06d3f7d31f43c8d558f6f6223d9b8accf37c832b20181b2f8c5c1ef00c812': 'synthetic_ssrf_test',
    'd296f3619457ef1f664a4f113b824c6f3a2b78f6dcd724ab8591dadd61edb12c': 'synthetic_mocked_route_bearer_test',
    '434ae68072a4d554bb11e92f884b9de7e44bc6623478328ce25dac43fe90a2c2': 'synthetic_snapshot_security_test',
}
FIXTURE_ENDS = {
    '06d5f2680138c9fa4919fc13afd362fe3c969fe58c1c54d635380fe80181e7a1': '/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/tests/test_v53_legacy_security.py',
    '32a06d3f7d31f43c8d558f6f6223d9b8accf37c832b20181b2f8c5c1ef00c812': '/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/tests/test_v53_ssrf.py',
    'd296f3619457ef1f664a4f113b824c6f3a2b78f6dcd724ab8591dadd61edb12c': '/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/tests/test_v53_live_routes.py',
    '434ae68072a4d554bb11e92f884b9de7e44bc6623478328ce25dac43fe90a2c2': 'tests/test_snapshot.py',
}
# Reviewed upstream test versions: only synthetic header/cookie and SSRF fixtures.
REVIEWED_CORE_FIXTURES = {
    "7876af93ac05b133b27856e4115577d16f6057af6024461c1f684cf78122b19a": "tests-unit/billing_capabilities_test.py",
    "c2d8722f1987ec8f2519e9b2867cf48d181e2b695812fad2780f2a7fdabe33b4": "tests/execution/test_billing_capabilities_relay.py",
    "d9e6362f5e3e05bad927c2f45d9ebe3bba3b38b882e96e7090914f651adf6fae": "tests-unit/billing_capabilities_test.py",
    "16788a85ccab792040246c2b785fef35aa00d164f9ef69f87414a6868ee02316": "tests/execution/test_billing_capabilities_relay.py",
    "972c8aea5d3a96c8a3cf066361b942c3d04ebd613a62abafdefbd1f1d521f289": "tests/execution/test_billing_capabilities_relay.py",
    "23841ec72d155014bf7a5bdad933958bb301b187c21d29841191a1ab43d81d0a": "tests/execution/test_billing_capabilities_relay.py",
    "4f3a7e9e47f8a0ee4ff0c2593047b3372a4b47900ff076ad439a67b56fdc1623": "tests/execution/test_billing_capabilities_relay.py",
    "50ebc2a4806ebc1572b360ab76d35a0c57452518653c8e6dd5f9a9a8356d27f9": "tests-unit/billing_capabilities_test.py",
    "9e596de46bf2ae039667844f8c7a16094fb1fa6695f78f69cc3e0fd3d04d43d8": "tests-unit/billing_capabilities_test.py",
    "2e6e1d103ed7c612d31cbef2cb2df2bf1ad0e1e131665c60901cabc4c5ed505a": "tests-unit/model_downloader_test/test_security.py",
    "7c0a0a0d905782c785d54028b23c00c79b57734e5ebfb252f9d2f19851c1b99d": "tests-unit/model_downloader_test/test_security.py",
    "847790d2b929028ce27a39dde33e8837c1be443563468cdf92cfae4021b40786": "tests-unit/model_downloader_test/test_security.py",
    "b57a297f35f7770608517d6809d9f18d2a932d1b9b55b31b190d39c1a30c0216": "tests-unit/model_downloader_test/test_security.py",
    "4a06cf91405f62e4f00798faa41567daae169cebf3483dae4bf18a3281994739": "tests-unit/model_downloader_test/test_security.py",
}
for _fixture_sha, _fixture_path in REVIEWED_CORE_FIXTURES.items():
    REVIEWED_FIXTURES[_fixture_sha] = 'reviewed_upstream_synthetic_security_test'
    FIXTURE_ENDS[_fixture_sha] = _fixture_path

# Reviewed non-credential character training trigger in an audit record.
# Ace's versioned syntax-token scopes have a separate exact-byte/path registry.
REVIEWED_SOURCE_LITERALS = {
    '633e43d12fd347edba569b97b9e23dea4698a840ec022e938f8f268d49a4e473':
        'character_lora_forge/tools/merge_alicia_morning_star_replacements.py',
}
for _source_sha, _source_path in REVIEWED_SOURCE_LITERALS.items():
    REVIEWED_FIXTURES[_source_sha] = 'reviewed_noncredential_domain_token'
    FIXTURE_ENDS[_source_sha] = _source_path

SOURCE_REVIEW_RULES = frozenset({'literal_credential_assignment', 'escaped_literal_credential_assignment'})


def load_source_review_file(path=REPO / 'governance/security-review-fixtures.json'):
    """Exact independently reviewed bytes and file paths, never a directory skip."""
    if Path(path).stat().st_size > 1024 * 1024:
        raise ValueError('Source review registry size limit')
    data = json.loads(Path(path).read_bytes())
    required = {'schema', 'review', 'allowed_rules', 'entries'}
    if not isinstance(data, dict) or set(data) != required or type(data['schema']) is not int or data['schema'] != 1:
        raise ValueError('Invalid source review registry schema')
    if data['review'] != 'reviewed_ace_syntax_token_scopes' or not isinstance(data['allowed_rules'], list) or set(data['allowed_rules']) != SOURCE_REVIEW_RULES:
        raise ValueError('Invalid source review registry scope')
    if not isinstance(data['entries'], list) or len(data['entries']) > 10000:
        raise ValueError('Invalid source review registry entries')
    result = {}
    for item in data['entries']:
        if not isinstance(item, dict) or set(item) != {'sha256', 'path_ends'}:
            raise ValueError('Invalid source review entry')
        sha, ends = item['sha256'], item['path_ends']
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha) or sha in result:
            raise ValueError('Invalid or duplicate source review digest')
        if not isinstance(ends, list) or not ends or any(not isinstance(end, str) for end in ends) or len(set(ends)) != len(ends):
            raise ValueError('Invalid source review paths')
        for end in ends:
            if re.search(r'[\\:*?"<>|\x00-\x1f]', end) or any(part in {'', '.', '..'} or part.rstrip(' .') != part for part in end.split('/')):
                raise ValueError('Nonportable source review path')
            if not end.endswith('.js') or '/ace-builds/' not in end:
                raise ValueError('Source review scope must remain an exact Ace file')
        result[sha] = tuple(ends)
    return result


REVIEWED_ACE_SOURCE_PATHS = load_source_review_file()


def reviewed_ace_paths(digest, paths):
    ends = REVIEWED_ACE_SOURCE_PATHS.get(digest, ())
    return bool(paths and ends) and all(any(path == end or path.endswith('/' + end) for end in ends) for path in paths)

REVIEWED_HISTORICAL_PATHS = {
    ('snapshot/runtime/ComfyUI/custom_nodes/TB_Multi_API_Caption_ConfigPage_V17_ProviderAdapters/models_cache.json',
     '256920e0f444fce3358401b72bc1529e32d3954690ec2f1cd397aaf9251df3c6'): 'reviewed_model_names_only_cache',
}

STRONG = {
    'openai_style_key': re.compile(rb'(?<![A-Za-z0-9])sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}'),
    'github_token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'huggingface_token': re.compile(rb'\bhf_[A-Za-z0-9]{24,}'),
    'aws_access_key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'google_api_key': re.compile(rb'\bAIza[A-Za-z0-9_-]{30,}'),
    'slack_token': re.compile(rb'\bxox[baprs]-[A-Za-z0-9-]{20,}'),
    'stripe_secret_key': re.compile(rb'\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}'),
    'private_key': re.compile(rb'-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----'),
    'jwt': re.compile(rb'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{12,}'),
    'url_userinfo': re.compile(rb'(?i)https?://[^\s/:@"\'<>]{1,100}:[^\s/@"\'<>]{4,}@'),
}
KEY = rb'(?:[A-Za-z][A-Za-z0-9_-]*[_-])?(?:api[_-]?keys?|access[_-]?token|refresh[_-]?token|auth[_-]?token|secret[_-]?key|client[_-]?secret|password|passwd|authorization|cookie|bearer|token)'
ASSIGN = re.compile(rb'(?i)\b(' + KEY + rb')["\']?\s*[:=]\s*(["\'])([^"\'\r\n]{4,4096})\2')
SQL_PAIR = re.compile(rb"(?i)'(" + KEY + rb")'\s*,\s*'([^'\r\n]{4,4096})'")
UNQUOTED = re.compile(rb'(?im)^\s*(' + KEY + rb')\s*=\s*([^\s#"\']{8,4096})\s*(?:#.*)?$')
QUERY = re.compile(rb'(?i)[?&](api[_-]?key|access[_-]?token|auth[_-]?token|password|secret|token)=([^&#\s"\'<>]{8,4096})')
BEARER = re.compile(rb'(?i)\bBearer\s+([A-Za-z0-9_.~+/-]{16,}=*)')
SENSITIVE_PATH = re.compile(r'(?i)(?:credential|secret|auth|cookie|token|api[_-]?key|cache|\.map$|\.gz$)')
UNESCAPE = re.compile(rb'\\u00([0-9a-fA-F]{2})|\\x([0-9a-fA-F]{2})')
RULE_NEEDLES = {
    'openai_style_key': (b'sk-',), 'github_token': (b'gh',), 'huggingface_token': (b'hf_',),
    'aws_access_key': (b'AKIA', b'ASIA'), 'google_api_key': (b'AIza',), 'slack_token': (b'xox',),
    'stripe_secret_key': (b'sk_', b'rk_'), 'private_key': (b'-----BEGIN',), 'jwt': (b'eyJ',),
    'url_userinfo': (b'://',),
}


def git(repo, *args, input_data=None):
    result = subprocess.run(['git', '-C', str(repo), *args], input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError('Git command failed: ' + args[0])
    return result.stdout


def _raw_ref_lines(repo):
    """Internal comparison input only; never include raw secret-bearing names in a report."""
    result = subprocess.run(['git', '-C', str(repo), 'show-ref'], capture_output=True)
    if result.returncode not in {0, 1}:
        raise RuntimeError('Cannot read Git refs')
    return result.stdout.decode('utf-8', errors='surrogateescape').splitlines()


def refs(repo):
    # Stable opaque names preserve ref-change comparisons without leaking a name.
    result = []
    for line in _raw_ref_lines(repo):
        oid, name = line.split(' ', 1)
        result.append(oid + ' ' + safe_report_name(name))
    return result


def entropy(value):
    counts = collections.Counter(value)
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in counts.values()) if value else 0


def placeholder(value):
    """Only unmistakable whole-value placeholders; no substring exemptions."""
    value = value.strip()
    if re.fullmatch(rb'(?:<[^<>]+>|\$\{[^{}]+\}|\{\{[^{}]+\}\})', value):
        return True
    if re.fullmatch(rb'env:[A-Z][A-Z0-9_]+', value):
        return True  # Explicit plugin environment-variable reference.
    if re.fullmatch(rb'(?:\$[A-Z_][A-Z0-9_]*|%[A-Z_][A-Z0-9_]*%)', value):
        return True
    if re.fullmatch(rb'(?i)(?:your[-_ ](?:[a-z]{2,24}[-_ ])?(?:api[-_ ])?(?:key|token|password)(?:[-_ ]here)?|replace[-_ ]me|changeme|redacted|none|null|undefined|\*+|x{4,}|example|dummy|test)', value):
        return True
    return False


def plausible(value):
    value = value.strip()
    if placeholder(value) or len(value) < 12:
        return False
    if re.search(rb'[{}<>\s]', value) or value.startswith((b'process.env.', b'os.getenv(', b'settings.', b'config.')):
        return False
    if value in {b'__Secure-next-auth.session-token', b'next-auth.session-token'}:
        return False  # Standard cookie names, not cookie values.
    if re.fullmatch(rb'(?:__Secure-|__Host-)[A-Za-z0-9_.-]{1,64}=', value):
        return False  # Cookie name followed by '=', with no value present.
    if re.fullmatch(rb'[a-z_]+(?:\.[a-z_]+)+', value):
        return False  # Model tensor/state-dict identifier, not a token literal.
    if re.fullmatch(rb'[A-Z]+(?:_[A-Z]+)+', value):
        return False  # Symbolic field/enum names, no opaque value present.
    if len(value) >= 20 and entropy(value) >= 3.25:
        return True
    return len(value) >= 12 and entropy(value) >= 3.1 and bool(re.search(rb'[a-zA-Z]', value)) and bool(re.search(rb'\d', value))


def patterns(block):
    result = set()
    for name, pattern in STRONG.items():
        if not any(needle in block for needle in RULE_NEEDLES[name]):
            continue
        for match in pattern.finditer(block):
            if name == 'url_userinfo' and placeholder(match.group().split(b'://', 1)[1].split(b':', 1)[1][:-1]):
                continue
            result.add(name)
            break
    lower = block.lower()
    if not any(needle in lower for needle in (b'key', b'token', b'password', b'passwd', b'authorization', b'cookie', b'bearer', b'secret')):
        return result
    for match in ASSIGN.finditer(block):
        if plausible(match.group(3)):
            result.add('literal_credential_assignment')
    for match in SQL_PAIR.finditer(block):
        if plausible(match.group(2)):
            result.add('sql_credential_key_value')
    for match in UNQUOTED.finditer(block):
        value = match.group(2)
        if re.search(rb'[()\[\],:;]', value) or re.fullmatch(rb'[A-Za-z_]+_[A-Za-z_]+', value):
            continue  # A source expression/variable rather than an env literal.
        if plausible(value):
            result.add('unquoted_credential_assignment')
    for match in QUERY.finditer(block):
        if plausible(match.group(2)):
            result.add('url_credential_query')
    for match in BEARER.finditer(block):
        if plausible(match.group(1)):
            result.add('bearer_token')
    return result


def strong_name_rules(name):
    """Names get strong signatures only, not entropy/assignment heuristics."""
    data = name.encode('utf-8', errors='surrogateescape')
    result = set()
    for rule, pattern in STRONG.items():
        if not any(needle in data for needle in RULE_NEEDLES[rule]):
            continue
        for match in pattern.finditer(data):
            if rule == 'url_userinfo' and placeholder(match.group().split(b'://', 1)[1].split(b':', 1)[1][:-1]):
                continue
            result.add(rule)
            break
    return result


def name_digest(name):
    return hashlib.sha256(name.encode('utf-8', errors='surrogateescape')).hexdigest()


def safe_report_name(name):
    return '<redacted-name:sha256:' + name_digest(name) + '>' if strong_name_rules(name) else name


def sanitize_report_names(value):
    """Defense in depth for paths in compressed/fixture/boundary/ref metadata."""
    if isinstance(value, str):
        return safe_report_name(value)
    if isinstance(value, list):
        return [sanitize_report_names(item) for item in value]
    if isinstance(value, dict):
        return {safe_report_name(key) if isinstance(key, str) else key: sanitize_report_names(item)
                for key, item in value.items()}
    return value


def name_findings(name, oid, kind='filename'):
    rules = strong_name_rules(name)
    if not rules:
        return []
    digest = name_digest(name)
    return [{'path': '<redacted-name:sha256:' + digest + '>', 'object': oid,
             'rule': kind + '_' + rule, 'name_sha256': digest} for rule in sorted(rules)]


def ref_name_findings(repo):
    names = {}
    for line in _raw_ref_lines(repo):
        oid, name = line.split(' ', 1)
        names[name] = oid
    # The staged gate also protects the first commit on a named unborn branch.
    symbolic = subprocess.run(['git', '-C', str(repo), 'symbolic-ref', '-q', 'HEAD'], capture_output=True)
    if symbolic.returncode not in {0, 1}:
        raise RuntimeError('Cannot inspect symbolic HEAD')
    if symbolic.returncode == 0:
        names.setdefault(symbolic.stdout.decode('utf-8', errors='surrogateescape').strip(), '')
    return [finding for name, oid in names.items() for finding in name_findings(name, oid, 'refname')]


class StreamScanner:
    def __init__(self):
        self.tail = b''
        self.findings = set()
        self.bytes = 0

    def feed(self, block):
        self.bytes += len(block)
        joined = self.tail + block
        self.findings.update(patterns(joined))
        # Handles source-map escapes and JSON-in-SQL encoded key names/values.
        if b'\\u00' in joined or b'\\x' in joined or b'\\"' in joined or b'\\/' in joined:
            normalized = UNESCAPE.sub(lambda m: bytes([int(m.group(1) or m.group(2), 16)]), joined)
            normalized = normalized.replace(b'\\"', b'"').replace(b'\\/', b'/')
            self.findings.update('escaped_' + rule for rule in patterns(normalized))
        if joined.count(b'\0') > len(joined) // 10:
            self.findings.update('nul_encoded_' + rule for rule in patterns(joined.replace(b'\0', b'')))
        self.tail = joined[-OVERLAP:]


def archive_magic(prefix):
    """Supported formats are gzip and ZIP; other recognized archives block."""
    signatures = [
        ('zip', (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')),
        ('gzip', (b'\x1f\x8b',)), ('7z', (b'7z\xbc\xaf\x27\x1c',)),
        ('rar', (b'Rar!',)), ('bzip2', (b'BZh',)),
        ('xz', (b'\xfd7zXZ\x00',)), ('zstd', (b'\x28\xb5\x2f\xfd',)),
        ('lz4', (b'\x04\x22\x4d\x18',)), ('compress', (b'\x1f\x9d',)),
    ]
    for kind, variants in signatures:
        if prefix.startswith(variants):
            return kind
    if len(prefix) >= 4 and 0x50 <= prefix[0] <= 0x5F and prefix[1:4] == b'\x2a\x4d\x18':
        return 'zstd_skippable'
    if len(prefix) >= 262 and prefix[257:262] == b'ustar':
        return 'tar'
    return None


def scan_zip_payload(data):
    """Inspect members in memory, never extract a ZIP onto the filesystem."""
    rules = set()
    total = 0
    members = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                members += 1
                name = member.filename.replace('\\', '/')
                if member.flag_bits & 1:
                    rules.add('encrypted_archive_member'); continue
                if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
                    rules.add('unsafe_archive_member_path')
                rules.update('archive_' + rule for rule in blocked_path(name))
                if member.is_dir():
                    continue
                if total + member.file_size > MAX_INFLATED:
                    rules.add('archive_expansion_limit'); break
                scanner = StreamScanner()
                gzip_scanner = StreamScanner()
                inflater = None
                decoded_prefix = b''
                nested_member = False
                first = True
                with archive.open(member) as source:
                    while block := source.read(CHUNK):
                        total += len(block)
                        if total > MAX_INFLATED:
                            rules.add('archive_expansion_limit'); break
                        if first:
                            first = False
                            kind = archive_magic(block[:512])
                            if name.lower().endswith(('.gz', '.tgz')) and kind != 'gzip':
                                rules.add('invalid_gzip_archive_member')
                            if name.lower().endswith('.zip') and kind != 'zip':
                                rules.add('invalid_zip_archive_member')
                            if kind == 'gzip':
                                inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
                            elif kind:
                                rules.add('nested_archive_requires_review')
                        scanner.feed(block)
                        if inflater is not None:
                            pending = block
                            while pending:
                                decoded = inflater.decompress(pending, CHUNK)
                                gzip_scanner.feed(decoded)
                                decoded_prefix = (decoded_prefix + decoded)[:512]
                                if archive_magic(decoded_prefix):
                                    rules.add('nested_archive_requires_review')
                                    nested_member = True
                                    break
                                if total + gzip_scanner.bytes > MAX_INFLATED:
                                    rules.add('archive_expansion_limit'); break
                                pending = inflater.unconsumed_tail
                                if inflater.eof and inflater.unused_data:
                                    pending = inflater.unused_data
                                    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
                                    decoded_prefix = b''
                        if 'archive_expansion_limit' in rules or nested_member:
                            break
                rules.update('zip_' + rule for rule in scanner.findings)
                rules.update('zip_gzip_' + rule for rule in gzip_scanner.findings)
                if inflater is not None and not inflater.eof:
                    rules.add('zip_truncated_gzip_payload')
                if 'archive_expansion_limit' in rules:
                    break
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, zlib.error, OSError):
        rules.add('invalid_or_unsupported_zip_payload')
    return rules, {'members': members, 'uncompressed_bytes': total}


def blocked_path(path):
    p = PurePosixPath(path)
    lower = path.lower()
    rules = []
    if lower.startswith(RUNTIME_PAYLOAD_PREFIXES):
        rules.append('external_runtime_asset_payload')
    if '/user_data/prompt_selector/preview/' in lower or '/user_data/prompt_selector/preview_thumbnails/' in lower:
        rules.append('external_library_preview_payload')
    if lower.endswith(UNSUPPORTED_ARCHIVE_SUFFIXES):
        rules.append('unsupported_archive_suffix')
    if any(part.lower() in PRIVATE_SEGMENTS for part in p.parts):
        rules.append('private_runtime_directory')
    if p.suffix.lower() in WEIGHTS:
        rules.append('model_weight_payload')
    if p.suffix.lower() in DATABASES or lower.endswith(('-wal', '-shm')):
        rules.append('database_binary_or_journal')
    tokenizer_dictionary = lower.endswith(('/text_encoders/byt5_tokenizer/added_tokens.json',
                                           '/text_encoders/t5_pile_tokenizer/added_tokens.json'))
    if (PRIVATE_NAMES.fullmatch(p.name) and not tokenizer_dictionary) or p.suffix.lower() in PRIVATE_SUFFIXES:
        rules.append('private_credential_file')
    if any(lower.endswith(suffix.lower()) for suffix in KNOWN_PRIVATE_ENDS):
        rules.append('known_private_plugin_config_or_cache')
    return rules


def inventory(repo, staged):
    objects = {}
    gitlinks = []
    if staged:
        for line in git(repo, 'ls-files', '--stage', '-z').split(b'\0'):
            if not line:
                continue
            metadata, rawpath = line.split(b'\t', 1)
            mode, oid, stage = metadata.decode('ascii').split()
            path = rawpath.decode('utf-8', errors='surrogateescape')
            if stage != '0':
                raise RuntimeError('Index contains unresolved merges')
            if mode == '160000':
                gitlinks.append({'path': safe_report_name(path), 'object': oid, 'rule': 'nested_gitlink'})
                gitlinks.extend(name_findings(path, oid))
                continue
            objects.setdefault(oid, set()).add(path)
    else:
        for rawline in git(repo, 'rev-list', '--objects', '--all').splitlines():
            oid, separator, rawpath = rawline.partition(b' ')
            objects.setdefault(oid.decode('ascii'), set()).add(rawpath.decode('utf-8', errors='surrogateescape') if separator else '<metadata>')
        # All historical path aliases, including renames/deletions and gitlinks.
        records = iter(git(repo, 'log', '--all', '--format=', '--raw', '-z', '--no-renames', '--no-abbrev', '--root').split(b'\0'))
        for record in records:
            metadata = record.lstrip(b'\r\n')
            if not metadata.startswith(b':'):
                continue
            parts = metadata[1:].split()
            if len(parts) != 5:
                raise RuntimeError('Unexpected raw history record')
            oldmode, newmode, oldoid, newoid, status = parts
            rawpath = next(records)
            path = rawpath.decode('utf-8', errors='surrogateescape')
            for mode, rawoid in [(oldmode, oldoid), (newmode, newoid)]:
                oid = rawoid.decode('ascii')
                if set(oid) == {'0'}:
                    continue
                if mode == b'160000':
                    gitlinks.append({'path': safe_report_name(path), 'object': oid, 'rule': 'nested_gitlink'})
                    gitlinks.extend(name_findings(path, oid))
                else:
                    objects.setdefault(oid, set()).add(path)
    query = b''.join(oid.encode('ascii') + b'\n' for oid in objects)
    metadata = git(repo, 'cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)', input_data=query)
    selected = []
    for line in metadata.decode('ascii').splitlines():
        oid, kind, size = line.split()
        if kind in {'blob', 'commit', 'tag'}:
            selected.append({'object': oid, 'type': kind, 'bytes': int(size), 'paths': sorted(objects[oid])})
        elif kind == 'tree':
            # Empty historical directories/tree refs have no leaf blob to scan.
            for path in objects[oid]:
                gitlinks.extend(name_findings(path, oid))
    return selected, gitlinks


def scan_objects(repo, entries, staged=False, content_only=False):
    # Keep this here so independent SourceGraph/parallel callers cannot skip refs.
    findings = ref_name_findings(repo)
    reviewed = []
    compressed = []
    sensitive = []
    total = 0
    part_edges = collections.defaultdict(dict)
    manifest_boundaries = set()
    proc = subprocess.Popen(['git', '-C', str(repo), 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for entry in entries:
            oid = entry['object']
            proc.stdin.write(oid.encode('ascii') + b'\n')
            proc.stdin.flush()
            header = proc.stdout.readline().decode('ascii').strip().split()
            if len(header) != 3 or header[0] != oid or int(header[2]) != entry['bytes']:
                raise RuntimeError('Unexpected Git object stream')
            scanner = StreamScanner()
            inflated_scanner = StreamScanner()
            sha = hashlib.sha256()
            inflater = None
            inflated_prefix = b''
            zip_signature = False
            zip_blocks = []
            manifest_blocks = []
            manifest_paths = [path for path in entry['paths'] if path == 'snapshot/manifest.json']
            other_archive = False
            errors = set()
            head = b''
            remaining = entry['bytes']
            while remaining:
                block = proc.stdout.read(min(CHUNK, remaining))
                if not block:
                    raise RuntimeError('Truncated Git object stream')
                if remaining == entry['bytes']:
                    kind = archive_magic(block[:512])
                    if kind == 'gzip':
                        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    zip_signature = kind == 'zip'
                    other_archive = kind not in {None, 'zip', 'gzip'}
                    if any(path.lower().endswith(('.gz', '.tgz')) for path in entry['paths']) and kind != 'gzip':
                        errors.add('invalid_gzip_payload')
                    if any(path.lower().endswith('.zip') for path in entry['paths']) and kind != 'zip':
                        errors.add('invalid_zip_payload')
                if zip_signature and entry['bytes'] <= MAX_BLOB:
                    zip_blocks.append(block)
                if manifest_paths and entry['bytes'] <= MAX_BLOB:
                    manifest_blocks.append(block)
                head = (head + block[:OVERLAP])[:OVERLAP]
                scanner.feed(block)
                sha.update(block)
                if inflater is not None and not errors:
                    try:
                        pending = block
                        while pending:
                            decoded = inflater.decompress(pending, CHUNK)
                            inflated_scanner.feed(decoded)
                            inflated_prefix = (inflated_prefix + decoded)[:512]
                            if archive_magic(inflated_prefix):
                                errors.add('nested_archive_requires_review')
                                break
                            if inflated_scanner.bytes > MAX_INFLATED:
                                errors.add('compressed_expansion_limit'); break
                            pending = inflater.unconsumed_tail
                            if inflater.eof and inflater.unused_data:
                                pending = inflater.unused_data
                                inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
                                inflated_prefix = b''
                    except zlib.error:
                        errors.add('invalid_gzip_payload')
                remaining -= len(block)
            if proc.stdout.read(1) != b'\n':
                raise RuntimeError('Invalid Git object separator')
            total += entry['bytes']
            digest = sha.hexdigest()
            content_rules = set(scanner.findings)
            if entry['bytes'] == 0 and any(path.lower().endswith(('.gz', '.tgz', '.zip')) for path in entry['paths']):
                errors.add('empty_archive_payload')
            if manifest_blocks:
                try:
                    manifest = json.loads(b''.join(manifest_blocks))
                    for manifest_entry in manifest.get('files', []):
                        parts = manifest_entry.get('parts', [])
                        ordered = [(PurePosixPath('snapshot') / manifest_entry['path'] / part['path']).as_posix() for part in parts]
                        manifest_boundaries.update(zip(ordered, ordered[1:]))
                except (ValueError, KeyError, TypeError):
                    errors.add('invalid_chunk_manifest')
            if inflater is not None:
                if not inflater.eof:
                    errors.add('truncated_gzip_payload')
                content_rules.update('gzip_' + rule for rule in inflated_scanner.findings)
                compressed.append({'paths': entry['paths'], 'object': oid, 'uncompressed_bytes': inflated_scanner.bytes})
            if zip_signature and zip_blocks:
                zip_rules, zip_metadata = scan_zip_payload(b''.join(zip_blocks))
                content_rules.update(zip_rules)
                compressed.append({'paths': entry['paths'], 'object': oid, 'format': 'zip', **zip_metadata})
            elif zip_signature or other_archive:
                errors.add('unsupported_archive_requires_review')
            fixture = REVIEWED_FIXTURES.get(digest)
            fixture_suffix = FIXTURE_ENDS.get(digest)
            fixture_paths_match = bool(fixture_suffix) and all(path.endswith(fixture_suffix) for path in entry['paths'])
            if fixture and fixture_paths_match and content_rules:
                reviewed.append({'paths': entry['paths'], 'object': oid, 'sha256': digest, 'rule': fixture, 'matched_rules': sorted(content_rules)})
                content_rules.clear()
            if reviewed_ace_paths(digest, entry['paths']):
                reviewed_rules = content_rules & SOURCE_REVIEW_RULES
                if reviewed_rules:
                    reviewed.append({'paths': entry['paths'], 'object': oid, 'sha256': digest,
                                     'rule': 'reviewed_ace_syntax_token_scopes', 'matched_rules': sorted(reviewed_rules)})
                    content_rules.difference_update(reviewed_rules)
            for path in entry['paths']:
                findings.extend(name_findings(path, oid))
                path_rules = blocked_path(path) if entry['type'] == 'blob' and not content_only else []
                if entry['type'] == 'blob' and entry['bytes'] > MAX_BLOB and not content_only:
                    path_rules.append('oversize_git_blob')
                historical_review = REVIEWED_HISTORICAL_PATHS.get((path, digest))
                if historical_review and path_rules and not staged:
                    reviewed.append({'paths': [path], 'object': oid, 'sha256': digest, 'rule': historical_review, 'matched_rules': path_rules})
                    path_rules = []
                if SENSITIVE_PATH.search(path):
                    sensitive.append({'path': path, 'object': oid, 'bytes': entry['bytes']})
                for rule in sorted(set(path_rules) | content_rules | errors):
                    findings.append({'path': path, 'object': oid, 'rule': rule})
                if path.endswith('.part'):
                    part_edges[path][oid] = (head, scanner.tail)
        proc.stdin.close()
        if proc.wait(timeout=60):
            raise RuntimeError('Git object reader failed')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for handle in [proc.stdin, proc.stdout, proc.stderr]:
            handle.close()
    # Scan tails+heads in filename order. Existing manifest uses ordered part-00000.
    # StreamScanner also carries an overlap inside each part; no boundary gap.
    groups = collections.defaultdict(list)
    for path in part_edges:
        groups[str(PurePosixPath(path).parent)].append(path)
    boundary_pairs = set(manifest_boundaries)
    for paths in groups.values():
        boundary_pairs.update(zip(sorted(paths), sorted(paths)[1:]))
    boundaries = 0
    for left, right in sorted(boundary_pairs):
        if left not in part_edges or right not in part_edges:
            findings.append({'path': left + ' -> ' + right, 'object': '', 'rule': 'missing_manifest_chunk'})
            continue
            # Conservative across all historical versions; cannot lose a boundary
            # when an earlier part version was overwritten in a newer commit.
        for left_oid, (_, left_tail) in part_edges[left].items():
            for right_oid, (right_head, _) in part_edges[right].items():
                boundaries += 1
                combined = StreamScanner()
                combined.feed(left_tail + right_head)
                for rule in sorted(combined.findings):
                    findings.append({'path': left + ' -> ' + right, 'object': left_oid + ':' + right_oid, 'rule': 'cross_part_' + rule})
    return sanitize_report_names({'findings': findings, 'reviewed_fixtures': reviewed, 'compressed_objects': compressed,
                                  'sensitive_named_objects': sensitive, 'scanned_bytes': total, 'cross_part_boundaries': boundaries})


def run(repo=REPO, staged=False, content_only=False):
    repo = Path(repo).resolve()
    refs_before = refs(repo)
    index_before = git(repo, 'ls-files', '--stage', '-z') if staged else None
    entries, gitlinks = inventory(repo, staged)
    result = scan_objects(repo, entries, staged=staged, content_only=content_only)
    result['findings'].extend(item for item in gitlinks if not content_only or item['rule'] != 'nested_gitlink')
    refs_after = refs(repo)
    if refs_before != refs_after:
        result['findings'].append({'path': '<git refs>', 'object': '', 'rule': 'refs_changed_during_scan'})
    if staged and index_before != git(repo, 'ls-files', '--stage', '-z'):
        result['findings'].append({'path': '<git index>', 'object': '', 'rule': 'index_changed_during_scan'})
    result.update({'schema': 1, 'mode': 'staged' if staged else 'all-history', 'pass': not result['findings'],
                   'scanned_objects': len(entries), 'scanned_blobs': sum(e['type'] == 'blob' for e in entries),
                   'refs': refs_before, 'offline': True,
                   'content_only': content_only,
                   'limits': ['Heuristic credential detection is not proof of absence.', 'Encrypted or unsupported archives are rejected, not silently skipped.', 'Unreachable objects are outside --all-history; never publish local .git by copying it.']})
    return result


def scan_names(repo=REPO, staged=False):
    """Supplemental cheap name audit; this does not scan any payload content."""
    repo = Path(repo).resolve()
    before = refs(repo)
    index_before = git(repo, 'ls-files', '--stage', '-z') if staged else None
    entries, extra = inventory(repo, staged)
    findings = ref_name_findings(repo)
    findings.extend(item for item in extra if item['rule'].startswith('filename_'))
    findings.extend(finding for entry in entries for path in entry['paths']
                    for finding in name_findings(path, entry['object']))
    if before != refs(repo):
        findings.append({'path': '<git refs>', 'object': '', 'rule': 'refs_changed_during_scan'})
    if staged and index_before != git(repo, 'ls-files', '--stage', '-z'):
        findings.append({'path': '<git index>', 'object': '', 'rule': 'index_changed_during_scan'})
    return sanitize_report_names({'schema': 1, 'pass': not findings, 'mode': 'names-only-staged' if staged else 'names-only-all-history',
                                  'scanned_objects': len(entries), 'scanned_blobs': sum(item['type'] == 'blob' for item in entries),
                                  'scanned_bytes': 0, 'cross_part_boundaries': 0, 'refs': before,
                                  'findings': findings, 'reviewed_fixtures': [], 'compressed_objects': [],
                                  'payloads_scanned': False, 'offline': True,
                                  'limits': ['Names-only is supplemental and never replaces the full publication gate.']})


def run_pre_push(repo, records):
    """Reject raw/unreferenced push roots which an --all scan cannot cover."""
    repo = Path(repo).resolve()
    before = refs(repo)
    roots = set()
    push_name_findings = []
    for line in records.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 4 or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', parts[1]):
            raise ValueError('Invalid pre-push protocol')
        if set(parts[1]) != {'0'}:
            roots.add(parts[1])
            push_name_findings.extend(name_findings(parts[0], parts[1], 'push_refname'))
            push_name_findings.extend(name_findings(parts[2], parts[1], 'push_refname'))
    if roots:
        reachable = {line.split(b' ', 1)[0].decode('ascii') for line in git(repo, 'rev-list', '--objects', '--all').splitlines()}
        missing = sorted(roots - reachable)
        if missing:
            return {'schema': 1, 'pass': False, 'mode': 'pre-push', 'scanned_objects': 0, 'scanned_blobs': 0,
                    'scanned_bytes': 0, 'cross_part_boundaries': 0, 'reviewed_fixtures': [], 'compressed_objects': [],
                    'findings': push_name_findings + [{'path': '<push root; create a local branch or tag before audit>', 'object': oid,
                                  'rule': 'unscanned_unreferenced_push_root'} for oid in missing]}
        report = run(repo, staged=False)
        report['mode'] = 'pre-push'
        report['push_roots'] = sorted(roots)
        report['findings'].extend(push_name_findings)
        report['pass'] = not report['findings']
        if before != report['refs'] or before != refs(repo):
            report['findings'].append({'path': '<git refs>', 'object': '', 'rule': 'refs_changed_during_pre_push'})
            report['pass'] = False
        return report
    return {'schema': 1, 'pass': True, 'mode': 'pre-push', 'scanned_objects': 0, 'scanned_blobs': 0,
            'scanned_bytes': 0, 'cross_part_boundaries': 0, 'reviewed_fixtures': [], 'compressed_objects': [],
            'findings': [], 'note': 'Deletion-only or empty push: no local objects are uploaded.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--staged', action='store_true')
    modes.add_argument('--all-history', action='store_true')
    modes.add_argument('--pre-push', action='store_true', help='Read Git pre-push stdin and require every non-deletion local OID to be covered')
    parser.add_argument('--repo', type=Path, default=REPO)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--audit-content-only', action='store_true', help='Audit imported upstream content; not a publication payload gate')
    parser.add_argument('--names-only', action='store_true', help='Supplemental strong filename/refname check without reading payloads; not a publication gate')
    args = parser.parse_args()
    try:
        if args.pre_push and (args.audit_content_only or args.names_only):
            raise ValueError('Pre-push cannot bypass the payload gate')
        if args.names_only and args.audit_content_only:
            raise ValueError('Names-only cannot be combined with a content-only audit')
        report = (scan_names(args.repo, args.staged) if args.names_only else
                  run_pre_push(args.repo, sys.stdin.read()) if args.pre_push else run(args.repo, args.staged, args.audit_content_only))
    except Exception as exc:
        # Exception text can originate in a malformed object; never echo it.
        print(json.dumps({'pass': False, 'error': type(exc).__name__, 'rule': 'scan_failed_closed'}))
        return 2
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    summary = {key: report[key] for key in ('pass', 'mode', 'scanned_objects', 'scanned_blobs', 'scanned_bytes', 'cross_part_boundaries')}
    summary.update({'finding_count': len(report['findings']), 'findings': report['findings'][:25],
                    'reviewed_fixture_count': len(report['reviewed_fixtures']), 'compressed_object_count': len(report['compressed_objects'])})
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
