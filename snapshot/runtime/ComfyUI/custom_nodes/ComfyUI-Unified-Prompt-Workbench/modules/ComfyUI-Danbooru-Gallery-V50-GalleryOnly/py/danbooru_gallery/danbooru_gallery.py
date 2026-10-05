import requests
import json
import folder_paths
from server import PromptServer
from aiohttp import web
import time
import threading
import asyncio
import torch
import io
import urllib.request
import urllib.parse
import numpy as np
from PIL import Image
import os
import csv
import re
import math
import logging
import traceback
import html as html_lib
from requests.auth import HTTPBasicAuth
import urllib3
import socket
import ssl
import ipaddress
import unicodedata
from pathlib import Path
import sys
import subprocess
from ..utils.logger import get_logger

logger = get_logger(__name__)

try:
    from curl_cffi import requests as curl_cffi_requests
    _CURL_CFFI_AVAILABLE = True
    _CURL_CFFI_IMPORT_ERROR = ""
except Exception as _curl_cffi_error:
    curl_cffi_requests = None
    _CURL_CFFI_AVAILABLE = False
    _CURL_CFFI_IMPORT_ERROR = str(_curl_cffi_error)

# 导入数据库管理器
try:
    from ..shared.db.db_manager import get_db_manager
except ImportError as e:
    logger.warning(f"[Autocomplete] 无法导入数据库管理器，将仅使用远程API模式: {e}")
    get_db_manager = None

try:
    from ..shared.db.weilin_tag_bridge import WeiLinCatalogError, WeiLinTagBridge
except ImportError as e:
    logger.warning(f"[TagCatalog] 无法导入 WeiLin 只读词库桥接器: {e}")
    WeiLinCatalogError = RuntimeError
    WeiLinTagBridge = None

_WEILIN_BRIDGE_INSTANCE = None
_WEILIN_BRIDGE_GALLERY_DB = None
_CIVITAI_BRIDGE_RENEWAL_LAST_OPEN = 0.0
_CIVITAI_BRIDGE_RENEWAL_LOCK = threading.Lock()
_CIVITAI_BRIDGE_FETCH_LOCK = threading.Lock()
_DANBOORU_BRIDGE_FETCH_LOCK = threading.Lock()


def _get_weilin_tag_bridge():
    """Return the lazy read-only WeiLin bridge for the active Gallery cache."""

    global _WEILIN_BRIDGE_INSTANCE, _WEILIN_BRIDGE_GALLERY_DB
    if WeiLinTagBridge is None:
        return None
    gallery_db = None
    if get_db_manager is not None:
        try:
            gallery_db = str(Path(get_db_manager().db_path).expanduser().resolve())
        except Exception as exc:
            logger.debug(f"[TagCatalog] 无法读取当前 Gallery tag DB 路径: {exc}")
    cache_key = gallery_db or "<default>"
    if _WEILIN_BRIDGE_INSTANCE is None or _WEILIN_BRIDGE_GALLERY_DB != cache_key:
        kwargs = {"gallery_db_path": gallery_db} if gallery_db else {}
        _WEILIN_BRIDGE_INSTANCE = WeiLinTagBridge(**kwargs)
        _WEILIN_BRIDGE_GALLERY_DB = cache_key
    return _WEILIN_BRIDGE_INSTANCE

# 禁用 SSL 警告（如果需要禁用证书验证）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Danbooru API文档链接 https://danbooru.donmai.us/wiki_pages/help:api

# Booru API 基础 URL
DANBOORU_BASE_URL = "https://danbooru.donmai.us"
GELBOORU_BASE_URL = "https://gelbooru.com"
YANDERE_BASE_URL = "https://yande.re"
CIVITAI_BASE_URL = "https://civitai.red"
CIVITAI_FALLBACK_BASE_URL = "https://civitai.com"
CIVITAI_SEARCH_URL = "https://search-new.civitai.com/multi-search"
# 向后兼容旧代码里的 BASE_URL 引用。
BASE_URL = DANBOORU_BASE_URL

# 需要一个非 python-requests 的描述性 UA。Gelbooru 也复用该 UA，避免上游把请求识别为默认脚本爬虫。
DANBOORU_HEADERS = {
    "User-Agent": "Danbooru-Gallery/1.0",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}
DANBOORU_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
GELBOORU_HEADERS = {
    "User-Agent": "Danbooru-Gallery/1.0",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Referer": "https://gelbooru.com/",
}
YANDERE_HEADERS = {
    "User-Agent": DANBOORU_BROWSER_UA,
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Referer": "https://yande.re/",
}
CIVITAI_HEADERS = {
    "User-Agent": "Danbooru-Gallery/1.0",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Referer": "https://civitai.red/",
    "Origin": "https://civitai.red",
}

# Civitai 站内远端收藏 image.getInfinite 返回的 url 通常是媒体 UUID，需要拼成 image.civitai.com 的可访问资源 URL。
# 该前缀是 Civitai 当前公开图片服务使用的稳定样式；若站方后续调整，远端收藏浏览仍可继续通过页面链接兜底。
CIVITAI_IMAGE_CDN_PREFIX = "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA"
# 与 Civitai Web 收藏页默认浏览配置保持接近，避免把 POI/minor 等额外内容塞进插件画廊。
CIVITAI_REMOTE_COLLECTION_EXCLUDED_TAG_IDS = [5161, 5162, 5188, 5249, 130818, 130820, 133182, 5351, 306619, 154326, 161829, 163032]

# 官方文档限速为 10 req/s，保守取一半 = 5 req/s（200ms 间隔），避免触发 CF 或被站方拉黑。
class _RateLimiter:
    def __init__(self, min_interval_sec):
        self.min_interval = min_interval_sec
        self._last_ts = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_ts
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_ts = time.monotonic()

_donmai_throttle = _RateLimiter(min_interval_sec=0.2)
_gelbooru_throttle = _RateLimiter(min_interval_sec=0.35)
_yandere_throttle = _RateLimiter(min_interval_sec=0.45)
_civitai_throttle = _RateLimiter(min_interval_sec=0.6)
_system_proxy_cache = {"ts": 0.0, "value": None}

# requests 默认会自动读取 HTTP_PROXY/HTTPS_PROXY 等环境变量。插件已经有显式代理解析，
# 因此统一关闭 trust_env，避免“直连诊断/直连 fallback”实际仍然走系统代理。
_PROXY_REQUESTS_SESSION = requests.Session()
_PROXY_REQUESTS_SESSION.trust_env = False
_DIRECT_REQUESTS_SESSION = requests.Session()
_DIRECT_REQUESTS_SESSION.trust_env = False


# V52: cache Civitai prompt/tag detail results for the lifetime of the ComfyUI
# process.  Hover, selection and export can ask for the same image independently;
# without a shared cache each request repeats several remote Civitai calls.
_CIVITAI_PROMPT_DETAIL_CACHE = {}
_CIVITAI_PROMPT_DETAIL_INFLIGHT = {}
_CIVITAI_PROMPT_DETAIL_SUCCESS_TTL = 6 * 60 * 60
_CIVITAI_PROMPT_DETAIL_FAILURE_TTL = 60
_CIVITAI_PROMPT_DETAIL_CACHE_LIMIT = 512



def _normalize_proxy_url(value):
    """把 127.0.0.1:10081 / http=...;https=... 统一成 requests 可用的代理 URL。"""
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None

    # Windows 系统代理常见格式："http=127.0.0.1:10081;https=127.0.0.1:10081"
    if ";" in value or "=" in value:
        parts = {}
        for item in value.split(";"):
            if "=" in item:
                k, v = item.split("=", 1)
                parts[k.strip().lower()] = v.strip()
        value = parts.get("https") or parts.get("http") or parts.get("socks") or next(iter(parts.values()), "")

    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://") or value.startswith("socks5://") or value.startswith("socks4://"):
        return value
    return "http://" + value


def _read_windows_system_proxy():
    """读取 Windows 系统代理。普通 requests 不会自动吃浏览器/系统代理，这里手动补上。"""
    # 缓存 10 秒，避免频繁访问注册表。
    now = time.monotonic()
    if now - _system_proxy_cache.get("ts", 0.0) < 10.0:
        return _system_proxy_cache.get("value")

    proxy = None
    if os.name == "nt":
        try:
            import winreg
            path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if enabled:
                    server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    proxy = _normalize_proxy_url(server)
        except Exception as e:
            logger.debug(f"[Proxy] 读取 Windows 系统代理失败: {e}")

    _system_proxy_cache["ts"] = now
    _system_proxy_cache["value"] = proxy
    return proxy


def _get_proxy_url():
    """返回应当用于后端请求的代理 URL。优先级：settings.proxy_url > 环境变量 > Windows 系统代理。"""
    try:
        settings = load_settings()
        if settings.get("proxy_enabled", True) is False:
            return None
        configured = _normalize_proxy_url(settings.get("proxy_url", ""))
        if configured:
            return configured
    except Exception:
        pass

    for env_name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(env_name)
        proxy = _normalize_proxy_url(value)
        if proxy:
            return proxy

    return _read_windows_system_proxy()


def _requests_kwargs_with_proxy(kwargs):
    if "proxies" not in kwargs:
        proxy = _get_proxy_url()
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
    return kwargs


def _call_curl_cffi_compat(callable_obj, *args, clear_proxy_env=False, **kwargs):
    """Call curl_cffi across versions while keeping direct mode deterministic."""
    proxy_env_keys = (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    )
    def invoke():
        if not clear_proxy_env:
            return callable_obj(*args, **kwargs)
        saved = {key: os.environ.pop(key) for key in proxy_env_keys if key in os.environ}
        try:
            return callable_obj(*args, **kwargs)
        finally:
            for key, value in saved.items():
                os.environ[key] = value
    try:
        return invoke()
    except TypeError as exc:
        if "trust_env" not in kwargs or "trust_env" not in str(exc):
            raise
        kwargs = dict(kwargs)
        kwargs.pop("trust_env", None)
        return _call_curl_cffi_compat(callable_obj, *args, clear_proxy_env=True, **kwargs)


def _curl_cffi_request_with_headers(method, url, headers, throttle=None, **kwargs):
    """可选的浏览器指纹 HTTP 客户端。未安装 curl_cffi 时直接抛出 ImportError。"""
    if not _CURL_CFFI_AVAILABLE or curl_cffi_requests is None:
        raise ImportError(_CURL_CFFI_IMPORT_ERROR or "curl_cffi is not installed")

    merged_headers = dict(kwargs.pop("headers", None) or {})
    force_direct = bool(kwargs.pop("_force_direct", False))
    suppress_credentials = bool(kwargs.pop("_suppress_credentials", False))
    for k, v in headers.items():
        merged_headers.setdefault(k, v)
    # curl_cffi 已经提供浏览器级 TLS/HTTP2 指纹；UA 同步成浏览器 UA，避免 HTTP 层和 TLS 层矛盾。
    merged_headers["User-Agent"] = DANBOORU_BROWSER_UA
    if suppress_credentials:
        merged_headers = _strip_credential_headers(merged_headers)
    else:
        merged_headers = _apply_danbooru_cookie_headers(merged_headers, url)

    proxies = kwargs.pop("proxies", None)
    if force_direct:
        proxies = {}
    elif proxies is None:
        proxy = _get_proxy_url()
        if proxy:
            proxies = {"http": proxy, "https": proxy}

    request_kwargs = {
        "params": kwargs.pop("params", None),
        "data": kwargs.pop("data", None),
        "json": kwargs.pop("json", None),
        "headers": merged_headers,
        "timeout": kwargs.pop("timeout", 30),
        "proxies": proxies,
        "allow_redirects": kwargs.pop("allow_redirects", True),
        "impersonate": kwargs.pop("impersonate", "chrome"),
    }
    # curl_cffi 的 verify 参数与 requests 兼容。
    if "verify" in kwargs:
        request_kwargs["verify"] = kwargs.pop("verify")
    # BasicAuth 在这里不是主路径；Danbooru 诊断/搜索均优先 login/api_key URL 参数。
    kwargs.pop("auth", None)

    if throttle:
        throttle.wait()

    return _call_curl_cffi_compat(
        curl_cffi_requests.request,
        method,
        url,
        clear_proxy_env=force_direct or proxies == {},
        **request_kwargs,
    )


def _is_cloudflare_challenge(resp):
    try:
        text = resp.text[:1200].lower()
    except Exception:
        text = ""
    return (
        resp.headers.get("CF-Mitigated", "").lower() == "challenge"
        or "just a moment" in text
        or "challenges.cloudflare.com" in text
    )


def _normalize_danbooru_query_tags(tags):
    """Danbooru 查询标签使用空格分隔；这里兼容用户从提示词中粘贴的逗号分隔写法。"""
    tags = str(tags or "").strip()
    if not tags:
        return ""
    tags = tags.replace(",", " ")
    return " ".join(part.strip() for part in tags.split() if part.strip())


def _normalize_cookie_header(cookie_value):
    """Normalize a user-pasted browser Cookie header without exposing it in diagnostics."""
    cookie = str(cookie_value or "").strip()
    if not cookie:
        return ""
    if cookie.lower().startswith("cookie:"):
        cookie = cookie.split(":", 1)[1].strip()
    # Cookie headers must be one line. Strip CR/LF to avoid header injection.
    cookie = re.sub(r"[\r\n]+", "; ", cookie)
    cookie = re.sub(r"\s*;\s*", "; ", cookie).strip("; ").strip()
    return cookie


def _danbooru_cookie_has_login_session(cookie_value):
    cookie = _normalize_cookie_header(cookie_value).lower()
    if not cookie:
        return False
    names = []
    for part in cookie.split(";"):
        name = part.split("=", 1)[0].strip()
        if name:
            names.append(name)
    return any(
        name in ("danbooru2_session", "_danbooru2_session") or ("danbooru" in name and "session" in name)
        for name in names
    )


def load_danbooru_cookie():
    settings = load_settings()
    enabled = bool(settings.get("danbooru_cookie_enabled", False))
    cookie = _normalize_cookie_header(settings.get("danbooru_cookie", ""))
    return enabled, cookie


def save_danbooru_cookie(cookie, enabled=False):
    settings = load_settings()
    settings["danbooru_cookie_enabled"] = bool(enabled)
    settings["danbooru_cookie"] = _normalize_cookie_header(cookie)
    return save_settings(settings)


def _normalize_raw_browser_headers(raw_value):
    """Normalize a user-pasted Request Headers block / copy-as-cURL command.

    This is intentionally simple: it stores a single text block locally, strips
    CRLF injection, and later parses only safe request headers for donmai.us.
    """
    raw = str(raw_value or "").strip()
    if not raw:
        return ""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Drop very long pasted bodies/commands by keeping a conservative local cap.
    raw = raw[:100000]
    return raw.strip()


def _parse_danbooru_browser_headers(raw_value):
    """Parse Chrome/Edge Network -> Request Headers or Copy as cURL headers.

    User-Agent + Cookie copied from the same proxy/browser session can be more
    useful than Cookie alone because cf_clearance may be tied to UA/client hints.
    Dangerous hop-by-hop/body headers are discarded.
    """
    raw = _normalize_raw_browser_headers(raw_value)
    parsed = {}
    if not raw:
        return parsed

    header_lines = []
    # Support DevTools "Copy as cURL" snippets: -H 'name: value'.
    try:
        for m in re.finditer(r'(?:^|\s)-H\s+([\'"])(.*?)\1', raw, flags=re.S):
            header_lines.append(m.group(2))
        # Common curl form for UA: -A '...' / --user-agent '...'
        ua_match = re.search(r'(?:^|\s)(?:-A|--user-agent)\s+([\'"])(.*?)\1', raw, flags=re.S)
        if ua_match:
            header_lines.append("User-Agent: " + ua_match.group(2))
    except Exception:
        header_lines = []

    if not header_lines:
        header_lines = [line.strip() for line in raw.split("\n") if line.strip()]

    banned = {
        "host", "content-length", "connection", "proxy-connection", "transfer-encoding",
        "te", "trailer", "upgrade", "keep-alive", "accept-encoding", "authorization"
    }
    allowed_prefixes = ("sec-",)
    allowed_exact = {
        "user-agent", "accept", "accept-language", "cookie", "referer", "origin",
        "cache-control", "pragma", "dnt", "priority"
    }
    for line in header_lines:
        line = str(line or "").strip()
        if not line or line.startswith(("GET ", "POST ", "curl ")):
            continue
        # Ignore HTTP/2 pseudo headers like :authority, :method.
        if line.startswith(":"):
            continue
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value:
            continue
        lname = name.lower()
        if lname in banned:
            continue
        if not (lname in allowed_exact or lname.startswith(allowed_prefixes)):
            continue
        # Prevent header injection.
        value = re.sub(r"[\r\n]+", " ", value).strip()
        if not value:
            continue
        if lname == "cookie":
            value = _normalize_cookie_header(value)
            canon = "Cookie"
        elif lname == "user-agent":
            canon = "User-Agent"
        elif lname == "accept-language":
            canon = "Accept-Language"
        elif lname == "accept":
            canon = "Accept"
        elif lname == "referer":
            canon = "Referer"
        elif lname == "origin":
            canon = "Origin"
        elif lname == "cache-control":
            canon = "Cache-Control"
        elif lname == "pragma":
            canon = "Pragma"
        elif lname == "dnt":
            canon = "DNT"
        elif lname == "priority":
            canon = "Priority"
        else:
            # Preserve sec-ch-ua / sec-fetch-* spelling enough for servers that check it.
            canon = "-".join(part.capitalize() if part else part for part in lname.split("-"))
        parsed[canon] = value
    return parsed


def load_danbooru_browser_headers():
    settings = load_settings()
    enabled = bool(settings.get("danbooru_browser_headers_enabled", False))
    raw_headers = _normalize_raw_browser_headers(settings.get("danbooru_browser_headers", ""))
    return enabled, raw_headers, _parse_danbooru_browser_headers(raw_headers)


def save_danbooru_browser_headers(raw_headers, enabled=False):
    settings = load_settings()
    settings["danbooru_browser_headers_enabled"] = bool(enabled)
    settings["danbooru_browser_headers"] = _normalize_raw_browser_headers(raw_headers)
    return save_settings(settings)


def _danbooru_browser_headers_status():
    enabled, raw_headers, parsed = load_danbooru_browser_headers()
    cookie = parsed.get("Cookie", "")
    ua = parsed.get("User-Agent", "")
    return {
        "enabled": enabled,
        "has_headers": bool(raw_headers),
        "parsed_count": len(parsed),
        "has_cookie": bool(cookie),
        "has_cf_clearance": "cf_clearance=" in cookie.lower(),
        "has_user_agent": bool(ua),
        "length": len(raw_headers or ""),
    }


def _apply_danbooru_browser_headers(headers, url=None):
    try:
        if url and "donmai.us" not in str(url):
            return headers
        enabled, raw_headers, parsed = load_danbooru_browser_headers()
        if enabled and raw_headers and parsed:
            # Browser header mode deliberately overrides Cookie/User-Agent from the
            # simpler cookie fallback. This mirrors the browser request more closely.
            headers.update(parsed)
            headers.setdefault("Referer", DANBOORU_BASE_URL + "/posts")
        return headers
    except Exception as e:
        logger.debug(f"[Danbooru] Browser header apply skipped: {e}")
        return headers




def _parse_civitai_browser_headers(raw_value):
    """Parse Civitai browser Request Headers / Copy-as-cURL for authenticated tRPC collection calls.

    Stores only local user-provided headers. Diagnostics/log exports should redact this block.
    """
    raw = _normalize_raw_browser_headers(raw_value)
    parsed = {}
    if not raw:
        return parsed
    header_lines = []
    try:
        for m in re.finditer(r'(?:^|\s)-H\s+([\'"])(.*?)\1', raw, flags=re.S):
            header_lines.append(m.group(2))
        ua_match = re.search(r'(?:^|\s)(?:-A|--user-agent)\s+([\'"])(.*?)\1', raw, flags=re.S)
        if ua_match:
            header_lines.append('User-Agent: ' + ua_match.group(2))
        # Chrome DevTools Copy as cURL often emits Cookie via curl's -b/--cookie
        # option rather than as a literal -H 'cookie: ...' header. v25 only parsed
        # -H headers, which caused Civitai remote favorites to silently lose auth
        # and return 401 UNAUTHORIZED.
        for cm in re.finditer(r'(?:^|\s)(?:-b|--cookie)\s+([\'"])(.*?)\1', raw, flags=re.S):
            cookie_val = (cm.group(2) or '').strip()
            if cookie_val:
                header_lines.append('Cookie: ' + cookie_val)
    except Exception:
        header_lines = []
    if not header_lines:
        header_lines = [line.strip() for line in raw.split('\n') if line.strip()]

    banned = {
        'host', 'content-length', 'connection', 'proxy-connection', 'transfer-encoding',
        'te', 'trailer', 'upgrade', 'keep-alive', 'accept-encoding'
    }
    allowed_exact = {
        'user-agent', 'accept', 'accept-language', 'content-type', 'cookie', 'referer', 'origin',
        'cache-control', 'pragma', 'dnt', 'priority', 'authorization', 'x-meili-api-key', 'x-client', 'x-client-date', 'x-client-version'
    }
    for line in header_lines:
        line = str(line or '').strip()
        if not line or ':' not in line:
            continue
        name, value = line.split(':', 1)
        lname = name.strip().lower()
        value = value.strip()
        if not lname or lname in banned or not value:
            continue
        if not (lname in allowed_exact or lname.startswith('sec-')):
            continue
        if lname == 'cookie':
            value = _normalize_cookie_header(value)
            canon = 'Cookie'
        elif lname == 'user-agent':
            canon = 'User-Agent'
        elif lname == 'content-type':
            canon = 'Content-Type'
        elif lname == 'accept':
            canon = 'Accept'
        elif lname == 'accept-language':
            canon = 'Accept-Language'
        elif lname == 'referer':
            canon = 'Referer'
        elif lname == 'origin':
            canon = 'Origin'
        elif lname == 'dnt':
            canon = 'DNT'
        elif lname == 'authorization':
            canon = 'Authorization'
        elif lname == 'x-meili-api-key':
            canon = 'X-Meili-API-Key'
        elif lname.startswith('x-client'):
            canon = lname
        else:
            canon = '-'.join(part.capitalize() if part else part for part in lname.split('-'))
        parsed[canon] = value
    return parsed



def _cookie_header_to_dict(cookie_value):
    out = {}
    for part in str(cookie_value or '').split(';'):
        part = part.strip()
        if not part or '=' not in part:
            continue
        k, v = part.split('=', 1)
        k = k.strip()
        v = v.strip()
        if k:
            out[k] = v
    return out


def _cookie_dict_to_header(cookie_dict):
    if not isinstance(cookie_dict, dict):
        return ''
    return _normalize_cookie_header('; '.join(f'{k}={v}' for k, v in cookie_dict.items() if k and v is not None))


def _civitai_headers_to_raw(parsed):
    if not isinstance(parsed, dict):
        return ''
    preferred = [
        'Cookie', 'Authorization', 'X-Meili-API-Key', 'User-Agent', 'Accept', 'Accept-Language',
        'Content-Type', 'Origin', 'Referer', 'x-client', 'x-client-date', 'x-client-version',
        'DNT', 'Priority', 'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform',
        'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site'
    ]
    lines = []
    seen = set()
    for key in preferred:
        if parsed.get(key):
            lines.append(f'{key}: {parsed[key]}')
            seen.add(key)
    for key, value in parsed.items():
        if key in seen or not value:
            continue
        lines.append(f'{key}: {value}')
    return '\n'.join(lines)


def _merge_civitai_browser_headers(current_raw, new_raw):
    """Merge collection-cookie cURL and multi-search Authorization cURL.

    Users usually paste collection.getAllUser cURL first (contains civitai.red Cookie),
    then multi-search cURL later (contains Authorization for search-new.civitai.com).
    Saving the latter used to overwrite the former, causing collection.getAllUser 401.
    """
    current = _parse_civitai_browser_headers(current_raw)
    new = _parse_civitai_browser_headers(new_raw)
    if not current:
        return _normalize_raw_browser_headers(new_raw)
    if not new:
        return _normalize_raw_browser_headers(current_raw)
    merged = dict(current)
    # Merge cookies by cookie name instead of letting a partial multi-search Cookie overwrite
    # the civitai.red login token. If the new Cookie contains the secure token, it updates it.
    cur_cookie = _cookie_header_to_dict(current.get('Cookie', ''))
    new_cookie = _cookie_header_to_dict(new.get('Cookie', ''))
    if cur_cookie or new_cookie:
        cur_cookie.update(new_cookie)
        merged['Cookie'] = _cookie_dict_to_header(cur_cookie)
    for key, value in new.items():
        if key == 'Cookie':
            continue
        if value:
            merged[key] = value
    return _civitai_headers_to_raw(merged)

def _split_civitai_raw_headers(raw_headers):
    """Split a combined Civitai cURL/header blob into collection-cookie and search-auth parts.

    - collection_headers: civitai.red Cookie used by collection.* and image.getInfinite.
    - search_headers: Authorization / X-Meili-API-Key used by search-new.civitai.com/multi-search.
    The old single civitai_browser_headers key is still kept as a legacy backup for import/export compatibility.
    """
    parsed = _parse_civitai_browser_headers(raw_headers)
    if not parsed:
        return '', ''
    collection = {}
    search = {}
    for key, value in parsed.items():
        if not value:
            continue
        if key == 'Cookie':
            collection[key] = value
        elif key in ('Authorization', 'X-Meili-API-Key'):
            search[key] = value
        elif key in ('User-Agent', 'Accept', 'Accept-Language', 'Content-Type', 'x-client', 'x-client-date', 'x-client-version') or str(key).lower().startswith('sec-'):
            # shared browser-shape headers are safe to store in both buckets.
            collection[key] = value
            search[key] = value
        elif key in ('Origin', 'Referer'):
            # endpoint-specific Origin/Referer are set at request time; keep out to avoid cross-domain confusion.
            continue
    return _civitai_headers_to_raw(collection), _civitai_headers_to_raw(search)


def load_civitai_remote_favorites_settings():
    settings = load_settings()
    enabled = bool(settings.get('civitai_remote_favorites_enabled', False))
    legacy_raw = _normalize_raw_browser_headers(settings.get('civitai_browser_headers', ''))
    collection_raw = _normalize_raw_browser_headers(settings.get('civitai_collection_headers', ''))
    search_raw = _normalize_raw_browser_headers(settings.get('civitai_search_headers', ''))
    if legacy_raw and (not collection_raw or not search_raw):
        legacy_collection, legacy_search = _split_civitai_raw_headers(legacy_raw)
        if not collection_raw:
            collection_raw = legacy_collection
        if not search_raw:
            search_raw = legacy_search
    default_collection_id = str(settings.get('civitai_default_collection_id', '') or '').strip()
    return enabled, collection_raw, default_collection_id, _parse_civitai_browser_headers(collection_raw)


def load_civitai_search_headers():
    settings = load_settings()
    legacy_raw = _normalize_raw_browser_headers(settings.get('civitai_browser_headers', ''))
    search_raw = _normalize_raw_browser_headers(settings.get('civitai_search_headers', ''))
    if not search_raw and legacy_raw:
        _collection, search_raw = _split_civitai_raw_headers(legacy_raw)
    return search_raw, _parse_civitai_browser_headers(search_raw)


def save_civitai_remote_favorites_settings(raw_headers='', enabled=False, default_collection_id='', preserve_if_empty=True, search_headers=None, collection_headers=None):
    settings = load_settings()
    current_legacy = _normalize_raw_browser_headers(settings.get('civitai_browser_headers', ''))
    current_collection = _normalize_raw_browser_headers(settings.get('civitai_collection_headers', ''))
    current_search = _normalize_raw_browser_headers(settings.get('civitai_search_headers', ''))
    if current_legacy and (not current_collection or not current_search):
        legacy_collection, legacy_search = _split_civitai_raw_headers(current_legacy)
        current_collection = current_collection or legacy_collection
        current_search = current_search or legacy_search

    # Backward compatibility: if caller sends one combined textarea, split it.
    raw_headers = _normalize_raw_browser_headers(raw_headers)
    incoming_collection = _normalize_raw_browser_headers(collection_headers if collection_headers is not None else '')
    incoming_search = _normalize_raw_browser_headers(search_headers if search_headers is not None else '')
    if raw_headers and not incoming_collection and not incoming_search:
        incoming_collection, incoming_search = _split_civitai_raw_headers(raw_headers)

    if preserve_if_empty:
        if not incoming_collection:
            incoming_collection = current_collection
        elif current_collection:
            # Merge cookies if user pasted a refreshed collection cURL.
            incoming_collection = _merge_civitai_browser_headers(current_collection, incoming_collection)
        if not incoming_search:
            incoming_search = current_search
        elif current_search:
            incoming_search = _merge_civitai_browser_headers(current_search, incoming_search)

    settings['civitai_remote_favorites_enabled'] = bool(enabled)
    settings['civitai_collection_headers'] = incoming_collection
    settings['civitai_search_headers'] = incoming_search
    # Keep a merged legacy key so old exports/imports and older builds still have something usable.
    settings['civitai_browser_headers'] = _merge_civitai_browser_headers(incoming_collection, incoming_search) if (incoming_collection or incoming_search) else ''
    settings['civitai_default_collection_id'] = str(default_collection_id or '').strip()
    saved = save_settings(settings)
    if saved:
        _invalidate_civitai_remote_collection_cache()
    return saved


def _civitai_remote_status():
    enabled, collection_raw, default_collection_id, collection_parsed = load_civitai_remote_favorites_settings()
    search_raw, search_parsed = load_civitai_search_headers()
    bridge = _civitai_browser_bridge_settings()
    cookie = collection_parsed.get('Cookie', '')
    return {
        'enabled': enabled,
        'has_headers': bool(collection_raw or search_raw),
        'has_collection_headers': bool(collection_raw),
        'has_search_headers': bool(search_raw),
        'has_cookie': bool(cookie),
        'cookie_len': len(cookie),
        'has_civitai_token': '__Secure-civitai-token=' in cookie,
        'has_authorization': bool(search_parsed.get('Authorization') or search_parsed.get('X-Meili-API-Key')),
        'collection_parsed_count': len(collection_parsed),
        'search_parsed_count': len(search_parsed),
        'parsed_count': len(collection_parsed) + len(search_parsed),
        'default_collection_id': default_collection_id,
        'browser_bridge_enabled': bool(bridge.get('enabled')),
        'browser_bridge_prefer': bool(bridge.get('prefer')),
        'browser_bridge_auto_renew': bool(bridge.get('auto_renew')),
        'browser_bridge_cdp_url': bridge.get('cdp_url') or '',
    }


def _civitai_trpc_headers(referer_image_id=None):
    enabled, raw_headers, default_collection_id, parsed = load_civitai_remote_favorites_settings()
    if not enabled or not raw_headers or not parsed:
        raise RuntimeError('Civitai 远端收藏未启用或未配置浏览器 Cookie/Headers')
    headers = dict(CIVITAI_HEADERS)
    headers.update(parsed)

    # v35: collection.* / image.getInfinite 是 civitai.red 站内 tRPC，认证靠
    # __Secure-civitai-token Cookie。search-new.civitai.com 的 Authorization/X-Meili
    # 只给 multi-search 用，不能带到 civitai.red tRPC，否则服务端可能按错误认证路径处理并返回 401。
    headers.pop('Authorization', None)
    headers.pop('X-Meili-API-Key', None)
    headers.pop('x-meili-api-key', None)

    headers.setdefault('Content-Type', 'application/json')
    headers.setdefault('Accept', '*/*')
    headers.setdefault('x-client', 'web')
    headers.setdefault('x-client-version', '5.0.1771')
    headers['Origin'] = CIVITAI_BASE_URL
    if referer_image_id:
        headers['Referer'] = f"{CIVITAI_BASE_URL}/images/{referer_image_id}"
    else:
        headers['Referer'] = f"{CIVITAI_BASE_URL}/"
    return headers


def _civitai_trpc_get(procedure, payload, timeout=20, referer_image_id=None, meta_values=None):
    # Civitai 的 tRPC 使用 superjson。浏览器在 image.getInfinite 首页请求里会把
    # cursor=null 配合 meta.values.cursor=["undefined"] 发送，否则后端会把 cursor 当作
    # null 校验，触发 invalid_union / expected bigint 之类的 400。
    input_obj = {'json': payload}
    if meta_values:
        input_obj['meta'] = {'values': meta_values}
    encoded = urllib.parse.quote(json.dumps(input_obj, ensure_ascii=False, separators=(',', ':')), safe='')
    url = f"{CIVITAI_BASE_URL}/api/trpc/{procedure}?input={encoded}"
    bridge = _civitai_browser_bridge_settings()
    if bridge.get('enabled') and bridge.get('prefer'):
        try:
            return _civitai_bridge_fetch(
                url,
                method='GET',
                headers={
                    'Accept': '*/*',
                    'Content-Type': 'application/json',
                    'x-client': 'web',
                    'x-client-version': '5.1.35',
                },
                timeout_ms=int(timeout or 20) * 1000,
                label=f'trpc_get:{procedure}',
            )
        except Exception as e:
            logger.warning(f"[CivitaiBrowserBridge] {procedure} GET failed, falling back to stored headers: {_safe_exception_text(e)}")
            try:
                enabled, raw_headers, _default_collection_id, parsed = load_civitai_remote_favorites_settings()
                if not (enabled and raw_headers and parsed):
                    raise
            except Exception:
                _civitai_bridge_open_renewal(f"{procedure} bridge unavailable")
                raise
    resp = _request_with_headers('GET', url, _civitai_trpc_headers(referer_image_id), throttle=_civitai_throttle, timeout=timeout)
    if int(getattr(resp, 'status_code', 0) or 0) in (401, 403):
        _civitai_bridge_open_renewal(f"{procedure} HTTP {resp.status_code}")
    return resp


def _civitai_trpc_post(procedure, payload, timeout=20, referer_image_id=None):
    url = f"{CIVITAI_BASE_URL}/api/trpc/{procedure}"
    bridge = _civitai_browser_bridge_settings()
    if bridge.get('enabled') and bridge.get('prefer'):
        try:
            return _civitai_bridge_fetch(
                url,
                method='POST',
                headers={
                    'Accept': '*/*',
                    'Content-Type': 'application/json',
                    'x-client': 'web',
                    'x-client-version': '5.1.35',
                },
                json_payload={'json': payload},
                timeout_ms=int(timeout or 20) * 1000,
                label=f'trpc_post:{procedure}',
            )
        except Exception as e:
            logger.warning(f"[CivitaiBrowserBridge] {procedure} POST failed, falling back to stored headers: {_safe_exception_text(e)}")
            try:
                enabled, raw_headers, _default_collection_id, parsed = load_civitai_remote_favorites_settings()
                if not (enabled and raw_headers and parsed):
                    raise
            except Exception:
                _civitai_bridge_open_renewal(f"{procedure} bridge unavailable")
                raise
    resp = _request_with_headers('POST', url, _civitai_trpc_headers(referer_image_id), throttle=_civitai_throttle, json={'json': payload}, timeout=timeout)
    if int(getattr(resp, 'status_code', 0) or 0) in (401, 403):
        _civitai_bridge_open_renewal(f"{procedure} HTTP {resp.status_code}")
    return resp


_CIVITAI_DEVALUE_UNDEFINED = object()
_CIVITAI_DEVALUE_HOLE = object()
_CIVITAI_DEVALUE_MAX_CHARS = 8 * 1024 * 1024
_CIVITAI_DEVALUE_MAX_NODES = 250000
_CIVITAI_DEVALUE_MAX_DEPTH = 128
_CIVITAI_DEVALUE_MAX_ARRAY_ITEMS = 250000
_CIVITAI_DEVALUE_MAX_TOTAL_SLOTS = 500000


def _civitai_devalue_unflatten(serialized):
    """Decode the JSON-safe subset emitted by Civitai's devalue transformer.

    Civitai currently serves a union of the older SuperJSON response envelope and
    ``devalue.stringify`` output.  Devalue containers hold integer references into
    one flat value table, so calling ``json.loads`` alone is not sufficient.

    The decoder is deliberately bounded and does not execute custom revivers.  It
    supports the JSON-like graph used by image.getInfinite plus Date, BigInt,
    primitive Object wrappers and null-prototype objects.  Unknown typed values,
    circular graphs and unsafe object keys fail closed.
    """
    if not isinstance(serialized, str):
        raise RuntimeError('Civitai tRPC devalue payload is not a string')
    if len(serialized) > _CIVITAI_DEVALUE_MAX_CHARS:
        raise RuntimeError('Civitai tRPC devalue payload is too large')
    try:
        values = json.loads(
            serialized,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                RuntimeError('Civitai tRPC devalue contains a non-finite number')
            ),
        )
    except Exception as exc:
        raise RuntimeError('Civitai tRPC devalue payload is not valid JSON') from exc
    # devalue can serialize a standalone primitive sentinel without a value
    # table (notably ``undefined`` results from mutation procedures).
    if type(values) is int:
        if values in (-1, -3, -4, -5):
            return None
        if values == -6:
            return -0.0
        raise RuntimeError('Civitai tRPC devalue standalone value is unsupported')
    if not isinstance(values, list) or not values:
        raise RuntimeError('Civitai tRPC devalue payload is not a value table')
    if len(values) > _CIVITAI_DEVALUE_MAX_NODES:
        raise RuntimeError('Civitai tRPC devalue value table is too large')

    hydrated = {}
    visiting = set()
    allocated_slots = 0

    def _reserve_slots(count):
        nonlocal allocated_slots
        if type(count) is not int or count < 0:
            raise RuntimeError('Civitai tRPC devalue allocation is invalid')
        allocated_slots += count
        if allocated_slots > _CIVITAI_DEVALUE_MAX_TOTAL_SLOTS:
            raise RuntimeError('Civitai tRPC devalue graph allocation is too large')

    def _reference(index, depth):
        if type(index) is not int:
            raise RuntimeError('Civitai tRPC devalue reference is not an integer')
        if index == -1:
            return _CIVITAI_DEVALUE_UNDEFINED
        if index == -2:
            return _CIVITAI_DEVALUE_HOLE
        # Keep the plugin's HTTP response strict JSON. These values have no useful
        # meaning in collection metadata and JSON.stringify would turn them null.
        if index in (-3, -4, -5):
            return None
        if index == -6:
            return -0.0
        if index < 0 or index >= len(values):
            raise RuntimeError('Civitai tRPC devalue reference is out of range')
        return _hydrate(index, depth)

    def _safe_key(key):
        if not isinstance(key, str):
            raise RuntimeError('Civitai tRPC devalue object key is not a string')
        if key in ('__proto__', 'prototype', 'constructor'):
            raise RuntimeError('Civitai tRPC devalue object contains an unsafe key')
        return key

    def _hydrate(index, depth=0):
        if depth > _CIVITAI_DEVALUE_MAX_DEPTH:
            raise RuntimeError('Civitai tRPC devalue graph is too deep')
        if index in visiting:
            raise RuntimeError('Civitai tRPC devalue graph contains a cycle')
        if index in hydrated:
            return hydrated[index]

        visiting.add(index)
        try:
            value = values[index]
            if isinstance(value, float) and not math.isfinite(value):
                raise RuntimeError('Civitai tRPC devalue contains a non-finite number')
            if value is None or isinstance(value, (str, bool, int, float)):
                hydrated[index] = value
                return value

            if isinstance(value, dict):
                _reserve_slots(len(value))
                obj = {}
                hydrated[index] = obj
                if len(value) > _CIVITAI_DEVALUE_MAX_ARRAY_ITEMS:
                    raise RuntimeError('Civitai tRPC devalue object is too large')
                for raw_key, raw_ref in value.items():
                    key = _safe_key(raw_key)
                    decoded = _reference(raw_ref, depth + 1)
                    if decoded is _CIVITAI_DEVALUE_UNDEFINED:
                        continue
                    if decoded is _CIVITAI_DEVALUE_HOLE:
                        raise RuntimeError('Civitai tRPC devalue hole appears outside an array')
                    obj[key] = decoded
                return obj

            if not isinstance(value, list):
                raise RuntimeError('Civitai tRPC devalue node has an unsupported type')
            if len(value) > _CIVITAI_DEVALUE_MAX_ARRAY_ITEMS:
                raise RuntimeError('Civitai tRPC devalue array is too large')

            if value and isinstance(value[0], str):
                kind = value[0]
                if kind == 'Date':
                    if len(value) != 2 or not isinstance(value[1], str) or len(value[1]) > 256:
                        raise RuntimeError('Civitai tRPC devalue Date is invalid')
                    hydrated[index] = value[1]
                    return value[1]
                if kind == 'BigInt':
                    raw = value[1] if len(value) == 2 else None
                    if not isinstance(raw, str) or len(raw) > 4096 or not re.fullmatch(r'-?\d+', raw):
                        raise RuntimeError('Civitai tRPC devalue BigInt is invalid')
                    decoded = int(raw)
                    hydrated[index] = decoded
                    return decoded
                if kind == 'Object':
                    if len(value) != 2:
                        raise RuntimeError('Civitai tRPC devalue Object wrapper is invalid')
                    decoded = _reference(value[1], depth + 1)
                    hydrated[index] = decoded
                    return decoded
                if kind == 'null':
                    if len(value) % 2 == 0:
                        raise RuntimeError('Civitai tRPC devalue null-object is invalid')
                    _reserve_slots((len(value) - 1) // 2)
                    obj = {}
                    hydrated[index] = obj
                    for offset in range(1, len(value), 2):
                        key = _safe_key(value[offset])
                        decoded = _reference(value[offset + 1], depth + 1)
                        if decoded is _CIVITAI_DEVALUE_UNDEFINED:
                            continue
                        if decoded is _CIVITAI_DEVALUE_HOLE:
                            raise RuntimeError('Civitai tRPC devalue hole appears outside an array')
                        obj[key] = decoded
                    return obj
                raise RuntimeError('Civitai tRPC devalue type is unsupported')

            # devalue sparse arrays are [-7, length, index, reference, ...].
            if value and value[0] == -7:
                if len(value) < 2 or type(value[1]) is not int:
                    raise RuntimeError('Civitai tRPC devalue sparse array is invalid')
                length = value[1]
                if length < 0 or length > _CIVITAI_DEVALUE_MAX_ARRAY_ITEMS or len(value) % 2 != 0:
                    raise RuntimeError('Civitai tRPC devalue sparse array is too large or malformed')
                _reserve_slots(length)
                array = [None] * length
                hydrated[index] = array
                for offset in range(2, len(value), 2):
                    slot = value[offset]
                    if type(slot) is not int or slot < 0 or slot >= length:
                        raise RuntimeError('Civitai tRPC devalue sparse array index is invalid')
                    decoded = _reference(value[offset + 1], depth + 1)
                    is_missing = (
                        decoded is _CIVITAI_DEVALUE_UNDEFINED
                        or decoded is _CIVITAI_DEVALUE_HOLE
                    )
                    array[slot] = None if is_missing else decoded
                return array

            _reserve_slots(len(value))
            array = []
            hydrated[index] = array
            for raw_ref in value:
                decoded = _reference(raw_ref, depth + 1)
                is_missing = (
                    decoded is _CIVITAI_DEVALUE_UNDEFINED
                    or decoded is _CIVITAI_DEVALUE_HOLE
                )
                array.append(None if is_missing else decoded)
            return array
        finally:
            visiting.discard(index)

    root = _hydrate(0)
    if root is _CIVITAI_DEVALUE_UNDEFINED or root is _CIVITAI_DEVALUE_HOLE:
        return None
    return root


def _civitai_unwrap_trpc_document(document, procedure='Civitai tRPC'):
    """Unwrap either the old SuperJSON envelope or the current devalue string."""
    label = re.sub(r'[^A-Za-z0-9_.-]+', '', str(procedure or 'Civitai tRPC'))[:80] or 'Civitai tRPC'
    if not isinstance(document, dict):
        raise RuntimeError(f'{label} response root is not an object')
    if document.get('error') is not None:
        raise RuntimeError(f'{label} returned a tRPC error envelope')
    result = document.get('result')
    if not isinstance(result, dict) or 'data' not in result:
        raise RuntimeError(f'{label} response is missing result.data')
    data = result.get('data')
    if isinstance(data, dict) and 'json' in data:
        return data.get('json')
    if isinstance(data, str):
        return _civitai_devalue_unflatten(data)
    if data is None:
        return None
    raise RuntimeError(f'{label} result.data has an unsupported type')


def _civitai_trpc_json(procedure, payload, timeout=20, referer_image_id=None, meta_values=None):
    """Call a Civitai tRPC GET endpoint and unwrap SuperJSON/devalue data.

    Remote collection rows returned by image.getInfinite usually omit generation
    metadata.  The public REST image query is not a reliable detail endpoint for
    every collection image, so selected collection items need the same tRPC
    detail calls used by the Civitai web client.
    """
    resp = _civitai_trpc_get(
        procedure, payload, timeout=timeout,
        referer_image_id=referer_image_id, meta_values=meta_values,
    )
    if resp.status_code != 200:
        raise RuntimeError(f'{procedure} HTTP {resp.status_code}')
    return _civitai_unwrap_trpc_document(resp.json(), procedure)


def _civitai_generation_detail_to_post(image_id, post_id, image_url, generation_data, votable_tags=None):
    """Normalize image.getGenerationData/tag.getVotableTags into gallery fields."""
    detail = {}
    if isinstance(generation_data, dict):
        detail.update(generation_data)
        detail['generationData'] = generation_data
        # Generation data schemas vary.  Treat the complete response as metadata
        # when there is no explicit meta object so existing recursive extractors
        # can still find prompt/negativePrompt/resources/tags.
        if not isinstance(detail.get('meta'), dict):
            detail['meta'] = generation_data
    elif generation_data not in (None, ''):
        detail['generationData'] = generation_data
        detail['meta'] = generation_data

    if image_id:
        detail.setdefault('id', image_id)
        detail.setdefault('imageId', image_id)
    if post_id:
        detail.setdefault('postId', post_id)
    if image_url:
        detail.setdefault('url', image_url)

    if isinstance(votable_tags, (list, tuple, dict, str)) and votable_tags:
        # _civitai_extract_tag_names supports lists of {name: ...} as well as
        # strings and nested objects.  Keep generation tags and public image tags.
        detail['imageTags'] = votable_tags

    return _civitai_item_to_danbooru_shape(detail)


def _civitai_remote_get_collections():
    payload = {'permissions': ['ADD', 'ADD_REVIEW'], 'type': 'Image', 'authed': True}
    resp = _civitai_trpc_get('collection.getAllUser', payload, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f'collection.getAllUser HTTP {resp.status_code}')
    collections = _civitai_unwrap_trpc_document(resp.json(), 'collection.getAllUser')
    if not isinstance(collections, list) or any(not isinstance(item, dict) for item in collections):
        raise RuntimeError('collection.getAllUser response is not a list of collection objects')
    return collections


def _civitai_remote_pick_collection():
    enabled, raw_headers, default_collection_id, parsed = load_civitai_remote_favorites_settings()
    collections = _civitai_remote_get_collections()
    if not collections:
        raise RuntimeError('Civitai 账号没有可写 Image 收藏夹')
    if default_collection_id:
        for c in collections:
            if str(c.get('id')) == str(default_collection_id):
                return c
    for c in collections:
        if str(c.get('type') or '').lower() == 'image' and bool(c.get('isOwner', True)):
            return c
    return collections[0]


def _civitai_remote_item_collections(image_id):
    payload = {'imageId': int(image_id), 'type': 'Image', 'authed': True}
    resp = _civitai_trpc_get('collection.getUserCollectionItemsByItem', payload, timeout=20, referer_image_id=image_id)
    if resp.status_code != 200:
        raise RuntimeError(f'collection.getUserCollectionItemsByItem HTTP {resp.status_code}')
    items = _civitai_unwrap_trpc_document(resp.json(), 'collection.getUserCollectionItemsByItem')
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise RuntimeError('collection.getUserCollectionItemsByItem response is not a list of objects')
    return items


def _civitai_remote_save_item(image_id, remove=False):
    image_id = int(image_id)
    selected = _civitai_remote_pick_collection()
    collection_id = int(selected.get('id'))
    user_id = selected.get('userId')
    read = selected.get('read') or 'Private'
    if remove:
        collections = []
        remove_ids = [collection_id]
    else:
        collections = [{'collectionId': collection_id, 'read': read}]
        if user_id is not None:
            collections[0]['userId'] = user_id
        remove_ids = []
    payload = {
        'imageId': image_id,
        'type': 'Image',
        'authed': True,
        'collections': collections,
        'removeFromCollectionIds': remove_ids,
    }
    resp = _civitai_trpc_post('collection.saveItem', payload, timeout=20, referer_image_id=image_id)
    if resp.status_code != 200:
        raise RuntimeError(f'collection.saveItem HTTP {resp.status_code}')
    response_data = _civitai_unwrap_trpc_document(resp.json(), 'collection.saveItem')
    _invalidate_civitai_remote_collection_cache(collection_id)
    return {'collection': selected, 'response': response_data}


def _civitai_remote_resolve_collection(collection_ref=''):
    collections = _civitai_remote_get_collections()
    if not collections:
        raise RuntimeError('Civitai 账号没有可浏览的 Image 收藏夹')
    ref = str(collection_ref or '').strip()
    if ref:
        ref_l = ref.lower()
        for c in collections:
            if str(c.get('id')) == ref or str(c.get('name') or '').strip().lower() == ref_l:
                return c
    return _civitai_remote_pick_collection()


def _civitai_remote_media_url(item, width=None, original=False):
    if not isinstance(item, dict):
        return ''
    thumb = str(item.get('thumbnailUrl') or '').strip()
    raw_url = str(item.get('url') or item.get('image') or item.get('imageUrl') or '').strip()
    if thumb.startswith('http') and not original:
        return thumb
    if raw_url.startswith('http'):
        return raw_url
    if not raw_url:
        return ''
    name = str(item.get('name') or '').strip().lstrip('/')
    ext = _file_ext_from_url(name or '', fallback=str((item.get('mimeType') or 'image/jpeg')).split('/')[-1])
    filename = name or f"{item.get('id') or raw_url}.{ext}"
    filename_q = urllib.parse.quote(filename, safe='-_.()~')
    prefix = CIVITAI_IMAGE_CDN_PREFIX.rstrip('/')
    if original:
        return f"{prefix}/{raw_url}/original=true/{filename_q}"
    if width:
        return f"{prefix}/{raw_url}/width={int(width)},quality=90/{filename_q}"
    return f"{prefix}/{raw_url}/original=true/{filename_q}"


def _civitai_remote_get_collection_posts(
    collection_ref='', limit=40, page=1, force_refresh=False, session_id=None
):
    """Read a remote collection into a bounded prefix buffer and page locally.

    ``image.getInfinite`` currently returns up to 100 images per upstream cursor
    even when the gallery page size is 40. Advancing that cursor after returning
    only the first 40 silently skips the other 60. The cache therefore retains
    every decoded upstream batch, fetches until the requested local page is
    covered, and only advances the upstream cursor after the whole batch has been
    buffered.
    """
    global _CIVITAI_LAST_SEARCH_DEBUG
    selected = _civitai_remote_resolve_collection(collection_ref)
    if not isinstance(selected, dict) or selected.get('id') in (None, ''):
        raise RuntimeError('Civitai selected collection is missing an id')
    collection_id = int(selected.get('id'))
    limit_i = max(1, min(int(limit or 40), 100))
    page_i = max(int(page or 1), 1)
    target_count = page_i * limit_i
    requested_session_id = str(session_id or '').strip()
    if target_count > _CIVITAI_REMOTE_COLLECTION_MAX_BUFFERED_POSTS:
        raise RuntimeError('Civitai remote collection page exceeds the safe buffer limit')

    full_key = json.dumps(
        {'kind': 'remote_collection_buffer_v54_union', 'collectionId': collection_id},
        sort_keys=True, ensure_ascii=False,
    )

    collection_count_fields = {}
    for k in ('items', 'itemCount', 'imageCount', 'count', 'size', 'totalItems', 'totalCount'):
        if k in selected:
            collection_count_fields[k] = selected.get(k)
    for k in ('stats', 'metadata', '_count'):
        if isinstance(selected.get(k), dict):
            collection_count_fields[k] = selected.get(k)

    now = time.time()
    with _CIVITAI_REMOTE_COLLECTION_CACHE_LOCK:
        for stale_key, stale_state in list(_CIVITAI_REMOTE_COLLECTION_FULL_CACHE.items()):
            stale_at = stale_state.get('timestamp', 0) if isinstance(stale_state, dict) else 0
            if now - float(stale_at or 0) > _CIVITAI_REMOTE_COLLECTION_CACHE_TTL_SECONDS:
                _CIVITAI_REMOTE_COLLECTION_FULL_CACHE.pop(stale_key, None)

        if force_refresh:
            _CIVITAI_REMOTE_COLLECTION_FULL_CACHE.pop(full_key, None)
        state = _CIVITAI_REMOTE_COLLECTION_FULL_CACHE.get(full_key)
        if requested_session_id and (
            not isinstance(state, dict)
            or str(state.get('session_id') or '') != requested_session_id
        ):
            raise RuntimeError('Civitai remote collection pagination session expired')
        if not isinstance(state, dict) or not isinstance(state.get('posts'), list):
            state = {
                'collection_id': collection_id,
                'session_id': os.urandom(16).hex(),
                'posts': [],
                'seen': set(),
                'cursor_history': set(),
                'consecutive_empty_batches': 0,
                'started': False,
                'complete': False,
                'next_cursor': None,
                'upstream_batches': 0,
                'timestamp': now,
                'collection': dict(selected),
            }
            _CIVITAI_REMOTE_COLLECTION_FULL_CACHE[full_key] = state
        elif not isinstance(state.get('seen'), set):
            state['seen'] = {
                str(post.get('civitai_image_id') or post.get('id') or post.get('file_url') or '')
                for post in state.get('posts') or [] if isinstance(post, dict)
            }
        if not isinstance(state.get('cursor_history'), set):
            state['cursor_history'] = set()
        if not str(state.get('session_id') or ''):
            state['session_id'] = os.urandom(16).hex()

        batches_this_call = 0
        last_payload_keys = []
        while len(state['posts']) < target_count and not state.get('complete'):
            if batches_this_call >= _CIVITAI_REMOTE_COLLECTION_MAX_BATCHES_PER_CALL:
                raise RuntimeError('Civitai remote collection requires too many upstream batches')
            cursor = state.get('next_cursor') if state.get('started') else None
            cursor_marker = (type(cursor).__name__, str(cursor))
            if cursor_marker in state['cursor_history']:
                raise RuntimeError('image.getInfinite returned a repeated or cyclic cursor')
            payload = {
                'collectionId': collection_id,
                'period': 'AllTime',
                'sort': 'Newest',
                'include': ['cosmetics'],
                'cursor': cursor,
                'authed': True,
            }
            last_payload_keys = sorted(payload.keys())
            meta_values = {'cursor': ['undefined']} if cursor is None else None
            resp = _civitai_trpc_get('image.getInfinite', payload, timeout=30, meta_values=meta_values)
            if resp.status_code != 200:
                raise RuntimeError(f'image.getInfinite HTTP {resp.status_code}')
            blob = _civitai_unwrap_trpc_document(resp.json(), 'image.getInfinite')
            if not isinstance(blob, dict):
                raise RuntimeError('image.getInfinite response is not an object')
            items = blob.get('items')
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise RuntimeError('image.getInfinite items is not a list of objects')
            next_cursor = blob.get('nextCursor')
            if isinstance(next_cursor, bool) or (
                next_cursor is not None and not isinstance(next_cursor, (int, str))
            ):
                raise RuntimeError('image.getInfinite nextCursor has an unsupported type')
            if isinstance(next_cursor, str):
                next_cursor = next_cursor.strip() or None
            if next_cursor is not None and state.get('started') and next_cursor == cursor:
                raise RuntimeError('image.getInfinite returned a non-advancing cursor')

            normalized_batch = []
            pending_seen = set()
            for batch_index, raw_item in enumerate(items):
                item = dict(raw_item)
                item['_civitai_api_base'] = CIVITAI_BASE_URL
                post = _civitai_item_to_danbooru_shape(item)
                if not post:
                    continue
                post['civitai_api_base'] = CIVITAI_BASE_URL
                post['civitai_remote_collection_id'] = str(collection_id)
                post['civitai_remote_collection_name'] = str(selected.get('name') or '')
                post['civitai_remote_favorited'] = True
                identity = str(
                    post.get('civitai_image_id') or post.get('id') or post.get('file_url')
                    or f"batch:{state.get('upstream_batches', 0)}:{batch_index}"
                )
                if identity in state['seen'] or identity in pending_seen:
                    continue
                pending_seen.add(identity)
                normalized_batch.append(post)

            if len(state['posts']) + len(normalized_batch) > _CIVITAI_REMOTE_COLLECTION_MAX_BUFFERED_POSTS:
                raise RuntimeError('Civitai remote collection exceeds the safe buffer limit')
            state['seen'].update(pending_seen)
            state['posts'].extend(normalized_batch)
            state['cursor_history'].add(cursor_marker)
            state['started'] = True
            state['next_cursor'] = next_cursor
            state['complete'] = next_cursor is None
            state['consecutive_empty_batches'] = (
                0 if normalized_batch
                else int(state.get('consecutive_empty_batches') or 0) + 1
            )
            state['upstream_batches'] = int(state.get('upstream_batches') or 0) + 1
            state['timestamp'] = time.time()
            batches_this_call += 1

            if not items and next_cursor is None:
                state['complete'] = True
            if (
                next_cursor is not None
                and state['consecutive_empty_batches'] >= 3
            ):
                raise RuntimeError('image.getInfinite pagination made no progress')

        state['timestamp'] = time.time()
        posts = list(state.get('posts') or [])
        has_more = not bool(state.get('complete'))
        upstream_batches = int(state.get('upstream_batches') or 0)

    return posts, {
        'label': 'remote_collection_buffer',
        'collectionId': collection_id,
        'collectionName': str(selected.get('name') or ''),
        'session_id': str(state.get('session_id') or ''),
        'items': len(posts),
        'total_items': len(posts),
        'next_cursor': has_more,
        'has_more': has_more,
        'local_pagination': True,
        'filter_mode': 'browser_collection_unfiltered_v54_union',
        'collection_count_fields': collection_count_fields,
        'payload_keys': last_payload_keys,
        'cache_key': full_key,
        'upstream_batches': upstream_batches,
        'end_reason': 'buffered_with_upstream_cursor' if has_more else 'remote_collection_complete',
    }

def _danbooru_cookie_status():
    enabled, cookie = load_danbooru_cookie()
    return {
        "enabled": enabled,
        "has_cookie": bool(cookie),
        "has_cf_clearance": "cf_clearance=" in cookie.lower(),
        "length": len(cookie or ""),
    }


def _apply_danbooru_cookie_headers(headers, url=None):
    """Apply optional user-provided Danbooru browser cookies to Danbooru requests only."""
    try:
        if url and "donmai.us" not in str(url):
            return headers
        enabled, cookie = load_danbooru_cookie()
        if enabled and cookie:
            headers["Cookie"] = cookie
            # Keep UA close to the browser used to obtain cf_clearance. curl_cffi supplies
            # the corresponding TLS/HTTP2 fingerprint when that path is used.
            headers["User-Agent"] = DANBOORU_BROWSER_UA
            headers.setdefault("Referer", DANBOORU_BASE_URL + "/posts")
        headers = _apply_danbooru_browser_headers(headers, url)
        return headers
    except Exception as e:
        logger.debug(f"[Danbooru] Cookie header apply skipped: {e}")
        return headers


_REDACTED = "<redacted>"
_SENSITIVE_HEADER_NAMES = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie",
    "x-meili-api-key", "x-api-key",
})
_SENSITIVE_QUERY_NAMES = frozenset({
    "api_key", "apikey", "api-key", "key", "token", "access_token",
    "access-token", "refresh_token", "refresh-token", "authorization",
    "auth", "cookie", "password", "passwd", "client_secret", "secret",
    "login", "x-meili-api-key", "x_api_key",
})
_CONFIG_SECRET_REDACTION_STATE = threading.local()


def _is_sensitive_name(name):
    normalized = str(name or "").strip().lower()
    return normalized in _SENSITIVE_HEADER_NAMES or normalized in _SENSITIVE_QUERY_NAMES


def _redact_url(url):
    """Return a log-safe URL while preserving non-sensitive routing information."""
    text = str(url or "")
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme and parsed.netloc:
            host = parsed.hostname or ""
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            try:
                port = f":{parsed.port}" if parsed.port else ""
            except ValueError:
                port = ""
            netloc = f"{host}{port}"
            query_items = []
            for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
                query_items.append((key, _REDACTED if _is_sensitive_name(key) else value))
            safe_query = urllib.parse.urlencode(query_items, doseq=True)
            safe_fragment = _REDACTED if parsed.fragment and any(
                f"{name}=" in parsed.fragment.lower() for name in _SENSITIVE_QUERY_NAMES
            ) else parsed.fragment
            return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, safe_query, safe_fragment))
    except Exception:
        pass

    # Best effort for URL fragments embedded in requests exception strings.
    text = re.sub(
        r"(?i)(https?://)[^/@\s'\"]+@",
        lambda match: match.group(1) + _REDACTED + "@",
        text,
    )
    sensitive_names = "|".join(re.escape(name) for name in sorted(_SENSITIVE_QUERY_NAMES, key=len, reverse=True))
    return re.sub(
        rf"(?i)([?&](?:{sensitive_names})=)[^&#\s'\"]+",
        lambda match: match.group(1) + _REDACTED,
        text,
    )


def _redact_headers(headers):
    """Copy headers for diagnostics without exposing authentication material."""
    safe = {}
    for key, value in dict(headers or {}).items():
        safe[key] = _REDACTED if _is_sensitive_name(key) else value
    return safe


def _configured_secret_values():
    """Best-effort configured secrets for diagnostic text; guarded against log recursion."""
    if getattr(_CONFIG_SECRET_REDACTION_STATE, "active", False):
        return []
    _CONFIG_SECRET_REDACTION_STATE.active = True
    values = []

    def add(value):
        value = str(value or "")
        # Avoid replacing common one-character values throughout a log line.
        if len(value) >= 4 and value not in values:
            values.append(value)

    try:
        loader = globals().get("load_user_auth")
        if callable(loader):
            username, api_key = loader()
            add(username)
            add(api_key)
        loader = globals().get("load_gelbooru_auth")
        if callable(loader):
            user_id, api_key = loader()
            add(user_id)
            add(api_key)
        loader = globals().get("load_civitai_auth")
        if callable(loader):
            add(loader())
        loader = globals().get("load_danbooru_cookie")
        if callable(loader):
            _enabled, cookie = loader()
            add(cookie)
        loader = globals().get("load_danbooru_browser_headers")
        if callable(loader):
            _enabled, raw, parsed = loader()
            add(raw)
            for key, value in dict(parsed or {}).items():
                if _is_sensitive_name(key):
                    add(value)
        loader = globals().get("load_civitai_remote_favorites_settings")
        if callable(loader):
            _enabled, raw, _collection_id, parsed = loader()
            add(raw)
            for key, value in dict(parsed or {}).items():
                if _is_sensitive_name(key):
                    add(value)
        loader = globals().get("load_civitai_search_headers")
        if callable(loader):
            raw, parsed = loader()
            add(raw)
            for key, value in dict(parsed or {}).items():
                if _is_sensitive_name(key):
                    add(value)
    except Exception:
        # Redaction must never turn a log call into another failure.
        pass
    finally:
        _CONFIG_SECRET_REDACTION_STATE.active = False
    return values


def _sanitize_log_text(text, *, include_configured=True, max_length=None):
    """Sanitize URLs, credential headers, query secrets and exception text for logs."""
    value = str(text or "")

    # Sanitize complete URLs first so userinfo and query strings are handled structurally.
    value = re.sub(
        r"https?://[^\s'\"<>]+",
        lambda match: _redact_url(match.group(0)),
        value,
        flags=re.I,
    )

    header_names = "|".join(re.escape(name) for name in sorted(_SENSITIVE_HEADER_NAMES, key=len, reverse=True))
    query_names = "|".join(re.escape(name) for name in sorted(_SENSITIVE_QUERY_NAMES, key=len, reverse=True))

    # Dict/JSON/repr forms, for example {'Authorization': 'Bearer secret'}.
    quoted_pattern = re.compile(
        rf"(?i)(?P<prefix>['\"]?(?:{header_names}|{query_names})['\"]?\s*[:=]\s*)"
        rf"(?P<quote>['\"])(?P<secret>.*?)(?P=quote)"
    )
    value = quoted_pattern.sub(
        lambda match: f"{match.group('prefix')}{match.group('quote')}{_REDACTED}{match.group('quote')}",
        value,
    )

    # Header-line and unquoted key/value forms used by requests/curl errors.
    value = re.sub(
        rf"(?im)(\b(?:{header_names})\b\s*:\s*)(?!['\"])[^\r\n]+",
        lambda match: match.group(1) + _REDACTED,
        value,
    )
    value = re.sub(
        rf"(?i)(\b(?:{query_names})\b\s*[=:]\s*)(?!['\"])[^&\s,;}}\]]+",
        lambda match: match.group(1) + _REDACTED,
        value,
    )
    value = re.sub(
        r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+",
        lambda match: f"{match.group(1)} {_REDACTED}",
        value,
    )

    if include_configured:
        for secret in sorted(_configured_secret_values(), key=len, reverse=True):
            value = value.replace(secret, _REDACTED)
    if max_length is not None:
        value = value[:max(0, int(max_length))]
    return value


def _safe_exception_text(exc):
    return _sanitize_log_text(f"{type(exc).__name__}: {exc}")


class _SensitiveLogFilter(logging.Filter):
    """Defense in depth: every record emitted by this module is redacted."""

    def filter(self, record):
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + "".join(traceback.format_exception(*record.exc_info))
            record.msg = _sanitize_log_text(message, include_configured=False)
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            if record.stack_info:
                record.stack_info = _sanitize_log_text(record.stack_info, include_configured=False)
        except Exception:
            record.msg = "<log message redacted>"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


if not any(isinstance(existing, _SensitiveLogFilter) for existing in logger.filters):
    logger.addFilter(_SensitiveLogFilter())


def _diag_redact_url(url):
    return _redact_url(url)


class LegacyGalleryError(RuntimeError):
    """Structured failure for the legacy /posts data path."""

    def __init__(self, code, http_status, message, *, source="", retryable=False,
                 upstream_status=None, retry_after_seconds=None):
        super().__init__(message)
        self.code = str(code or "upstream_error")
        self.http_status = int(http_status or 500)
        self.public_message = str(message or "上游请求失败")
        self.source = str(source or "")
        self.retryable = bool(retryable)
        self.upstream_status = int(upstream_status) if upstream_status is not None else None
        self.retry_after_seconds = retry_after_seconds

    def to_dict(self):
        payload = {
            "code": self.code,
            "httpStatus": self.http_status,
            "retryable": self.retryable,
            "message": self.public_message,
        }
        if self.source:
            payload["source"] = self.source
        if self.upstream_status is not None:
            payload["upstreamStatus"] = self.upstream_status
        if self.retry_after_seconds is not None:
            payload["retryAfterSeconds"] = self.retry_after_seconds
        return payload


def _retry_after_seconds(response):
    try:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        return max(0, int(float(value)))
    except Exception:
        return None


def _legacy_error_from_response(source, response, context="上游请求"):
    status = int(getattr(response, "status_code", 0) or 0)
    retry_after = _retry_after_seconds(response)
    if status == 400:
        return LegacyGalleryError("invalid_request", 400, f"{context}被上游拒绝", source=source, upstream_status=status)
    if status == 401:
        return LegacyGalleryError("auth_invalid", 401, f"{context}认证失败", source=source, upstream_status=status)
    if status == 403:
        code = "challenge" if _is_cloudflare_challenge(response) else "forbidden"
        return LegacyGalleryError(code, 403, f"{context}被上游拒绝", source=source, upstream_status=status)
    if status == 429:
        return LegacyGalleryError(
            "rate_limited", 429, f"{context}触发上游限流", source=source,
            retryable=True, upstream_status=status, retry_after_seconds=retry_after,
        )
    if status in (408, 504):
        return LegacyGalleryError("upstream_timeout", 504, f"{context}超时", source=source, retryable=True, upstream_status=status)
    if status == 503:
        return LegacyGalleryError(
            "upstream_busy", 503, f"{context}暂时不可用", source=source,
            retryable=True, upstream_status=status, retry_after_seconds=retry_after,
        )
    return LegacyGalleryError(
        "bad_gateway", 502, f"{context}返回异常状态", source=source,
        retryable=status >= 500 or status == 0, upstream_status=status or None,
    )


def _legacy_error_from_exception(source, exc, context="上游请求"):
    if isinstance(exc, LegacyGalleryError):
        return exc
    if isinstance(exc, requests.exceptions.HTTPError) and getattr(exc, "response", None) is not None:
        return _legacy_error_from_response(source, exc.response, context=context)
    if isinstance(exc, requests.exceptions.Timeout):
        return LegacyGalleryError("upstream_timeout", 504, f"{context}超时", source=source, retryable=True)
    if isinstance(exc, (requests.exceptions.ProxyError, requests.exceptions.ConnectionError, requests.exceptions.SSLError)):
        return LegacyGalleryError("network_unavailable", 502, f"{context}网络不可用", source=source, retryable=True)
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return LegacyGalleryError("schema_changed", 502, f"{context}响应无法解析", source=source, retryable=False)
    return LegacyGalleryError("upstream_error", 502, f"{context}失败", source=source, retryable=False)


def _raise_for_legacy_response(source, response, context="上游请求"):
    if not (200 <= int(getattr(response, "status_code", 0) or 0) < 300):
        raise _legacy_error_from_response(source, response, context=context)


def _validate_legacy_posts_json(result_text, source):
    """Validate the legacy success payload without changing its bare-array shape."""
    try:
        value = json.loads(result_text)
    except Exception as exc:
        raise LegacyGalleryError(
            "schema_changed", 502, "上游响应无法解析", source=source
        ) from exc
    if not isinstance(value, list):
        raise LegacyGalleryError(
            "schema_changed", 502, "上游响应结构异常", source=source
        )
    return result_text


class URLPolicyError(ValueError):
    """A user-controlled URL failed the purpose-specific outbound policy."""

    def __init__(self, code, message, http_status=403):
        super().__init__(message)
        self.code = str(code or "url_not_allowed")
        self.public_message = str(message or "目标 URL 不允许访问")
        self.http_status = int(http_status or 403)


_OUTBOUND_URL_POLICIES = {
    # User-facing media proxy and workflow selections can fetch only media owned by
    # the four providers supported by this node.
    "image_proxy": {
        "suffixes": ("donmai.us", "gelbooru.com", "yande.re", "civitai.com", "civitai.red", "civitai.green", "civitai.delivery"),
    },
    "selection_media": {
        "suffixes": ("donmai.us", "gelbooru.com", "yande.re", "civitai.com", "civitai.red", "civitai.green", "civitai.delivery"),
    },
    "danbooru_media": {"suffixes": ("donmai.us",)},
    "gelbooru_media": {"suffixes": ("gelbooru.com",)},
    "yandere_media": {"suffixes": ("yande.re",)},
    "civitai_media": {
        "suffixes": ("civitai.com", "civitai.red", "civitai.green", "civitai.delivery"),
    },
    "civitai_prompt": {
        "suffixes": ("civitai.com", "civitai.red", "civitai.green", "civitai.delivery"),
    },
    # Kept separate from media so future user-controlled provider API URLs cannot
    # silently widen the image policy.
    "provider_api": {
        "exact": (
            "danbooru.donmai.us", "gelbooru.com", "yande.re",
            "civitai.com", "civitai.red", "search-new.civitai.com",
        ),
    },
}
_REDIRECT_STATUSES = frozenset((301, 302, 303, 307, 308))
_CREDENTIAL_HEADER_NAMES = frozenset({
    "authorization", "proxy-authorization", "cookie", "x-meili-api-key", "x-api-key",
})


def _normalize_policy_host(host):
    host = str(host or "").strip().rstrip(".").lower()
    if not host:
        return ""
    try:
        host = host.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError) as exc:
        raise URLPolicyError("invalid_host", "目标 URL 主机名无效", 400) from exc
    if len(host) > 253:
        raise URLPolicyError("invalid_host", "目标 URL 主机名无效", 400)
    labels = host.split(".")
    if any(
        not label
        or len(label) > 63
        or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
        for label in labels
    ):
        raise URLPolicyError("invalid_host", "目标 URL 主机名无效", 400)
    return host


def _host_matches_policy(host, purpose):
    policy = _OUTBOUND_URL_POLICIES.get(str(purpose or ""))
    if not policy:
        return False
    if host in set(policy.get("exact") or ()):
        return True
    return any(host == suffix or host.endswith("." + suffix) for suffix in (policy.get("suffixes") or ()))


def _strip_credential_headers(headers):
    return {
        key: value for key, value in dict(headers or {}).items()
        if str(key or "").strip().lower() not in _CREDENTIAL_HEADER_NAMES
    }


def _assert_public_ip(value):
    try:
        address = ipaddress.ip_address(str(value).split("%", 1)[0])
    except ValueError as exc:
        raise URLPolicyError("invalid_dns_result", "目标主机 DNS 结果无效", 403) from exc
    if (
        not address.is_global
        or address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise URLPolicyError("non_public_address", "目标主机解析到非公网地址", 403)
    return str(address)


def _validate_url_for_purpose(url, purpose, resolver=None):
    """Validate syntax, allowlist and every DNS answer before an outbound fetch."""
    raw = str(url or "").strip()
    if not raw:
        raise URLPolicyError("empty_url", "目标 URL 不能为空", 400)
    if any(ord(char) < 32 for char in raw):
        raise URLPolicyError("invalid_url", "目标 URL 格式无效", 400)
    try:
        parsed = urllib.parse.urlsplit(raw)
    except Exception as exc:
        raise URLPolicyError("invalid_url", "目标 URL 格式无效", 400) from exc
    if parsed.scheme.lower() != "https":
        raise URLPolicyError("https_required", "仅允许 HTTPS 目标 URL", 400)
    try:
        username = parsed.username
        password = parsed.password
        raw_host = parsed.hostname
    except ValueError as exc:
        raise URLPolicyError("invalid_url", "目标 URL 格式无效", 400) from exc
    if username is not None or password is not None:
        raise URLPolicyError("userinfo_forbidden", "目标 URL 不允许包含用户信息", 400)
    if not parsed.netloc or not raw_host:
        raise URLPolicyError("empty_host", "目标 URL 缺少主机名", 400)
    try:
        port = parsed.port
    except ValueError as exc:
        raise URLPolicyError("invalid_port", "目标 URL 端口无效", 400) from exc
    if port not in (None, 443):
        raise URLPolicyError("port_not_allowed", "目标 URL 端口不允许访问", 403)

    try:
        literal_ip = ipaddress.ip_address(str(raw_host).split("%", 1)[0])
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        _assert_public_ip(literal_ip)
        # These purpose policies intentionally contain provider DNS names only.
        raise URLPolicyError("ip_literal_forbidden", "目标 URL 不允许使用 IP 地址", 403)

    host = _normalize_policy_host(raw_host)
    if not _host_matches_policy(host, purpose):
        raise URLPolicyError("host_not_allowed", "目标 URL 主机不在允许列表", 403)

    resolver = resolver or socket.getaddrinfo
    try:
        answers = resolver(host, 443, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as exc:
        raise URLPolicyError("dns_unavailable", "目标主机 DNS 校验失败", 403) from exc
    addresses = []
    for answer in answers or ():
        try:
            candidate = answer[4][0]
        except (IndexError, TypeError):
            raise URLPolicyError("invalid_dns_result", "目标主机 DNS 结果无效", 403)
        normalized_ip = _assert_public_ip(candidate)
        if normalized_ip not in addresses:
            addresses.append(normalized_ip)
    if not addresses:
        raise URLPolicyError("dns_empty", "目标主机没有可用公网地址", 403)

    # HTTPS port 443 is the default origin; canonicalize an explicit :443 so it
    # cannot manufacture a false cross-origin boundary (or bypass a same-origin one).
    normalized_netloc = host
    normalized_url = urllib.parse.urlunsplit(("https", normalized_netloc, parsed.path or "/", parsed.query, parsed.fragment))
    return {
        "url": normalized_url,
        "host": host,
        "origin": f"https://{normalized_netloc}",
        "addresses": tuple(addresses),
        "purpose": str(purpose),
    }


def _validate_response_redirect_history(response, purpose):
    """Reject clients that auto-followed; first validate every observed hop for evidence."""
    history = list(getattr(response, "history", None) or ())
    for hop in history:
        hop_url = str(getattr(hop, "url", "") or "")
        if hop_url:
            _validate_url_for_purpose(hop_url, purpose)
        location = str(getattr(hop, "headers", {}).get("Location", "") or "")
        if location:
            _validate_url_for_purpose(urllib.parse.urljoin(hop_url, location), purpose)
    final_url = str(getattr(response, "url", "") or "")
    if final_url:
        _validate_url_for_purpose(final_url, purpose)
    if history:
        raise URLPolicyError("automatic_redirect_forbidden", "上游重定向未通过安全客户端处理", 403)


def _close_outbound_response(response):
    try:
        close_response = getattr(response, "close", None)
        if callable(close_response):
            close_response()
    except Exception:
        pass
    try:
        ephemeral_session = getattr(response, "_outbound_ephemeral_session", None)
        if ephemeral_session is not None:
            ephemeral_session.close()
    except Exception:
        pass


def _safe_fetch_with_allowlist(url, purpose, request_once, max_redirects=5):
    """GET with manual, pre-flight validated redirects and credential stripping."""
    current = _validate_url_for_purpose(url, purpose)
    suppress_credentials = False
    for redirect_count in range(max(0, int(max_redirects)) + 1):
        response = request_once(
            current["url"],
            allow_redirects=False,
            suppress_credentials=suppress_credentials,
        )
        try:
            _validate_response_redirect_history(response, purpose)
            response_url = str(getattr(response, "url", "") or current["url"])
            validated_response_url = _validate_url_for_purpose(response_url, purpose)
            if validated_response_url["origin"] != current["origin"]:
                raise URLPolicyError("automatic_redirect_forbidden", "上游发生未受控跨站重定向", 403)
        except Exception:
            _close_outbound_response(response)
            raise

        status = int(getattr(response, "status_code", 0) or 0)
        if status not in _REDIRECT_STATUSES:
            return response
        location = str(getattr(response, "headers", {}).get("Location", "") or "").strip()
        if not location:
            _close_outbound_response(response)
            raise URLPolicyError("invalid_redirect", "上游重定向缺少目标地址", 403)
        if redirect_count >= max_redirects:
            _close_outbound_response(response)
            raise URLPolicyError("too_many_redirects", "上游重定向次数过多", 403)

        next_url = urllib.parse.urljoin(current["url"], location)
        try:
            # Validate the next hop before any client can connect to it. Closing the
            # redirect response also releases pooled sockets before the next request.
            next_target = _validate_url_for_purpose(next_url, purpose)
        finally:
            _close_outbound_response(response)
        if next_target["origin"] != current["origin"]:
            suppress_credentials = True
        current = next_target
    raise URLPolicyError("too_many_redirects", "上游重定向次数过多", 403)



# 前端 selection_data widget 有时不会及时进入 ComfyUI 执行参数。
# 用后端缓存兜底；不影响搜索/预览链路。
_SELECTION_STATE_CACHE = {}
_SELECTION_STATE_REV = {}
_SELECTION_STATE_LOCK = threading.Lock()


def _normalize_selection_payload(payload):
    """统一 selection_data 为 {selections:[...]}；兼容旧版 {prompt,image_url}。"""
    if payload is None:
        return {"selections": []}
    if isinstance(payload, str):
        if not payload or payload.strip() == "{}":
            return {"selections": []}
        try:
            payload = json.loads(payload)
        except Exception:
            return {"selections": []}
    if isinstance(payload, list):
        return {"selections": [x for x in payload if isinstance(x, dict)]}
    if isinstance(payload, dict):
        selections = payload.get("selections")
        if isinstance(selections, list):
            return {"selections": [x for x in selections if isinstance(x, dict)]}
        if payload.get("prompt") is not None or payload.get("image_url") or payload.get("file_url"):
            return {"selections": [payload]}
    return {"selections": []}


def _selection_rev(unique_id=None):
    key = str(unique_id or "__latest__")
    with _SELECTION_STATE_LOCK:
        return _SELECTION_STATE_REV.get(key, _SELECTION_STATE_REV.get("__latest__", 0))


def _get_cached_selection_payload(unique_id=None):
    key = str(unique_id or "__latest__")
    with _SELECTION_STATE_LOCK:
        payload = _SELECTION_STATE_CACHE.get(key) or _SELECTION_STATE_CACHE.get("__latest__") or {"selections": []}
        try:
            return json.loads(json.dumps(payload, ensure_ascii=False))
        except Exception:
            return {"selections": []}

def _request_with_headers(method, url, headers, throttle=None, **kwargs):
    merged_headers = dict(kwargs.pop("headers", None) or {})
    force_direct = bool(kwargs.pop("_force_direct", False))
    suppress_credentials = bool(kwargs.pop("_suppress_credentials", False))
    for k, v in headers.items():
        merged_headers.setdefault(k, v)
    if suppress_credentials:
        merged_headers = _strip_credential_headers(merged_headers)
        # requests.Session may retain Set-Cookie values from prior calls. A fresh
        # trust_env-disabled session prevents its cookie jar from silently restoring
        # credentials after explicit Cookie headers were removed.
        kwargs.pop("auth", None)
    else:
        merged_headers = _apply_danbooru_cookie_headers(merged_headers, url)

    if force_direct:
        # 确保真正直连：不用插件代理，也不吃 requests 的环境变量代理。
        kwargs.pop("proxies", None)
        session = _DIRECT_REQUESTS_SESSION
    else:
        kwargs = _requests_kwargs_with_proxy(kwargs)
        session = _PROXY_REQUESTS_SESSION

    ephemeral_session = None
    if suppress_credentials:
        ephemeral_session = requests.Session()
        ephemeral_session.trust_env = False
        session = ephemeral_session

    if throttle:
        throttle.wait()
    try:
        response = session.request(method, url, headers=merged_headers, **kwargs)
    except Exception:
        if ephemeral_session is not None:
            ephemeral_session.close()
        raise
    if ephemeral_session is not None:
        try:
            response._outbound_ephemeral_session = ephemeral_session
        except Exception:
            pass
    return response


def _danbooru_request(method, url, **kwargs):
    """Fail fast while the external site is unreachable, then pass through."""
    with _DANBOORU_BREAKER_LOCK:
        if time.time() < _DANBOORU_BREAKER["until"]:
            raise LegacyGalleryError(
                "network_unavailable", 502,
                "外部站点暂时不可用，已跳过请求，稍后自动重试。",
            )
    try:
        response = _danbooru_request_inner(method, url, **kwargs)
    except Exception:
        _danbooru_breaker_record(False)
        raise
    _danbooru_breaker_record(True)
    return response


_DANBOORU_BREAKER = {"failures": 0, "until": 0.0}
_DANBOORU_BREAKER_LOCK = threading.Lock()
_DANBOORU_BREAKER_FAILURES = 2
_DANBOORU_BREAKER_COOLDOWN_SEC = 60.0
_DANBOORU_TIMEOUT = 8


def _danbooru_breaker_record(ok):
    """Two consecutive failures open a short cooldown so the UI stays responsive."""
    with _DANBOORU_BREAKER_LOCK:
        if ok:
            _DANBOORU_BREAKER["failures"] = 0
            _DANBOORU_BREAKER["until"] = 0.0
            return
        _DANBOORU_BREAKER["failures"] += 1
        if _DANBOORU_BREAKER["failures"] >= _DANBOORU_BREAKER_FAILURES:
            _DANBOORU_BREAKER["until"] = time.time() + _DANBOORU_BREAKER_COOLDOWN_SEC


def _danbooru_request_inner(method, url, **kwargs):
    """统一的 donmai.us 请求入口。

    修复点：
    - 显式代理失败或被 Cloudflare challenge 时，GET 请求自动直连重试一次。
    - 所有请求都关闭 requests 环境变量代理自动读取，避免“直连”被环境代理污染。
    - 429/503 仍按 Retry-After 退避。
    """
    allow_direct_fallback = bool(kwargs.pop("_allow_direct_fallback", True))
    force_direct = bool(kwargs.get("_force_direct", False))
    method_upper = str(method or "GET").upper()
    proxy_available = (not force_direct) and (bool(kwargs.get("proxies")) or bool(_get_proxy_url()))

    def _do_request(call_kwargs):
        resp = None
        for attempt in range(2):
            resp = _request_with_headers(method, url, DANBOORU_HEADERS, throttle=_donmai_throttle, **dict(call_kwargs))
            if resp.status_code not in (429, 503) or attempt == 1:
                if resp.status_code == 403 and _is_cloudflare_challenge(resp):
                    logger.warning(f"[Danbooru] Cloudflare challenge 拦截: {url}")
                return resp
            retry_after = resp.headers.get("Retry-After")
            delay = 2.0
            try:
                if retry_after is not None:
                    delay = min(max(float(retry_after), 0.5), 10.0)
            except ValueError:
                pass
            logger.warning(f"[Danbooru] {resp.status_code} 限流，{delay:.1f}s 后重试: {url}")
            time.sleep(delay)
        return resp

    def _try_curl_cffi(call_kwargs, direct=False):
        if method_upper != "GET" or not _CURL_CFFI_AVAILABLE:
            return None
        try:
            cffi_kwargs = dict(call_kwargs)
            if direct:
                cffi_kwargs["_force_direct"] = True
            mode_label = "直连" if direct else "代理"
            logger.warning(f"[Danbooru] 尝试 curl_cffi Chrome 指纹 {mode_label} 请求: {url}")
            cffi_resp = _curl_cffi_request_with_headers(method, url, DANBOORU_HEADERS, throttle=_donmai_throttle, **cffi_kwargs)
            if cffi_resp is not None and not (cffi_resp.status_code == 403 and _is_cloudflare_challenge(cffi_resp)):
                return cffi_resp
            if cffi_resp is not None:
                logger.warning(f"[Danbooru] curl_cffi {mode_label} 仍被 Cloudflare challenge: {url}")
        except Exception as ce:
            logger.warning(f"[Danbooru] curl_cffi 请求失败: {type(ce).__name__}: {ce}")
        return None

    try:
        resp = _do_request(kwargs)
    except (requests.exceptions.ProxyError, requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError, requests.exceptions.SSLError) as e:
        if allow_direct_fallback and proxy_available and method_upper == "GET":
            cffi_resp = _try_curl_cffi(kwargs, direct=False)
            if cffi_resp is not None:
                return cffi_resp
            logger.warning(f"[Danbooru] 代理请求失败，改用直连重试一次: {type(e).__name__}: {e}")
            direct_kwargs = dict(kwargs)
            direct_kwargs["_force_direct"] = True
            direct_cffi_resp = _try_curl_cffi(direct_kwargs, direct=True)
            if direct_cffi_resp is not None:
                return direct_cffi_resp
            return _danbooru_request(method, url, _allow_direct_fallback=False, **direct_kwargs)
        raise

    if (
        allow_direct_fallback
        and proxy_available
        and method_upper == "GET"
        and resp is not None
        and resp.status_code == 403
        and _is_cloudflare_challenge(resp)
    ):
        cffi_resp = _try_curl_cffi(kwargs, direct=False)
        if cffi_resp is not None:
            return cffi_resp
        logger.warning("[Danbooru] 代理 IP 被 Cloudflare challenge，改用直连重试一次")
        direct_kwargs = dict(kwargs)
        direct_kwargs["_force_direct"] = True
        direct_cffi_resp = _try_curl_cffi(direct_kwargs, direct=True)
        if direct_cffi_resp is not None:
            return direct_cffi_resp
        return _danbooru_request(method, url, _allow_direct_fallback=False, **direct_kwargs)

    return resp


def _gelbooru_request(method, url, **kwargs):
    """Gelbooru 请求入口：默认 UA + 代理 + 简单限流。"""
    # HTML fallback supplies a different Accept header. Pop and merge it here instead
    # of forwarding two values for _request_with_headers(..., headers=...), which used
    # to raise "multiple values for argument 'headers'" before any request was made.
    headers = dict(GELBOORU_HEADERS)
    headers.update(dict(kwargs.pop("headers", None) or {}))
    resp = _request_with_headers(method, url, headers, throttle=_gelbooru_throttle, **kwargs)
    if resp.status_code == 403 and _is_cloudflare_challenge(resp):
        logger.warning(f"[Gelbooru] Cloudflare challenge 拦截: {_redact_url(url)}")
    return resp


def _yandere_request(method, url, **kwargs):
    """Yande.re 请求入口：Moebooru/Danbooru 1.x compatible JSON API。"""
    resp = _request_with_headers(method, url, YANDERE_HEADERS, throttle=_yandere_throttle, **kwargs)
    if resp.status_code == 403 and _is_cloudflare_challenge(resp):
        logger.warning(f"[Yande.re] Cloudflare/challenge 拦截: {url}")
    return resp

def _is_civitai_host(host: str) -> bool:
    host = (host or "").lower()
    return (
        host == "civitai.com" or host.endswith(".civitai.com")
        or host == "civitai.red" or host.endswith(".civitai.red")
        or host == "civitai.green" or host.endswith(".civitai.green")
        or host == "civitai.delivery" or host.endswith(".civitai.delivery")
    )


def _civitai_request(method, url, **kwargs):
    """Civitai 请求入口：默认走 civitai.red，必要时允许上层回退 civitai.com。"""
    headers = dict(CIVITAI_HEADERS)
    is_civitai_origin = False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if _is_civitai_host(parsed.hostname):
                is_civitai_origin = True
                headers["Referer"] = origin + "/"
                headers["Origin"] = origin
    except Exception:
        pass
    try:
        civitai_key = load_civitai_auth()
        if civitai_key and is_civitai_origin and not kwargs.get("_suppress_credentials", False):
            headers.setdefault("Authorization", f"Bearer {civitai_key}")
    except Exception:
        pass
    resp = _request_with_headers(method, url, headers, throttle=_civitai_throttle, **kwargs)
    if resp.status_code == 403 and _is_cloudflare_challenge(resp):
        logger.warning(f"[Civitai] Cloudflare challenge 拦截: {url}")
    return resp


def _civitai_api_url(path: str, base: str = None) -> str:
    base = (base or CIVITAI_BASE_URL).rstrip('/')
    path = '/' + str(path or '').lstrip('/')
    return base + path


def _civitai_api_get(path: str, params=None, timeout=25, allow_fallback=True):
    """Civitai API GET：优先 civitai.red，HTTP/JSON异常时回退 civitai.com。"""
    params = dict(params or {})
    last_exc = None
    bases = [CIVITAI_BASE_URL]
    if allow_fallback and CIVITAI_FALLBACK_BASE_URL not in bases:
        bases.append(CIVITAI_FALLBACK_BASE_URL)
    for base in bases:
        url = _civitai_api_url(path, base=base)
        try:
            resp = _civitai_request('GET', url, params=params, timeout=timeout)
            resp._civitai_base_used = base
            if resp.status_code == 200:
                return resp
            logger.warning(f"[Civitai] API {_redact_url(base)} HTTP {resp.status_code}: {_sanitize_log_text(resp.text[:160])}")
        except Exception as e:
            last_exc = e
            logger.warning(f"[Civitai] API {_redact_url(base)} 请求异常: {_safe_exception_text(e)}")
    if last_exc:
        raise last_exc
    return resp

# 获取插件目录路径
# 获取当前文件所在目录
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LEGACY_SETTINGS_FILE = os.path.join(PLUGIN_DIR, "settings.json")

def _resolve_persistent_settings_file():
    """
    Store credentials/settings outside the plugin folder so custom-node updates do not
    overwrite Danbooru/Gelbooru API keys or Danbooru Cookie fallback.
    """
    candidates = []
    try:
        getter = getattr(folder_paths, "get_user_directory", None)
        user_dir = getter() if callable(getter) else getattr(folder_paths, "user_directory", None)
        if user_dir:
            candidates.append(Path(user_dir) / "ComfyUI-Danbooru-Gallery" / "settings.json")
    except Exception:
        pass
    try:
        base_path = getattr(folder_paths, "base_path", None)
        if base_path:
            candidates.append(Path(base_path) / "user" / "ComfyUI-Danbooru-Gallery" / "settings.json")
    except Exception:
        pass

    # Fallback keeps old behavior if ComfyUI's user directory is unavailable.
    candidates.append(Path(LEGACY_SETTINGS_FILE))

    seen = set()
    for candidate in candidates:
        try:
            candidate = Path(candidate).resolve()
            if candidate in seen:
                continue
            seen.add(candidate)
            candidate.parent.mkdir(parents=True, exist_ok=True)
            return str(candidate)
        except Exception:
            continue
    return LEGACY_SETTINGS_FILE

SETTINGS_FILE = _resolve_persistent_settings_file()

def load_settings():
    """从本地文件加载所有设置；优先使用 ComfyUI/user 下的持久配置，并从旧插件目录自动迁移一次。"""
    default_settings = {
        "language": "zh",
        "blacklist": [],
        "filter_tags": [
            "watermark", "sample_watermark", "weibo_username", "weibo", "weibo_logo",
            "weibo_watermark", "censored", "mosaic_censoring", "artist_name", "twitter_username"
        ],
        "filter_enabled": True,
        "danbooru_username": "",
        "danbooru_api_key": "",
        "danbooru_cookie_enabled": False,
        "danbooru_cookie": "",
        "danbooru_browser_headers_enabled": False,
        "danbooru_browser_headers": "",
        "danbooru_browser_bridge_enabled": False,
        "danbooru_browser_bridge_cdp_url": "http://127.0.0.1:9222",
        "danbooru_browser_bridge_timeout_ms": 60000,
        "danbooru_browser_bridge_prefer": False,
        "gelbooru_user_id": "",
        "gelbooru_api_key": "",
        "civitai_api_key": "",
        "civitai_remote_favorites_enabled": False,
        "civitai_browser_headers": "",  # legacy merged backup
        "civitai_collection_headers": "",
        "civitai_search_headers": "",
        "civitai_default_collection_id": "",
        "civitai_browser_bridge_enabled": None,
        "civitai_browser_bridge_cdp_url": "http://127.0.0.1:9222",
        "civitai_browser_bridge_timeout_ms": 60000,
        "civitai_browser_bridge_prefer": True,
        "civitai_browser_bridge_auto_renew": False,
        "civitai_browser_bridge_renew_url": "https://civitai.red/",
        "proxy_enabled": True,
        "proxy_url": "",
        "default_source": "danbooru",
        "favorites": [],
        "civitai_favorites": [],
        "debug_mode": False,
        "cache_enabled": True,
        "max_cache_age": 3600,
        "default_page_size": 20,
        "autocomplete_enabled": True,
        "tooltip_enabled": True,
        "autocomplete_max_results": 20,
        "selected_categories": ["copyright", "character", "general"],
        "formatting": {
            "escapeBrackets": True,
            "replaceUnderscores": True
        }
    }

    try:
        # First run after v9: migrate existing plugin-local settings to the persistent location.
        if SETTINGS_FILE != LEGACY_SETTINGS_FILE and (not os.path.exists(SETTINGS_FILE)) and os.path.exists(LEGACY_SETTINGS_FILE):
            try:
                with open(LEGACY_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    legacy_data = json.load(f)
                if isinstance(legacy_data, dict):
                    SETTINGS_PARENT = os.path.dirname(SETTINGS_FILE)
                    if SETTINGS_PARENT:
                        os.makedirs(SETTINGS_PARENT, exist_ok=True)
                    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                        json.dump(legacy_data, f, ensure_ascii=False, indent=2)
                    logger.info(f"[DanbooruGallery] 已迁移设置到持久目录: {SETTINGS_FILE}")
            except Exception as migrate_error:
                logger.warning(f"[DanbooruGallery] 迁移旧设置失败，将继续尝试读取持久设置: {migrate_error}")

        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
                for key, value in default_settings.items():
                    if key not in data:
                        data[key] = value
                return data
    except Exception as e:
        logger.error(f"加载设置失败: {e}")

    return default_settings

def load_autocomplete_config():
    """加载自动补全配置（用于数据库优先+API fallback机制）"""
    # 默认配置
    default_config = {
        "offline_mode": {
            "enabled": True,
            "fallback_to_remote": True,
            "remote_timeout_ms": 2000  # 2秒超时
        },
        "cache": {
            "use_database_query": True
        }
    }

    # 尝试从多个位置加载配置
    config_paths = [
        Path(PLUGIN_DIR) / "config.json",
        Path(PLUGIN_DIR).parent / "config.json",
    ]

    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # 深度合并配置
                    if "offline_mode" in loaded:
                        default_config["offline_mode"].update(loaded["offline_mode"])
                    if "cache" in loaded:
                        default_config["cache"].update(loaded["cache"])
                    logger.info(f"[Autocomplete] 加载配置: {config_path}")
                    return default_config
            except Exception as e:
                logger.warning(f"[Autocomplete] 配置文件加载失败 {config_path}: {e}")

    logger.info("[Autocomplete] 使用默认配置")
    return default_config

def save_settings(settings):
    """保存所有设置到本地文件。使用原子替换，避免写入中断导致认证信息丢失。"""
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        tmp_file = SETTINGS_FILE + ".tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, SETTINGS_FILE)
        return True
    except Exception as e:
        logger.error(f"保存设置失败: {e}")
        try:
            tmp_file = SETTINGS_FILE + ".tmp"
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except Exception:
            pass
        return False

def load_user_auth():
    """从统一设置文件加载用户认证信息"""
    settings = load_settings()
    return settings.get("danbooru_username", ""), settings.get("danbooru_api_key", "")


def _with_danbooru_auth_params(params=None):
    """Danbooru API 推荐 login/api_key URL 参数认证；同时便于诊断和实际搜索路径一致。"""
    merged = dict(params or {})
    username, api_key = load_user_auth()
    username = str(username or "").strip()
    api_key = str(api_key or "").strip()
    if username and api_key:
        merged.setdefault("login", username)
        merged.setdefault("api_key", api_key)
    return merged

def save_user_auth(username, api_key):
    """保存 Danbooru 用户认证信息到统一设置文件"""
    settings = load_settings()
    settings["danbooru_username"] = username
    settings["danbooru_api_key"] = api_key
    return save_settings(settings)


def load_gelbooru_auth():
    """从统一设置文件加载 Gelbooru API 认证信息。Gelbooru 使用 user_id + api_key。"""
    settings = load_settings()
    return settings.get("gelbooru_user_id", ""), settings.get("gelbooru_api_key", "")


def save_gelbooru_auth(user_id, api_key):
    """保存 Gelbooru API 认证信息到统一设置文件"""
    settings = load_settings()
    settings["gelbooru_user_id"] = str(user_id or "").strip()
    settings["gelbooru_api_key"] = str(api_key or "").strip()
    return save_settings(settings)


def load_civitai_auth():
    """从统一设置文件加载 Civitai API Key。Civitai 可匿名访问，API Key 仅用于更高限制/账号内容。"""
    settings = load_settings()
    return str(settings.get("civitai_api_key", "") or "").strip()


def save_civitai_auth(api_key):
    """保存 Civitai API Key 到统一设置文件。"""
    settings = load_settings()
    settings["civitai_api_key"] = str(api_key or "").strip()
    return save_settings(settings)


def load_browser_bridge_settings():
    """加载 Danbooru 浏览器桥接设置。桥接默认关闭，只在用户显式启用后使用。"""
    settings = load_settings()
    return {
        "enabled": bool(settings.get("danbooru_browser_bridge_enabled", False)),
        "cdp_url": str(settings.get("danbooru_browser_bridge_cdp_url", "http://127.0.0.1:9222") or "http://127.0.0.1:9222").strip(),
        "timeout_ms": int(settings.get("danbooru_browser_bridge_timeout_ms", 60000) or 60000),
        "prefer": bool(settings.get("danbooru_browser_bridge_prefer", False)),
    }


def save_browser_bridge_settings(enabled=False, cdp_url="http://127.0.0.1:9222", timeout_ms=60000, prefer=False):
    """保存 Danbooru 浏览器桥接设置。"""
    settings = load_settings()
    settings["danbooru_browser_bridge_enabled"] = bool(enabled)
    settings["danbooru_browser_bridge_cdp_url"] = str(cdp_url or "http://127.0.0.1:9222").strip()
    try:
        timeout_ms = int(timeout_ms)
    except Exception:
        timeout_ms = 60000
    settings["danbooru_browser_bridge_timeout_ms"] = max(10000, min(timeout_ms, 180000))
    settings["danbooru_browser_bridge_prefer"] = bool(prefer)
    return save_settings(settings)


def _browser_bridge_import_status():
    try:
        import playwright  # noqa: F401
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True, ""
    except Exception as e:
        playwright_error = str(e)
    try:
        import websocket  # noqa: F401
        return True, f"Playwright unavailable; using websocket CDP fallback: {playwright_error}"
    except Exception as websocket_error:
        return False, f"Playwright unavailable: {playwright_error}; websocket fallback unavailable: {websocket_error}"


class _BrowserBridgeResponse:
    """Small response-like object used by diagnostics for browser bridge results."""
    def __init__(self, status_code=0, headers=None, text=""):
        self.status_code = status_code or 0
        self.headers = headers or {}
        self.text = text or ""
        self.content = self.text.encode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


def _browser_bridge_build_url(path_or_url, params=None):
    if str(path_or_url).startswith("http://") or str(path_or_url).startswith("https://"):
        base = str(path_or_url)
    else:
        base = DANBOORU_BASE_URL + str(path_or_url)
    params = params or {}
    if params:
        sep = "&" if "?" in base else "?"
        base += sep + urllib.parse.urlencode(params)
    return base


def _browser_bridge_http_json(cdp_url, path, method="GET", timeout=10):
    base = (cdp_url or "http://127.0.0.1:9222").rstrip("/")
    request = urllib.request.Request(base + path, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _browser_bridge_list_targets(cdp_url, timeout=10):
    targets = _browser_bridge_http_json(cdp_url, "/json/list", method="GET", timeout=timeout)
    return targets if isinstance(targets, list) else []


def _browser_bridge_create_target(cdp_url, url, timeout=10):
    escaped_url = urllib.parse.quote(str(url or "about:blank"), safe="")
    try:
        return _browser_bridge_http_json(cdp_url, f"/json/new?{escaped_url}", method="PUT", timeout=timeout)
    except Exception:
        return _browser_bridge_http_json(cdp_url, f"/json/new?{escaped_url}", method="GET", timeout=timeout)


def _browser_bridge_is_ready(cdp_url, timeout=3):
    try:
        _browser_bridge_http_json(cdp_url, "/json/version", method="GET", timeout=timeout)
        return True
    except Exception:
        return False


def _browser_bridge_listener_pid(cdp_url):
    if os.name != "nt":
        return 0
    parsed = urllib.parse.urlparse((cdp_url or "http://127.0.0.1:9222").rstrip("/"))
    try:
        port = int(parsed.port or 9222)
    except Exception:
        port = 9222
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        output = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=creationflags,
            timeout=5,
        )
    except Exception:
        return 0
    needle = f":{port}"
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[1].endswith(needle):
                try:
                    return int(parts[-1])
                except Exception:
                    return 0
    return 0


def _browser_bridge_focus_window(cdp_url=None):
    """Bring the bridge Chrome top-level window to the foreground on Windows."""
    if os.name != "nt":
        return False
    pid = _browser_bridge_listener_pid(cdp_url)
    if not pid:
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return False

    user32 = ctypes.windll.user32
    matching_hwnds = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        proc_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value == pid and user32.IsWindowVisible(hwnd):
            matching_hwnds.append(hwnd)
        return True

    try:
        user32.EnumWindows(EnumWindowsProc(callback), 0)
    except Exception:
        return False
    if not matching_hwnds:
        return False
    hwnd = matching_hwnds[0]
    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _browser_bridge_find_chrome_exe():
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return ""


def _browser_bridge_start_chrome(cdp_url=None, start_url=None):
    cdp_url = (cdp_url or "http://127.0.0.1:9222").rstrip("/")
    if _browser_bridge_is_ready(cdp_url, timeout=2):
        return True
    parsed = urllib.parse.urlparse(cdp_url)
    host = parsed.hostname or "127.0.0.1"
    try:
        port = int(parsed.port or 9222)
    except Exception:
        port = 9222
    if host not in ("127.0.0.1", "localhost"):
        raise RuntimeError(f"只支持自动启动本机桥接 Chrome，当前 CDP={cdp_url}")
    chrome_exe = _browser_bridge_find_chrome_exe()
    if not chrome_exe:
        raise RuntimeError("未找到 Chrome/Edge 可执行文件")
    profile_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "DanbooruBridgeChrome")
    os.makedirs(profile_dir, exist_ok=True)
    args = [
        chrome_exe,
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
    ]
    proxy_url = _get_proxy_url()
    if proxy_url:
        args.append(f"--proxy-server={proxy_url}")
    args.append(start_url or "https://danbooru.donmai.us/posts.json?limit=1")
    subprocess.Popen(args, close_fds=True)
    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        if _browser_bridge_is_ready(cdp_url, timeout=2):
            return True
        time.sleep(0.5)
    return _browser_bridge_is_ready(cdp_url, timeout=2)


def _browser_bridge_activate_target(cdp_url, target_id, timeout=5):
    if not target_id:
        return False
    try:
        _browser_bridge_http_json(cdp_url, f"/json/activate/{urllib.parse.quote(str(target_id), safe='')}", method="GET", timeout=timeout)
        _browser_bridge_focus_window(cdp_url)
        return True
    except Exception:
        return False


def _browser_bridge_navigate_target(target, url, timeout_seconds=20.0):
    ws = None
    msg_id = 0

    def next_id():
        nonlocal msg_id
        msg_id += 1
        return msg_id

    def send(cdp_method, params=None, wait=True):
        command_id = next_id()
        ws.send(json.dumps({"id": command_id, "method": cdp_method, "params": params or {}}))
        if not wait:
            return None
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            raw = ws.recv()
            message = json.loads(raw)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {cdp_method} failed: {message.get('error')}")
                return message.get("result") or {}
        raise TimeoutError(f"CDP {cdp_method} timed out")

    try:
        import websocket
    except Exception as e:
        raise RuntimeError(f"websocket-client 未安装或不可用: {e}") from e
    ws_url = (target or {}).get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError(f"CDP target has no webSocketDebuggerUrl: {target}")
    try:
        ws = websocket.create_connection(ws_url, timeout=timeout_seconds, suppress_origin=True)
        send("Page.enable")
        send("Page.navigate", {"url": url}, wait=False)
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass


def _danbooru_bridge_target_matches(target):
    if not isinstance(target, dict) or target.get("type") not in (None, "page"):
        return False
    url = str(target.get("url") or "")
    return url.startswith(DANBOORU_BASE_URL.rstrip("/") + "/") or url == DANBOORU_BASE_URL.rstrip("/")


def _danbooru_bridge_get_or_create_target(cdp_url, url=None, timeout=10):
    for target in _browser_bridge_list_targets(cdp_url, timeout=timeout):
        if _danbooru_bridge_target_matches(target) and target.get("webSocketDebuggerUrl"):
            return target, False
    return _browser_bridge_create_target(cdp_url, url or f"{DANBOORU_BASE_URL}/posts.json?limit=1", timeout=timeout), True


def _danbooru_bridge_open_login():
    bridge = load_browser_bridge_settings()
    cdp_url = bridge.get("cdp_url") or "http://127.0.0.1:9222"
    login_url = f"{DANBOORU_BASE_URL}/profile"
    _browser_bridge_start_chrome(cdp_url, start_url=login_url)
    target, _created = _danbooru_bridge_get_or_create_target(cdp_url, login_url, timeout=10)
    _browser_bridge_navigate_target(target, login_url, timeout_seconds=20.0)
    _browser_bridge_activate_target(cdp_url, target.get("id"), timeout=5)
    return True


def _danbooru_bridge_capture_login_state():
    bridge = load_browser_bridge_settings()
    cdp_url = bridge.get("cdp_url") or "http://127.0.0.1:9222"
    if not _browser_bridge_is_ready(cdp_url, timeout=3):
        raise RuntimeError("桥接 Chrome 端口 9222 未启动；请先点打开/切到 D 登录")
    try:
        import websocket
    except Exception as e:
        raise RuntimeError(f"websocket-client 未安装或不可用: {e}") from e

    target = None
    ws = None
    msg_id = 0
    timeout_seconds = max(10.0, min(float(bridge.get("timeout_ms") or 60000) / 1000.0, 60.0))

    def next_id():
        nonlocal msg_id
        msg_id += 1
        return msg_id

    def send(cdp_method, params=None):
        command_id = next_id()
        ws.send(json.dumps({"id": command_id, "method": cdp_method, "params": params or {}}))
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            raw = ws.recv()
            message = json.loads(raw)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {cdp_method} failed: {message.get('error')}")
                return message.get("result") or {}
        raise TimeoutError(f"CDP {cdp_method} timed out")

    try:
        target, _created = _danbooru_bridge_get_or_create_target(cdp_url, f"{DANBOORU_BASE_URL}/profile", timeout=10)
        ws_url = target.get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError(f"CDP target has no webSocketDebuggerUrl: {target}")
        ws = websocket.create_connection(ws_url, timeout=timeout_seconds, suppress_origin=True)
        send("Runtime.enable")
        send("Network.enable")
        cookies_result = send("Network.getAllCookies")
        cookies = cookies_result.get("cookies") if isinstance(cookies_result, dict) else []
        danbooru_cookies = {}
        for cookie in cookies or []:
            if not isinstance(cookie, dict):
                continue
            name = str(cookie.get("name") or "").strip()
            value = str(cookie.get("value") or "")
            domain = str(cookie.get("domain") or "").lstrip(".").lower()
            if name and value and (domain == "danbooru.donmai.us" or domain == "donmai.us" or domain.endswith(".donmai.us")):
                danbooru_cookies[name] = value
        cookie_header = _cookie_dict_to_header(danbooru_cookies)
        if not cookie_header:
            raise RuntimeError("桥接 Chrome 当前没有 Danbooru Cookie；请先打开验证页并通过 Cloudflare 验证")
        has_login_session = any(
            name.lower() in ("danbooru2_session", "_danbooru2_session") or ("danbooru" in name.lower() and "session" in name.lower())
            for name in danbooru_cookies.keys()
        )
        if not has_login_session:
            raise RuntimeError("桥接 Chrome 只有 Cloudflare Cookie，没有 Danbooru 登录 session；请在打开的 D 页面登录账号后再保存")
        ua_result = send("Runtime.evaluate", {
            "expression": "navigator.userAgent",
            "returnByValue": True,
            "awaitPromise": True,
        })
        user_agent = str(((ua_result.get("result") or {}).get("value") or DANBOORU_HEADERS.get("User-Agent") or "")).strip()
        raw_headers = _normalize_raw_browser_headers("\n".join([
            f"User-Agent: {user_agent}",
            "Accept: application/json,text/plain,*/*",
            "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
            f"Referer: {DANBOORU_BASE_URL}/posts",
            f"Cookie: {cookie_header}",
        ]))
        return cookie_header, raw_headers, has_login_session
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass


def _danbooru_bridge_favorite_request(post_id, remove=False):
    bridge = load_browser_bridge_settings()
    cdp_url = bridge.get("cdp_url") or "http://127.0.0.1:9222"
    if not _browser_bridge_is_ready(cdp_url, timeout=3):
        raise RuntimeError("桥接 Chrome 端口 9222 未启动；请先点打开/切到 D 登录")
    try:
        import websocket
    except Exception as e:
        raise RuntimeError(f"websocket-client 未安装或不可用: {e}") from e

    target = None
    ws = None
    msg_id = 0
    timeout_seconds = max(10.0, min(float(bridge.get("timeout_ms") or 60000) / 1000.0, 60.0))

    def next_id():
        nonlocal msg_id
        msg_id += 1
        return msg_id

    def send(cdp_method, params=None):
        command_id = next_id()
        ws.send(json.dumps({"id": command_id, "method": cdp_method, "params": params or {}}))
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            raw = ws.recv()
            message = json.loads(raw)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {cdp_method} failed: {message.get('error')}")
                return message.get("result") or {}
        raise TimeoutError(f"CDP {cdp_method} timed out")

    try:
        with _DANBOORU_BRIDGE_FETCH_LOCK:
            target, _created = _danbooru_bridge_get_or_create_target(cdp_url, f"{DANBOORU_BASE_URL}/profile", timeout=10)
            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                raise RuntimeError(f"CDP target has no webSocketDebuggerUrl: {target}")
            ws = websocket.create_connection(ws_url, timeout=timeout_seconds, suppress_origin=True)
            send("Runtime.enable")
            send("Page.enable")
            current_url = str(target.get("url") or "")
            if not current_url.startswith(DANBOORU_BASE_URL):
                send("Page.navigate", {"url": f"{DANBOORU_BASE_URL}/profile"})
                time.sleep(0.6)
            endpoint = f"/favorites/{urllib.parse.quote(str(post_id), safe='')}.json" if remove else "/favorites.json"
            method = "DELETE" if remove else "POST"
            body = "" if remove else f"post_id={urllib.parse.quote(str(post_id), safe='')}"
            expression = """
(async () => {
  const token = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const resp = await fetch(%s, {
    method: %s,
    credentials: 'include',
    headers: {
      'Accept': 'application/json',
      'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
      'X-CSRF-Token': token,
      'X-Requested-With': 'XMLHttpRequest'
    },
    body: %s || undefined
  });
  const text = await resp.text();
  return JSON.stringify({ status: resp.status, ok: resp.ok, text });
})()
""" % (json.dumps(endpoint), json.dumps(method), json.dumps(body))
            result = send("Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "timeout": int(timeout_seconds * 1000),
            })
            value = ((result.get("result") or {}).get("value") or "").strip()
            if not value:
                raise RuntimeError("Danbooru browser bridge returned an empty favorite result")
            payload = json.loads(value)
            return _BrowserBridgeResponse(status_code=int(payload.get("status") or 0), headers={}, text=str(payload.get("text") or ""))
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass


def _danbooru_bridge_fetch(path_or_url, method="GET", params=None, headers=None, body=None, timeout_ms=None, cdp_url=None, label="danbooru_bridge"):
    """Fetch Danbooru through the existing bridge Chrome page without opening throwaway tabs."""
    bridge = load_browser_bridge_settings()
    cdp_url = (cdp_url or bridge.get("cdp_url") or "http://127.0.0.1:9222").strip()
    if not _browser_bridge_is_ready(cdp_url, timeout=3):
        raise RuntimeError("桥接 Chrome 端口 9222 未启动；请先点“打开/切到 D 登录”，登录后保存当前登录态")
    try:
        import websocket
    except Exception as e:
        raise RuntimeError(f"websocket-client 未安装或不可用: {e}") from e

    timeout_ms = int(timeout_ms or bridge.get("timeout_ms") or 60000)
    timeout_seconds = max(10.0, min(float(timeout_ms) / 1000.0, 180.0))
    url = _browser_bridge_build_url(path_or_url, params)
    target = None
    ws = None
    msg_id = 0
    start = time.monotonic()

    def next_id():
        nonlocal msg_id
        msg_id += 1
        return msg_id

    def send(cdp_method, cdp_params=None, wait=True):
        command_id = next_id()
        ws.send(json.dumps({"id": command_id, "method": cdp_method, "params": cdp_params or {}}))
        if not wait:
            return None
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            raw = ws.recv()
            message = json.loads(raw)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {cdp_method} failed: {message.get('error')}")
                return message.get("result") or {}
        raise TimeoutError(f"CDP {cdp_method} timed out")

    try:
        with _DANBOORU_BRIDGE_FETCH_LOCK:
            target, created = _danbooru_bridge_get_or_create_target(cdp_url, f"{DANBOORU_BASE_URL}/profile", timeout=10)
            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                raise RuntimeError(f"CDP target has no webSocketDebuggerUrl: {target}")
            logger.info(f"[DanbooruBrowserBridge] {label} connecting to {cdp_url}, reused={not created}, url={_diag_sanitize_text(url)}")
            ws = websocket.create_connection(ws_url, timeout=timeout_seconds, suppress_origin=True)
            send("Page.enable")
            send("Runtime.enable")
            current_url = str(target.get("url") or "")
            if created or not current_url.startswith(DANBOORU_BASE_URL.rstrip("/") + "/"):
                send("Page.navigate", {"url": f"{DANBOORU_BASE_URL}/profile"}, wait=False)
                time.sleep(0.5)
            origin_deadline = time.monotonic() + min(8.0, timeout_seconds)
            while time.monotonic() < origin_deadline:
                try:
                    loc_result = send("Runtime.evaluate", {
                        "expression": "location.href",
                        "returnByValue": True,
                        "awaitPromise": True,
                    })
                    location_href = str(((loc_result.get("result") or {}).get("value") or "")).strip()
                    if location_href.startswith(DANBOORU_BASE_URL.rstrip("/") + "/"):
                        break
                except Exception:
                    pass
                time.sleep(0.25)

            safe_headers = dict(headers or {})
            for blocked in ("Cookie", "Host", "Origin", "Referer", "Content-Length", "Connection", "Proxy-Connection"):
                safe_headers.pop(blocked, None)
            safe_headers.setdefault("Accept", "application/json,text/plain,*/*")

            fetch_options = {
                "method": str(method or "GET").upper(),
                "credentials": "include",
                "headers": safe_headers,
            }
            if body is not None:
                fetch_options["body"] = str(body)
            expression = """
(async () => {
  const resp = await fetch(%s, %s);
  const text = await resp.text();
  return JSON.stringify({
    status: resp.status,
    ok: resp.ok,
    headers: Object.fromEntries(resp.headers.entries()),
    text
  });
})()
""" % (json.dumps(url), json.dumps(fetch_options, ensure_ascii=False))
            result = send("Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "timeout": int(timeout_seconds * 1000),
            })
            value = ((result.get("result") or {}).get("value") or "").strip()
            if not value:
                raise RuntimeError("Danbooru browser bridge returned an empty fetch result")
            payload = json.loads(value)
            status = int(payload.get("status") or 0)
            text = str(payload.get("text") or "")
            response_headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(f"[DanbooruBrowserBridge] {label} status={status} elapsed={elapsed_ms}ms")
            return _BrowserBridgeResponse(status_code=status, headers=response_headers, text=text)
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass


def _browser_bridge_websocket_fetch_json(url, timeout_ms, cdp_url, label):
    """Fetch a JSON URL through Chrome DevTools Protocol without Playwright."""
    try:
        import websocket
    except Exception as e:
        raise RuntimeError(f"websocket-client 未安装或不可用: {e}") from e

    timeout_seconds = max(10.0, min(float(timeout_ms or 60000) / 1000.0, 180.0))
    escaped_url = urllib.parse.quote(url, safe="")
    target = None
    ws = None
    msg_id = 0
    start = time.monotonic()

    def next_id():
        nonlocal msg_id
        msg_id += 1
        return msg_id

    def send(method, params=None, wait=True):
        command_id = next_id()
        ws.send(json.dumps({"id": command_id, "method": method, "params": params or {}}))
        if not wait:
            return None
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            raw = ws.recv()
            message = json.loads(raw)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {method} failed: {message.get('error')}")
                return message.get("result") or {}
        raise TimeoutError(f"CDP {method} timed out")

    try:
        try:
            target = _browser_bridge_http_json(cdp_url, f"/json/new?{escaped_url}", method="PUT", timeout=10)
        except Exception:
            target = _browser_bridge_http_json(cdp_url, f"/json/new?{escaped_url}", method="GET", timeout=10)
        ws_url = target.get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError(f"CDP target has no webSocketDebuggerUrl: {target}")

        logger.info(f"[DanbooruBrowserBridge] {label} websocket fallback connecting to {cdp_url}, url={_diag_sanitize_text(url)}")
        ws = websocket.create_connection(ws_url, timeout=timeout_seconds, suppress_origin=True)
        send("Page.enable")
        send("Runtime.enable")
        send("Page.navigate", {"url": url}, wait=False)

        deadline = time.monotonic() + timeout_seconds
        parsed = None
        last_text = ""
        last_error = None
        status_code = 200
        headers = {}
        while time.monotonic() < deadline:
            try:
                result = send(
                    "Runtime.evaluate",
                    {
                        "expression": "document.body ? document.body.innerText : document.documentElement.innerText",
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                )
                value = ((result.get("result") or {}).get("value") or "").strip()
                last_text = value
                if value:
                    try:
                        parsed = json.loads(value)
                        break
                    except Exception as e:
                        last_error = e
                        low = value[:2000].lower()
                        if "just a moment" in low or "challenges.cloudflare.com" in low or "verify you are human" in low:
                            time.sleep(1.2)
                            continue
            except Exception as e:
                last_error = e
            time.sleep(0.5)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        if parsed is None:
            snippet = _diag_sanitize_text((last_text or "")[:1000])
            if "just a moment" in (last_text or "").lower() or "challenges.cloudflare.com" in (last_text or "").lower():
                raise RuntimeError(f"浏览器桥接仍看到 Cloudflare challenge，可能需要先在该 Chrome 配置里手动通过验证。elapsed={elapsed_ms}ms body={snippet}")
            raise RuntimeError(f"浏览器桥接没有取得 JSON。elapsed={elapsed_ms}ms error={last_error} body={snippet}")

        text = json.dumps(parsed, ensure_ascii=False)
        logger.info(f"[DanbooruBrowserBridge] {label} websocket fallback ok elapsed={elapsed_ms}ms items={len(parsed) if isinstance(parsed, list) else 'dict'}")
        return _BrowserBridgeResponse(status_code=status_code, headers=headers, text=text)
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass
        try:
            target_id = (target or {}).get("id")
            if target_id:
                _browser_bridge_http_json(cdp_url, f"/json/close/{urllib.parse.quote(str(target_id), safe='')}", method="GET", timeout=3)
        except Exception:
            pass


def _civitai_browser_bridge_settings():
    settings = load_settings()
    danbooru_bridge = load_browser_bridge_settings()
    enabled_value = settings.get("civitai_browser_bridge_enabled", None)
    return {
        "enabled": bool(danbooru_bridge.get("enabled", False) if enabled_value is None else enabled_value),
        "cdp_url": str(settings.get("civitai_browser_bridge_cdp_url", danbooru_bridge.get("cdp_url") or "http://127.0.0.1:9222") or "http://127.0.0.1:9222").strip(),
        "timeout_ms": int(settings.get("civitai_browser_bridge_timeout_ms", danbooru_bridge.get("timeout_ms") or 60000) or 60000),
        "prefer": bool(settings.get("civitai_browser_bridge_prefer", True)),
        "auto_renew": bool(settings.get("civitai_browser_bridge_auto_renew", False)),
        "renew_url": str(settings.get("civitai_browser_bridge_renew_url", f"{CIVITAI_BASE_URL}/") or f"{CIVITAI_BASE_URL}/").strip(),
    }


def _civitai_bridge_target_matches(target):
    if not isinstance(target, dict) or target.get("type") not in (None, "page"):
        return False
    url = str(target.get("url") or "")
    return url.startswith(CIVITAI_BASE_URL.rstrip("/") + "/") or url == CIVITAI_BASE_URL.rstrip("/")


def _civitai_bridge_get_or_create_target(cdp_url, url=None, timeout=10):
    for target in _browser_bridge_list_targets(cdp_url, timeout=timeout):
        if _civitai_bridge_target_matches(target) and target.get("webSocketDebuggerUrl"):
            return target, False
    return _browser_bridge_create_target(cdp_url, url or f"{CIVITAI_BASE_URL}/", timeout=timeout), True


def _civitai_bridge_open_renewal(reason="", force=False):
    bridge = _civitai_browser_bridge_settings()
    if not force and (not bridge.get("enabled") or not bridge.get("auto_renew")):
        return False
    global _CIVITAI_BRIDGE_RENEWAL_LAST_OPEN
    now = time.monotonic()
    with _CIVITAI_BRIDGE_RENEWAL_LOCK:
        if not force and now - _CIVITAI_BRIDGE_RENEWAL_LAST_OPEN < 60.0:
            return False
        _CIVITAI_BRIDGE_RENEWAL_LAST_OPEN = now
    renew_url = bridge.get("renew_url") or f"{CIVITAI_BASE_URL}/"
    try:
        if force:
            _browser_bridge_start_chrome(bridge.get("cdp_url"), start_url=renew_url)
        target, created = _civitai_bridge_get_or_create_target(bridge.get("cdp_url"), renew_url, timeout=10)
        if force:
            _browser_bridge_navigate_target(target, renew_url, timeout_seconds=20.0)
        _browser_bridge_activate_target(bridge.get("cdp_url"), target.get("id"), timeout=5)
    except Exception as e:
        logger.warning(f"[CivitaiBrowserBridge] 续期窗口打开失败: {_safe_exception_text(e)}")
        return False
    action = "已打开" if created else "已切到"
    logger.warning(f"[CivitaiBrowserBridge] {action} Civitai 续期窗口: {_diag_sanitize_text(reason)}")
    return True


def _civitai_bridge_capture_collection_headers():
    bridge = _civitai_browser_bridge_settings()
    if not bridge.get("enabled"):
        raise RuntimeError("Civitai 浏览器桥接未启用")
    try:
        import websocket
    except Exception as e:
        raise RuntimeError(f"websocket-client 未安装或不可用: {e}") from e

    cdp_url = bridge.get("cdp_url") or "http://127.0.0.1:9222"
    timeout_seconds = max(10.0, min(float(bridge.get("timeout_ms") or 60000) / 1000.0, 60.0))
    target = None
    ws = None
    msg_id = 0

    def next_id():
        nonlocal msg_id
        msg_id += 1
        return msg_id

    def send(cdp_method, params=None):
        command_id = next_id()
        ws.send(json.dumps({"id": command_id, "method": cdp_method, "params": params or {}}))
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            raw = ws.recv()
            message = json.loads(raw)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {cdp_method} failed: {message.get('error')}")
                return message.get("result") or {}
        raise TimeoutError(f"CDP {cdp_method} timed out")

    try:
        with _CIVITAI_BRIDGE_FETCH_LOCK:
            target, _created = _civitai_bridge_get_or_create_target(cdp_url, f"{CIVITAI_BASE_URL}/", timeout=10)
            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                raise RuntimeError(f"CDP target has no webSocketDebuggerUrl: {target}")
            ws = websocket.create_connection(ws_url, timeout=timeout_seconds, suppress_origin=True)
            send("Runtime.enable")
            send("Network.enable")
            cookies_result = send("Network.getAllCookies")
            cookies = cookies_result.get("cookies") if isinstance(cookies_result, dict) else []
            civitai_cookies = {}
            for cookie in cookies or []:
                if not isinstance(cookie, dict):
                    continue
                name = str(cookie.get("name") or "").strip()
                value = str(cookie.get("value") or "")
                domain = str(cookie.get("domain") or "").lstrip(".").lower()
                if name and value and (domain == "civitai.red" or domain.endswith(".civitai.red")):
                    civitai_cookies[name] = value
            cookie_header = _cookie_dict_to_header(civitai_cookies)
            if not cookie_header:
                raise RuntimeError("桥接 Chrome 当前没有 civitai.red Cookie；请先点登录按钮并在打开的窗口完成登录")
            ua_result = send("Runtime.evaluate", {
                "expression": "navigator.userAgent",
                "returnByValue": True,
                "awaitPromise": True,
            })
            user_agent = str(((ua_result.get("result") or {}).get("value") or CIVITAI_HEADERS.get("User-Agent") or "")).strip()
            header_lines = [
                f"User-Agent: {user_agent}",
                "Accept: */*",
                "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
                "Content-Type: application/json",
                f"Origin: {CIVITAI_BASE_URL}",
                f"Referer: {CIVITAI_BASE_URL}/",
                f"Cookie: {cookie_header}",
            ]
            return _normalize_raw_browser_headers("\n".join(line for line in header_lines if line.strip()))
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass


def _civitai_bridge_fetch(url, method="GET", headers=None, json_payload=None, timeout_ms=None, label="civitai_bridge"):
    bridge = _civitai_browser_bridge_settings()
    if not bridge.get("enabled"):
        raise RuntimeError("Civitai browser bridge is disabled")
    try:
        import websocket
    except Exception as e:
        raise RuntimeError(f"websocket-client 未安装或不可用: {e}") from e

    cdp_url = bridge.get("cdp_url") or "http://127.0.0.1:9222"
    timeout_ms = int(timeout_ms or bridge.get("timeout_ms") or 60000)
    timeout_seconds = max(10.0, min(float(timeout_ms) / 1000.0, 180.0))
    origin_url = f"{CIVITAI_BASE_URL}/"
    target = None
    ws = None
    msg_id = 0
    start = time.monotonic()

    def next_id():
        nonlocal msg_id
        msg_id += 1
        return msg_id

    def send(cdp_method, params=None, wait=True):
        command_id = next_id()
        ws.send(json.dumps({"id": command_id, "method": cdp_method, "params": params or {}}))
        if not wait:
            return None
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            raw = ws.recv()
            message = json.loads(raw)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {cdp_method} failed: {message.get('error')}")
                return message.get("result") or {}
        raise TimeoutError(f"CDP {cdp_method} timed out")

    try:
        with _CIVITAI_BRIDGE_FETCH_LOCK:
            target, created = _civitai_bridge_get_or_create_target(cdp_url, origin_url, timeout=10)
            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                raise RuntimeError(f"CDP target has no webSocketDebuggerUrl: {target}")
            logger.info(f"[CivitaiBrowserBridge] {label} connecting to {cdp_url}, reused={not created}, url={_diag_sanitize_text(url)}")
            ws = websocket.create_connection(ws_url, timeout=timeout_seconds, suppress_origin=True)
            send("Page.enable")
            send("Runtime.enable")
            if created:
                send("Page.navigate", {"url": origin_url}, wait=False)
                time.sleep(0.4)

            safe_headers = dict(headers or {})
            for blocked in ("Cookie", "Host", "Origin", "Referer", "Content-Length", "Connection", "Proxy-Connection"):
                safe_headers.pop(blocked, None)
            body = None
            if json_payload is not None:
                body = json.dumps(json_payload, ensure_ascii=False, separators=(",", ":"))
                safe_headers.setdefault("Content-Type", "application/json")
            safe_headers.setdefault("Accept", "*/*")
            safe_headers.setdefault("x-client", "web")

            fetch_options = {
                "method": str(method or "GET").upper(),
                "credentials": "include",
                "headers": safe_headers,
            }
            if body is not None:
                fetch_options["body"] = body
            expression = """
(async () => {
  const resp = await fetch(%s, %s);
  const text = await resp.text();
  return JSON.stringify({
    status: resp.status,
    ok: resp.ok,
    headers: Object.fromEntries(resp.headers.entries()),
    text
  });
})()
""" % (json.dumps(url), json.dumps(fetch_options, ensure_ascii=False))
            result = send(
                "Runtime.evaluate",
                {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                    "timeout": int(timeout_seconds * 1000),
                },
            )
            value = ((result.get("result") or {}).get("value") or "").strip()
            if not value:
                raise RuntimeError("Civitai browser bridge returned an empty fetch result")
            payload = json.loads(value)
            status = int(payload.get("status") or 0)
            text = str(payload.get("text") or "")
            response_headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(f"[CivitaiBrowserBridge] {label} status={status} elapsed={elapsed_ms}ms")
            if status in (401, 403):
                _civitai_bridge_open_renewal(f"{label} HTTP {status}")
            return _BrowserBridgeResponse(status_code=status, headers=response_headers, text=text)
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass


def _browser_bridge_fetch_json(path_or_url, params=None, timeout_ms=None, cdp_url=None, label="browser_bridge"):
    """
    Fetch Danbooru JSON through a real Chromium/Chrome instance exposed by CDP.

    This is intentionally optional. It does not bypass site access controls: the user must
    launch Chrome/Edge with --remote-debugging-port and complete any Cloudflare challenge
    in that browser/profile first. The advantage is that the HTTP request is made by the
    real browser context instead of Python requests/curl_cffi, so browser cookies, proxy
    settings and Cloudflare clearance can be reused when valid.
    """
    bridge = load_browser_bridge_settings()
    cdp_url = (cdp_url or bridge.get("cdp_url") or "http://127.0.0.1:9222").strip()
    timeout_ms = int(timeout_ms or bridge.get("timeout_ms") or 60000)
    timeout_ms = max(10000, min(timeout_ms, 180000))
    resp = _danbooru_bridge_fetch(path_or_url, params=params, timeout_ms=timeout_ms, cdp_url=cdp_url, label=label)
    try:
        json.loads(resp.text or "")
    except Exception as e:
        snippet = _diag_sanitize_text((resp.text or "")[:1000])
        low = (resp.text or "").lower()
        if "just a moment" in low or "challenges.cloudflare.com" in low or "verify you are human" in low:
            raise RuntimeError(f"浏览器桥接仍看到 Cloudflare challenge，可能需要先在该 Chrome 配置里手动通过验证。status={resp.status_code} body={snippet}") from e
        raise RuntimeError(f"浏览器桥接没有取得 JSON。status={resp.status_code} body={snippet}") from e
    return resp


def _danbooru_browser_bridge_get_posts(tags: str, limit: int = 100, page: int = 1, rating: str = None):
    tags = _normalize_danbooru_query_tags(tags)
    # Keep this logic identical to _get_danbooru_posts so bridge mode returns the same result shape.
    date_tag = ''
    other_tags = []
    for tag in tags.split(' '):
        if tag.strip().startswith('date:'):
            date_tag = tag.strip()
        elif tag.strip():
            other_tags.append(tag.strip())
    if len(other_tags) > 2:
        other_tags = other_tags[:2]
    final_tags = ' '.join(other_tags)
    if date_tag:
        final_tags = f"{final_tags} {date_tag}".strip()
    if rating and rating.lower() != 'all':
        allowed = {'general', 'sensitive', 'questionable', 'explicit', 'g', 's', 'q', 'e'}
        rating_values = [r.strip().lower() for r in rating.split(',') if r.strip()]
        rating_values = [r for r in rating_values if r in allowed]
        if len(rating_values) == 1:
            final_tags = f"{final_tags} rating:{rating_values[0]}".strip()
        elif len(rating_values) > 1:
            or_tags = ' '.join(f"~rating:{r}" for r in rating_values)
            final_tags = f"{final_tags} {or_tags}".strip()
    params = _with_danbooru_auth_params({"tags": final_tags.strip(), "limit": max(1, min(int(limit or 100), 100)), "page": max(1, int(page or 1))})
    resp = _browser_bridge_fetch_json("/posts.json", params=params, label="posts_search")
    if not (200 <= int(resp.status_code or 0) < 300):
        raise RuntimeError(f"浏览器桥接 HTTP {resp.status_code}")
    return resp.text


def _danbooru_browser_bridge_get_post_by_id(post_id: str):
    params = _with_danbooru_auth_params({})
    resp = _browser_bridge_fetch_json(f"/posts/{str(post_id).strip()}.json", params=params, label="post_by_id")
    if not (200 <= int(resp.status_code or 0) < 300):
        raise RuntimeError(f"浏览器桥接 HTTP {resp.status_code}")
    return json.dumps([resp.json()], ensure_ascii=False)


def _normalize_full_settings_import(payload):
    """兼容 v9 完整导出和旧版前端导出格式。只合并已知设置键。"""
    current = load_settings()
    source = payload.get("settings", payload) if isinstance(payload, dict) else {}
    if not isinstance(source, dict):
        source = {}

    # 兼容新版 auth 包装字段
    auth = payload.get("auth") if isinstance(payload, dict) else None
    if isinstance(auth, dict):
        danbooru = auth.get("danbooru", {}) or {}
        danbooru_cookie = auth.get("danbooru_cookie", {}) or {}
        gelbooru = auth.get("gelbooru", {}) or {}
        if "username" in danbooru:
            source["danbooru_username"] = danbooru.get("username", "")
        if "api_key" in danbooru:
            source["danbooru_api_key"] = danbooru.get("api_key", "")
        if "cookie_enabled" in danbooru:
            source["danbooru_cookie_enabled"] = bool(danbooru.get("cookie_enabled"))
        if "cookie_fallback_enabled" in danbooru:
            source["danbooru_cookie_enabled"] = bool(danbooru.get("cookie_fallback_enabled"))
        if "enabled" in danbooru_cookie:
            source["danbooru_cookie_enabled"] = bool(danbooru_cookie.get("enabled"))
        if "cookie" in danbooru:
            source["danbooru_cookie"] = _normalize_cookie_header(danbooru.get("cookie", ""))
        if "cookie" in danbooru_cookie:
            source["danbooru_cookie"] = _normalize_cookie_header(danbooru_cookie.get("cookie", ""))
        if "user_id" in gelbooru:
            source["gelbooru_user_id"] = gelbooru.get("user_id", "")
        if "api_key" in gelbooru:
            source["gelbooru_api_key"] = gelbooru.get("api_key", "")
        browser_headers = auth.get("danbooru_browser_headers", {}) or auth.get("browser_headers", {}) or {}
        if isinstance(browser_headers, dict):
            if "enabled" in browser_headers:
                source["danbooru_browser_headers_enabled"] = bool(browser_headers.get("enabled"))
            if "headers" in browser_headers:
                source["danbooru_browser_headers"] = _normalize_raw_browser_headers(browser_headers.get("headers", ""))
            if "raw_headers" in browser_headers:
                source["danbooru_browser_headers"] = _normalize_raw_browser_headers(browser_headers.get("raw_headers", ""))
        browser_bridge = auth.get("danbooru_browser_bridge", {}) or auth.get("browser_bridge", {}) or {}
        if isinstance(browser_bridge, dict):
            if "enabled" in browser_bridge:
                source["danbooru_browser_bridge_enabled"] = bool(browser_bridge.get("enabled"))
            if "cdp_url" in browser_bridge:
                source["danbooru_browser_bridge_cdp_url"] = str(browser_bridge.get("cdp_url") or "")
            if "timeout_ms" in browser_bridge:
                source["danbooru_browser_bridge_timeout_ms"] = int(browser_bridge.get("timeout_ms") or 60000)
            if "prefer" in browser_bridge:
                source["danbooru_browser_bridge_prefer"] = bool(browser_bridge.get("prefer"))
        civitai_auth = auth.get("civitai", {}) or {}
        if isinstance(civitai_auth, dict):
            if "api_key" in civitai_auth:
                source["civitai_api_key"] = str(civitai_auth.get("api_key") or "")
            if "remote_favorites_enabled" in civitai_auth:
                source["civitai_remote_favorites_enabled"] = bool(civitai_auth.get("remote_favorites_enabled"))
            if "collection_headers" in civitai_auth:
                source["civitai_collection_headers"] = _normalize_raw_browser_headers(civitai_auth.get("collection_headers", ""))
            if "search_headers" in civitai_auth:
                source["civitai_search_headers"] = _normalize_raw_browser_headers(civitai_auth.get("search_headers", ""))
            if "legacy_merged_headers" in civitai_auth:
                source["civitai_browser_headers"] = _normalize_raw_browser_headers(civitai_auth.get("legacy_merged_headers", ""))
            if "default_collection_id" in civitai_auth:
                source["civitai_default_collection_id"] = str(civitai_auth.get("default_collection_id") or "")

    # 兼容旧版前端导出格式
    if isinstance(payload, dict) and "prompt_filter" in payload and isinstance(payload["prompt_filter"], dict):
        pf = payload["prompt_filter"]
        if "tags" in pf:
            source["filter_tags"] = pf.get("tags") or []
        if "enabled" in pf:
            source["filter_enabled"] = bool(pf.get("enabled"))
    if isinstance(payload, dict) and "ui" in payload and isinstance(payload["ui"], dict):
        ui = payload["ui"]
        for k in ("autocomplete_enabled", "tooltip_enabled", "autocomplete_max_results", "selected_categories", "multi_select_enabled", "formatting"):
            if k in ui:
                source[k] = ui[k]
    if isinstance(payload, dict) and "language" in payload:
        source["language"] = payload.get("language")
    if isinstance(payload, dict) and "blacklist" in payload:
        source["blacklist"] = payload.get("blacklist")

    allowed = set(current.keys())
    merged = dict(current)
    for key, value in source.items():
        if key in allowed:
            merged[key] = value

    # 字段标准化
    for key in ("danbooru_username", "danbooru_api_key", "gelbooru_user_id", "gelbooru_api_key", "civitai_api_key", "civitai_default_collection_id"):
        merged[key] = str(merged.get(key, "") or "").strip()
    merged["danbooru_cookie"] = _normalize_cookie_header(merged.get("danbooru_cookie", ""))
    merged["danbooru_cookie_enabled"] = bool(merged.get("danbooru_cookie_enabled", False))
    merged["danbooru_browser_headers"] = _normalize_raw_browser_headers(merged.get("danbooru_browser_headers", ""))
    merged["danbooru_browser_headers_enabled"] = bool(merged.get("danbooru_browser_headers_enabled", False))
    merged["civitai_collection_headers"] = _normalize_raw_browser_headers(merged.get("civitai_collection_headers", ""))
    merged["civitai_search_headers"] = _normalize_raw_browser_headers(merged.get("civitai_search_headers", ""))
    merged["civitai_browser_headers"] = _normalize_raw_browser_headers(merged.get("civitai_browser_headers", ""))
    if merged.get("civitai_browser_headers") and (not merged.get("civitai_collection_headers") or not merged.get("civitai_search_headers")):
        col, sea = _split_civitai_raw_headers(merged.get("civitai_browser_headers"))
        merged["civitai_collection_headers"] = merged.get("civitai_collection_headers") or col
        merged["civitai_search_headers"] = merged.get("civitai_search_headers") or sea
    merged["civitai_remote_favorites_enabled"] = bool(merged.get("civitai_remote_favorites_enabled", False))
    return merged

def load_favorites():
    """从统一设置文件加载收藏列表"""
    settings = load_settings()
    return settings.get("favorites", [])

def save_favorites(favorites):
    """保存收藏列表到统一设置文件"""
    settings = load_settings()
    settings["favorites"] = favorites
    return save_settings(settings)

def load_civitai_favorites():
    """加载 Civitai 本地收藏。保存完整 post 片段，避免 Civitai 没有稳定 imageId 单图 REST 查询。"""
    settings = load_settings()
    favs = settings.get("civitai_favorites", [])
    return favs if isinstance(favs, list) else []

def save_civitai_favorites(favorites):
    settings = load_settings()
    settings["civitai_favorites"] = favorites if isinstance(favorites, list) else []
    return save_settings(settings)

def _civitai_favorite_key(post_or_id):
    if isinstance(post_or_id, dict):
        return str(post_or_id.get('id') or post_or_id.get('civitai_post_id') or post_or_id.get('file_url') or '').strip()
    return str(post_or_id or '').strip()

def load_language():
    """从统一设置文件加载语言设置"""
    settings = load_settings()
    return settings.get("language", "zh")

def save_language(language):
    """保存语言设置到统一设置文件"""
    settings = load_settings()
    settings["language"] = language
    return save_settings(settings)

def load_blacklist():
    """从统一设置文件加载黑名单"""
    settings = load_settings()
    return settings.get("blacklist", [])

def save_blacklist(blacklist_items):
    """保存黑名单到统一设置文件"""
    settings = load_settings()
    settings["blacklist"] = blacklist_items
    return save_settings(settings)

def load_filter_tags():
    """从统一设置文件加载提示词过滤设置"""
    settings = load_settings()
    return settings.get("filter_tags", []), settings.get("filter_enabled", True)

def save_filter_tags(filter_tags, enabled):
    """保存提示词过滤设置到统一设置文件"""
    settings = load_settings()
    settings["filter_tags"] = filter_tags
    settings["filter_enabled"] = enabled
    return save_settings(settings)

def load_ui_settings():
    """从统一设置文件加载UI设置"""
    settings = load_settings()
    return {
        "autocomplete_enabled": settings.get("autocomplete_enabled", True),
        "tooltip_enabled": settings.get("tooltip_enabled", True),
        "autocomplete_max_results": settings.get("autocomplete_max_results", 20),
        "selected_categories": settings.get("selected_categories", ["copyright", "character", "general"]),
        "multi_select_enabled": settings.get("multi_select_enabled", False),
        "formatting": settings.get("formatting", {"escapeBrackets": True, "replaceUnderscores": True})
    }

def save_ui_settings(ui_settings):
    """保存UI设置到统一设置文件"""
    settings = load_settings()
    settings["autocomplete_enabled"] = ui_settings.get("autocomplete_enabled", True)
    settings["tooltip_enabled"] = ui_settings.get("tooltip_enabled", True)
    settings["autocomplete_max_results"] = ui_settings.get("autocomplete_max_results", 20)
    settings["selected_categories"] = ui_settings.get("selected_categories", ["copyright", "character", "general"])
    settings["multi_select_enabled"] = ui_settings.get("multi_select_enabled", False)
    settings["formatting"] = ui_settings.get("formatting", settings.get("formatting", {"escapeBrackets": True, "replaceUnderscores": True}))
    return save_settings(settings)

# ================================
# Tag翻译系统
# ================================

def _normalize_translation_tag(value):
    """Return the canonical lookup form used by Booru tag inventories."""
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"\s+", "_", value)

class TagTranslationSystem:
    """Tag翻译系统，负责加载、处理和查询汉化数据"""
    
    def __init__(self):
        self.en_to_cn = {}  # 英文->中文映射
        # A Chinese label is not a canonical identity. Several distinct tags
        # can legitimately share the same display translation, so keep every
        # English tag instead of silently overwriting the previous one.
        self.cn_to_en = {}  # 中文->英文映射（一对多）
        self.cn_search_index = {}  # 中文搜索索引
        self.loaded = False
        self._translation_cache = {}  # 翻译缓存
        self._search_cache = {}  # 搜索缓存
        self.max_cache_size = 1000  # 最大缓存条目数

    def _register_chinese_reverse(self, cn_tag, en_tag):
        """Register a stable one-to-many Chinese -> English relationship."""
        cn_tag = cn_tag.strip() if isinstance(cn_tag, str) else ""
        en_tag = en_tag.strip() if isinstance(en_tag, str) else ""
        if not cn_tag or not en_tag:
            return
        english_tags = self.cn_to_en.setdefault(cn_tag, [])
        if en_tag not in english_tags:
            english_tags.append(en_tag)
        
    def load_translation_data(self):
        """加载所有汉化数据文件"""
        if self.loaded:
            return True
            
        try:
            zh_cn_dir = os.path.join(PLUGIN_DIR, "zh_cn")
            
            # 加载JSON格式数据
            self._load_json_data(zh_cn_dir)
            # 加载CSV格式数据
            self._load_csv_data(zh_cn_dir)
            # 加载角色CSV数据
            self._load_character_csv_data(zh_cn_dir)
            
            # 构建下划线匹配映射
            self._build_underscore_variants()
            # 构建中文搜索索引
            self._build_chinese_search_index()
            
            self.loaded = True
            return True
            
        except Exception as e:
            logger.error(f"[翻译系统] 加载失败: {e}")
            return False
    
    def _load_json_data(self, zh_cn_dir):
        """加载JSON格式的翻译数据"""
        json_file = os.path.join(zh_cn_dir, "all_tags_cn.json")
        if os.path.exists(json_file):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for en_tag, cn_tag in data.items():
                        if en_tag and cn_tag:
                            self.en_to_cn[en_tag.strip()] = cn_tag.strip()
                            self._register_chinese_reverse(cn_tag, en_tag)
            except Exception as e:
                logger.error(f"[翻译系统] JSON加载失败: {e}")
    
    def _load_csv_data(self, zh_cn_dir):
        """加载CSV格式的翻译数据"""
        csv_file = os.path.join(zh_cn_dir, "danbooru.csv")
        if os.path.exists(csv_file):
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    count = 0
                    for row in reader:
                        if len(row) >= 2 and row[0] and row[1]:
                            en_tag = row[0].strip()
                            cn_tag = row[1].strip()
                            # 如果已存在翻译，跳过（保持第一个找到的）
                            if en_tag not in self.en_to_cn:
                                self.en_to_cn[en_tag] = cn_tag
                            self._register_chinese_reverse(cn_tag, en_tag)
                            count += 1
            except Exception as e:
                logger.error(f"[翻译系统] CSV加载失败: {e}")
    
    def _load_character_csv_data(self, zh_cn_dir):
        """加载角色CSV格式的翻译数据（格式：中文名称,英文tag）"""
        csv_file = os.path.join(zh_cn_dir, "wai_characters.csv")
        if os.path.exists(csv_file):
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    count = 0
                    for row in reader:
                        if len(row) >= 2 and row[0] and row[1]:
                            cn_tag = row[0].strip()
                            en_tag = row[1].strip()
                            # 如果已存在翻译，跳过（保持第一个找到的）
                            if en_tag not in self.en_to_cn:
                                self.en_to_cn[en_tag] = cn_tag
                            self._register_chinese_reverse(cn_tag, en_tag)
                            count += 1
            except Exception as e:
                logger.error(f"[翻译系统] 角色CSV加载失败: {e}")
    
    def _build_underscore_variants(self):
        """构建下划线变体映射，处理有无下划线的匹配问题"""
        variants_to_add = {}
        
        for en_tag, cn_tag in list(self.en_to_cn.items()):
            # 为有下划线的tag生成无下划线版本
            if '_' in en_tag:
                no_underscore = en_tag.replace('_', '')
                if no_underscore not in self.en_to_cn:
                    variants_to_add[no_underscore] = cn_tag
            
            # 为无下划线的tag生成可能的下划线版本（基于常见模式）
            else:
                # 在数字和字母之间添加下划线 (如: 1girl -> 1_girl)
                with_underscore = re.sub(r'(\d)([a-zA-Z])', r'\1_\2', en_tag)
                if with_underscore != en_tag and with_underscore not in self.en_to_cn:
                    variants_to_add[with_underscore] = cn_tag
        
        # 添加变体到主字典
        self.en_to_cn.update(variants_to_add)
    
    def _build_chinese_search_index(self):
        """构建中文搜索索引，支持部分匹配"""
        for cn_tag in self.cn_to_en.keys():
            # 为中文tag的每个字符建立索引
            for i, char in enumerate(cn_tag):
                if char not in self.cn_search_index:
                    self.cn_search_index[char] = set()
                self.cn_search_index[char].add(cn_tag)
                
                # 也为子字符串建立索引（2-3字符的组合）
                for length in [2, 3]:
                    if i + length <= len(cn_tag):
                        substring = cn_tag[i:i + length]
                        if substring not in self.cn_search_index:
                            self.cn_search_index[substring] = set()
                        self.cn_search_index[substring].add(cn_tag)
        
        # 转换set为list以便JSON序列化
        for key in self.cn_search_index:
            self.cn_search_index[key] = list(self.cn_search_index[key])
            
    
    def translate_tag(self, en_tag):
        """翻译单个英文tag到中文"""
        if not self.loaded:
            self.load_translation_data()

        original_key = en_tag.strip() if isinstance(en_tag, str) else ""
        tag_key = _normalize_translation_tag(original_key)
        if not tag_key:
            return None
        
        # 检查缓存
        if tag_key in self._translation_cache:
            return self._translation_cache[tag_key]
        
        # Existing files are mostly canonical underscore tags. Keep an exact
        # fallback for legacy mixed-case entries while making prompt-space and
        # underscore forms resolve consistently.
        translation = self.en_to_cn.get(tag_key) or self.en_to_cn.get(original_key)
        
        # 添加到缓存
        if len(self._translation_cache) < self.max_cache_size:
            self._translation_cache[tag_key] = translation
        
        return translation
    
    def translate_tags_batch(self, en_tags):
        """批量翻译英文tags"""
        if not self.loaded:
            self.load_translation_data()
        
        result = {}
        for tag in en_tags:
            translation = self.translate_tag(tag)
            if translation:
                result[tag] = translation
        return result
    
    def search_chinese_tags(self, query, limit=10):
        """搜索中文tag，返回匹配的中文tag及对应英文tag，支持模糊搜索"""
        if not self.loaded:
            self.load_translation_data()
        
        query = query.strip()
        if not query:
            return []
        
        # 检查搜索缓存
        cache_key = f"{query}:{limit}"
        if cache_key in self._search_cache:
            return self._search_cache[cache_key]
        
        matches = {}  # 使用字典存储匹配结果和权重
        
        # 1. 精确匹配（权重10）
        if query in self.cn_to_en:
            matches[query] = 10
        
        # 2. 前缀匹配（权重8）
        for cn_tag in self.cn_to_en.keys():
            if cn_tag.startswith(query) and cn_tag not in matches:
                matches[cn_tag] = 8
        
        # 3. 索引匹配（权重6）
        if query in self.cn_search_index:
            for cn_tag in self.cn_search_index[query]:
                if cn_tag not in matches:
                    matches[cn_tag] = 6
        
        # 4. 包含匹配（权重4）
        for cn_tag in self.cn_to_en.keys():
            if query in cn_tag and cn_tag not in matches:
                matches[cn_tag] = 4
        
        # 5. 模糊匹配（权重2）- 支持字符顺序模糊匹配
        if len(query) >= 2:
            query_chars = set(query)
            for cn_tag in self.cn_to_en.keys():
                if cn_tag not in matches:
                    tag_chars = set(cn_tag)
                    # 如果查询字符的50%以上都在tag中，认为是模糊匹配
                    if len(query_chars & tag_chars) / len(query_chars) >= 0.5:
                        matches[cn_tag] = 2
        
        # 6. 部分字符匹配（权重1）
        for char in query:
            if char in self.cn_search_index:
                for cn_tag in self.cn_search_index[char]:
                    if cn_tag not in matches:
                        matches[cn_tag] = 1
        
        # 按权重和长度排序
        sorted_matches = sorted(matches.items(), key=lambda x: (-x[1], len(x[0])))
        
        # 转换为结果格式并限制数量。相同中文译文下的不同英文 tag
        # 各自保留身份；括号限定符和连字符不会被折叠或剥离。
        results = []
        for cn_tag, weight in sorted_matches:
            for en_tag in self.cn_to_en.get(cn_tag, []):
                results.append({
                    'chinese': cn_tag,
                    'english': en_tag,
                    'weight': weight
                })
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
        
        # 添加到缓存
        if len(self._search_cache) < self.max_cache_size:
            self._search_cache[cache_key] = results
        
        return results

# 全局翻译系统实例
translation_system = TagTranslationSystem()


async def _resolve_tag_translations(tags, max_tags=500):
    """Resolve safe display translations through one category-aware path.

    SQLite is authoritative because it owns both the Danbooru category and the
    current integrated translation. Static files only fill a known non-artist
    database row with no SQLite translation. Category lookup is deliberately
    fail-closed for the static layer so an artist entry can never leak merely
    because it also exists in a legacy JSON/CSV file.
    """
    clean_tags = []
    seen = set()
    for value in tags or []:
        if not isinstance(value, str):
            continue
        value = value.strip()
        if not value or len(value) > 256 or value in seen:
            continue
        seen.add(value)
        clean_tags.append(value)
        if len(clean_tags) >= max_tags:
            break

    if not clean_tags:
        return {}

    db = None
    categories = {}
    category_lookup_ready = False
    if get_db_manager:
        try:
            db = get_db_manager()
            get_categories = getattr(db, "get_categories", None)
            if get_categories:
                raw_categories = await get_categories(clean_tags)
                if isinstance(raw_categories, dict):
                    for key, value in raw_categories.items():
                        if isinstance(value, dict):
                            value = value.get("category")
                        try:
                            category = int(value)
                        except (TypeError, ValueError):
                            continue
                        categories[str(key)] = category
                        categories[_normalize_translation_tag(str(key))] = category
                category_lookup_ready = True
        except Exception as e:
            logger.warning(f"[TagTranslation] SQLite category lookup failed; static fallback disabled: {e}")

    def category_for(tag):
        return categories.get(tag, categories.get(_normalize_translation_tag(tag)))

    # No category means no safe proof that the tag is not an artist. This also
    # keeps partially upgraded/third-party database managers fail-closed.
    non_artist_tags = [
        tag for tag in clean_tags
        if category_lookup_ready
        and category_for(tag) is not None
        and category_for(tag) != 1
    ]
    translations = {}

    # The database manager also applies the artist mask internally. Keeping the
    # runtime check makes the boundary explicit even for older/custom managers.
    if db and non_artist_tags:
        try:
            db_translations = await db.get_translations(non_artist_tags)
            normalized_db = {
                _normalize_translation_tag(key): value
                for key, value in (db_translations or {}).items()
                if isinstance(key, str) and value
            }
            for tag in non_artist_tags:
                translation = (db_translations or {}).get(tag)
                if not translation:
                    translation = normalized_db.get(_normalize_translation_tag(tag))
                if translation:
                    translations[tag] = translation
        except Exception as e:
            logger.warning(f"[TagTranslation] SQLite translation lookup failed: {e}")

    # Static dictionaries do not contain category metadata. Only use them when
    # SQLite positively identified the tag as an allowed non-artist category.
    if category_lookup_ready:
        static_candidates = [tag for tag in non_artist_tags if tag not in translations]
        for tag, translation in translation_system.translate_tags_batch(static_candidates).items():
            if translation:
                translations.setdefault(tag, translation)
    return translations

# 预加载翻译数据
def preload_translation_data():
    """预加载翻译数据，在服务器启动时调用"""
    try:
        success = translation_system.load_translation_data()
        if not success:
            logger.warning("[翻译系统] 预加载失败")
    except Exception as e:
        logger.error(f"[翻译系统] 预加载异常: {e}")

# 在模块加载时预加载翻译数据
preload_translation_data()

def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _absolute_url(url, base_url=GELBOORU_BASE_URL):
    if not url:
        return ""
    url = str(url).strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urllib.parse.urljoin(base_url, url)
    return url


def _file_ext_from_url(url, fallback="jpg"):
    try:
        path = urllib.parse.urlparse(url).path
        ext = os.path.splitext(path)[1].lstrip('.').lower()
        return ext or fallback
    except Exception:
        return fallback


def _normalize_tag_string(tags):
    if not tags:
        return ""
    if isinstance(tags, list):
        tags = " ".join(str(x) for x in tags)
    return " ".join(str(tags).replace("\n", " ").split())


def _normalize_gelbooru_response(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    posts = data.get("post") or data.get("posts") or []
    if isinstance(posts, dict):
        return [posts]
    if isinstance(posts, list):
        return posts
    return []


def _gelbooru_post_to_danbooru_shape(post):
    """把 Gelbooru API post 转成前端已有 Danbooru 卡片结构。"""
    if not isinstance(post, dict):
        return None

    post_id = post.get("id")
    tags = _normalize_tag_string(post.get("tags") or post.get("tag_string") or "")

    file_url = _absolute_url(post.get("file_url"))
    sample_url = _absolute_url(post.get("sample_url") or post.get("large_file_url"))
    preview_url = _absolute_url(post.get("preview_url") or post.get("preview_file_url"))

    # 某些 Gelbooru 响应只给 directory/image。
    if not file_url and post.get("directory") and post.get("image"):
        file_url = f"https://img4.gelbooru.com/images/{post.get('directory')}/{post.get('image')}"
    if not sample_url:
        sample_url = file_url
    if not preview_url:
        preview_url = sample_url or file_url

    width = _safe_int(post.get("width") or post.get("image_width") or post.get("sample_width") or post.get("preview_width"), 0)
    height = _safe_int(post.get("height") or post.get("image_height") or post.get("sample_height") or post.get("preview_height"), 0)
    if width <= 0:
        width = _safe_int(post.get("sample_width") or post.get("preview_width"), 0)
    if height <= 0:
        height = _safe_int(post.get("sample_height") or post.get("preview_height"), 0)

    rating = str(post.get("rating") or "").lower()
    rating_map = {
        "safe": "general",
        "s": "general",
        "questionable": "questionable",
        "q": "questionable",
        "explicit": "explicit",
        "e": "explicit",
    }

    normalized = {
        "id": post_id,
        "source_site": "gelbooru",
        "source": "gelbooru",
        "md5": str(post.get("md5") or post_id or int(time.time() * 1000)),
        "created_at": post.get("created_at") or post.get("created_at_str") or post.get("change") or "",
        "score": _safe_int(post.get("score"), 0),
        "rating": rating_map.get(rating, rating or "general"),
        "file_ext": str(post.get("file_ext") or _file_ext_from_url(file_url or sample_url or preview_url)).lower(),
        "file_url": file_url,
        "large_file_url": sample_url or file_url,
        "preview_file_url": preview_url or sample_url or file_url,
        "image_width": width,
        "image_height": height,
        "tag_string": tags,
        # Gelbooru 的 post API 通常只返回平铺 tags，不返回每个 tag 的分类。
        # 为了不丢 tag，把所有 tag 放进 general。用户仍可通过类别下拉勾选 general 输出。
        "tag_string_artist": "",
        "tag_string_copyright": "",
        "tag_string_character": "",
        "tag_string_general": tags,
        "tag_string_meta": "",
    }
    return normalized


def _load_gelbooru_auth_params():
    user_id, api_key = load_gelbooru_auth()
    params = {}
    if user_id and api_key:
        params["user_id"] = str(user_id).strip()
        params["api_key"] = str(api_key).strip()
    return params


def _gelbooru_build_tags(tags, rating=None):
    parts = []
    for tag in (tags or "").split():
        if not tag:
            continue
        # Gelbooru 对 Danbooru 的 order:rank 不兼容，用更接近的 sort:score 替代。
        if tag == "order:rank":
            parts.append("sort:score")
            continue
        # date:... 在 Gelbooru DAPI 中兼容性较差；保守跳过，避免整个查询失败。
        if tag.startswith("date:"):
            continue
        parts.append(tag)

    if rating and rating.lower() != "all":
        raw = [r.strip().lower() for r in rating.split(',') if r.strip()]
        mapped = set()
        for r in raw:
            if r in ("general", "sensitive", "g", "s", "safe"):
                mapped.add("safe")
            elif r in ("questionable", "q"):
                mapped.add("questionable")
            elif r in ("explicit", "e"):
                mapped.add("explicit")
        # Gelbooru 的 DAPI 对 OR rating 不如 Danbooru 稳定；只在单一 rating 时追加。
        if len(mapped) == 1:
            parts.append(f"rating:{next(iter(mapped))}")
        elif mapped == {"safe", "questionable"}:
            parts.append("-rating:explicit")
        elif mapped == {"safe", "explicit"}:
            parts.append("-rating:questionable")
        elif mapped == {"questionable", "explicit"}:
            parts.append("-rating:safe")


    return " ".join(parts).strip()


def _parse_html_attrs(text):
    """Parse a small HTML tag attribute string without external dependencies."""
    attrs = {}
    if not text:
        return attrs
    for m in re.finditer(r'([:\w-]+)\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', str(text), re.S):
        key = m.group(1).lower()
        val = m.group(2).strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        attrs[key] = html_lib.unescape(val)
    return attrs


def _clean_gelbooru_tag_text(raw):
    raw = html_lib.unescape(str(raw or ""))
    # Thumbnail titles sometimes contain compact tags. Keep booru-style tokens and drop obvious UI noise.
    raw = raw.replace(',', ' ').replace('\n', ' ').replace('\r', ' ')
    raw = re.sub(r'\s+', ' ', raw).strip()
    if not raw:
        return ""
    # Avoid leaking common non-tag fragments into prompts.
    bad = {
        'posts', 'image', 'images', 'edit', 'delete', 'flag_for_deletion',
        'add_to_favorites', 'add_note', 'add_to_pool', 'lock_image', 'tag_merge',
        'up', 'all', 'safe_images_only_mode'
    }
    tags = []
    for tok in raw.split(' '):
        tok = tok.strip().strip(',;')
        if not tok:
            continue
        norm = tok.replace(' ', '_')
        if norm.lower() in bad:
            continue
        # Keep meta-like tokens only if they are normal booru tokens. Drop labels.
        if norm.lower() in {'rating:', 'score:', 'id:', 'size:'}:
            continue
        tags.append(norm)
    return _normalize_tag_string(tags)


def _gelbooru_guess_sample_from_thumbnail(url):
    """Best-effort convert Gelbooru thumbnail URL to sample URL.

    Common pattern:
    /thumbnails/aa/bb/thumbnail_HASH.jpg -> /samples/aa/bb/sample_HASH.jpg
    This gives a usable display/download image even when DAPI is unavailable.
    """
    url = _absolute_url(url)
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        if '/thumbnails/' in path:
            new_path = path.replace('/thumbnails/', '/samples/')
            new_path = re.sub(r'/thumbnail_', '/sample_', new_path)
            return urllib.parse.urlunparse(parsed._replace(path=new_path, query=''))
    except Exception:
        pass
    return url


def _gelbooru_post_from_html_bits(post_id, block_attrs=None, img_attrs=None, a_attrs=None, body_text=""):
    block_attrs = block_attrs or {}
    img_attrs = img_attrs or {}
    a_attrs = a_attrs or {}
    post_id = str(post_id or block_attrs.get('data-id') or block_attrs.get('id') or '').lstrip('p')
    if not post_id:
        return None

    preview_url = (
        img_attrs.get('data-original') or img_attrs.get('data-src') or img_attrs.get('src') or
        block_attrs.get('data-preview-url') or block_attrs.get('data-preview-file-url') or block_attrs.get('data-thumb-url') or ''
    )
    preview_url = _absolute_url(preview_url)

    sample_url = _absolute_url(
        block_attrs.get('data-sample-url') or block_attrs.get('data-large-file-url') or block_attrs.get('data-large-url') or ''
    )
    file_url = _absolute_url(
        block_attrs.get('data-file-url') or block_attrs.get('data-image-url') or block_attrs.get('data-original-url') or ''
    )
    if not sample_url and preview_url:
        sample_url = _gelbooru_guess_sample_from_thumbnail(preview_url)
    if not file_url:
        # Prefer sample-sized file over thumbnail for ComfyUI output. If the guessed sample 404s,
        # the existing image loader will fall back to preview_file_url from selection data.
        file_url = sample_url or preview_url

    tag_raw = (
        block_attrs.get('data-tags') or block_attrs.get('tags') or
        img_attrs.get('title') or img_attrs.get('alt') or a_attrs.get('title') or body_text or ''
    )
    tags = _clean_gelbooru_tag_text(tag_raw)

    rating = str(block_attrs.get('data-rating') or block_attrs.get('rating') or '').lower()
    if rating in ('s', 'safe'):
        rating = 'general'
    elif rating in ('q', 'questionable'):
        rating = 'questionable'
    elif rating in ('e', 'explicit'):
        rating = 'explicit'
    elif rating in ('g', 'general'):
        rating = 'general'
    elif not rating:
        rating = 'general'

    width = _safe_int(img_attrs.get('width') or block_attrs.get('data-width') or block_attrs.get('data-image-width'), 0)
    height = _safe_int(img_attrs.get('height') or block_attrs.get('data-height') or block_attrs.get('data-image-height'), 0)

    return {
        'id': post_id,
        'source_site': 'gelbooru',
        'source': 'gelbooru',
        'md5': str(block_attrs.get('data-md5') or post_id),
        'created_at': '',
        'score': _safe_int(block_attrs.get('data-score'), 0),
        'rating': rating,
        'file_ext': _file_ext_from_url(file_url or sample_url or preview_url),
        'file_url': file_url,
        'large_file_url': sample_url or file_url or preview_url,
        'preview_file_url': preview_url or sample_url or file_url,
        'image_width': width,
        'image_height': height,
        'tag_string': tags,
        'tag_string_artist': '',
        'tag_string_copyright': '',
        'tag_string_character': '',
        'tag_string_general': tags,
        'tag_string_meta': '',
    }


def _extract_gelbooru_posts_from_html(text, limit=100):
    posts = []
    seen = set()
    html = text or ""

    def add_post(post):
        if not post or not post.get('id') or not post.get('preview_file_url'):
            return
        pid = str(post['id'])
        if pid in seen:
            return
        seen.add(pid)
        posts.append(post)

    # Modern Gelbooru uses article.thumbnail-preview blocks.
    for m in re.finditer(r'<article\b(?P<attrs>[^>]*)>(?P<body>.*?)</article>', html, re.I | re.S):
        attrs = _parse_html_attrs(m.group('attrs'))
        body = m.group('body') or ''
        id_match = re.search(r'(?:^|\s)id\s*=\s*["\']?p?(\d+)', m.group('attrs') or '', re.I)
        href_match = re.search(r'href\s*=\s*["\']([^"\']*page=post[^"\']*s=view[^"\']*id=(\d+)[^"\']*)["\']', body, re.I)
        post_id = (id_match.group(1) if id_match else None) or (href_match.group(2) if href_match else None)
        img_match = re.search(r'<img\b(?P<attrs>[^>]*)>', body, re.I | re.S)
        img_attrs = _parse_html_attrs(img_match.group('attrs') if img_match else '')
        a_attrs = _parse_html_attrs(href_match.group(0) if href_match else '')
        add_post(_gelbooru_post_from_html_bits(post_id, attrs, img_attrs, a_attrs))
        if len(posts) >= int(limit or 100):
            return posts[:int(limit or 100)]

    # Fallback for older layouts: parse individual anchors containing an image.
    for m in re.finditer(r'<a\b(?P<a_attrs>[^>]*href\s*=\s*["\'][^"\']*page=post[^"\']*s=view[^"\']*id=(?P<id>\d+)[^"\']*["\'][^>]*)>(?P<body>.*?)</a>', html, re.I | re.S):
        body = m.group('body') or ''
        img_match = re.search(r'<img\b(?P<img_attrs>[^>]*)>', body, re.I | re.S)
        if not img_match:
            continue
        add_post(_gelbooru_post_from_html_bits(m.group('id'), {}, _parse_html_attrs(img_match.group('img_attrs')), _parse_html_attrs(m.group('a_attrs'))))
        if len(posts) >= int(limit or 100):
            break

    return posts[:int(limit or 100)]


def _get_gelbooru_posts_html(tags: str, limit: int = 100, page: int = 1, rating: str = None):
    """Fallback search via Gelbooru HTML pages. This avoids DAPI 401 when API auth is not set."""
    final_tags = _gelbooru_build_tags(tags, rating=rating)
    params = {
        'page': 'post',
        's': 'list',
        'tags': final_tags,
    }
    # Gelbooru HTML pagination uses an offset. The page normally contains 42 thumbs.
    page_i = max(int(page or 1), 1)
    if page_i > 1:
        params['pid'] = (page_i - 1) * 42
    response = _gelbooru_request('GET', f'{GELBOORU_BASE_URL}/index.php', params=params, timeout=20, headers={'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'})
    if response.status_code != 200:
        logger.error(f'[GelbooruHTML] 搜索页面失败: HTTP {response.status_code}')
        raise _legacy_error_from_response('gelbooru', response, context='Gelbooru HTML fallback')
    if _is_cloudflare_challenge(response):
        raise LegacyGalleryError(
            'challenge', 403, 'Gelbooru HTML fallback 被上游验证页面拦截',
            source='gelbooru', upstream_status=403,
        )
    posts = _extract_gelbooru_posts_from_html(response.text, limit=limit)
    logger.info(f'[GelbooruHTML] fallback parsed {len(posts)} posts for tags={_sanitize_log_text(final_tags)!r} page={page_i}')
    return posts


def _get_gelbooru_post_by_id_html(post_id: str):
    params = {'page': 'post', 's': 'view', 'id': str(post_id).strip()}
    response = _gelbooru_request('GET', f'{GELBOORU_BASE_URL}/index.php', params=params, timeout=20, headers={'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'})
    if response.status_code != 200:
        logger.error(f'[GelbooruHTML] 单图页面失败 {post_id}: HTTP {response.status_code}')
        if response.status_code == 404:
            return None
        raise _legacy_error_from_response('gelbooru', response, context='Gelbooru 单图 HTML fallback')
    if _is_cloudflare_challenge(response):
        raise LegacyGalleryError(
            'challenge', 403, 'Gelbooru 单图 HTML fallback 被上游验证页面拦截',
            source='gelbooru', upstream_status=403,
        )
    text = response.text or ''

    tags = ''
    m = re.search(r'<textarea\b[^>]*(?:name|id)\s*=\s*["\']tags["\'][^>]*>(.*?)</textarea>', text, re.I | re.S)
    if m:
        tags = _clean_gelbooru_tag_text(re.sub(r'<[^>]+>', ' ', m.group(1)))
    if not tags:
        m = re.search(r'<input\b[^>]*(?:name|id)\s*=\s*["\']tags["\'][^>]*value\s*=\s*("[^"]*"|\'[^\']*\')', text, re.I | re.S)
        if m:
            tags = _clean_gelbooru_tag_text(m.group(1).strip('"\''))
    if not tags:
        m = re.search(r'<title>(.*?)\s+-\s+Image View', text, re.I | re.S)
        if m:
            tags = _clean_gelbooru_tag_text(re.sub(r'<[^>]+>', ' ', m.group(1)))

    file_url = ''
    sample_url = ''
    # Original image link.
    m = re.search(r'href\s*=\s*["\'](https?://(?:img\d+\.)?gelbooru\.com/(?:images|samples)/[^"\']+)["\'][^>]*>\s*Original image', text, re.I | re.S)
    if m:
        file_url = _absolute_url(html_lib.unescape(m.group(1)))
    # Display image.
    m = re.search(r'<img\b[^>]*(?:id|class)\s*=\s*["\'][^"\']*image[^"\']*["\'][^>]*src\s*=\s*["\']([^"\']+)["\']', text, re.I | re.S)
    if m:
        sample_url = _absolute_url(html_lib.unescape(m.group(1)))
    if not file_url:
        m = re.search(r'href\s*=\s*["\'](https?://(?:img\d+\.)?gelbooru\.com/(?:images|samples)/[^"\']+)["\']', text, re.I | re.S)
        if m:
            file_url = _absolute_url(html_lib.unescape(m.group(1)))
    if not sample_url:
        sample_url = file_url

    width = height = 0
    m = re.search(r'Size:\s*(\d+)\s*x\s*(\d+)', text, re.I)
    if m:
        width = _safe_int(m.group(1), 0)
        height = _safe_int(m.group(2), 0)

    rating = 'general'
    m = re.search(r'Rating:\s*([A-Za-z]+)', text, re.I)
    if m:
        r = m.group(1).lower()
        rating = {'safe': 'general', 'sensitive': 'sensitive', 'questionable': 'questionable', 'explicit': 'explicit', 'general': 'general'}.get(r, r)

    return {
        'id': str(post_id),
        'source_site': 'gelbooru',
        'source': 'gelbooru',
        'md5': str(post_id),
        'created_at': '',
        'score': 0,
        'rating': rating,
        'file_ext': _file_ext_from_url(file_url or sample_url),
        'file_url': file_url or sample_url,
        'large_file_url': sample_url or file_url,
        'preview_file_url': sample_url or file_url,
        'image_width': width,
        'image_height': height,
        'tag_string': tags,
        'tag_string_artist': '',
        'tag_string_copyright': '',
        'tag_string_character': '',
        'tag_string_general': tags,
        'tag_string_meta': '',
    }



_CIVITAI_CURSOR_CACHE = {}
# V54: image.getInfinite may return 100 records while the UI asks for 40. Keep a
# bounded, ordered prefix per collection so local pages can cross upstream batch
# boundaries without skipping the unused tail of a batch.
_CIVITAI_REMOTE_COLLECTION_FULL_CACHE = {}
_CIVITAI_REMOTE_COLLECTION_CACHE_LOCK = threading.RLock()
_CIVITAI_REMOTE_COLLECTION_CACHE_TTL_SECONDS = 5 * 60
_CIVITAI_REMOTE_COLLECTION_MAX_BUFFERED_POSTS = 20000
_CIVITAI_REMOTE_COLLECTION_MAX_BATCHES_PER_CALL = 50
_CIVITAI_REMOTE_COLLECTION_MAX_FILTER_SCAN_POSTS = 5000
_CIVITAI_MODEL_DISCOVERY_CACHE = {}
_CIVITAI_TAG_DISCOVERY_CACHE = {}
_CIVITAI_LAST_SEARCH_DEBUG = {}


def _invalidate_civitai_remote_collection_cache(collection_id=None):
    """Invalidate buffered remote collection pages after a write/settings change."""
    with _CIVITAI_REMOTE_COLLECTION_CACHE_LOCK:
        if collection_id in (None, ''):
            _CIVITAI_REMOTE_COLLECTION_FULL_CACHE.clear()
            return
        target = str(collection_id)
        for cache_key, state in list(_CIVITAI_REMOTE_COLLECTION_FULL_CACHE.items()):
            state_id = state.get('collection_id') if isinstance(state, dict) else None
            if str(state_id) == target:
                _CIVITAI_REMOTE_COLLECTION_FULL_CACHE.pop(cache_key, None)



# ================================
# Yande.re / Moebooru support (V27)
# ================================

_YANDERE_RATING_MAP = {
    's': 'general',
    'safe': 'general',
    'q': 'questionable',
    'questionable': 'questionable',
    'e': 'explicit',
    'explicit': 'explicit',
}
_YANDERE_TAG_TYPE_MAP = {
    0: 'general',
    1: 'artist',
    3: 'copyright',
    4: 'character',
}


def _yandere_build_tags(tags, rating=None):
    """Build Yande.re tag query.

    Yande.re follows Moebooru/Danbooru 1.x style: /post.json?tags=...&limit=&page=.
    Rating tags are safe/questionable/explicit rather than Danbooru's general/sensitive vocabulary.
    """
    parts = []
    for tag in (tags or '').split():
        tag = tag.strip()
        if not tag:
            continue
        if tag == 'order:rank':
            parts.append('order:score')
            continue
        # yande.re accepts many meta tags. Keep most user input unchanged.
        parts.append(tag)

    if rating and str(rating).lower() != 'all':
        raw = [r.strip().lower() for r in str(rating).split(',') if r.strip()]
        mapped = set()
        for r in raw:
            if r in ('general', 'sensitive', 'safe', 's'):
                mapped.add('safe')
            elif r in ('questionable', 'q'):
                mapped.add('questionable')
            elif r in ('explicit', 'e'):
                mapped.add('explicit')
        # Moebooru OR syntax is site-dependent; use a single exact rating only.
        if len(mapped) == 1:
            parts.append(f"rating:{next(iter(mapped))}")
    return ' '.join(parts).strip()


def _yandere_post_to_danbooru_shape(post):
    """Normalize Yande.re post JSON into the existing frontend post shape."""
    if not isinstance(post, dict):
        return None
    post_id = post.get('id')
    tags = _normalize_tag_string(post.get('tags') or post.get('tag_string') or '')

    file_url = _absolute_url(post.get('file_url') or post.get('jpeg_url'), YANDERE_BASE_URL)
    sample_url = _absolute_url(post.get('sample_url') or post.get('large_file_url') or post.get('jpeg_url'), YANDERE_BASE_URL)
    preview_url = _absolute_url(post.get('preview_url') or post.get('preview_file_url'), YANDERE_BASE_URL)
    if not sample_url:
        sample_url = file_url
    if not preview_url:
        preview_url = sample_url or file_url

    rating_raw = str(post.get('rating') or '').lower()
    rating = _YANDERE_RATING_MAP.get(rating_raw, rating_raw or 'general')
    width = _safe_int(post.get('width') or post.get('image_width') or post.get('sample_width') or post.get('jpeg_width'), 0)
    height = _safe_int(post.get('height') or post.get('image_height') or post.get('sample_height') or post.get('jpeg_height'), 0)
    if width <= 0:
        width = _safe_int(post.get('sample_width') or post.get('preview_width'), 0)
    if height <= 0:
        height = _safe_int(post.get('sample_height') or post.get('preview_height'), 0)

    file_ext = str(post.get('file_ext') or '').lower().strip()
    if not file_ext:
        file_ext = _file_ext_from_url(file_url or sample_url or preview_url, 'jpg')

    page_url = f"{YANDERE_BASE_URL}/post/show/{post_id}" if post_id else YANDERE_BASE_URL
    return {
        'id': post_id,
        'source_site': 'yandere',
        'source': 'yandere',
        'yandere_url': page_url,
        'md5': str(post.get('md5') or post.get('file_md5') or post_id or int(time.time() * 1000)),
        'created_at': post.get('created_at') or post.get('created_at_str') or post.get('change') or '',
        'score': _safe_int(post.get('score'), 0),
        'rating': rating,
        'file_ext': file_ext,
        'file_url': file_url,
        'large_file_url': sample_url or file_url,
        'preview_file_url': preview_url or sample_url or file_url,
        'sample_url': sample_url or file_url,
        'preview_url': preview_url or sample_url or file_url,
        'image_width': width,
        'image_height': height,
        # Yande.re post JSON exposes tags as a flat string. Tag category can be recovered via /tag.json, but
        # per-post category is not present in standard post response. Put all tags into general to preserve data.
        'tag_string': tags,
        'tag_string_artist': '',
        'tag_string_copyright': '',
        'tag_string_character': '',
        'tag_string_general': tags,
        'tag_string_meta': '',
    }


def _get_yandere_posts(tags: str, limit: int = 100, page: int = 1, rating: str = None):
    final_tags = _yandere_build_tags(tags, rating=rating)
    params = {
        'tags': final_tags,
        'limit': max(1, min(int(limit or 100), 100)),
        'page': max(int(page or 1), 1),
    }
    resp = _yandere_request('GET', f'{YANDERE_BASE_URL}/post.json', params=params, timeout=20)
    if resp.status_code != 200:
        logger.error(f'[Yande.re] /post.json HTTP {resp.status_code}: {_sanitize_log_text(resp.text[:200])}')
        raise _legacy_error_from_response('yandere', resp, context='Yande.re posts')
    try:
        data = resp.json()
    except Exception as exc:
        raise LegacyGalleryError(
            'schema_changed', 502, 'Yande.re posts 响应无法解析', source='yandere'
        ) from exc
    if not isinstance(data, list):
        logger.warning(f'[Yande.re] /post.json returned non-list: {type(data).__name__}')
        raise LegacyGalleryError(
            'schema_changed', 502, 'Yande.re posts 响应结构异常', source='yandere'
        )
    normalized = []
    for raw_post in data:
        post = _yandere_post_to_danbooru_shape(raw_post)
        if post and post.get('preview_file_url'):
            normalized.append(post)
    return json.dumps(normalized, ensure_ascii=False)


def _get_yandere_post_by_id(post_id: str):
    post_id = str(post_id or '').strip()
    if not post_id:
        return '[]'
    # Moebooru supports id:<id> in /post.json tags. This avoids relying on HTML scraping.
    return _get_yandere_posts(f'id:{post_id}', limit=1, page=1)


def _get_yandere_tag_suggestions(query: str, limit: int = 20):
    query = str(query or '').strip()
    if not query:
        return []
    params = {
        'name_pattern': f'{query}*',
        'order': 'count',
        'limit': max(1, min(int(limit or 20), 100)),
    }
    try:
        resp = _yandere_request('GET', f'{YANDERE_BASE_URL}/tag.json', params=params, timeout=8)
        if resp.status_code != 200:
            logger.warning(f'[Yande.re] /tag.json HTTP {resp.status_code}')
            return []
        data = resp.json()
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get('name') or item.get('tag')
            if not name:
                continue
            tag_type = _safe_int(item.get('type') or item.get('tag_type'), 0)
            out.append({
                'name': name,
                'tag': name,
                'category': _YANDERE_TAG_TYPE_MAP.get(tag_type, 'general'),
                'post_count': _safe_int(item.get('count') or item.get('post_count'), 0),
                'source': 'yandere',
            })
        out.sort(key=lambda x: x.get('post_count', 0), reverse=True)
        return out[:int(limit or 20)]
    except Exception as e:
        logger.warning(f'[Yande.re] tag suggestions failed: {e}')
        return []

def _civitai_normalize_bool_mode(value):
    v = str(value or '').strip().lower().replace('-', '_')
    if v in ('true', '1', 'yes', 'y', 'on', 'adult', 'nsfw', 'r', 'x', 'xxx', 'mature', 'explicit', 'only'):
        return 'nsfw'
    if v in ('false', '0', 'no', 'n', 'off', 'sfw', 'safe', 'general', 'none'):
        return 'sfw'
    if v in ('any', 'all', 'both', 'unset', 'ignore', '*'):
        return 'any'
    if v in ('api', 'default', 'api_default'):
        return 'api_default'
    return ''


def _civitai_sort_value(value):
    sv = str(value or '').strip().replace('_', ' ')
    key = sv.lower().replace(' ', '')
    aliases = {
        'mostreactions': 'Most Reactions', 'reaction': 'Most Reactions', 'reactions': 'Most Reactions',
        'mostcomments': 'Most Comments', 'comment': 'Most Comments', 'comments': 'Most Comments',
        'new': 'Newest', 'newest': 'Newest',
    }
    return aliases.get(key, sv or 'Newest')


def _civitai_period_value(value):
    pv = str(value or '').strip().replace('_', '')
    aliases = {'all': 'AllTime', 'alltime': 'AllTime', 'day': 'Day', 'week': 'Week', 'month': 'Month', 'year': 'Year'}
    return aliases.get(pv.lower(), str(value or '').strip() or 'AllTime')



def _civitai_normalize_search_text(value):
    """Normalize user-entered Civitai search text.

    Civitai users often paste booru-like tags with Chinese punctuation or compact
    variants. Normalize these before tokenizing so strict multi-tag search doesn't
    treat "2girls，sex" as one impossible token.
    """
    s = str(value or '')
    trans = {
        '\u3000': ' ',  # ideographic space
        '，': ',', '、': ',', '；': ',', ';': ',',
        '｜': ' ', '|': ' ',
        '＋': '+',
    }
    for k, v in trans.items():
        s = s.replace(k, v)
    # Common compact booru tag aliases seen in Civitai UI / filenames.
    aliases = {
        'sexfrombehind': 'sex_from_behind',
        'frombehind': 'from_behind',
        'longhair': 'long_hair',
        'bluehair': 'blue_hair',
        'blackhair': 'black_hair',
        'blondehair': 'blonde_hair',
        'whitehair': 'white_hair',
        'redhair': 'red_hair',
        'brownhair': 'brown_hair',
        'greeneyes': 'green_eyes',
        'blueeyes': 'blue_eyes',
        'redeyes': 'red_eyes',
        'browneyes': 'brown_eyes',
    }
    # Only replace whole tokens around comma/space boundaries.
    parts = re.split(r'([\s,]+)', s)
    for i, part in enumerate(parts):
        key = part.strip().lower()
        if key in aliases:
            parts[i] = aliases[key]
    return ''.join(parts)

def _civitai_extract_search_filters(tags: str, rating: str = None):
    raw = str(tags or '').strip()
    tokens = [t.strip() for t in re.split(r'[\n,]+|\s+', raw) if t and str(t).strip()]
    params = {}
    local_terms = []
    tag_terms = []
    model_terms = []
    user_terms = []
    query_terms = []
    structured = []
    # v24: Civitai 默认不做 SFW/NSFW 预置；不写 sfw/nsfw 就等价 any。
    nsfw_mode = 'any'
    local_nsfw_filter = None
    strict_search = None
    favorite_mode = False
    remote_collection = ''

    def set_nsfw_mode(mode):
        nonlocal nsfw_mode, local_nsfw_filter
        mode = str(mode or '').strip().lower()
        if mode in ('sfw', 'safe', 'false', '0'):
            nsfw_mode = 'sfw'
            params['nsfw'] = 'false'
            local_nsfw_filter = False
        elif mode in ('nsfw', 'adult', 'true', '1'):
            nsfw_mode = 'nsfw'
            params['nsfw'] = 'true'
            local_nsfw_filter = True
        elif mode in ('any', 'all'):
            nsfw_mode = 'any'
            params.pop('nsfw', None)
            local_nsfw_filter = None
        else:
            nsfw_mode = 'any'
            params.pop('nsfw', None)
            local_nsfw_filter = None

    for tok in tokens:
        if ':' in tok:
            key, val = tok.split(':', 1)
            key_l = key.strip().lower()
            val = val.strip()
            if key_l in ('civitai', 'source') and val.lower() in ('favorites', 'favs', 'favorite'):
                favorite_mode = True
                structured.append('civitai_favorites')
                continue
            if key_l in ('collection', 'collectionid', 'folder'):
                favorite_mode = True
                remote_collection = val
                structured.append('civitai_collection')
                continue
            if not val and key_l not in ('strict', 'mode', 'search', 'nsfw'):
                continue
            if key_l in ('model', 'modelid'):
                params['modelId'] = val
                structured.append('modelId')
                continue
            if key_l in ('version', 'modelversion', 'modelversionid'):
                params['modelVersionId'] = val
                structured.append('modelVersionId')
                continue
            if key_l in ('post', 'postid'):
                params['postId'] = val
                structured.append('postId')
                continue
            if key_l in ('user', 'username', 'creator'):
                params['username'] = val
                user_terms.append(val)
                local_terms.append(val)
                structured.append('username')
                continue
            if key_l == 'nsfw':
                set_nsfw_mode(val or 'api_default')
                structured.append('nsfw')
                continue
            if key_l == 'sort':
                params['sort'] = _civitai_sort_value(val)
                structured.append('sort')
                continue
            if key_l == 'period':
                params['period'] = _civitai_period_value(val)
                structured.append('period')
                continue
            if key_l in ('tag', 'tags'):
                tag_terms.append(val)
                local_terms.append(val)
                structured.append('tag')
                continue
            if key_l in ('q', 'query', 'prompt', 'text'):
                query_terms.append(val)
                local_terms.append(val)
                structured.append('query')
                continue
            if key_l in ('strict', 'mode', 'search'):
                v = (val or '').strip().lower()
                if key_l == 'strict':
                    strict_search = v not in ('0', 'false', 'no', 'off', 'loose', 'or')
                elif v in ('strict', 'and', 'all', 'must', 'required'):
                    strict_search = True
                elif v in ('loose', 'soft', 'or', 'any'):
                    strict_search = False
                structured.append('search_mode')
                continue
        else:
            tl = tok.lower()
            if tl in ('favorites', 'favs', 'favorite', 'localfav', 'civitai:favorites', 'civitai_favorites'):
                favorite_mode = True
                structured.append('civitai_favorites')
                continue
            if tl in ('sfw', 'safe'):
                set_nsfw_mode('sfw')
                structured.append('nsfw')
                continue
            if tl in ('nsfw', 'adult'):
                set_nsfw_mode('nsfw')
                structured.append('nsfw')
                continue
            if tl in ('any', 'nsfw:any'):
                set_nsfw_mode('any')
                structured.append('nsfw')
                continue
            if tl in ('strict', 'all', 'and', 'must'):
                strict_search = True
                structured.append('search_mode')
                continue
            if tl in ('loose', 'soft', 'or'):
                strict_search = False
                structured.append('search_mode')
                continue
        query_terms.append(tok)
        local_terms.append(tok)

    # v24: Civitai 评级不再从通用 rating 下拉自动推断。
    # 只有搜索框里显式写 sfw / nsfw / any / nsfw:true / nsfw:false 时才过滤。

    # v24: 不再根据关键词或 rating 下拉自动推断 sfw/nsfw。
    # Civitai 的成人/安全过滤只按用户显式输入处理：sfw / nsfw / any / nsfw:true / nsfw:false。

    # 普通词先作为 tag/model 检索候选；模型/API 参数明确时只用于排序，不强制过滤。
    if not tag_terms and query_terms:
        tag_terms.extend(query_terms[:3])
    if not model_terms and query_terms:
        model_terms.extend(query_terms[:3])

    # Civitai 多关键词默认更适合严格模式：当出现 2 个及以上普通词时，默认严格匹配，除非显式 loose。
    if strict_search is None:
        strict_search = len([t for t in local_terms if str(t).strip()]) >= 2

    params.setdefault('sort', 'Newest')
    return {
        'raw': raw,
        'tokens': tokens,
        'params': params,
        'local_terms': local_terms,
        'tag_terms': tag_terms,
        'model_terms': model_terms,
        'user_terms': user_terms,
        'query_terms': query_terms,
        'nsfw_mode': nsfw_mode,
        'local_nsfw_filter': local_nsfw_filter,
        'structured': structured,
        'strict_search': bool(strict_search),
        'favorite_mode': bool(favorite_mode),
        'remote_collection': remote_collection,
        'has_direct_image_filter': any(k in params for k in ('modelId', 'modelVersionId', 'postId', 'username')),
    }


def _civitai_meta_get(meta, *keys):
    if not isinstance(meta, dict):
        return ''
    lower = {str(k).lower(): v for k, v in meta.items()}
    for k in keys:
        if k in meta:
            return meta.get(k) or ''
        lk = str(k).lower()
        if lk in lower:
            return lower.get(lk) or ''
    return ''


def _civitai_try_json_loads(value):
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode('utf-8', errors='ignore')
        except Exception:
            return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Some EXIF/UserComment values contain a binary prefix before the JSON payload and/or
    # trailing bytes after it. raw_decode lets us recover the first valid JSON object.
    json_start = min([x for x in [s.find('{'), s.find('[')] if x >= 0] or [-1])
    if json_start > 0:
        s = s[json_start:]
    try:
        return json.loads(s)
    except Exception:
        pass
    try:
        obj, _ = json.JSONDecoder().raw_decode(s)
        return obj
    except Exception:
        return None


def _civitai_normalize_meta(meta):
    """Civitai/red sometimes returns meta as dict, JSON string, empty string, or nested generation data."""
    if isinstance(meta, dict):
        return meta
    parsed = _civitai_try_json_loads(meta)
    if isinstance(parsed, dict):
        return parsed
    return {}


def _civitai_find_key_recursive(obj, names, max_depth=4):
    names_l = {str(n).lower() for n in names}
    if max_depth < 0:
        return ''
    if isinstance(obj, dict):
        lower_map = {str(k).lower(): v for k, v in obj.items()}
        for name in names_l:
            if name in lower_map and lower_map[name] not in (None, ''):
                v = lower_map[name]
                if isinstance(v, (dict, list)):
                    return json.dumps(v, ensure_ascii=False)
                return str(v)
        for v in obj.values():
            found = _civitai_find_key_recursive(v, names, max_depth=max_depth-1)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj[:20]:
            found = _civitai_find_key_recursive(v, names, max_depth=max_depth-1)
            if found:
                return found
    return ''



def _civitai_extract_prompt_from_structured_metadata(obj, max_depth=5):
    """Extract only real prompt fields from structured Civitai/ComfyUI metadata.

    Prevents dumping an entire ComfyUI workflow JSON as prompt. Handles:
    - Civitai extraMetadata JSON string with prompt/negativePrompt
    - Civitai API/meta dicts
    - embedded ComfyUI workflow nodes with _meta.title Positive/Negative and inputs.text
    """
    obj = _civitai_try_json_loads(obj)
    if not isinstance(obj, (dict, list)):
        return '', '', ''

    def plausible(v):
        return v if _civitai_is_plausible_prompt_text(v) else ''

    # Civitai's extraMetadata often contains the clean prompt/negativePrompt even when
    # the EXIF payload contains a whole ComfyUI workflow.
    if isinstance(obj, dict):
        extra = obj.get('extraMetadata') or obj.get('extra_metadata') or obj.get('generationMetadata')
        parsed_extra = _civitai_try_json_loads(extra)
        if isinstance(parsed_extra, dict):
            p, n, src = _civitai_extract_prompt_from_structured_metadata(parsed_extra, max_depth=max_depth-1)
            if p or n:
                return p, n, 'extraMetadata' + (f':{src}' if src else '')

        p = plausible(_civitai_find_key_recursive(obj, ['prompt', 'positivePrompt', 'positive_prompt', 'positive', 'Prompt'], max_depth=max_depth))
        n = plausible(_civitai_find_key_recursive(obj, ['negativePrompt', 'negative_prompt', 'negative', 'Negative prompt'], max_depth=max_depth))
        # Avoid treating a huge workflow dict or node registry as a prompt. A real prompt should
        # be a prompt-like string, not the serialized workflow object itself.
        if p or n:
            return p, n, 'structured_keys'

        # ComfyUI workflow fallback: find nodes titled Positive/Negative, then use inputs.text.
        pos_texts = []
        neg_texts = []
        for v in obj.values():
            if not isinstance(v, dict):
                continue
            meta = v.get('_meta') if isinstance(v.get('_meta'), dict) else {}
            title = str(meta.get('title') or '').strip().lower()
            inputs = v.get('inputs') if isinstance(v.get('inputs'), dict) else {}
            node_text = inputs.get('text')
            if not _civitai_is_plausible_prompt_text(node_text):
                continue
            if 'negative' in title:
                neg_texts.append(str(node_text))
            elif 'positive' in title:
                pos_texts.append(str(node_text))
        if pos_texts or neg_texts:
            return pos_texts[0] if pos_texts else '', neg_texts[0] if neg_texts else '', 'comfy_workflow_nodes'

    return '', '', ''

def _civitai_parse_parameters_text(text_value):
    """Parse A1111/Forge-style parameter text into prompt/negative/settings best-effort."""
    s = str(text_value or '').strip()
    if not s:
        return {}
    parsed_json = _civitai_try_json_loads(s)
    if isinstance(parsed_json, dict):
        prompt, negative, source = _civitai_extract_prompt_from_structured_metadata(parsed_json)
        return {'prompt': prompt, 'negativePrompt': negative, 'source': source, 'raw': s}

    lower = s.lower()
    neg_marker = 'negative prompt:'
    steps_marker = '\nsteps:'
    prompt = s
    negative = ''
    neg_idx = lower.find(neg_marker)
    if neg_idx >= 0:
        prompt = s[:neg_idx].strip()
        rest = s[neg_idx + len(neg_marker):]
        rest_lower = rest.lower()
        steps_idx = rest_lower.find(steps_marker)
        if steps_idx >= 0:
            negative = rest[:steps_idx].strip()
        else:
            negative = rest.strip()
    else:
        steps_idx = lower.find(steps_marker)
        if steps_idx >= 0:
            prompt = s[:steps_idx].strip()
    return {'prompt': prompt.strip(), 'negativePrompt': negative.strip(), 'raw': s}


def _civitai_extract_prompt_fields_from_item(item, meta=None):
    """Robust prompt extraction from Civitai API item/top-level/meta/generation fields.

    v39: only mark a source when a real prompt/negativePrompt was extracted. Avoid
    reporting api_nested when nested fields exist but are empty or technical metadata.
    """
    if not isinstance(item, dict):
        item = {}
    meta = _civitai_normalize_meta(meta if meta is not None else item.get('meta'))

    candidates = []
    candidates.append(('api_meta', meta))
    for key in ('generation', 'generationData', 'metadata', 'generationMetadata', 'data'):
        if key in item:
            candidates.append(('api_nested', _civitai_normalize_meta(item.get(key))))
    candidates.append(('api_top_level', item))

    def accept_prompt(value):
        return str(value or '').strip() if _civitai_is_plausible_prompt_text(value) else ''

    # Structured extraction handles extraMetadata and ComfyUI workflows without dumping the full JSON.
    for source_name, obj in candidates:
        if not obj:
            continue
        p, n, src = _civitai_extract_prompt_from_structured_metadata(obj)
        p = accept_prompt(p)
        n = accept_prompt(n)
        if p or n:
            return p, n, src or source_name

    # Direct key fallback. Keep this intentionally narrow; broad keys like input/inputs/text
    # caused false api_nested hits on empty/technical objects.
    for source_name, obj in candidates:
        if not isinstance(obj, dict):
            continue
        p = accept_prompt(_civitai_find_key_recursive(obj, ['prompt', 'Prompt', 'positivePrompt', 'positive_prompt', 'positive']))
        n = accept_prompt(_civitai_find_key_recursive(obj, ['negativePrompt', 'Negative prompt', 'negative_prompt', 'negative', 'negativeText']))
        if p or n:
            return p, n, source_name

    # Some metadata is a single A1111/Forge parameter string.
    for source_name, obj in candidates:
        if not isinstance(obj, dict):
            continue
        for key in ('parameters', 'Parameters', 'UserComment', 'comment', 'Description', 'description'):
            if obj.get(key):
                parsed = _civitai_parse_parameters_text(obj.get(key))
                p = accept_prompt(parsed.get('prompt'))
                n = accept_prompt(parsed.get('negativePrompt'))
                if p or n:
                    return p, n, parsed.get('source') or 'api_parameters_text'

    return '', '', ''

def _civitai_is_plausible_prompt_text(value):
    s = str(value or '').strip()
    if not s:
        return False
    if len(s) < 6:
        return False
    # Filter common technical metadata that Pillow exposes as strings/tuples.
    if re.fullmatch(r'[\(\[\{]?\s*[0-9]+(?:\s*[,xX.]\s*[0-9]+){0,4}\s*[\)\]\}]?', s):
        return False
    sl = s.lower()
    if sl in ('none', 'null', 'true', 'false', 'baseline', 'progressive'):
        return False
    if ('"class_type"' in s or '"resource-stack"' in s or '"extraMetadata"' in s) and len(s) > 1000:
        return False
    if sl.startswith('{"resource-stack"') or sl.startswith('{"workflow"'):
        return False
    return True


def _civitai_should_probe_metadata_key(key):
    k = str(key or '').lower()
    # JFIF/ICC/DPI/size fields are technical image metadata, not generation prompts.
    blocked = ('jfif', 'dpi', 'icc', 'exif_offset', 'photoshop', 'adobe', 'gamma', 'duration', 'loop', 'transparency')
    return not any(b in k for b in blocked)


def _civitai_extract_prompt_from_image_url(image_url, timeout=20, max_bytes=16 * 1024 * 1024):
    """Best-effort remote image metadata prompt extraction. Used lazily when API meta is missing."""
    image_url = str(image_url or '').strip()
    if not image_url:
        return {'success': False, 'error': 'empty_image_url'}
    resp = None
    try:
        def request_once(target_url, allow_redirects=False, suppress_credentials=False):
            # Remote image metadata never needs account credentials. Keeping this
            # client credential-free also makes same-origin redirects harmless.
            headers = {
                'User-Agent': DANBOORU_BROWSER_UA,
                'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
                'Referer': CIVITAI_FALLBACK_BASE_URL.rstrip('/') + '/',
            }
            return _request_with_headers(
                'GET', target_url, headers, throttle=_civitai_throttle,
                timeout=timeout, stream=True, allow_redirects=allow_redirects,
                _suppress_credentials=True,
            )

        resp = _safe_fetch_with_allowlist(
            image_url, 'civitai_prompt', request_once, max_redirects=5,
        )
        resp.raise_for_status()
        buf = io.BytesIO()
        total = 0
        for chunk in resp.iter_content(chunk_size=1024 * 128):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                return {'success': False, 'error': f'image_too_large_for_metadata_probe>{max_bytes}'}
            buf.write(chunk)
        buf.seek(0)
        img = Image.open(buf)
        info = {}
        try:
            info.update(getattr(img, 'info', {}) or {})
        except Exception:
            pass
        try:
            exif = img.getexif()
            if exif:
                # Common EXIF tags: 270 ImageDescription, 37510 UserComment, 40092 XPComment.
                for k, v in exif.items():
                    if k in (270, 37510, 40092, 40091, 40093, 40094, 40095):
                        info[f'exif_{k}'] = v
        except Exception:
            pass

        text_blobs = []
        for k, v in info.items():
            if not _civitai_should_probe_metadata_key(k):
                continue
            if isinstance(v, bytes):
                # Strip common EXIF user-comment encoding prefix if present.
                vb = v
                for prefix in (b'UNICODE\x00', b'ASCII\x00\x00\x00', b'JIS\x00\x00\x00\x00\x00'):
                    if vb.startswith(prefix):
                        vb = vb[len(prefix):]
                        break
                try:
                    sv = vb.decode('utf-16', errors='ignore') if b'\x00' in vb[:20] else vb.decode('utf-8', errors='ignore')
                except Exception:
                    sv = vb.decode('latin-1', errors='ignore')
            else:
                sv = str(v)
            if sv and _civitai_is_plausible_prompt_text(sv):
                text_blobs.append((str(k), sv.strip()))

        for k, blob in text_blobs:
            parsed_json = _civitai_try_json_loads(blob)
            if isinstance(parsed_json, dict):
                prompt, negative, src = _civitai_extract_prompt_from_structured_metadata(parsed_json)
                if (_civitai_is_plausible_prompt_text(prompt) or _civitai_is_plausible_prompt_text(negative)):
                    return {
                        'success': True,
                        'prompt': prompt if _civitai_is_plausible_prompt_text(prompt) else '',
                        'negativePrompt': negative if _civitai_is_plausible_prompt_text(negative) else '',
                        'source': f'image_metadata_json:{k}:{src or "structured"}'
                    }
            # Do not allow a raw serialized workflow JSON to become the prompt.
            if isinstance(blob, str) and ('"resource-stack"' in blob or '"class_type"' in blob or '"extraMetadata"' in blob):
                continue
            parsed = _civitai_parse_parameters_text(blob)
            pp = parsed.get('prompt') or ''
            nn = parsed.get('negativePrompt') or ''
            if _civitai_is_plausible_prompt_text(pp) or _civitai_is_plausible_prompt_text(nn):
                return {'success': True, 'prompt': pp if _civitai_is_plausible_prompt_text(pp) else '', 'negativePrompt': nn if _civitai_is_plausible_prompt_text(nn) else '', 'source': f'image_metadata_text:{k}:{parsed.get("source") or "parameters"}'}
        return {'success': False, 'error': 'no_prompt_metadata_in_image'}
    except URLPolicyError as e:
        return {'success': False, 'error': e.code}
    except Exception as e:
        return {'success': False, 'error': _safe_exception_text(e)}
    finally:
        if resp is not None:
            _close_outbound_response(resp)


def _civitai_clean_tag_token(value, max_len=120):
    """Normalize a Civitai tag without assuming ASCII-only tag names."""
    if value is None:
        return ''
    text = html_lib.unescape(str(value)).strip()
    if not text:
        return ''
    text = re.sub(r'\s+', '_', text)
    # Keep unicode word characters plus the punctuation commonly used by booru tags.
    text = re.sub(r'[^\w()\-:.]+', '', text, flags=re.UNICODE)
    return text[:max_len]


def _civitai_prompt_to_tagish(prompt: str, limit=80):
    if not prompt:
        return ''
    parts = []
    seen = set()
    for part in re.split(r'[,;\n]+', str(prompt)):
        cleaned = _civitai_clean_tag_token(part, max_len=80)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            parts.append(cleaned)
        if len(parts) >= limit:
            break
    return ' '.join(parts)


def _civitai_extract_tag_names(item, meta=None, limit=160):
    """Extract tags across Civitai REST and web-search response schema variants.

    Civitai's internal search payload has changed field names over time. Older
    builds only consumed ``tagNames`` which made image results appear normally
    while their tags became empty whenever the field was renamed or nested.
    """
    if not isinstance(item, dict):
        return []

    field_names = (
        'tagNames', 'tag_names', 'tags', 'imageTags', 'image_tags',
        'tagList', 'tag_list', 'tagCollection', 'tag_collection',
    )
    nested_names = (
        'meta', 'metadata', 'generation', 'generationData', 'data',
        'image', 'attributes', 'properties',
    )
    out = []
    seen = set()

    def add(value):
        if len(out) >= limit or value is None:
            return
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return
            if raw[:1] in ('[', '{'):
                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = None
                if parsed is not None:
                    add(parsed)
                    return
            # Civitai sometimes serializes tag arrays as comma/semicolon lists.
            values = re.split(r'[,;|\n]+', raw) if re.search(r'[,;|\n]', raw) else [raw]
            for part in values:
                cleaned = _civitai_clean_tag_token(part)
                key = cleaned.casefold()
                if cleaned and key not in seen:
                    seen.add(key)
                    out.append(cleaned)
                    if len(out) >= limit:
                        return
            return
        if isinstance(value, dict):
            named = value.get('name') or value.get('tag') or value.get('label') or value.get('value') or value.get('title')
            if named is not None:
                add(named)
                return
            for key in field_names:
                if key in value:
                    add(value.get(key))
            return
        if isinstance(value, (list, tuple, set)):
            for entry in value:
                add(entry)
                if len(out) >= limit:
                    return

    containers = [item]
    if isinstance(meta, dict) and meta is not item:
        containers.append(meta)
    for name in nested_names:
        value = item.get(name)
        if isinstance(value, dict) and value not in containers:
            containers.append(value)

    for container in containers:
        if not isinstance(container, dict):
            continue
        for name in field_names:
            if name in container:
                add(container.get(name))
        if len(out) >= limit:
            break
    return out


def _civitai_merge_tag_strings(*groups, limit=260):
    merged = []
    seen = set()
    for group in groups:
        if isinstance(group, str):
            values = group.split()
        elif isinstance(group, (list, tuple, set)):
            values = group
        else:
            continue
        for value in values:
            cleaned = _civitai_clean_tag_token(value)
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                merged.append(cleaned)
                if len(merged) >= limit:
                    return ' '.join(merged)
    return ' '.join(merged)


def _civitai_resource_strings(meta):
    resources = meta.get('resources') if isinstance(meta, dict) else []
    names = []
    versions = []
    types = []
    if isinstance(resources, list):
        for r in resources:
            if isinstance(r, dict):
                name = str(r.get('name') or '').strip()
                version = str(r.get('modelVersionName') or r.get('version') or '').strip()
                typ = str(r.get('type') or '').strip()
                if name:
                    names.append(name)
                if version:
                    versions.append(version)
                if typ:
                    types.append(typ)
    return names, versions, types


def _civitai_item_to_danbooru_shape(item):
    if not isinstance(item, dict):
        return None
    image_url = item.get('url') or item.get('image') or item.get('imageUrl') or ''
    image_url = _absolute_url(image_url) if image_url else ''
    # Civitai search/image.getInfinite often returns a media UUID instead of a full URL.
    # Convert such UUIDs into image.civitai.com URLs before sending them to the frontend proxy.
    if image_url and not re.match(r'^https?://', str(image_url), flags=re.I):
        image_url = _civitai_remote_media_url(item, original=True)
    preview_url = str(item.get('thumbnailUrl') or '').strip()
    if preview_url and not preview_url.startswith('http'):
        preview_url = ''
    if not image_url:
        image_url = _civitai_remote_media_url(item, original=True)
    if not preview_url:
        preview_url = _civitai_remote_media_url(item, width=450)
    large_url = _civitai_remote_media_url(item, width=900) or image_url or preview_url
    if not image_url:
        image_url = large_url or preview_url
    if not image_url and not preview_url:
        return None
    meta = _civitai_normalize_meta(item.get('meta') or {})
    prompt, negative, prompt_source = _civitai_extract_prompt_fields_from_item(item, meta)
    # v43: 不再把文件名当作 prompt。文件名经常是被截断的片段，
    # 会阻止前端继续懒加载真实 Civitai prompt。没有公开 prompt 时保持空输出。
    resource_names, resource_versions, resource_types = _civitai_resource_strings(meta)
    resource_tags = [_civitai_clean_tag_token(value) for value in (resource_names + resource_versions + resource_types)]
    resource_tags = [value for value in resource_tags if value]

    prompt_tags = _civitai_prompt_to_tagish(prompt)
    # v46: support tagNames/tags/imageTags and their nested REST/search variants.
    tag_name_tags = _civitai_extract_tag_names(item, meta=meta, limit=160)
    content_tagish = _civitai_merge_tag_strings(prompt_tags, tag_name_tags)
    tagish = _civitai_merge_tag_strings(content_tagish, resource_tags)
    nsfw_raw = item.get('nsfw')
    if isinstance(nsfw_raw, bool):
        nsfw_bool = nsfw_raw
    else:
        nsfw_bool = str(nsfw_raw or '').strip().lower() in ('true', '1', 'yes', 'y', 'nsfw', 'adult')
    nsfw_level_raw = item.get('nsfwLevel')
    nsfw_level = str(nsfw_level_raw or '').lower()
    try:
        if isinstance(nsfw_level_raw, (int, float)) and nsfw_level_raw >= 2:
            nsfw_bool = True
    except Exception:
        pass
    if nsfw_level in ('x', 'xxx', 'r', 'mature', 'adult', 'explicit'):
        nsfw_bool = True
    rating = 'explicit' if nsfw_bool else 'general'
    width = _safe_int(item.get('width') or _civitai_meta_get(meta, 'width'), 0)
    height = _safe_int(item.get('height') or _civitai_meta_get(meta, 'height'), 0)
    item_id = item.get('imageId') or item.get('id') or item.get('postId') or item.get('url')
    stats = item.get('stats') or {}
    score = 0
    if isinstance(stats, dict):
        score = sum(_safe_int(stats.get(k), 0) for k in ('likeCount', 'heartCount', 'laughCount', 'commentCount'))
    user_info = item.get('user') or {}
    username = item.get('username') or (user_info.get('username') if isinstance(user_info, dict) else '') or ''
    model_name = _civitai_meta_get(meta, 'Model', 'model') or (resource_names[0] if resource_names else '')
    model_version = _civitai_meta_get(meta, 'Model hash', 'modelVersion', 'modelVersionName') or (resource_versions[0] if resource_versions else '')
    seed = _civitai_meta_get(meta, 'seed', 'Seed')
    sampler = _civitai_meta_get(meta, 'sampler', 'Sampler')
    steps = _civitai_meta_get(meta, 'steps', 'Steps')
    cfg = _civitai_meta_get(meta, 'cfgScale', 'CFG scale', 'cfg')
    item_url = f"{CIVITAI_BASE_URL.rstrip('/')}/images/{item_id}" if item_id else image_url
    post_id = item.get('postId')
    post_url = f"{CIVITAI_BASE_URL.rstrip('/')}/posts/{post_id}" if post_id else ''

    normalized = {
        'id': str(item_id),
        'source_site': 'civitai',
        'source': 'civitai',
        'md5': str(item.get('hash') or item_id or int(time.time() * 1000)),
        'created_at': item.get('createdAt') or item.get('publishedAt') or '',
        'score': score,
        'rating': rating,
        'file_ext': str(_file_ext_from_url(image_url, fallback='jpg')).lower(),
        'file_url': image_url,
        'large_file_url': large_url or image_url,
        'preview_file_url': preview_url or large_url or image_url,
        'image_width': width,
        'image_height': height,
        'tag_string': tagish,
        'tag_string_artist': str(username or '').strip().replace(' ', '_'),
        'tag_string_copyright': 'civitai',
        'tag_string_character': '',
        'tag_string_general': tagish,
        'tag_string_meta': 'civitai ' + ('nsfw' if nsfw_bool else 'sfw'),
        'civitai_prompt': str(prompt or ''),
        'civitai_negative_prompt': str(negative or ''),
        'civitai_prompt_source': str(prompt_source or ''),
        'civitai_content_tags': content_tagish,
        'civitai_has_content_tags': bool(content_tagish),
        'civitai_tag_names': tag_name_tags,
        'civitai_meta': meta,
        'civitai_image_id': str(item.get('imageId') or item.get('id') or item_id or ''),
        'civitai_post_id': post_id,
        'civitai_username': username,
        'civitai_nsfw': bool(nsfw_bool),
        'civitai_nsfw_level': nsfw_level_raw,
        'civitai_model': str(model_name or ''),
        'civitai_model_version': str(model_version or ''),
        'civitai_seed': str(seed or ''),
        'civitai_sampler': str(sampler or ''),
        'civitai_steps': str(steps or ''),
        'civitai_cfg': str(cfg or ''),
        'civitai_resources': resource_names,
        'civitai_url': item_url,
        'civitai_post_url': post_url,
        'civitai_api_base': getattr(item, '_civitai_api_base', ''),
    }
    return normalized


def _civitai_nsfw_matches(post, nsfw_filter=None):
    if nsfw_filter is None:
        return True
    return bool(post.get('civitai_nsfw')) is bool(nsfw_filter)


def _civitai_term_variants(term):
    """Return comparable forms for booru-like tags and natural-language Civitai prompts."""
    raw = str(term or '').strip().lower()
    if not raw:
        return []
    variants = []
    def add(v):
        v = str(v or '').strip().lower()
        if v and v not in variants:
            variants.append(v)
    add(raw)
    add(raw.replace('_', ' '))
    add(raw.replace('-', ' '))
    add(raw.replace(' ', '_'))
    add(raw.replace(' ', '-'))
    add(raw.replace('_', '-'))
    add(raw.replace('-', '_'))
    compact = re.sub(r'[\s_\-]+', '', raw)
    add(compact)
    alias_map = {
        'sexfrombehind': ['sex_from_behind', 'sex from behind', 'from_behind', 'from behind'],
        'frombehind': ['from_behind', 'from behind'],
        'longhair': ['long_hair', 'long hair'],
        'bluehair': ['blue_hair', 'blue hair'],
        'blackhair': ['black_hair', 'black hair'],
        'blondehair': ['blonde_hair', 'blonde hair'],
        'whitehair': ['white_hair', 'white hair'],
        'redhair': ['red_hair', 'red hair'],
        'brownhair': ['brown_hair', 'brown hair'],
        'greeneyes': ['green_eyes', 'green eyes'],
        'blueeyes': ['blue_eyes', 'blue eyes'],
        'redeyes': ['red_eyes', 'red eyes'],
        'browneyes': ['brown_eyes', 'brown eyes'],
    }
    for alias in alias_map.get(compact, []):
        add(alias)
        add(alias.replace('_', ' '))
        add(alias.replace(' ', '_'))
    # Civitai tags sometimes pluralize booru tags, e.g. 1girl -> 1girls.
    for v in list(variants):
        if len(v) > 3 and not v.endswith('s'):
            add(v + 's')
        if len(v) > 4 and v.endswith('s'):
            add(v[:-1])
    return variants


def _civitai_match_variant_in_text(term, text):
    """Loose substring/variant match for loose search scoring only."""
    text = str(text or '').lower()
    if not text:
        return False
    normalized_texts = [text]
    text_spaced = re.sub(r'[_\-]+', ' ', text)
    if text_spaced not in normalized_texts:
        normalized_texts.append(text_spaced)
    text_underscored = re.sub(r'[\s\-]+', '_', text)
    if text_underscored not in normalized_texts:
        normalized_texts.append(text_underscored)
    text_compact = re.sub(r'[\s_\-]+', '', text)
    if text_compact not in normalized_texts:
        normalized_texts.append(text_compact)
    for variant in _civitai_term_variants(term):
        if any(variant in h for h in normalized_texts):
            return True
    return False


def _civitai_exact_variants(term):
    """Exact variants used by strict search. No generic substring or plural/singular expansion."""
    raw = str(term or '').strip().lower()
    if not raw:
        return []
    variants = []
    def add(v):
        v = str(v or '').strip().lower()
        if v and v not in variants:
            variants.append(v)
    add(raw)
    add(raw.replace('_', ' '))
    add(raw.replace('-', ' '))
    add(raw.replace(' ', '_'))
    add(raw.replace(' ', '-'))
    compact = re.sub(r'[\s_\-]+', '', raw)
    # Compact aliases are useful for user input like sexfrombehind, but only as full-token/phrase matches.
    alias_map = {
        'sexfrombehind': ['sex from behind', 'sex_from_behind', 'sex-from-behind', 'sexfrombehind'],
        'frombehind': ['from behind', 'from_behind', 'from-behind', 'frombehind'],
        'longhair': ['long hair', 'long_hair', 'long-hair', 'longhair'],
        'bluehair': ['blue hair', 'blue_hair', 'blue-hair', 'bluehair'],
        'blackhair': ['black hair', 'black_hair', 'black-hair', 'blackhair'],
        'blondehair': ['blonde hair', 'blonde_hair', 'blonde-hair', 'blondehair'],
        'whitehair': ['white hair', 'white_hair', 'white-hair', 'whitehair'],
        'redhair': ['red hair', 'red_hair', 'red-hair', 'redhair'],
        'brownhair': ['brown hair', 'brown_hair', 'brown-hair', 'brownhair'],
        'greeneyes': ['green eyes', 'green_eyes', 'green-eyes', 'greeneyes'],
        'blueeyes': ['blue eyes', 'blue_eyes', 'blue-eyes', 'blueeyes'],
        'redeyes': ['red eyes', 'red_eyes', 'red-eyes', 'redeyes'],
        'browneyes': ['brown eyes', 'brown_eyes', 'brown-eyes', 'browneyes'],
    }
    if compact and compact != raw:
        add(compact)
    for alias in alias_map.get(compact, []):
        add(alias)
    return variants


def _civitai_normalize_exact_text(text):
    text = str(text or '').lower()
    text = re.sub(r'[_\-]+', ' ', text)
    text = re.sub(r'[^0-9a-z]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _civitai_exact_match_in_text(term, text):
    """Boundary-based exact match for strict mode.

    This prevents 2girls from matching 2girls1boy and sex from matching sexual.
    Multi-word aliases like sex from behind still work as exact phrases.
    """
    hay = _civitai_normalize_exact_text(text)
    if not hay:
        return False
    tokens = set(hay.split())
    padded = f' {hay} '
    for variant in _civitai_exact_variants(term):
        needle = _civitai_normalize_exact_text(variant)
        if not needle:
            continue
        if ' ' in needle:
            if f' {needle} ' in padded:
                return True
        else:
            if needle in tokens:
                return True
    return False


def _civitai_term_hit_details(post, terms, exact=False):
    terms = [str(t).strip().lower() for t in terms if str(t).strip()]
    if not terms:
        return {'all_match': True, 'matched_terms': [], 'unmatched_terms': [], 'scores': {}, 'total_score': 0}

    prompt = str(post.get('civitai_prompt') or '').lower()
    negative = str(post.get('civitai_negative_prompt') or '').lower()
    tags = str(post.get('tag_string') or '').lower()
    user = str(post.get('civitai_username') or post.get('tag_string_artist') or '').lower()
    model = str(post.get('civitai_model') or '').lower()
    model_version = str(post.get('civitai_model_version') or '').lower()
    resources = ' '.join(str(x) for x in (post.get('civitai_resources') or [])).lower()
    hay_all = ' '.join([prompt, negative, tags, user, model, model_version, resources])

    match_fn = _civitai_exact_match_in_text if exact else _civitai_match_variant_in_text
    matched_terms = []
    unmatched_terms = []
    scores = {}
    total_score = 0

    for t in terms:
        term_score = 0
        if match_fn(t, user) or any(_civitai_normalize_exact_text(v) == _civitai_normalize_exact_text(user) for v in (_civitai_exact_variants(t) if exact else _civitai_term_variants(t))):
            term_score = max(term_score, 45)
        if match_fn(t, model) or match_fn(t, model_version) or match_fn(t, resources):
            term_score = max(term_score, 40)
        if match_fn(t, tags):
            term_score = max(term_score, 30)
        if match_fn(t, prompt):
            term_score = max(term_score, 18)
        if match_fn(t, negative):
            term_score = max(term_score, 5)
        if (term_score <= 0) and match_fn(t, hay_all):
            term_score = 3

        scores[t] = term_score
        if term_score > 0:
            matched_terms.append(t)
            total_score += term_score
        else:
            unmatched_terms.append(t)

    if len(matched_terms) == len(terms):
        total_score += 25

    return {
        'all_match': len(unmatched_terms) == 0,
        'matched_terms': matched_terms,
        'unmatched_terms': unmatched_terms,
        'scores': scores,
        'total_score': total_score,
        'exact': bool(exact),
    }


def _civitai_score_post(post, terms):
    details = _civitai_term_hit_details(post, terms, exact=False)
    return details.get('total_score', 0)


def _civitai_rank_and_filter(posts, local_terms, nsfw_filter=None, strict_terms=False, preserve_order=False):
    scored = []
    for post in posts:
        if not _civitai_nsfw_matches(post, nsfw_filter):
            continue
        details = _civitai_term_hit_details(post, local_terms, exact=bool(strict_terms))
        score = details.get('total_score', 0)
        if strict_terms and local_terms and not details.get('all_match'):
            continue
        scored.append((score, _safe_int(post.get('score'), 0), post))
    if not preserve_order:
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [p for _, __, p in scored]


def _civitai_dedupe_posts(posts):
    seen = set()
    out = []
    for post in posts:
        key = str(post.get('id') or post.get('file_url') or '')
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(post)
    return out


def _civitai_fetch_json(path, params, timeout=25, allow_fallback=True):
    resp = _civitai_api_get(path, params=params, timeout=timeout, allow_fallback=allow_fallback)
    if int(getattr(resp, 'status_code', 0) or 0) != 200:
        raise _legacy_error_from_response('civitai', resp, context='Civitai API')
    try:
        data = resp.json()
    except Exception as exc:
        raise LegacyGalleryError(
            'schema_changed', 502, 'Civitai API 响应无法解析', source='civitai'
        ) from exc
    return data, getattr(resp, '_civitai_base_used', CIVITAI_BASE_URL)


def _civitai_discover_tags(term, limit=12):
    term = str(term or '').strip()
    if not term:
        return []
    key = term.lower()
    hit = _CIVITAI_TAG_DISCOVERY_CACHE.get(key)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    out = []
    try:
        data, base = _civitai_fetch_json('/api/v1/tags', {'limit': max(1, min(limit, 50)), 'query': term}, timeout=12, allow_fallback=True)
        for item in (data.get('items') if isinstance(data, dict) else []) or []:
            if isinstance(item, dict):
                name = str(item.get('name') or '').strip()
                if name:
                    out.append({
                        'name': name,
                        'base': base,
                        'id': item.get('id'),
                        'post_count': _safe_int(item.get('postCount') or item.get('modelCount') or item.get('count'), 0),
                    })
    except Exception as e:
        logger.warning(f"[Civitai] tag discovery failed term={term}: {e}")
    _CIVITAI_TAG_DISCOVERY_CACHE[key] = (time.time(), out)
    return out


def _get_civitai_tag_suggestions(query, limit=20):
    suggestions = []
    for item in _civitai_discover_tags(query, limit=max(1, min(limit, 50))):
        name = _civitai_clean_tag_token(item.get('name'))
        if not name:
            continue
        row = {
            'name': name,
            'category': 0,
            'post_count': _safe_int(item.get('post_count'), 0),
            'aliases': [],
            'source': 'civitai',
        }
        suggestions.append(row)
    return suggestions[:limit]


def _civitai_discover_models(term, username=None, limit=12):
    term = str(term or '').strip()
    username = str(username or '').strip()
    if not term and not username:
        return []
    cache_key = json.dumps({'term': term.lower(), 'username': username.lower(), 'limit': limit}, ensure_ascii=False, sort_keys=True)
    hit = _CIVITAI_MODEL_DISCOVERY_CACHE.get(cache_key)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    attempts = []
    if term:
        attempts.append(('tag', {'limit': max(1, min(limit, 50)), 'tag': term}))
        attempts.append(('query', {'limit': max(1, min(limit, 50)), 'query': term}))
    if username:
        attempts.append(('username', {'limit': max(1, min(limit, 50)), 'username': username}))
    models = []
    seen = set()
    for mode, params in attempts:
        try:
            data, base = _civitai_fetch_json('/api/v1/models', params, timeout=15, allow_fallback=True)
            for item in (data.get('items') if isinstance(data, dict) else []) or []:
                if not isinstance(item, dict):
                    continue
                model_id = item.get('id')
                if not model_id or model_id in seen:
                    continue
                seen.add(model_id)
                models.append({
                    'id': model_id,
                    'name': item.get('name') or '',
                    'type': item.get('type') or '',
                    'nsfw': item.get('nsfw'),
                    'mode': mode,
                    'base': base,
                    'tags': item.get('tags') or [],
                })
                if len(models) >= limit:
                    break
        except Exception as e:
            logger.warning(f"[Civitai] model discovery failed mode={mode} term={term}: {e}")
        if len(models) >= limit:
            break
    _CIVITAI_MODEL_DISCOVERY_CACHE[cache_key] = (time.time(), models)
    return models


def _civitai_get_images_page(params, limit, page, cache_key):
    params = dict(params or {})
    params.setdefault('limit', max(1, min(int(limit or 40), 100)))
    page_i = max(int(page or 1), 1)
    if page_i <= 1:
        _CIVITAI_CURSOR_CACHE.pop(cache_key, None)
    else:
        cursor = _CIVITAI_CURSOR_CACHE.get(cache_key)
        if cursor:
            params['cursor'] = cursor
        else:
            # 旧 Images API 文档仍使用 page/nextPage；没有 cursor 时回退 page，避免滚动第二页直接空。
            params['page'] = page_i
    data, api_base_used = _civitai_fetch_json('/api/v1/images', params=params, timeout=25, allow_fallback=True)
    if not isinstance(data, dict) or not isinstance(data.get('items', []), list):
        raise LegacyGalleryError(
            'schema_changed', 502, 'Civitai images 响应结构异常', source='civitai'
        )
    items = data.get('items') if isinstance(data, dict) else []
    metadata = data.get('metadata') if isinstance(data, dict) else {}
    next_cursor = ''
    next_page = ''
    if isinstance(metadata, dict):
        next_cursor = str(metadata.get('nextCursor') or '')
        next_page = str(metadata.get('nextPage') or '')
    if next_cursor:
        _CIVITAI_CURSOR_CACHE[cache_key] = next_cursor
    elif next_page and page_i >= 1:
        # 有些旧 API 只返回 nextPage，没有 nextCursor。这里以 page 继续作为兜底。
        _CIVITAI_CURSOR_CACHE.pop(cache_key, None)
    else:
        _CIVITAI_CURSOR_CACHE.pop(cache_key, None)
    posts = []
    for item in items or []:
        if isinstance(item, dict):
            item['_civitai_api_base'] = api_base_used
        post = _civitai_item_to_danbooru_shape(item)
        if post:
            post['civitai_api_base'] = api_base_used
            posts.append(post)
    return posts, {'params': params, 'api_base': api_base_used, 'metadata': metadata, 'items': len(items or []), 'next_cursor': bool(next_cursor), 'next_page': bool(next_page)}


def _civitai_multisearch_sort(sort_value):
    sv = str(sort_value or '').strip().lower().replace(' ', '').replace('_', '')
    if sv in ('newest', 'new'):
        return ['createdAt:desc']
    if sv in ('oldest', 'old'):
        return ['createdAt:asc']
    if sv in ('mostreactions', 'reaction', 'reactions', 'mostliked'):
        return ['stats.reactionCountAllTime:desc']
    if sv in ('mostcollected', 'collected'):
        return ['stats.collectedCountAllTime:desc']
    return None


def _civitai_multisearch_headers(query):
    headers = {
        'User-Agent': CIVITAI_HEADERS.get('User-Agent', 'Danbooru-Gallery/1.0'),
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Origin': CIVITAI_BASE_URL,
        'Referer': f'{CIVITAI_BASE_URL}/search/images?query={urllib.parse.quote(str(query or ""))}',
    }
    # search-new.civitai.com currently requires a browser-provided Bearer authorization
    # token / Meilisearch key. Let users paste the multi-search Copy-as-cURL into the
    # existing Civitai Request Headers box; this parser now preserves Authorization.
    try:
        _search_raw, parsed = load_civitai_search_headers()
        if parsed:
            # v37: multi-search 只从独立 SearchAuth 输入读取 search-new 授权。
            # Cookie 留给 civitai.red collection/image.getInfinite，避免相互覆盖和误带。
            for key in ('Authorization', 'X-Meili-API-Key', 'User-Agent', 'Accept-Language', 'x-client', 'x-client-version', 'x-client-date'):
                if parsed.get(key):
                    headers[key] = parsed[key]
    except Exception as e:
        logger.debug(f'[Civitai] multi-search browser header merge skipped: {e}')
    return headers


def _civitai_multisearch_images(plan, limit=40, page=1):
    """Use Civitai's web search index for image/prompt/tag search.

    The public /api/v1/images endpoint has no real tag/query parameter; the web UI uses
    search-new.civitai.com/multi-search with images_v6, whose hits include prompt/tagNames.
    This makes searches like "sex 1girl" work without the old narrow model-candidate pool.
    """
    query = ' '.join(str(x).strip() for x in (plan.get('query_terms') or plan.get('local_terms') or []) if str(x).strip())
    if not query:
        return [], {'label': 'multi_search_images', 'skipped': 'empty_query', 'items': 0}
    # Keep this aligned with the V53 Civitai provider limit.  The web index
    # accepts 200; silently clipping to 100 makes a 200-item request look like
    # a terminal short page and breaks cursor pagination.
    limit_i = max(1, min(int(limit or 40), 200))
    page_i = max(int(page or 1), 1)
    offset = (page_i - 1) * limit_i
    q = {
        'indexUid': 'images_v6',
        'q': query,
        'limit': limit_i,
        'offset': offset,
        # Meilisearch's `all` strategy requires every query term.  Its default
        # `last` strategy progressively drops trailing terms, which matches the
        # gallery's explicit loose-search mode without local re-pagination.
        'matchingStrategy': 'all' if bool(plan.get('strict_search')) else 'last',
    }
    sort = _civitai_multisearch_sort((plan.get('params') or {}).get('sort'))
    if sort:
        q['sort'] = sort
    # Keep filters minimal because Civitai's index filter schema changes more
    # often than q/limit/offset. Strictness is handled above; only the legacy
    # caller applies optional local safety/type filtering, while V53 advertises
    # this endpoint as query-only.
    payload = {'queries': [q]}
    headers = _civitai_multisearch_headers(query)
    resp = _request_with_headers('POST', CIVITAI_SEARCH_URL, headers, throttle=_civitai_throttle, json=payload, timeout=25)
    if resp.status_code != 200:
        raise _legacy_error_from_response('civitai', resp, context='Civitai multi-search')
    try:
        data = resp.json()
    except Exception as exc:
        raise LegacyGalleryError(
            'schema_changed', 502, 'Civitai multi-search 响应无法解析', source='civitai'
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get('results'), list) or not data.get('results'):
        raise LegacyGalleryError(
            'schema_changed', 502, 'Civitai multi-search 响应结构异常', source='civitai'
        )
    results = data.get('results')
    first = results[0]
    if not isinstance(first, dict) or not isinstance(first.get('hits'), list):
        raise LegacyGalleryError(
            'schema_changed', 502, 'Civitai multi-search 响应结构异常', source='civitai'
        )
    hits = first.get('hits')
    estimated_total = None
    if isinstance(first, dict):
        for total_key in ('estimatedTotalHits', 'totalHits', 'total'):
            total_value = first.get(total_key)
            if isinstance(total_value, int) and not isinstance(total_value, bool) and total_value >= 0:
                estimated_total = total_value
                break
    posts = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        # Search can include video hits; this gallery is image-oriented.
        if str(hit.get('type') or '').lower() not in ('', 'image'):
            continue
        hit['_civitai_api_base'] = CIVITAI_BASE_URL
        post = _civitai_item_to_danbooru_shape(hit)
        if post:
            post['civitai_search_source'] = 'multi-search/images_v6'
            posts.append(post)
    return posts, {
        'label': 'multi_search_images',
        'endpoint': CIVITAI_SEARCH_URL,
        'indexUid': 'images_v6',
        'query': query,
        'limit': limit_i,
        'offset': offset,
        'items': len(posts),
        'raw_hits': len(hits or []),
        'estimated_total_hits': estimated_total,
        'matching_strategy': q['matchingStrategy'],
    }


def _get_civitai_images(tags: str, limit: int = 40, page: int = 1, rating: str = None, force_refresh=False):
    global _CIVITAI_LAST_SEARCH_DEBUG
    plan = _civitai_extract_search_filters(tags, rating=rating)
    limit_i = max(1, min(int(limit or 40), 100))
    if plan.get('favorite_mode'):
        page_i = max(int(page or 1), 1)
        enabled, raw_headers, default_collection_id, parsed = load_civitai_remote_favorites_settings()
        calls = []
        remote_failure = None
        # v29: civitai:favorites 优先走远端收藏夹。只要已经保存过 Civitai Cookie/Headers，就尝试远端；
        # enabled 仍控制心形按钮远端写入，但浏览收藏夹不再因为 enabled 状态漏掉远端结果。
        can_try_remote = bool(raw_headers and parsed and parsed.get('Cookie'))
        if can_try_remote:
            try:
                collection_ref = plan.get('remote_collection') or default_collection_id
                filter_terms = plan.get('local_terms') or []
                filter_nsfw = plan.get('local_nsfw_filter')
                needs_filter_fill = bool(filter_terms) or filter_nsfw is not None
                filtered_target = page_i * limit_i
                scan_page = page_i
                scan_calls = []
                scan_limited = False
                while True:
                    remote_posts_raw, call = _civitai_remote_get_collection_posts(
                        collection_ref,
                        limit_i,
                        scan_page,
                        force_refresh=bool(force_refresh and not scan_calls),
                    )
                    remote_posts = _civitai_rank_and_filter(
                        remote_posts_raw,
                        filter_terms,
                        filter_nsfw,
                        strict_terms=bool(plan.get('strict_search')),
                        preserve_order=True,
                    )
                    call = dict(call)
                    call['filter_scan_page'] = scan_page
                    scan_calls.append(call)
                    has_upstream_more = bool(call.get('has_more') or call.get('next_cursor'))
                    if (
                        not needs_filter_fill
                        or len(remote_posts) >= filtered_target
                        or not has_upstream_more
                    ):
                        break
                    if (
                        len(remote_posts_raw) >= _CIVITAI_REMOTE_COLLECTION_MAX_FILTER_SCAN_POSTS
                        or len(scan_calls) >= _CIVITAI_REMOTE_COLLECTION_MAX_BATCHES_PER_CALL
                    ):
                        scan_limited = True
                        break
                    # The current buffer may already cover several 40-item UI
                    # pages (the upstream batch is commonly 100). Jump directly
                    # to the first page boundary that forces one more batch.
                    scan_page = max(
                        scan_page + 1,
                        (len(remote_posts_raw) // limit_i) + 1,
                    )
                remote_total_after_filter = len(remote_posts)
                if call.get('local_pagination'):
                    start = max(0, (page_i - 1) * limit_i)
                    remote_page = remote_posts[start:start + limit_i]
                    call.update({
                        'local_pagination': True,
                        'offset': start,
                        'page_items': len(remote_page),
                        'filtered_total': remote_total_after_filter,
                        'filter_scan_limited': scan_limited,
                    })
                else:
                    remote_page = remote_posts[:limit_i]
                    call.update({
                        'local_pagination': False,
                        'page_items': len(remote_page),
                        'filtered_total': remote_total_after_filter,
                        'filter_scan_limited': scan_limited,
                    })
                scan_calls[-1] = call
                _CIVITAI_LAST_SEARCH_DEBUG = {'plan': plan, 'calls': scan_calls, 'remote_enabled': enabled, 'remote_has_cookie': True, 'result_count': len(remote_page), 'remote_total_after_filter': remote_total_after_filter, 'page': page_i, 'limit': limit_i}
                return json.dumps(remote_page, ensure_ascii=False)
            except Exception as e:
                remote_failure = e
                err = _safe_exception_text(e)
                logger.warning(f"[CivitaiRemoteFavorites] 远端收藏浏览失败，回退本地收藏: {err}")
                calls.append({'label': 'remote_collection', 'error': err[:500], 'remote_enabled': enabled, 'remote_has_cookie': True})
        else:
            calls.append({'label': 'remote_collection_skipped', 'remote_enabled': enabled, 'has_headers': bool(raw_headers), 'parsed_count': len(parsed or {}), 'has_cookie': bool((parsed or {}).get('Cookie'))})

        fav_posts = []
        for item in load_civitai_favorites():
            if isinstance(item, dict):
                fav_posts.append(item)
        fav_posts = _civitai_rank_and_filter(fav_posts, plan.get('local_terms') or [], plan.get('local_nsfw_filter'), strict_terms=bool(plan.get('strict_search')))
        local_total = len(fav_posts)
        start = max(0, (page_i - 1) * limit_i)
        fav_page = fav_posts[start:start + limit_i]
        calls.append({'label': 'local_civitai_favorites', 'items': local_total, 'page_items': len(fav_page), 'offset': start})
        _CIVITAI_LAST_SEARCH_DEBUG = {'plan': plan, 'calls': calls, 'remote_enabled': enabled, 'remote_has_cookie': bool((parsed or {}).get('Cookie')), 'result_count': len(fav_page), 'local_total': local_total, 'page': page_i, 'limit': limit_i}
        # Once page 1 came from the authenticated remote collection, switching a
        # later page to the unrelated local snapshot would splice two datasets and
        # create duplicates/gaps. Only the first page may use the offline fallback.
        if remote_failure is not None and (page_i > 1 or local_total == 0):
            raise _legacy_error_from_exception('civitai', remote_failure, context='Civitai 远端收藏') from remote_failure
        return json.dumps(fav_page, ensure_ascii=False)
    page_i = max(int(page or 1), 1)
    # v31: Civitai 普通搜索统一以网页真实图片搜索端点 multi-search/images_v6 为主。
    # strict / loose 只影响本地过滤规则，不再切回旧的 model-candidate 主流程。
    internal_limit_i = min(100, max(limit_i, 80 if (plan.get('strict_search') and plan.get('local_terms')) else limit_i))
    base_params = dict(plan.get('params') or {})
    base_params.setdefault('limit', internal_limit_i)
    base_params.setdefault('sort', 'Newest')
    posts = []
    debug = {'plan': plan, 'calls': [], 'model_candidates': [], 'tag_candidates': []}
    successful_upstream = False
    last_upstream_error = None

    direct_params = {k: v for k, v in base_params.items() if k in ('limit', 'sort', 'period', 'nsfw', 'modelId', 'modelVersionId', 'postId', 'username')}

    # 1. 结构化直达查询依然优先走官方 Images API。
    if plan.get('has_direct_image_filter'):
        cache_key = json.dumps({'kind': 'direct', 'tags': tags or '', 'rating': rating or '', 'params': direct_params}, sort_keys=True, ensure_ascii=False)
        try:
            direct_posts, call = _civitai_get_images_page(direct_params, internal_limit_i, page_i, cache_key)
            successful_upstream = True
            debug['calls'].append({'label': 'direct_images', **call})
            posts.extend(direct_posts)
        except Exception as e:
            last_upstream_error = e
            debug['calls'].append({'label': 'direct_images', 'error': _safe_exception_text(e), 'params': direct_params})
            logger.warning(f"[Civitai] direct images search failed: {_safe_exception_text(e)}")
    else:
        # 2. 所有普通文本搜索（包含 strict）统一走 multi-search/images_v6。
        try:
            ms_posts, ms_call = _civitai_multisearch_images(plan, internal_limit_i, page_i)
            if not ms_call.get('skipped'):
                successful_upstream = True
            debug['calls'].append(ms_call)
            ms_posts = _civitai_rank_and_filter(ms_posts, plan.get('local_terms') or [], plan.get('local_nsfw_filter'), strict_terms=bool(plan.get('strict_search')))
            posts.extend(ms_posts)
        except Exception as e:
            last_upstream_error = e
            debug['calls'].append({'label': 'multi_search_images', 'error': _safe_exception_text(e)})
            logger.warning(f"[Civitai] multi-search images failed: {_safe_exception_text(e)}")

        # 3. 只有在 multi-search 失败或输入为空时，才回退到公开 Images 最新页。
        should_fallback = (not posts) and (not plan.get('query_terms') or any('error' in (c or {}) for c in debug['calls'] if (c or {}).get('label') == 'multi_search_images'))
        if should_fallback:
            fallback_params = {k: v for k, v in base_params.items() if k in ('limit', 'sort', 'period', 'nsfw')}
            fallback_params['limit'] = internal_limit_i
            cache_key = json.dumps({'kind': 'latest_fallback', 'tags': tags or '', 'rating': rating or '', 'params': fallback_params}, sort_keys=True, ensure_ascii=False)
            try:
                latest_posts, call = _civitai_get_images_page(fallback_params, limit_i, page_i, cache_key)
                successful_upstream = True
                call['label'] = 'latest_prompt_fallback'
                debug['calls'].append(call)
                strict = bool(plan.get('strict_search')) and bool(plan.get('local_terms'))
                latest_posts = _civitai_rank_and_filter(latest_posts, plan.get('local_terms') or [], plan.get('local_nsfw_filter'), strict_terms=strict)
                posts.extend(latest_posts)
            except Exception as e:
                last_upstream_error = e
                debug['calls'].append({'label': 'latest_prompt_fallback', 'error': _safe_exception_text(e), 'params': fallback_params})
                logger.warning(f"[Civitai] fallback images search failed: {_safe_exception_text(e)}")

    if not successful_upstream and last_upstream_error is not None:
        raise _legacy_error_from_exception('civitai', last_upstream_error, context='Civitai 图片浏览') from last_upstream_error

    posts = _civitai_dedupe_posts(posts)
    # 对所有结果再按 prompt/resource/user 命中重排序；v18 严格模式要求所有关键词都命中。
    posts = _civitai_rank_and_filter(posts, plan.get('local_terms') or [], plan.get('local_nsfw_filter'), strict_terms=bool(plan.get('strict_search')))
    posts = posts[:limit_i]
    debug['result_count'] = len(posts)
    debug['page'] = page_i
    debug['limit'] = limit_i
    _CIVITAI_LAST_SEARCH_DEBUG = debug
    logger.info(f"[Civitai] v31 search tags={tags!r} plan={ {k: plan.get(k) for k in ('params','local_terms','query_terms','nsfw_mode','strict_search','has_direct_image_filter')} } calls={len(debug['calls'])} posts={len(posts)}")
    return json.dumps(posts, ensure_ascii=False)

def check_network_connection(source="danbooru"):
    """检测与指定图站的网络/API连接状态。401/403 属于服务端响应，不再粗暴归类为本机断网。"""
    source = (source or "danbooru").lower()
    try:
        if source == "civitai":
            response = _civitai_api_get("/api/v1/images", params={"limit": 1, "sort": "Newest"}, timeout=10, allow_fallback=True)
            return response.status_code in (200, 401, 403), response.status_code == 403 and _is_cloudflare_challenge(response)
        if source == "gelbooru":
            test_url = f"{GELBOORU_BASE_URL}/index.php"
            params = {
                "page": "dapi",
                "s": "post",
                "q": "index",
                "json": "1",
                "limit": "1",
            }
            params.update(_load_gelbooru_auth_params())
            response = _gelbooru_request("GET", test_url, params=params, timeout=10)
            # 200=可用；401=需要 Gelbooru API key；403=上游拦截。都说明网络链路不是断的。
            return response.status_code in (200, 401, 403), False
        if source == "yandere":
            response = _yandere_request("GET", f"{YANDERE_BASE_URL}/post.json", params={"limit": 1}, timeout=10)
            return response.status_code in (200, 401, 403), False

        test_url = f"{DANBOORU_BASE_URL}/posts.json?limit=1"
        response = _danbooru_request("GET", test_url, timeout=10)
        return response.status_code in (200, 401, 403), False
    except requests.exceptions.Timeout:
        logger.error(f"[{source}] 网络连接超时")
        return False, True
    except requests.exceptions.RequestException as e:
        logger.error(f"[{source}] 网络连接失败: {e}")
        return False, True
    except Exception as e:
        logger.error(f"[{source}] 网络检测发生未知错误: {e}")
        return False, True


def verify_danbooru_auth(username, api_key):
    """验证Danbooru用户认证"""
    if not username or not api_key:
        return False, False
    try:
        test_url = f"{DANBOORU_BASE_URL}/profile.json"
        # URL 参数认证比 Basic Auth 更贴近 Danbooru API 页面给出的示例。
        response = _danbooru_request("GET", test_url, params={"login": username, "api_key": api_key}, timeout=15)
        is_valid = response.status_code == 200
        return is_valid, False
    except Exception as e:
        logger.error(f"验证用户认证失败: {e}")
        return False, True


def verify_gelbooru_auth(user_id, api_key):
    """验证 Gelbooru API 认证。"""
    if not user_id or not api_key:
        return False, False
    try:
        test_url = f"{GELBOORU_BASE_URL}/index.php"
        params = {
            "page": "dapi",
            "s": "post",
            "q": "index",
            "json": "1",
            "limit": "1",
            "user_id": str(user_id).strip(),
            "api_key": str(api_key).strip(),
        }
        response = _gelbooru_request("GET", test_url, params=params, timeout=15)
        return response.status_code == 200, False
    except Exception as e:
        logger.error(f"验证 Gelbooru 认证失败: {e}")
        return False, True


# ================================
# Danbooru 诊断系统：只读、不改搜索逻辑
# ================================

_DIAG_UA_CANDIDATES = [
    ("plugin", "Danbooru-Gallery/1.0"),
    ("curl", "curl/8.0.1"),
]


def _diag_mask_secret(value, keep=3):
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return value[:keep] + "…" + value[-keep:]


def _diag_mask_proxy(proxy_url):
    proxy_url = str(proxy_url or "").strip()
    if not proxy_url:
        return ""
    try:
        p = urllib.parse.urlparse(proxy_url)
        host = p.hostname or ""
        port = f":{p.port}" if p.port else ""
        auth = "***@" if (p.username or p.password) else ""
        return urllib.parse.urlunparse((p.scheme or "http", f"{auth}{host}{port}", "", "", "", ""))
    except Exception:
        return _diag_mask_secret(proxy_url, keep=6)


def _diag_sanitize_text(text):
    text = _sanitize_log_text(text, include_configured=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:700]


def _diag_response_test(label, path, params=None, expect="json", use_proxy=True, ua_label="plugin", user_agent="Danbooru-Gallery/1.0", timeout=15, basic_auth=None, auth_method="url_params"):
    """执行单个 Danbooru 诊断请求。不会泄露 api_key。"""
    params = dict(params or {})
    proxy_url = _get_proxy_url() if use_proxy else None
    url = f"{DANBOORU_BASE_URL}{path}"
    session = requests.Session()
    # 诊断时禁用 requests 自动读取环境变量；代理由插件显式解析，结果更可控。
    session.trust_env = False
    proxies = {"http": proxy_url, "https": proxy_url} if (use_proxy and proxy_url) else {}
    headers = dict(DANBOORU_HEADERS)
    headers["User-Agent"] = user_agent
    headers = _apply_danbooru_cookie_headers(headers, url)
    cookie_status = _danbooru_cookie_status()
    browser_headers_status = _danbooru_browser_headers_status()
    if expect == "image":
        headers["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
    else:
        headers["Accept"] = "application/json,text/html;q=0.8,*/*;q=0.5"

    safe_params = {}
    for key, value in params.items():
        if key.lower() == "api_key":
            safe_params[key] = "<present>" if value else "<empty>"
        elif key.lower() == "login":
            safe_params[key] = _diag_mask_secret(value)
        else:
            safe_params[key] = value

    result = {
        "label": label,
        "path": path,
        "params": safe_params,
        "expect": expect,
        "mode": "proxy" if use_proxy else "direct",
        "proxy": _diag_mask_proxy(proxy_url) if use_proxy else "",
        "ua_label": ua_label,
        "user_agent": user_agent,
        "auth_method": auth_method,
        "cookie_mode": "enabled" if (cookie_status.get("enabled") and cookie_status.get("has_cookie")) else "disabled",
        "cookie_has_cf_clearance": bool(cookie_status.get("has_cf_clearance")),
        "browser_headers_mode": "enabled" if (browser_headers_status.get("enabled") and browser_headers_status.get("has_headers")) else "disabled",
        "browser_headers_has_cookie": bool(browser_headers_status.get("has_cookie")),
        "browser_headers_has_cf_clearance": bool(browser_headers_status.get("has_cf_clearance")),
        "browser_headers_has_user_agent": bool(browser_headers_status.get("has_user_agent")),
        "ok": False,
        "category": "unknown",
        "status_code": None,
        "elapsed_ms": None,
        "headers": {},
        "body_snippet": "",
        "error": "",
    }

    start = time.monotonic()
    try:
        resp = session.get(url, params=params, headers=headers, timeout=timeout, proxies=proxies, allow_redirects=True, auth=basic_auth)
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["status_code"] = int(resp.status_code)
        result["headers"] = {
            "server": resp.headers.get("Server", ""),
            "content_type": resp.headers.get("Content-Type", ""),
            "cf_mitigated": resp.headers.get("CF-Mitigated", ""),
            "cf_ray": resp.headers.get("CF-RAY", ""),
            "retry_after": resp.headers.get("Retry-After", ""),
            "www_authenticate": resp.headers.get("WWW-Authenticate", ""),
            "location": resp.headers.get("Location", ""),
        }

        cf = _is_cloudflare_challenge(resp)
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if cf:
            result["category"] = "cloudflare_challenge"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code == 401:
            result["category"] = "auth_api_key"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code == 407:
            result["category"] = "proxy_auth_required"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code == 403:
            result["category"] = "forbidden_permission_or_ip"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code == 429:
            result["category"] = "rate_limited"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code >= 500:
            result["category"] = "upstream_server_error"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code >= 400:
            result["category"] = "http_error"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif expect == "json":
            try:
                resp.json()
                result["ok"] = True
                result["category"] = "ok_json"
            except Exception:
                result["category"] = "unexpected_non_json"
                result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif expect == "image":
            if content_type.startswith("image/") or resp.content[:4] in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\x89PNG") or resp.content[:6] in (b"GIF87a", b"GIF89a"):
                result["ok"] = True
                result["category"] = "ok_image"
            else:
                result["category"] = "unexpected_non_image"
                result["body_snippet"] = _diag_sanitize_text(resp.text if hasattr(resp, "text") else "")
        else:
            result["ok"] = True
            result["category"] = "ok_http"
        return result, resp
    except requests.exceptions.ProxyError as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "proxy_error"
        result["error"] = _diag_sanitize_text(str(e))
        return result, None
    except requests.exceptions.ConnectTimeout as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "connect_timeout"
        result["error"] = _diag_sanitize_text(str(e))
        return result, None
    except requests.exceptions.ReadTimeout as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "read_timeout"
        result["error"] = _diag_sanitize_text(str(e))
        return result, None
    except requests.exceptions.SSLError as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "ssl_error"
        result["error"] = _diag_sanitize_text(str(e))
        return result, None
    except requests.exceptions.RequestException as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "request_error"
        result["error"] = _diag_sanitize_text(str(e))
        return result, None
    except Exception as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "unexpected_exception"
        result["error"] = _diag_sanitize_text(str(e))
        return result, None



def _diag_socket_connect_test(label="direct_socket_tls", host="danbooru.donmai.us", port=443, timeout=8):
    result = {
        "label": label,
        "path": f"{host}:{port}",
        "expect": "tcp_tls",
        "mode": "direct",
        "ok": False,
        "category": "unknown",
        "status_code": None,
        "elapsed_ms": None,
        "headers": {},
        "body_snippet": "",
        "error": "",
        "resolved_addresses": [],
        "tls_version": "",
        "tls_cipher": "",
    }
    start = time.monotonic()
    sock = None
    ssock = None
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addrs = []
        for info in infos:
            try:
                addrs.append(str(info[4][0]))
            except Exception:
                pass
        result["resolved_addresses"] = sorted(set(addrs))[:8]
        sock = socket.create_connection((host, port), timeout=timeout)
        ctx = ssl.create_default_context()
        ssock = ctx.wrap_socket(sock, server_hostname=host)
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["tls_version"] = ssock.version() or ""
        try:
            cipher = ssock.cipher()
            result["tls_cipher"] = cipher[0] if cipher else ""
        except Exception:
            pass
        result["ok"] = True
        result["category"] = "ok_tcp_tls"
    except socket.gaierror as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "dns_error"
        result["error"] = _diag_sanitize_text(str(e))
    except socket.timeout as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "connect_timeout"
        result["error"] = _diag_sanitize_text(str(e))
    except ssl.SSLError as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "ssl_error"
        result["error"] = _diag_sanitize_text(str(e))
    except OSError as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "socket_error"
        result["error"] = _diag_sanitize_text(str(e))
    except Exception as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "unexpected_exception"
        result["error"] = _diag_sanitize_text(str(e))
    finally:
        try:
            if ssock:
                ssock.close()
            elif sock:
                sock.close()
        except Exception:
            pass
    return result


def _diag_proxy_connect_test(label="proxy_connect_tunnel", host="danbooru.donmai.us", port=443, timeout=8):
    proxy_url = _get_proxy_url()
    result = {
        "label": label,
        "path": f"CONNECT {host}:{port}",
        "expect": "proxy_tunnel",
        "mode": "proxy",
        "proxy": _diag_mask_proxy(proxy_url),
        "ok": False,
        "category": "unknown",
        "status_code": None,
        "elapsed_ms": None,
        "headers": {},
        "body_snippet": "",
        "error": "",
    }
    if not proxy_url:
        result["category"] = "skipped_no_proxy"
        result["error"] = "未解析到代理地址。"
        return result
    p = urllib.parse.urlparse(proxy_url)
    if p.scheme and p.scheme.lower().startswith("socks"):
        result["category"] = "skipped_socks_proxy"
        result["error"] = "SOCKS 代理不适合用 HTTP CONNECT 文本握手测试；请看后续 requests/curl_cffi 代理测试。"
        return result
    proxy_host = p.hostname
    proxy_port = p.port or (443 if p.scheme == "https" else 80)
    if not proxy_host:
        result["category"] = "invalid_proxy_url"
        result["error"] = "代理地址无法解析 hostname。"
        return result
    start = time.monotonic()
    sock = None
    try:
        sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
        sock.settimeout(timeout)
        connect_req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\nUser-Agent: Danbooru-Gallery-Diagnostic/1.0\r\nProxy-Connection: Keep-Alive\r\n\r\n"
        sock.sendall(connect_req.encode("ascii", errors="ignore"))
        data = sock.recv(4096)
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        text = data.decode("iso-8859-1", errors="replace")
        result["body_snippet"] = _diag_sanitize_text(text)
        first_line = text.splitlines()[0] if text.splitlines() else ""
        m = re.search(r"HTTP/\d(?:\.\d)?\s+(\d{3})", first_line)
        if m:
            result["status_code"] = int(m.group(1))
        if result["status_code"] == 200:
            result["ok"] = True
            result["category"] = "ok_proxy_tunnel"
        elif result["status_code"] == 407:
            result["category"] = "proxy_auth_required"
        elif result["status_code"]:
            result["category"] = "proxy_connect_rejected"
        else:
            result["category"] = "unexpected_proxy_response"
    except socket.timeout as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "connect_timeout"
        result["error"] = _diag_sanitize_text(str(e))
    except OSError as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "socket_error"
        result["error"] = _diag_sanitize_text(str(e))
    except Exception as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "unexpected_exception"
        result["error"] = _diag_sanitize_text(str(e))
    finally:
        try:
            if sock:
                sock.close()
        except Exception:
            pass
    return result


def _diag_curl_cffi_response_test(label, path, params=None, expect="json", use_proxy=True, timeout=20, auth_method="url_params", impersonate="chrome"):
    params = dict(params or {})
    proxy_url = _get_proxy_url() if use_proxy else None
    url = f"{DANBOORU_BASE_URL}{path}"
    headers = dict(DANBOORU_HEADERS)
    headers["User-Agent"] = DANBOORU_BROWSER_UA
    headers = _apply_danbooru_cookie_headers(headers, url)
    cookie_status = _danbooru_cookie_status()
    browser_headers_status = _danbooru_browser_headers_status()
    headers["Accept"] = "application/json,text/html;q=0.8,*/*;q=0.5" if expect != "image" else "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
    safe_params = {}
    for key, value in params.items():
        if key.lower() == "api_key":
            safe_params[key] = "<present>" if value else "<empty>"
        elif key.lower() == "login":
            safe_params[key] = _diag_mask_secret(value)
        else:
            safe_params[key] = value
    result = {
        "label": label,
        "path": path,
        "params": safe_params,
        "expect": expect,
        "mode": "proxy" if use_proxy else "direct",
        "proxy": _diag_mask_proxy(proxy_url) if use_proxy else "",
        "ua_label": "curl_cffi_chrome",
        "user_agent": DANBOORU_BROWSER_UA,
        "auth_method": auth_method,
        "impersonate": impersonate,
        "cookie_mode": "enabled" if (cookie_status.get("enabled") and cookie_status.get("has_cookie")) else "disabled",
        "cookie_has_cf_clearance": bool(cookie_status.get("has_cf_clearance")),
        "browser_headers_mode": "enabled" if (browser_headers_status.get("enabled") and browser_headers_status.get("has_headers")) else "disabled",
        "browser_headers_has_cookie": bool(browser_headers_status.get("has_cookie")),
        "browser_headers_has_cf_clearance": bool(browser_headers_status.get("has_cf_clearance")),
        "browser_headers_has_user_agent": bool(browser_headers_status.get("has_user_agent")),
        "ok": False,
        "category": "unknown",
        "status_code": None,
        "elapsed_ms": None,
        "headers": {},
        "body_snippet": "",
        "error": "",
    }
    if not _CURL_CFFI_AVAILABLE or curl_cffi_requests is None:
        result["category"] = "optional_client_not_installed"
        result["error"] = "curl_cffi 未安装；这是可选浏览器指纹客户端，不影响普通 requests 诊断。"
        if _CURL_CFFI_IMPORT_ERROR:
            result["error"] += " import_error=" + _diag_sanitize_text(_CURL_CFFI_IMPORT_ERROR)
        return result, None
    proxies = {"http": proxy_url, "https": proxy_url} if (use_proxy and proxy_url) else {}
    start = time.monotonic()
    try:
        resp = _call_curl_cffi_compat(
            curl_cffi_requests.get,
            url,
            clear_proxy_env=not use_proxy,
            params=params,
            headers=headers,
            timeout=timeout,
            proxies=proxies,
            allow_redirects=True,
            impersonate=impersonate,
        )
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["status_code"] = int(resp.status_code)
        result["headers"] = {
            "server": resp.headers.get("Server", ""),
            "content_type": resp.headers.get("Content-Type", ""),
            "cf_mitigated": resp.headers.get("CF-Mitigated", ""),
            "cf_ray": resp.headers.get("CF-RAY", ""),
            "retry_after": resp.headers.get("Retry-After", ""),
            "www_authenticate": resp.headers.get("WWW-Authenticate", ""),
            "location": resp.headers.get("Location", ""),
        }
        cf = _is_cloudflare_challenge(resp)
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if cf:
            result["category"] = "cloudflare_challenge"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code == 401:
            result["category"] = "auth_api_key"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code == 407:
            result["category"] = "proxy_auth_required"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code == 403:
            result["category"] = "forbidden_permission_or_ip"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code == 429:
            result["category"] = "rate_limited"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code >= 500:
            result["category"] = "upstream_server_error"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code >= 400:
            result["category"] = "http_error"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif expect == "json":
            try:
                resp.json()
                result["ok"] = True
                result["category"] = "ok_json"
            except Exception:
                result["category"] = "unexpected_non_json"
                result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif expect == "image":
            if content_type.startswith("image/") or resp.content[:4] in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\x89PNG") or resp.content[:6] in (b"GIF87a", b"GIF89a"):
                result["ok"] = True
                result["category"] = "ok_image"
            else:
                result["category"] = "unexpected_non_image"
                result["body_snippet"] = _diag_sanitize_text(resp.text if hasattr(resp, "text") else "")
        else:
            result["ok"] = True
            result["category"] = "ok_http"
        return result, resp
    except Exception as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        name = type(e).__name__.lower()
        if "timeout" in name:
            result["category"] = "connect_timeout"
        elif "ssl" in name:
            result["category"] = "ssl_error"
        elif "proxy" in name:
            result["category"] = "proxy_error"
        else:
            result["category"] = "request_error"
        result["error"] = _diag_sanitize_text(str(e))
        return result, None

def _diag_extract_image_url_from_posts(resp):
    try:
        data = resp.json()
    except Exception:
        return ""
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        return ""
    post = data[0] or {}
    for key in ("preview_file_url", "large_file_url", "file_url"):
        url = post.get(key)
        if url:
            return str(url)
    media = post.get("media_asset") if isinstance(post, dict) else None
    if isinstance(media, dict):
        for key in ("preview_file_url", "large_file_url", "file_url"):
            url = media.get(key)
            if url:
                return str(url)
    return ""


def _diag_decide_overall(report):
    tests = report.get("tests") or []
    cats = [t.get("category") for t in tests]
    by_label = {t.get("label"): t for t in tests}

    profile_ok = any(t.get("ok") and t.get("expect") == "json" and t.get("path") == "/profile.json" for t in tests)
    posts_ok = any(t.get("ok") and t.get("path") == "/posts.json" for t in tests)
    url_params_ok = any(t.get("ok") and t.get("label") == "posts_search_proxy_url_params" for t in tests)
    basic_auth_tested = any(t.get("label") == "posts_search_proxy_basic_auth_current_node" for t in tests)
    basic_auth_ok = any(t.get("ok") and t.get("label") == "posts_search_proxy_basic_auth_current_node" for t in tests)
    bridge_ok = any(t.get("ok") and t.get("label") == "posts_search_browser_bridge" for t in tests)
    image_tests = [t for t in tests if t.get("expect") == "image"]
    image_failed = bool(image_tests) and not any(t.get("ok") for t in image_tests)

    proxy_problem_cats = {"proxy_error", "proxy_auth_required", "connect_timeout", "read_timeout", "ssl_error", "request_error"}
    proxy_tests = [t for t in tests if t.get("mode") == "proxy"]
    direct_tests = [t for t in tests if t.get("mode") == "direct"]

    if bridge_ok:
        return "browser_bridge_ok", "普通 Python 请求仍失败，但浏览器桥接已经能取得 Danbooru posts.json；可在设置里启用浏览器桥接 fallback 或优先模式。"
    if posts_ok and image_failed:
        return "image_cdn_issue", "Danbooru API 能返回帖子，但图片/CDN 请求失败；问题集中在图片代理、CDN 域名或图片请求头。"
    if url_params_ok and basic_auth_tested and not basic_auth_ok:
        return "auth_method_mismatch", "URL 参数认证可用，但当前节点同款 Basic Auth 测试失败；下一步应只改 D 站认证方式为 login/api_key URL 参数。"
    if posts_ok:
        return "api_ok", "Danbooru posts.json 已返回 JSON；如果画廊仍不显示，问题更可能在前端渲染、缓存或搜索参数。"
    if profile_ok:
        return "profile_ok_posts_failed", "profile.json 认证成功，但 posts.json 搜索失败；账号/API key 基本可用，问题更可能在搜索参数、权限、代理/IP 或 Cloudflare。"
    if any(t.get("category") == "auth_api_key" for t in tests):
        return "auth_api_key_issue", "Danbooru 返回 401；优先检查 login 是否为用户名、API key 是否复制完整、key 是否已重建/失效。"
    if any(t.get("category") == "cloudflare_challenge" for t in proxy_tests):
        direct_network_failed = any(t.get("category") in {"connect_timeout", "read_timeout", "request_error", "ssl_error"} for t in direct_tests)
        direct_cloudflare = any(t.get("category") == "cloudflare_challenge" for t in direct_tests)
        if any(t.get("ok") for t in direct_tests):
            return "proxy_ip_cloudflare_challenge", "走代理时被 Cloudflare challenge，但直连测试可用；当前代理节点/IP 更可疑。"
        if direct_network_failed and direct_cloudflare:
            return "proxy_cloudflare_direct_unstable", "代理出口被 Cloudflare challenge；直连链路同时出现超时/挑战，当前网络出口不稳定或被风控。"
        if direct_network_failed:
            return "proxy_cloudflare_direct_unreachable", "代理出口被 Cloudflare challenge，直连又超时/不可达；当前可行方向是换代理出口，或让浏览器与插件后端使用同一出口后再试 Cookie fallback。"
        if direct_cloudflare:
            return "python_client_cloudflare_challenge", "代理和直连都被 Cloudflare challenge；更像是 Python HTTP 客户端/TLS 指纹或当前网络环境被挑战。"
        return "cloudflare_challenge", "Danbooru 返回 Cloudflare challenge HTML；请求没有进入真正 API。浏览器可用不等于 Python 后端可用。"
    if any(t.get("category") in proxy_problem_cats for t in proxy_tests):
        if any(t.get("ok") for t in direct_tests):
            return "proxy_connection_issue", "代理模式失败但直连成功；检查系统代理端口、代理软件规则或该节点可用性。"
        return "network_or_proxy_issue", "请求在代理/网络层失败；检查 127.0.0.1 代理端口、ComfyUI 启动环境和代理软件连接记录。"
    if any(t.get("category") == "forbidden_permission_or_ip" for t in tests):
        return "forbidden_permission_or_ip", "Danbooru 返回非 Cloudflare 的 403；可能是权限、账号等级、搜索限制、IP 风控或请求参数问题。"
    if any(t.get("category") == "rate_limited" for t in tests):
        return "rate_limited", "Danbooru 返回 429；触发限速，等一段时间再试，或降低刷新/图片并发。"
    return "unknown", "诊断未能归类；查看每个测试的 status_code、category、body_snippet。"


def run_danbooru_diagnostics(tags="rating:general", include_direct=True):
    username, api_key = load_user_auth()
    proxy_url = _get_proxy_url()
    raw_tags = str(tags or "").strip()
    normalized_tags = _normalize_danbooru_query_tags(raw_tags)
    tags = normalized_tags or "rating:general"
    # 诊断默认只取 1 张，避免加重站方请求。
    posts_params = {"limit": 1, "page": 1, "tags": tags}
    public_posts_params = {"limit": 1, "page": 1, "tags": "order:id_desc"}
    auth_params = {}
    if username and api_key:
        auth_params = {"login": username.strip(), "api_key": api_key.strip()}
        posts_params.update(auth_params)

    report = {
        "success": True,
        "source": "danbooru",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "plugin_diagnostic_version": "v1.13-browser-headers",
        "status": "unknown",
        "summary": "",
        "settings": {
            "has_auth": bool(username and api_key),
            "login_masked": _diag_mask_secret(username),
            "api_key_present": bool(api_key),
            "api_key_length": len(api_key or ""),
            "proxy_enabled": load_settings().get("proxy_enabled", True),
            "resolved_proxy": _diag_mask_proxy(proxy_url),
            "tested_tags_raw": raw_tags,
            "tested_tags": tags,
            "tag_separator_normalized": bool(raw_tags and raw_tags != tags),
            "curl_cffi_available": bool(_CURL_CFFI_AVAILABLE),
            "danbooru_cookie_enabled": _danbooru_cookie_status().get("enabled"),
            "danbooru_cookie_present": _danbooru_cookie_status().get("has_cookie"),
            "danbooru_cookie_has_cf_clearance": _danbooru_cookie_status().get("has_cf_clearance"),
            "danbooru_browser_headers_enabled": _danbooru_browser_headers_status().get("enabled"),
            "danbooru_browser_headers_present": _danbooru_browser_headers_status().get("has_headers"),
            "danbooru_browser_headers_has_cookie": _danbooru_browser_headers_status().get("has_cookie"),
            "danbooru_browser_headers_has_cf_clearance": _danbooru_browser_headers_status().get("has_cf_clearance"),
            "danbooru_browser_headers_has_user_agent": _danbooru_browser_headers_status().get("has_user_agent"),
            "browser_bridge": load_browser_bridge_settings(),
            "browser_bridge_playwright_available": _browser_bridge_import_status()[0],
        },
        "tests": [],
        "notes": [
            "诊断不会返回完整 API key，也不会修改 Gelbooru 逻辑。",
            "HTTP 200 Connection established 只代表代理隧道建立，不代表 Danbooru API 成功。",
            "Danbooru 查询标签使用空格分隔；本版会把逗号分隔的提示词兼容转换为空格分隔。",
            "v1.5 起实际 Danbooru GET 请求在 requests 遇到 Cloudflare challenge 时，会优先尝试可选 curl_cffi Chrome 指纹客户端；未安装 curl_cffi 时自动跳过。",
            "v1.6 增加可选 Danbooru Cookie fallback：只读取本地设置中的 Cookie，不会在诊断文本里输出完整 Cookie。",
            "v1.10 起导出日志会附带前端保存的完整 D诊断/D浏览器诊断报告；同时不再向 curl_cffi 传入 trust_env 参数，兼容旧版 curl_cffi。",
            "直连 curl_cffi 测试会临时清理代理环境变量并传入空 proxies，尽量避免被系统代理污染。",
            "v1.12 增加可选浏览器桥接：通过本机 Chrome/Edge 的 CDP 调试端口读取 Danbooru JSON，需用户自行启动调试浏览器并通过 Cloudflare。",
            "v1.13 增加更轻量的浏览器请求头模式：可粘贴 DevTools Request Headers / Copy as cURL，用同一浏览器会话的 Cookie、User-Agent 和 Client Hints 尝试请求。",
        ],
    }
    if _CURL_CFFI_IMPORT_ERROR:
        report["settings"]["curl_cffi_import_error"] = _diag_sanitize_text(_CURL_CFFI_IMPORT_ERROR)

    def add(result):
        report["tests"].append(result)
        return result

    # 0) 传输层基础测试：区分 DNS/TCP/TLS、代理隧道、上游 Cloudflare 三类问题。
    add(_diag_socket_connect_test())
    if proxy_url:
        add(_diag_proxy_connect_test())

    # 1) 根页面：区分基础访问/代理层问题。
    root_test, _ = _diag_response_test("site_root_proxy", "/", params={}, expect="html", use_proxy=True, timeout=12)
    add(root_test)

    # 1b) posts.json 公共基线：不用账号、不带复杂标签，判断是不是搜索参数/账号之外的问题。
    public_posts_test, public_posts_resp = _diag_response_test("posts_public_proxy_order_id_desc", "/posts.json", params=public_posts_params, expect="json", use_proxy=True, timeout=15, auth_method="none")
    add(public_posts_test)

    # 2) profile.json：认证专测。无 auth 时跳过，避免误导。
    if username and api_key:
        profile_test, _ = _diag_response_test("profile_auth_proxy", "/profile.json", params=dict(auth_params), expect="json", use_proxy=True, timeout=15)
        add(profile_test)
    else:
        add({
            "label": "profile_auth_proxy",
            "path": "/profile.json",
            "expect": "json",
            "mode": "proxy",
            "ok": False,
            "category": "skipped_no_auth",
            "status_code": None,
            "error": "未配置 Danbooru login/api_key，无法验证账号认证。",
        })

    # 3) posts.json：画廊搜索核心请求。URL 参数认证贴近 Danbooru API 页面示例。
    posts_test, posts_resp = _diag_response_test("posts_search_proxy_url_params", "/posts.json", params=posts_params, expect="json", use_proxy=True, timeout=15, auth_method="url_params")
    add(posts_test)

    # 3b) 当前节点主逻辑使用 Basic Auth；单独测试，方便判断“API key 可用但节点认证方式不匹配”。
    basic_posts_resp = None
    if username and api_key:
        basic_params = {"limit": 1, "page": 1, "tags": tags}
        basic_test, basic_posts_resp = _diag_response_test(
            "posts_search_proxy_basic_auth_current_node",
            "/posts.json",
            params=basic_params,
            expect="json",
            use_proxy=True,
            timeout=15,
            basic_auth=HTTPBasicAuth(username.strip(), api_key.strip()),
            auth_method="basic_auth",
        )
        add(basic_test)

    # 4) UA 对照：仅在默认 UA 被 CF challenge 时，用 curl UA 再试一次，帮助判断“假浏览器 UA/TLS”问题。
    if posts_test.get("category") == "cloudflare_challenge":
        curl_test, _ = _diag_response_test("posts_search_proxy_curl_ua", "/posts.json", params=posts_params, expect="json", use_proxy=True, ua_label="curl", user_agent="curl/8.0.1", timeout=15, auth_method="url_params")
        add(curl_test)

    # 4b) 可选浏览器指纹客户端：有人成功通常是网络/IP + HTTP/TLS 指纹一起满足。
    cffi_posts_resp = None
    if posts_test.get("category") in ("cloudflare_challenge", "connect_timeout", "read_timeout", "request_error") or public_posts_test.get("category") == "cloudflare_challenge":
        cffi_test, cffi_posts_resp = _diag_curl_cffi_response_test("posts_search_proxy_curl_cffi_chrome", "/posts.json", params=posts_params, expect="json", use_proxy=True, timeout=20, auth_method="url_params", impersonate="chrome")
        add(cffi_test)

    # 5) 直连对照：有系统代理时才做，防止误以为代理就是唯一出口。
    if include_direct and proxy_url:
        direct_posts_test, direct_resp = _diag_response_test("posts_search_direct_url_params", "/posts.json", params=posts_params, expect="json", use_proxy=False, timeout=15, auth_method="url_params")
        add(direct_posts_test)
        if username and api_key:
            direct_profile_test, _ = _diag_response_test("profile_auth_direct", "/profile.json", params=dict(auth_params), expect="json", use_proxy=False, timeout=15, auth_method="url_params")
            add(direct_profile_test)
        if direct_posts_test.get("category") in ("cloudflare_challenge", "connect_timeout", "read_timeout", "request_error"):
            direct_cffi_test, direct_cffi_resp = _diag_curl_cffi_response_test("posts_search_direct_curl_cffi_chrome", "/posts.json", params=posts_params, expect="json", use_proxy=False, timeout=20, auth_method="url_params", impersonate="chrome")
            add(direct_cffi_test)
            if direct_resp is None and direct_cffi_resp is not None:
                direct_resp = direct_cffi_resp
    else:
        direct_resp = None

    # 5b) 可选真实浏览器桥接：只在用户启用后测试，避免未授权连接本机浏览器。
    bridge_settings = load_browser_bridge_settings()
    bridge_resp = None
    if bridge_settings.get("enabled"):
        bridge_test = {
            "label": "posts_search_browser_bridge",
            "path": "/posts.json",
            "expect": "json",
            "mode": "browser_bridge",
            "cdp_url": bridge_settings.get("cdp_url"),
            "ok": False,
            "category": "unknown",
            "status_code": None,
            "elapsed_ms": None,
            "error": "",
        }
        bridge_start = time.monotonic()
        try:
            bridge_resp = _browser_bridge_fetch_json("/posts.json", params=posts_params, timeout_ms=bridge_settings.get("timeout_ms"), cdp_url=bridge_settings.get("cdp_url"), label="diagnose_posts")
            bridge_test["elapsed_ms"] = int((time.monotonic() - bridge_start) * 1000)
            bridge_test["status_code"] = int(bridge_resp.status_code or 0)
            try:
                bridge_data = bridge_resp.json()
                bridge_test["ok"] = isinstance(bridge_data, list)
                bridge_test["category"] = "ok_json" if bridge_test["ok"] else "json_not_list"
                bridge_test["post_count"] = len(bridge_data) if isinstance(bridge_data, list) else None
                bridge_test["sample_post_id"] = bridge_data[0].get("id") if isinstance(bridge_data, list) and bridge_data and isinstance(bridge_data[0], dict) else None
            except Exception as e:
                bridge_test["category"] = "json_parse_error"
                bridge_test["error"] = _diag_sanitize_text(str(e))
        except Exception as e:
            bridge_test["elapsed_ms"] = int((time.monotonic() - bridge_start) * 1000)
            msg = _diag_sanitize_text(str(e))
            bridge_test["error"] = msg
            low = msg.lower()
            if "未安装" in msg or "playwright" in low and "not" in low:
                bridge_test["category"] = "playwright_not_installed"
            elif "connect" in low or "refused" in low or "ecconnrefused" in low:
                bridge_test["category"] = "cdp_connection_failed"
            elif "cloudflare" in low or "just a moment" in low:
                bridge_test["category"] = "browser_bridge_cloudflare_challenge"
            elif "timeout" in low:
                bridge_test["category"] = "browser_bridge_timeout"
            else:
                bridge_test["category"] = "browser_bridge_error"
        add(bridge_test)

    # 6) 图片/CDN 对照：只有 posts JSON 成功后才测。
    image_url = ""
    resp_for_image = posts_resp if posts_test.get("ok") else None
    if not resp_for_image and 'cffi_posts_resp' in locals() and cffi_posts_resp is not None:
        try:
            if any(t.get("label") == "posts_search_proxy_curl_cffi_chrome" and t.get("ok") for t in report["tests"]):
                resp_for_image = cffi_posts_resp
        except Exception:
            pass
    if not resp_for_image and 'direct_resp' in locals() and direct_resp is not None:
        # 直连成功但代理失败时，也尝试用直连返回的 post 测图，便于归类。
        try:
            if any(t.get("label") == "posts_search_direct_url_params" and t.get("ok") for t in report["tests"]):
                resp_for_image = direct_resp
        except Exception:
            pass
    if not resp_for_image and 'bridge_resp' in locals() and bridge_resp is not None:
        try:
            if any(t.get("label") == "posts_search_browser_bridge" and t.get("ok") for t in report["tests"]):
                resp_for_image = bridge_resp
        except Exception:
            pass
    if resp_for_image is not None:
        image_url = _diag_extract_image_url_from_posts(resp_for_image)
    if image_url:
        try:
            p = urllib.parse.urlparse(image_url)
            image_path_for_report = p.netloc + p.path
        except Exception:
            image_path_for_report = "<image_url>"
        # _diag_response_test 只能拼 DANBOORU_BASE_URL；cdn.donmai.us 等外链走专用图片测试。
        if image_url.startswith(DANBOORU_BASE_URL):
            img_test, _ = _diag_response_test("image_cdn_proxy", image_url.replace(DANBOORU_BASE_URL, ""), params={}, expect="image", use_proxy=True, timeout=20)
        else:
            img_test, _ = _diag_external_image_test(image_url, use_proxy=True)
        img_test["image_path"] = image_path_for_report
        add(img_test)
    else:
        add({
            "label": "image_cdn_proxy",
            "path": "<from first post>",
            "expect": "image",
            "mode": "proxy",
            "ok": False,
            "category": "skipped_no_post_json",
            "status_code": None,
            "error": "posts.json 未返回可解析 JSON，无法继续测试图片/CDN。",
        })

    status, summary = _diag_decide_overall(report)
    report["status"] = status
    report["summary"] = summary
    return report


def _diag_external_image_test(image_url, use_proxy=True):
    proxy_url = _get_proxy_url() if use_proxy else None
    session = requests.Session()
    session.trust_env = False
    proxies = {"http": proxy_url, "https": proxy_url} if (use_proxy and proxy_url) else {}
    headers = dict(DANBOORU_HEADERS)
    headers.update({"Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8", "Referer": DANBOORU_BASE_URL + "/"})
    result = {
        "label": "image_cdn_proxy",
        "path": urllib.parse.urlparse(image_url).netloc + urllib.parse.urlparse(image_url).path,
        "params": {},
        "expect": "image",
        "mode": "proxy" if use_proxy else "direct",
        "proxy": _diag_mask_proxy(proxy_url) if use_proxy else "",
        "ua_label": "plugin",
        "user_agent": headers.get("User-Agent"),
        "ok": False,
        "category": "unknown",
        "status_code": None,
        "elapsed_ms": None,
        "headers": {},
        "body_snippet": "",
        "error": "",
    }
    start = time.monotonic()
    try:
        def request_once(target_url, allow_redirects=False, suppress_credentials=False):
            request_headers = (
                _strip_credential_headers(headers) if suppress_credentials else dict(headers)
            )
            request_session = session
            if suppress_credentials:
                request_session = requests.Session()
                request_session.trust_env = False
            try:
                response = request_session.get(
                    target_url,
                    headers=request_headers,
                    timeout=20,
                    proxies=proxies,
                    allow_redirects=allow_redirects,
                )
            except Exception:
                if request_session is not session:
                    request_session.close()
                raise
            if request_session is not session:
                response._outbound_ephemeral_session = request_session
            return response

        resp = _safe_fetch_with_allowlist(
            image_url, "danbooru_media", request_once, max_redirects=5,
        )
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["status_code"] = int(resp.status_code)
        result["headers"] = {
            "server": resp.headers.get("Server", ""),
            "content_type": resp.headers.get("Content-Type", ""),
            "cf_mitigated": resp.headers.get("CF-Mitigated", ""),
            "cf_ray": resp.headers.get("CF-RAY", ""),
            "retry_after": resp.headers.get("Retry-After", ""),
        }
        if _is_cloudflare_challenge(resp):
            result["category"] = "cloudflare_challenge"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code == 200 and (resp.headers.get("Content-Type", "").lower().startswith("image/") or resp.content[:4] in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\x89PNG")):
            result["ok"] = True
            result["category"] = "ok_image"
        elif resp.status_code == 403:
            result["category"] = "forbidden_permission_or_ip"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        elif resp.status_code == 401:
            result["category"] = "auth_api_key"
            result["body_snippet"] = _diag_sanitize_text(resp.text)
        else:
            result["category"] = "http_error" if resp.status_code >= 400 else "unexpected_non_image"
            result["body_snippet"] = _diag_sanitize_text(resp.text if hasattr(resp, "text") else "")
        return result, resp
    except URLPolicyError as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "url_policy_rejected"
        result["error"] = e.code
        return result, None
    except requests.exceptions.RequestException as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "request_error"
        result["error"] = _diag_sanitize_text(str(e))
        return result, None
    except Exception as e:
        result["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        result["category"] = "unexpected_exception"
        result["error"] = _diag_sanitize_text(str(e))
        return result, None


def get_user_favorites(username, api_key):
    """获取用户的 Danbooru 收藏列表"""
    try:
        favorites_url = f"{DANBOORU_BASE_URL}/favorites.json"
        response = _danbooru_request("GET", favorites_url, auth=HTTPBasicAuth(username, api_key), timeout=15)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        logger.error(f"获取用户收藏列表失败: {e}")
        return []


def _danbooru_extract_username(profile_data):
    if isinstance(profile_data, dict):
        for key in ("name", "username", "login"):
            value = str(profile_data.get(key) or "").strip()
            if value:
                return value
        user = profile_data.get("user")
        if isinstance(user, dict):
            return _danbooru_extract_username(user)
    return ""


def _danbooru_extract_user_id(profile_data):
    if isinstance(profile_data, dict):
        value = profile_data.get("id")
        if value is not None and str(value).strip():
            return str(value).strip()
        user = profile_data.get("user")
        if isinstance(user, dict):
            return _danbooru_extract_user_id(user)
    return ""


def _danbooru_extract_favorite_post_ids(payload):
    if isinstance(payload, dict):
        for key in ("favorites", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                payload = value
                break
        else:
            payload = [payload]
    if not isinstance(payload, list):
        return []

    ids = []
    seen = set()
    for item in payload:
        post_id = None
        if isinstance(item, dict):
            for key in ("post_id", "postId"):
                value = item.get(key)
                if value is not None and str(value).strip():
                    post_id = str(value).strip()
                    break
            if post_id is None and isinstance(item.get("post"), dict):
                value = item["post"].get("id")
                if value is not None and str(value).strip():
                    post_id = str(value).strip()
            if post_id is None and any(k in item for k in ("file_url", "large_file_url", "preview_file_url", "tag_string")):
                value = item.get("id")
                if value is not None and str(value).strip():
                    post_id = str(value).strip()
        elif item is not None and str(item).strip().isdigit():
            post_id = str(item).strip()
        if post_id and post_id not in seen:
            seen.add(post_id)
            ids.append(post_id)
    return ids


def _danbooru_filter_favorites_for_user(payload, user_id):
    if not user_id:
        return payload
    if isinstance(payload, dict):
        for key in ("favorites", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                filtered = _danbooru_filter_favorites_for_user(value, user_id)
                clone = dict(payload)
                clone[key] = filtered
                return clone
        return payload
    if not isinstance(payload, list):
        return payload
    filtered = []
    saw_user_id = False
    for item in payload:
        if not isinstance(item, dict):
            filtered.append(item)
            continue
        value = item.get("user_id")
        if value is None:
            filtered.append(item)
            continue
        saw_user_id = True
        if str(value).strip() == str(user_id):
            filtered.append(item)
    return filtered if saw_user_id else payload


def _danbooru_bridge_fetch_favorite_ids(max_pages=5, limit=200):
    """Read the signed-in user's Danbooru favorite post IDs through bridge Chrome."""
    profile_resp = _danbooru_bridge_fetch("/profile.json", label="danbooru_profile")
    if profile_resp.status_code in (401, 403):
        raise RuntimeError("D 登录态不可用或已过期，请点“打开/切到 D 登录”后重新保存当前登录态")
    if profile_resp.status_code < 200 or profile_resp.status_code >= 300:
        raise RuntimeError(f"D 登录态验证失败，状态码: {profile_resp.status_code}")
    try:
        profile_data = profile_resp.json()
    except Exception as e:
        raise RuntimeError(f"D 登录态验证没有返回有效 JSON: {_safe_exception_text(e)}") from e

    username = _danbooru_extract_username(profile_data)
    if not username:
        raise RuntimeError("D 登录态验证成功，但无法读取当前用户名；请确认打开的是已登录的 /profile 页面")
    user_id = _danbooru_extract_user_id(profile_data)

    all_ids = []
    seen = set()
    pages_loaded = 0
    for page in range(1, max(1, int(max_pages)) + 1):
        params = {
            "limit": max(1, min(int(limit), 200)),
            "page": page,
            "search[user_name]": username,
        }
        resp = _danbooru_bridge_fetch("/favorites.json", params=params, label=f"danbooru_favorites_page_{page}")
        if resp.status_code in (401, 403):
            raise RuntimeError("D 收藏读取失败：登录态不可用或已过期，请重新打开 D 登录并保存当前登录态")
        if resp.status_code < 200 or resp.status_code >= 300:
            raise RuntimeError(f"D 收藏读取失败，状态码: {resp.status_code}")
        try:
            payload = resp.json()
        except Exception as e:
            raise RuntimeError(f"D 收藏读取没有返回有效 JSON: {_safe_exception_text(e)}") from e
        payload = _danbooru_filter_favorites_for_user(payload, user_id)
        page_ids = _danbooru_extract_favorite_post_ids(payload)
        for post_id in page_ids:
            if post_id not in seen:
                seen.add(post_id)
                all_ids.append(post_id)
        pages_loaded += 1
        item_count = len(payload) if isinstance(payload, list) else len(page_ids)
        if item_count < params["limit"]:
            break
    return all_ids, {"username": username, "user_id": user_id, "pages_loaded": pages_loaded, "limit": max(1, min(int(limit), 200))}


@PromptServer.instance.routes.post("/danbooru_gallery/favorites/add")
async def add_favorite(request):
    """添加收藏"""
    try:
        data = await request.json()
        post_id = data.get("post_id")
        source = str(data.get("source") or "danbooru").lower()

        if not post_id:
            return web.json_response({"success": False, "error": "缺少post_id"})

        if source == "civitai":
            post_data = data.get("post_data") if isinstance(data.get("post_data"), dict) else {}
            if not post_data:
                post_data = {"id": str(post_id), "source": "civitai", "source_site": "civitai"}
            post_data["id"] = str(post_data.get("id") or post_id)
            post_data["source"] = "civitai"
            post_data["source_site"] = "civitai"
            remote_result = None
            remote_error = ""
            try:
                enabled, raw_headers, _, parsed = load_civitai_remote_favorites_settings()
                if enabled and raw_headers and parsed:
                    remote_result = _civitai_remote_save_item(post_id, remove=False)
                    post_data["civitai_remote_favorited"] = True
                    post_data["civitai_remote_collection_id"] = str((remote_result.get("collection") or {}).get("id") or "")
                    post_data["civitai_remote_collection_name"] = str((remote_result.get("collection") or {}).get("name") or "")
            except Exception as e:
                remote_error = _safe_exception_text(e)
                logger.warning(f"[CivitaiRemoteFavorites] 远端收藏失败，回退本地收藏: {remote_error}")

            favs = load_civitai_favorites()
            key = _civitai_favorite_key(post_data)
            existing = [_civitai_favorite_key(x) for x in favs if isinstance(x, dict)]
            if key and key not in existing:
                favs.append(post_data)
                save_civitai_favorites(favs)
            return web.json_response({
                "success": True,
                "message": "Civitai 远端收藏成功" if remote_result else "Civitai 本地收藏成功（远端未启用或失败）",
                "remote": "ok" if remote_result else "fallback_local",
                "remote_error": remote_error,
                "collection": (remote_result or {}).get("collection") if remote_result else None,
            })

        username, api_key = load_user_auth()
        if not username or not api_key:
            try:
                response = _danbooru_bridge_favorite_request(post_id, remove=False)
                if response.status_code in [200, 201, 204]:
                    favorites = load_favorites()
                    if str(post_id) not in favorites:
                        favorites.append(str(post_id))
                        save_favorites(favorites)
                    return web.json_response({"success": True, "message": "收藏成功（浏览器登录态）"})
                if response.status_code == 422 and "already favorited" in response.text.lower():
                    favorites = load_favorites()
                    if str(post_id) not in favorites:
                        favorites.append(str(post_id))
                        save_favorites(favorites)
                    return web.json_response({"success": True, "message": "已收藏，无需重复操作"})
                if response.status_code in (401, 403):
                    return web.json_response({"success": False, "error": "D 登录态不可用或已过期，请点“打开/切到 D 登录”后重新保存当前登录态"})
                return web.json_response({"success": False, "error": f"收藏失败，浏览器登录态返回状态码: {response.status_code}"})
            except Exception as e:
                return web.json_response({"success": False, "error": f"请先配置用户名/API Key，或使用 D 登录按钮保存浏览器登录态：{_safe_exception_text(e)[:180]}"})

        # 验证认证
        is_valid, is_network_error = verify_danbooru_auth(username, api_key)
        if is_network_error:
            return web.json_response({"success": False, "error": "网络错误，无法连接到Danbooru服务器"})
        if not is_valid:
            return web.json_response({"success": False, "error": "认证无效，请检查用户名和API Key"})

        try:
            favorite_url = f"{BASE_URL}/favorites.json"
            response = _danbooru_request(
                "POST",
                favorite_url,
                auth=HTTPBasicAuth(username, api_key),
                data={"post_id": post_id},
                timeout=15,
            )


            if response.status_code in [200, 201]:
                favorites = load_favorites()
                if str(post_id) not in favorites:
                    favorites.append(str(post_id))
                    save_favorites(favorites)
                return web.json_response({"success": True, "message": "收藏成功"})
            
            try:
                error_data = response.json()
                reason = error_data.get("reason", "未知")
                message = error_data.get("message", "没有提供具体信息")
            except (json.JSONDecodeError, ValueError):
                error_data = {}
                reason = "无法解析响应"
                message = response.text

            if response.status_code == 422 and "You have already favorited this post" in message:
                favorites = load_favorites()
                if str(post_id) not in favorites:
                    favorites.append(str(post_id))
                    save_favorites(favorites)
                return web.json_response({"success": True, "message": "已收藏，无需重复操作"})
                
            error_map = {
                401: "认证失败，请检查用户名和API Key",
                403: "权限不足，可能需要Gold账户或更高权限",
                404: "图片不存在",
                429: "请求过于频繁，请稍后重试 (Rate Limited)",
            }
            
            error_message = error_map.get(response.status_code, f"收藏失败，状态码: {response.status_code}, 原因: {message}")
            logger.error(error_message)
            return web.json_response({"success": False, "error": error_message})

        except requests.exceptions.Timeout:
            logger.error("添加收藏时网络请求超时")
            return web.json_response({"success": False, "error": "网络请求超时"})
        except requests.exceptions.RequestException as e:
            logger.error(f"添加收藏时网络请求失败: {e}")
            return web.json_response({"success": False, "error": f"网络请求失败: {e}"})
        except Exception as e:
            import traceback
            logger.error(f"添加收藏时发生严重错误: {e}")
            logger.error(traceback.format_exc())
            return web.json_response({"success": False, "error": f"服务器内部错误: {e}"}, status=500)

    except Exception as e:
        logger.error(f"添加收藏接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

@PromptServer.instance.routes.post("/danbooru_gallery/favorites/remove")
async def remove_favorite(request):
    """移除收藏"""
    try:
        data = await request.json()
        post_id = data.get("post_id")
        source = str(data.get("source") or "danbooru").lower()

        if not post_id:
            return web.json_response({"success": False, "error": "缺少post_id"})

        if source == "civitai":
            remote_result = None
            remote_error = ""
            try:
                enabled, raw_headers, _, parsed = load_civitai_remote_favorites_settings()
                if enabled and raw_headers and parsed:
                    remote_result = _civitai_remote_save_item(post_id, remove=True)
            except Exception as e:
                remote_error = _safe_exception_text(e)
                logger.warning(f"[CivitaiRemoteFavorites] 远端取消收藏失败，仅同步本地: {remote_error}")

            favs = load_civitai_favorites()
            target = str(post_id)
            new_favs = [x for x in favs if _civitai_favorite_key(x) != target]
            if len(new_favs) != len(favs):
                save_civitai_favorites(new_favs)
            return web.json_response({
                "success": True,
                "message": "Civitai 远端取消收藏成功" if remote_result else "Civitai 本地取消收藏成功（远端未启用或失败）",
                "remote": "ok" if remote_result else "fallback_local",
                "remote_error": remote_error,
                "collection": (remote_result or {}).get("collection") if remote_result else None,
            })
        
        username, api_key = load_user_auth()
        if not username or not api_key:
            try:
                delete_response = _danbooru_bridge_favorite_request(post_id, remove=True)
                if delete_response.status_code in [200, 204, 404]:
                    favorites = load_favorites()
                    if str(post_id) in favorites:
                        favorites.remove(str(post_id))
                        save_favorites(favorites)
                    message = "取消收藏成功（浏览器登录态）" if delete_response.status_code != 404 else "该图片未在云端收藏，本地已同步"
                    return web.json_response({"success": True, "message": message})
                if delete_response.status_code in (401, 403):
                    return web.json_response({"success": False, "error": "D 登录态不可用或已过期，请点“打开/切到 D 登录”后重新保存当前登录态"})
                return web.json_response({"success": False, "error": f"取消收藏失败，浏览器登录态返回状态码: {delete_response.status_code}"})
            except Exception as e:
                return web.json_response({"success": False, "error": f"请先配置用户名/API Key，或使用 D 登录按钮保存浏览器登录态：{_safe_exception_text(e)[:180]}"})

        # 验证认证
        is_valid, is_network_error = verify_danbooru_auth(username, api_key)
        if is_network_error:
            return web.json_response({"success": False, "error": "网络错误，无法连接到Danbooru服务器"})
        if not is_valid:
            return web.json_response({"success": False, "error": "认证无效，请检查用户名和API Key"})
        
        try:
            # 直接使用帖子ID删除收藏
            delete_url = f"{BASE_URL}/favorites/{post_id}.json"
            delete_response = _danbooru_request("DELETE", delete_url, auth=HTTPBasicAuth(username, api_key), timeout=15)


            if delete_response.status_code in [200, 204]:
                favorites = load_favorites()
                if str(post_id) in favorites:
                    favorites.remove(str(post_id))
                    save_favorites(favorites)
                return web.json_response({"success": True, "message": "取消收藏成功"})
            elif delete_response.status_code == 404:
                # 如果收藏不存在，视为已删除
                favorites = load_favorites()
                if str(post_id) in favorites:
                    favorites.remove(str(post_id))
                    save_favorites(favorites)
                return web.json_response({"success": True, "message": "该图片未在云端收藏，本地已同步"})

            # 如果有收藏记录但删除失败，解析错误
            try:
                error_data = delete_response.json()
                reason = error_data.get("reason", "未知")
                message = error_data.get("message", "没有提供具体信息")
            except (json.JSONDecodeError, ValueError):
                error_data = {}
                reason = "无法解析响应"
                message = delete_response.text

            error_map = {
                401: "认证失败，请检查用户名和API Key",
                403: "权限不足，可能需要Gold账户",
                404: "收藏记录不存在",
                429: "请求过于频繁，请稍后重试 (Rate Limited)",
            }

            error_message = error_map.get(delete_response.status_code, f"取消收藏失败，状态码: {delete_response.status_code}, 原因: {message}")
            logger.error(error_message)
            return web.json_response({"success": False, "error": error_message})

        except requests.exceptions.Timeout:
            logger.error("移除收藏时网络请求超时")
            return web.json_response({"success": False, "error": "网络请求超时"})
        except requests.exceptions.RequestException as e:
            logger.error(f"移除收藏时网络请求失败: {e}")
            return web.json_response({"success": False, "error": f"网络请求失败: {e}"})
        except Exception as e:
            import traceback
            logger.error(f"移除收藏时发生严重错误: {e}")
            logger.error(traceback.format_exc())
            return web.json_response({"success": False, "error": f"服务器内部错误: {e}"}, status=500)

    except Exception as e:
        logger.error(f"移除收藏接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

@PromptServer.instance.routes.get("/danbooru_gallery/civitai_remote_favorites")
async def get_civitai_remote_favorites_settings_route(request):
    try:
        enabled, collection_headers, default_collection_id, collection_parsed = load_civitai_remote_favorites_settings()
        search_headers, search_parsed = load_civitai_search_headers()
        collections = []
        remote_error = ""
        if enabled and collection_headers and collection_parsed:
            try:
                collections = _civitai_remote_get_collections()
            except Exception as e:
                remote_error = _safe_exception_text(e)
        return web.json_response({
            "success": True,
            "enabled": enabled,
            "headers": _merge_civitai_browser_headers(collection_headers, search_headers),
            "collection_headers": collection_headers,
            "search_headers": search_headers,
            "has_headers": bool(collection_headers or search_headers),
            "has_collection_headers": bool(collection_headers),
            "has_search_headers": bool(search_headers),
            "has_cookie": bool(collection_parsed.get('Cookie')),
            "has_civitai_token": '__Secure-civitai-token=' in (collection_parsed.get('Cookie') or ''),
            "has_authorization": bool(search_parsed.get('Authorization') or search_parsed.get('X-Meili-API-Key')),
            "parsed_count": len(collection_parsed) + len(search_parsed),
            "collection_parsed_count": len(collection_parsed),
            "search_parsed_count": len(search_parsed),
            "default_collection_id": default_collection_id,
            "collections": collections,
            "selected_collection": (_civitai_remote_pick_collection() if collections else None),
            "remote_error": remote_error,
        })
    except Exception as e:
        logger.error(f"获取 Civitai 远端收藏设置失败: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

@PromptServer.instance.routes.post("/danbooru_gallery/civitai_remote_favorites")
async def save_civitai_remote_favorites_settings_route(request):
    try:
        data = await request.json()
        enabled = bool(data.get('enabled', False))
        raw_headers = data.get('headers', '')
        collection_headers = data.get('collection_headers', None)
        search_headers = data.get('search_headers', None)
        default_collection_id = str(data.get('default_collection_id', '') or '').strip()
        preserve_if_empty = bool(data.get('preserve_if_empty', True))
        if save_civitai_remote_favorites_settings(raw_headers, enabled, default_collection_id, preserve_if_empty, search_headers=search_headers, collection_headers=collection_headers):
            enabled2, collection2, cid2, collection_parsed = load_civitai_remote_favorites_settings()
            search2, search_parsed = load_civitai_search_headers()
            return web.json_response({
                "success": True,
                "enabled": enabled2,
                "headers": _merge_civitai_browser_headers(collection2, search2),
                "collection_headers": collection2,
                "search_headers": search2,
                "has_headers": bool(collection2 or search2),
                "has_collection_headers": bool(collection2),
                "has_search_headers": bool(search2),
                "has_cookie": bool(collection_parsed.get('Cookie')),
                "has_civitai_token": '__Secure-civitai-token=' in (collection_parsed.get('Cookie') or ''),
                "has_authorization": bool(search_parsed.get('Authorization') or search_parsed.get('X-Meili-API-Key')),
                "parsed_count": len(collection_parsed) + len(search_parsed),
                "collection_parsed_count": len(collection_parsed),
                "search_parsed_count": len(search_parsed),
                "default_collection_id": cid2,
            })
        return web.json_response({"success": False, "error": "无法保存 Civitai 远端收藏设置"}, status=500)
    except Exception as e:
        logger.error(f"保存 Civitai 远端收藏设置失败: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

@PromptServer.instance.routes.post("/danbooru_gallery/civitai_remote_favorites/test")
async def test_civitai_remote_favorites_route(request):
    try:
        collections = _civitai_remote_get_collections()
        selected = _civitai_remote_pick_collection() if collections else None
        return web.json_response({"success": True, "collections": collections, "selected": selected})
    except Exception as e:
        err = _safe_exception_text(e)
        logger.warning(f"测试 Civitai 远端收藏失败: {err}")
        hint = ''
        if '401' in err or 'UNAUTHORIZED' in err.upper():
            hint = '认证失败：请在设置里点“打开/切到 C 登录”，登录完成后点“保存当前登录态”。'
        return web.json_response({"success": False, "error": hint or err[:240], "raw_error": err[:500]})

@PromptServer.instance.routes.post("/danbooru_gallery/civitai_remote_favorites/open_login")
async def open_civitai_remote_favorites_login_route(request):
    try:
        opened = _civitai_bridge_open_renewal('manual civitai login', force=True)
        if not opened:
            return web.json_response({"success": False, "error": "无法打开 Civitai 登录页：请确认桥接 Chrome 端口 9222 已启动"}, status=500)
        return web.json_response({"success": True})
    except Exception as e:
        logger.warning(f"打开 Civitai 登录页失败: {_safe_exception_text(e)}")
        return web.json_response({"success": False, "error": _safe_exception_text(e)[:240]}, status=500)

@PromptServer.instance.routes.post("/danbooru_gallery/civitai_remote_favorites/capture_login")
async def capture_civitai_remote_favorites_login_route(request):
    try:
        enabled, _collection_headers, default_collection_id, _collection_parsed = load_civitai_remote_favorites_settings()
        search_headers, _search_parsed = load_civitai_search_headers()
        collection_headers = _civitai_bridge_capture_collection_headers()
        if save_civitai_remote_favorites_settings(
            '',
            enabled=True if not enabled else enabled,
            default_collection_id=default_collection_id,
            preserve_if_empty=True,
            search_headers=search_headers,
            collection_headers=collection_headers,
        ):
            enabled2, collection2, cid2, collection_parsed = load_civitai_remote_favorites_settings()
            search2, search_parsed = load_civitai_search_headers()
            return web.json_response({
                "success": True,
                "enabled": enabled2,
                "headers": _merge_civitai_browser_headers(collection2, search2),
                "collection_headers": collection2,
                "search_headers": search2,
                "has_headers": bool(collection2 or search2),
                "has_collection_headers": bool(collection2),
                "has_search_headers": bool(search2),
                "has_cookie": bool(collection_parsed.get('Cookie')),
                "has_civitai_token": '__Secure-civitai-token=' in (collection_parsed.get('Cookie') or ''),
                "has_authorization": bool(search_parsed.get('Authorization') or search_parsed.get('X-Meili-API-Key')),
                "parsed_count": len(collection_parsed) + len(search_parsed),
                "collection_parsed_count": len(collection_parsed),
                "search_parsed_count": len(search_parsed),
                "default_collection_id": cid2,
            })
        return web.json_response({"success": False, "error": "无法保存 Civitai 登录态"}, status=500)
    except Exception as e:
        logger.warning(f"保存 Civitai 登录态失败: {_safe_exception_text(e)}")
        return web.json_response({"success": False, "error": _safe_exception_text(e)[:240]}, status=500)

@PromptServer.instance.routes.get("/danbooru_gallery/user_auth")
async def get_user_auth_route(request):
    """获取用户认证信息"""
    try:
        username, api_key = load_user_auth()
        has_auth = bool(username and api_key)
        return web.json_response({"success": True, "username": username, "api_key": api_key, "has_auth": has_auth})
    except Exception as e:
        logger.error(f"获取用户认证接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

@PromptServer.instance.routes.get("/danbooru_gallery/favorites")
async def get_favorites_route(request):
    """获取收藏列表。Danbooru 返回 id 列表；Civitai 返回本地收藏的 id 列表和 post 快照。"""
    try:
        source = str(request.query.get("source") or "danbooru").lower()
        if source == "civitai":
            posts = [x for x in load_civitai_favorites() if isinstance(x, dict)]
            ids = [_civitai_favorite_key(x) for x in posts]
            return web.json_response({"success": True, "favorites": ids, "posts": posts, "source": "civitai"}, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})
        remote_error = ""
        try:
            favorites, meta = _danbooru_bridge_fetch_favorite_ids()
            save_favorites(favorites)
            return web.json_response({
                "success": True,
                "favorites": favorites,
                "source": "danbooru",
                "remote": "browser_session",
                "username": meta.get("username", ""),
                "pages_loaded": meta.get("pages_loaded", 0),
            }, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})
        except Exception as e:
            remote_error = _safe_exception_text(e)[:240]
            logger.warning(f"[DanbooruFavorites] 云端收藏读取失败，使用本地缓存: {remote_error}")
        favorites = load_favorites()
        return web.json_response({
            "success": True,
            "favorites": favorites,
            "source": "danbooru",
            "remote": "fallback_local",
            "remote_error": remote_error,
        }, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})
    except Exception as e:
        logger.error(f"获取收藏列表接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

@PromptServer.instance.routes.post("/danbooru_gallery/user_auth")
async def save_user_auth_route(request):
    """保存用户认证信息；默认避免空白表单误清除已保存的 API key。"""
    try:
        data = await request.json()
        preserve_if_empty = bool(data.get("preserve_if_empty", True))
        current_username, current_api_key = load_user_auth()
        username = str(data.get("username", current_username) or "")
        api_key = str(data.get("api_key", current_api_key) or "")
        if preserve_if_empty:
            if current_username and not username.strip():
                username = current_username
            if current_api_key and not api_key.strip():
                api_key = current_api_key
        if save_user_auth(username, api_key):
            return web.json_response({"success": True, "username": username, "api_key": api_key, "has_auth": bool(username and api_key)})
        else:
            return web.json_response({"success": False, "error": "无法保存用户认证信息"}, status=500)
    except Exception as e:
        logger.error(f"保存用户认证接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

@PromptServer.instance.routes.get("/danbooru_gallery/danbooru_cookie")
async def get_danbooru_cookie_route(request):
    """获取 Danbooru Cookie fallback 设置。Cookie 只返回给本地前端设置页。"""
    try:
        enabled, cookie = load_danbooru_cookie()
        return web.json_response({
            "success": True,
            "enabled": enabled,
            "cookie": cookie,
            "has_cookie": bool(cookie),
            "has_cf_clearance": "cf_clearance=" in cookie.lower(),
            "has_login_session": _danbooru_cookie_has_login_session(cookie),
            "length": len(cookie or ""),
        })
    except Exception as e:
        logger.error(f"获取 Danbooru Cookie 设置接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.post("/danbooru_gallery/danbooru_cookie")
async def save_danbooru_cookie_route(request):
    """保存 Danbooru Cookie fallback 设置；默认避免空白表单误清除已保存 Cookie。"""
    try:
        data = await request.json()
        preserve_if_empty = bool(data.get("preserve_if_empty", True))
        current_enabled, current_cookie = load_danbooru_cookie()
        cookie = str(data.get("cookie", current_cookie) or "")
        enabled = bool(data.get("enabled", current_enabled))
        if preserve_if_empty and current_cookie and not cookie.strip():
            cookie = current_cookie
        if save_danbooru_cookie(cookie, enabled):
            return web.json_response({
                "success": True,
                "enabled": enabled,
                "cookie": cookie,
                "has_cookie": bool(cookie),
                "has_cf_clearance": "cf_clearance=" in cookie.lower(),
                "has_login_session": _danbooru_cookie_has_login_session(cookie),
            })
        return web.json_response({"success": False, "error": "无法保存 Danbooru Cookie 设置"}, status=500)
    except Exception as e:
        logger.error(f"保存 Danbooru Cookie 设置接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.post("/danbooru_gallery/danbooru_cookie/open_login")
async def open_danbooru_cookie_login_route(request):
    try:
        _danbooru_bridge_open_login()
        return web.json_response({"success": True})
    except Exception as e:
        logger.warning(f"打开 Danbooru 验证页失败: {_safe_exception_text(e)}")
        return web.json_response({"success": False, "error": _safe_exception_text(e)[:240]}, status=500)


@PromptServer.instance.routes.post("/danbooru_gallery/danbooru_cookie/capture_login")
async def capture_danbooru_cookie_login_route(request):
    try:
        cookie_header, raw_headers, has_login_session = _danbooru_bridge_capture_login_state()
        if not save_danbooru_cookie(cookie_header, enabled=True):
            return web.json_response({"success": False, "error": "无法保存 Danbooru Cookie"}, status=500)
        if not save_danbooru_browser_headers(raw_headers, enabled=True):
            return web.json_response({"success": False, "error": "无法保存 Danbooru 浏览器请求头"}, status=500)
        _cookie_enabled, saved_cookie = load_danbooru_cookie()
        browser_enabled, saved_raw_headers, parsed = load_danbooru_browser_headers()
        return web.json_response({
            "success": True,
            "enabled": True,
            "cookie": saved_cookie,
            "has_cookie": bool(saved_cookie),
            "has_cf_clearance": "cf_clearance=" in str(saved_cookie or "").lower(),
            "has_login_session": bool(has_login_session),
            "browser_headers_enabled": browser_enabled,
            "browser_headers": saved_raw_headers,
            "browser_headers_has_cookie": bool(parsed.get("Cookie")),
            "browser_headers_has_cf_clearance": "cf_clearance=" in str(parsed.get("Cookie", "")).lower(),
            "browser_headers_has_user_agent": bool(parsed.get("User-Agent")),
            "browser_headers_parsed_count": len(parsed),
        })
    except Exception as e:
        logger.warning(f"保存 Danbooru 登录态失败: {_safe_exception_text(e)}")
        return web.json_response({"success": False, "error": _safe_exception_text(e)[:240]}, status=500)



@PromptServer.instance.routes.get("/danbooru_gallery/danbooru_browser_headers")
async def get_danbooru_browser_headers_route(request):
    """获取 Danbooru 浏览器请求头模式设置。只返回给本地设置页。"""
    try:
        enabled, raw_headers, parsed = load_danbooru_browser_headers()
        return web.json_response({
            "success": True,
            "enabled": enabled,
            "headers": raw_headers,
            "has_headers": bool(raw_headers),
            "parsed_count": len(parsed),
            "has_cookie": bool(parsed.get("Cookie")),
            "has_cf_clearance": "cf_clearance=" in str(parsed.get("Cookie", "")).lower(),
            "has_user_agent": bool(parsed.get("User-Agent")),
            "length": len(raw_headers or ""),
        })
    except Exception as e:
        logger.error(f"获取 Danbooru 浏览器请求头设置接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.post("/danbooru_gallery/danbooru_browser_headers")
async def save_danbooru_browser_headers_route(request):
    """保存 Danbooru 浏览器请求头模式设置；默认避免空白表单误清除。"""
    try:
        data = await request.json()
        preserve_if_empty = bool(data.get("preserve_if_empty", True))
        current_enabled, current_raw_headers, _ = load_danbooru_browser_headers()
        raw_headers = str(data.get("headers", current_raw_headers) or "")
        enabled = bool(data.get("enabled", current_enabled))
        if preserve_if_empty and current_raw_headers and not raw_headers.strip():
            raw_headers = current_raw_headers
        if save_danbooru_browser_headers(raw_headers, enabled):
            _, saved_raw_headers, parsed = load_danbooru_browser_headers()
            return web.json_response({
                "success": True,
                "enabled": enabled,
                "headers": saved_raw_headers,
                "has_headers": bool(saved_raw_headers),
                "parsed_count": len(parsed),
                "has_cookie": bool(parsed.get("Cookie")),
                "has_cf_clearance": "cf_clearance=" in str(parsed.get("Cookie", "")).lower(),
                "has_user_agent": bool(parsed.get("User-Agent")),
            })
        return web.json_response({"success": False, "error": "无法保存 Danbooru 浏览器请求头设置"}, status=500)
    except Exception as e:
        logger.error(f"保存 Danbooru 浏览器请求头设置接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.get("/danbooru_gallery/gelbooru_auth")
async def get_gelbooru_auth_route(request):
    """获取 Gelbooru API 认证信息"""
    try:
        user_id, api_key = load_gelbooru_auth()
        has_auth = bool(user_id and api_key)
        return web.json_response({"success": True, "user_id": user_id, "api_key": api_key, "has_auth": has_auth})
    except Exception as e:
        logger.error(f"获取 Gelbooru 认证接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.post("/danbooru_gallery/gelbooru_auth")
async def save_gelbooru_auth_route(request):
    """保存 Gelbooru API 认证信息；默认避免空白表单误清除已保存 API key。"""
    try:
        data = await request.json()
        preserve_if_empty = bool(data.get("preserve_if_empty", True))
        current_user_id, current_api_key = load_gelbooru_auth()
        user_id = str(data.get("user_id", current_user_id) or "")
        api_key = str(data.get("api_key", current_api_key) or "")
        if preserve_if_empty:
            if current_user_id and not user_id.strip():
                user_id = current_user_id
            if current_api_key and not api_key.strip():
                api_key = current_api_key
        if save_gelbooru_auth(user_id, api_key):
            return web.json_response({"success": True, "user_id": user_id, "api_key": api_key, "has_auth": bool(user_id and api_key)})
        return web.json_response({"success": False, "error": "无法保存 Gelbooru 认证信息"}, status=500)
    except Exception as e:
        logger.error(f"保存 Gelbooru 认证接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)



@PromptServer.instance.routes.get("/danbooru_gallery/civitai_auth")
async def get_civitai_auth_route(request):
    """获取 Civitai API Key 状态。"""
    try:
        api_key = load_civitai_auth()
        return web.json_response({"success": True, "api_key": api_key, "has_auth": bool(api_key)})
    except Exception as e:
        logger.error(f"获取 Civitai 认证接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.post("/danbooru_gallery/civitai_auth")
async def save_civitai_auth_route(request):
    """保存 Civitai API Key；默认避免空表单误清空。"""
    try:
        data = await request.json()
        preserve_if_empty = bool(data.get("preserve_if_empty", True))
        current_api_key = load_civitai_auth()
        api_key = str(data.get("api_key", current_api_key) or "")
        if preserve_if_empty and current_api_key and not api_key.strip():
            api_key = current_api_key
        if save_civitai_auth(api_key):
            return web.json_response({"success": True, "api_key": api_key, "has_auth": bool(api_key)})
        return web.json_response({"success": False, "error": "无法保存 Civitai API Key"}, status=500)
    except Exception as e:
        logger.error(f"保存 Civitai 认证接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.post("/danbooru_gallery/verify_gelbooru_auth")
async def verify_gelbooru_auth_route(request):
    """验证 Gelbooru API 认证"""
    try:
        data = await request.json()
        user_id = data.get("user_id", "")
        api_key = data.get("api_key", "")
        if not user_id or not api_key:
            return web.json_response({"success": False, "error": "缺少 user_id 或 API Key"})
        is_valid, is_network_error = verify_gelbooru_auth(user_id, api_key)
        return web.json_response({"success": True, "valid": is_valid, "network_error": is_network_error})
    except Exception as e:
        logger.error(f"验证 Gelbooru 认证接口错误: {e}")
        return web.json_response({"success": False, "error": "网络错误", "network_error": True}, status=500)


@PromptServer.instance.routes.get("/danbooru_gallery/browser_bridge_settings")
async def get_browser_bridge_settings_route(request):
    """获取 Danbooru 浏览器桥接设置。"""
    try:
        settings = load_browser_bridge_settings()
        available, import_error = _browser_bridge_import_status()
        return web.json_response({
            "success": True,
            "enabled": settings.get("enabled"),
            "cdp_url": settings.get("cdp_url"),
            "timeout_ms": settings.get("timeout_ms"),
            "prefer": settings.get("prefer"),
            "playwright_available": available,
            "playwright_error": import_error,
        })
    except Exception as e:
        logger.error(f"获取浏览器桥接设置失败: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.post("/danbooru_gallery/browser_bridge_settings")
async def save_browser_bridge_settings_route(request):
    """保存 Danbooru 浏览器桥接设置。"""
    try:
        data = await request.json()
        ok = save_browser_bridge_settings(
            enabled=bool(data.get("enabled", False)),
            cdp_url=data.get("cdp_url", "http://127.0.0.1:9222"),
            timeout_ms=data.get("timeout_ms", 60000),
            prefer=bool(data.get("prefer", False)),
        )
        if ok:
            settings = load_browser_bridge_settings()
            available, import_error = _browser_bridge_import_status()
            return web.json_response({"success": True, **settings, "playwright_available": available, "playwright_error": import_error})
        return web.json_response({"success": False, "error": "无法保存浏览器桥接设置"}, status=500)
    except Exception as e:
        logger.error(f"保存浏览器桥接设置失败: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.get("/danbooru_gallery/diagnose_browser_bridge")
async def diagnose_browser_bridge_route(request):
    """单独测试 Danbooru 浏览器桥接。"""
    tags = _normalize_danbooru_query_tags(request.query.get("tags", "rating:general") or "rating:general")
    limit = max(1, min(int(request.query.get("limit", "1") or 1), 5))
    page = max(1, int(request.query.get("page", "1") or 1))
    started = time.monotonic()
    bridge = load_browser_bridge_settings()
    available, import_error = _browser_bridge_import_status()
    result = {
        "success": True,
        "source": "danbooru",
        "diagnostic": "browser_bridge",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "settings": {
            "enabled": bridge.get("enabled"),
            "cdp_url": bridge.get("cdp_url"),
            "timeout_ms": bridge.get("timeout_ms"),
            "prefer": bridge.get("prefer"),
            "playwright_available": available,
            "playwright_error": import_error,
            "tested_tags": tags,
        },
        "ok": False,
        "category": "unknown",
        "status_code": None,
        "elapsed_ms": None,
        "post_count": 0,
        "sample_post_id": None,
        "error": "",
        "notes": [
            "浏览器桥接需要先启动带 --remote-debugging-port 的 Chrome/Edge。",
            "该浏览器配置必须能在地址栏打开 Danbooru posts.json 并看到 JSON。",
            "如果这里仍是 Cloudflare challenge，先在同一个调试浏览器配置里手动通过验证，或换代理出口。",
        ]
    }
    try:
        if not available:
            result.update({"category": "playwright_not_installed", "error": import_error or "Playwright 未安装"})
            return web.json_response(result, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, indent=2))
        params = _with_danbooru_auth_params({"tags": tags, "limit": limit, "page": page})
        resp = await asyncio.to_thread(_browser_bridge_fetch_json, "/posts.json", params, bridge.get("timeout_ms"), bridge.get("cdp_url"), "diagnose_posts")
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        result["status_code"] = int(resp.status_code or 0)
        data = resp.json()
        if isinstance(data, list):
            result["post_count"] = len(data)
            result["sample_post_id"] = data[0].get("id") if data and isinstance(data[0], dict) else None
        result["ok"] = isinstance(data, list)
        result["category"] = "ok_json" if result["ok"] else "json_not_list"
    except Exception as e:
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        msg = _diag_sanitize_text(str(e))
        result["error"] = msg
        low = msg.lower()
        if "playwright" in low and ("not installed" in low or "未安装" in msg):
            result["category"] = "playwright_not_installed"
        elif "connect" in low or "ecconnrefused" in low or "refused" in low:
            result["category"] = "cdp_connection_failed"
        elif "cloudflare" in low or "just a moment" in low:
            result["category"] = "browser_bridge_cloudflare_challenge"
        elif "timeout" in low:
            result["category"] = "browser_bridge_timeout"
        else:
            result["category"] = "browser_bridge_error"
    return web.json_response(result, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, indent=2))


@PromptServer.instance.routes.get("/danbooru_gallery/settings_full")
async def get_settings_full_route(request):
    """导出完整 Danbooru Gallery 设置。此接口会包含本地 API key/Cookie，仅用于用户本机备份。"""
    try:
        settings = load_settings()
        export_payload = {
            "format": "ComfyUI-Danbooru-Gallery settings export",
            "version": "v39-civitai-loose-button-prompt-fix",
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "contains_sensitive_secrets": True,
            "warning": "此文件包含 Danbooru/Gelbooru/Civitai API key、Cookie、浏览器请求头和 search-new 授权。只用于本机备份，不要发给别人。",
            "settings": settings,
            "auth": {
                "danbooru": {
                    "username": settings.get("danbooru_username", ""),
                    "api_key": settings.get("danbooru_api_key", ""),
                    "cookie_enabled": bool(settings.get("danbooru_cookie_enabled", False)),
                    "cookie_fallback_enabled": bool(settings.get("danbooru_cookie_enabled", False)),
                    "cookie": settings.get("danbooru_cookie", "")
                },
                "danbooru_browser_headers": {
                    "enabled": bool(settings.get("danbooru_browser_headers_enabled", False)),
                    "raw_headers": settings.get("danbooru_browser_headers", ""),
                    "parsed_count": _danbooru_browser_headers_status().get("parsed_count", 0),
                    "has_cookie": _danbooru_browser_headers_status().get("has_cookie", False),
                    "has_user_agent": _danbooru_browser_headers_status().get("has_user_agent", False)
                },
                "gelbooru": {
                    "user_id": settings.get("gelbooru_user_id", ""),
                    "api_key": settings.get("gelbooru_api_key", "")
                },
                "civitai": {
                    "api_key": settings.get("civitai_api_key", ""),
                    "remote_favorites_enabled": bool(settings.get("civitai_remote_favorites_enabled", False)),
                    "collection_headers": settings.get("civitai_collection_headers", ""),
                    "search_headers": settings.get("civitai_search_headers", ""),
                    "legacy_merged_headers": settings.get("civitai_browser_headers", ""),
                    "default_collection_id": settings.get("civitai_default_collection_id", ""),
                    "status": _civitai_remote_status(),
                },
                "danbooru_browser_bridge": {
                    "enabled": bool(settings.get("danbooru_browser_bridge_enabled", False)),
                    "cdp_url": settings.get("danbooru_browser_bridge_cdp_url", "http://127.0.0.1:9222"),
                    "timeout_ms": settings.get("danbooru_browser_bridge_timeout_ms", 60000),
                    "prefer": bool(settings.get("danbooru_browser_bridge_prefer", False))
                }
            }
        }
        return web.json_response({"success": True, "export": export_payload}, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.error(f"导出完整设置接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.post("/danbooru_gallery/settings_full")
async def import_settings_full_route(request):
    """导入完整设置；兼容旧版前端导出。"""
    try:
        payload = await request.json()
        settings = _normalize_full_settings_import(payload)
        if save_settings(settings):
            return web.json_response({"success": True})
        return web.json_response({"success": False, "error": "无法保存完整设置"}, status=500)
    except Exception as e:
        logger.error(f"导入完整设置接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.get("/danbooru_gallery/check_network")
async def check_network(request):
    """检测网络连接状态"""
    try:
        source = request.query.get("source", "danbooru")
        is_connected, is_network_error = check_network_connection(source)
        return web.json_response({"success": True, "connected": is_connected, "network_error": is_network_error, "source": source})
    except Exception as e:
        logger.error(f"网络检测接口错误: {e}")
        return web.json_response({"success": False, "error": "网络检测失败", "network_error": True}, status=500)



def _civitai_prompt_result_usable(post):
    return bool(
        isinstance(post, dict) and (
            post.get('civitai_prompt')
            or post.get('civitai_negative_prompt')
            or post.get('civitai_has_content_tags')
            or post.get('civitai_content_tags')
        )
    )


def _civitai_prompt_cache_key(image_id='', post_id='', image_url=''):
    image_id = str(image_id or '').strip()
    post_id = str(post_id or '').strip()
    image_url = str(image_url or '').strip()
    if image_id:
        return f'image:{image_id}'
    if post_id:
        return f'post:{post_id}'
    if image_url:
        return f'url:{image_url}'
    return ''


def _civitai_prompt_cache_get(cache_key):
    if not cache_key:
        return None
    entry = _CIVITAI_PROMPT_DETAIL_CACHE.get(cache_key)
    if not isinstance(entry, dict):
        return None
    if float(entry.get('expires_at') or 0) <= time.monotonic():
        _CIVITAI_PROMPT_DETAIL_CACHE.pop(cache_key, None)
        return None
    result = dict(entry.get('result') or {})
    result['cached'] = True
    return result


def _civitai_prompt_cache_put(cache_key, result):
    if not cache_key or not isinstance(result, dict):
        return
    ttl = _CIVITAI_PROMPT_DETAIL_SUCCESS_TTL if result.get('success') else _CIVITAI_PROMPT_DETAIL_FAILURE_TTL
    _CIVITAI_PROMPT_DETAIL_CACHE[cache_key] = {
        'expires_at': time.monotonic() + ttl,
        'result': dict(result),
    }
    if len(_CIVITAI_PROMPT_DETAIL_CACHE) > _CIVITAI_PROMPT_DETAIL_CACHE_LIMIT:
        # Dicts preserve insertion order. Remove the oldest quarter rather than
        # allowing a long browsing session to grow the cache without bound.
        remove_count = max(1, _CIVITAI_PROMPT_DETAIL_CACHE_LIMIT // 4)
        for old_key in list(_CIVITAI_PROMPT_DETAIL_CACHE.keys())[:remove_count]:
            _CIVITAI_PROMPT_DETAIL_CACHE.pop(old_key, None)


def _resolve_civitai_prompt_sync(image_id='', post_id='', image_url='', favorite=False):
    """Resolve one Civitai image detail in a worker thread.

    Favorite collection rows have a real image id but intentionally omit their
    generation metadata. For those rows, image.getGenerationData is the fastest
    useful detail call, so V52 uses it before the slower REST probes. The public
    tag endpoint is only queried when generation data did not already provide a
    prompt/tag string.
    """
    started = time.monotonic()
    image_id = str(image_id or '').strip()
    post_id = str(post_id or '').strip()
    image_url = str(image_url or '').strip()
    attempts = []

    def finish_success(post, source):
        return {
            'success': True,
            'source': source or (post or {}).get('civitai_prompt_source') or 'unknown',
            'post': post,
            'attempts': attempts,
            'elapsed_ms': int((time.monotonic() - started) * 1000),
            'cached': False,
        }

    def try_api(label, params):
        call_started = time.monotonic()
        try:
            data, base = _civitai_fetch_json('/api/v1/images', params=params, timeout=12, allow_fallback=True)
            items = data.get('items') if isinstance(data, dict) else []
            attempts.append({
                'label': label,
                'ok': True,
                'base': base,
                'items': len(items or []),
                'elapsed_ms': int((time.monotonic() - call_started) * 1000),
                'params': {k: ('<url>' if k == 'image_url' else v) for k, v in params.items()},
            })
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                norm = _civitai_item_to_danbooru_shape(item)
                if _civitai_prompt_result_usable(norm):
                    return norm
        except Exception as exc:
            attempts.append({
                'label': label,
                'ok': False,
                'elapsed_ms': int((time.monotonic() - call_started) * 1000),
                'error': _safe_exception_text(exc),
                'params': params,
            })
        return None

    def try_trpc():
        if not (image_id and re.fullmatch(r'\d+', image_id)):
            return None

        generation_data = None
        generation_started = time.monotonic()
        try:
            generation_data = _civitai_trpc_json(
                'image.getGenerationData', {'id': int(image_id)},
                timeout=12, referer_image_id=image_id,
            )
            attempts.append({
                'label': 'trpc_generation_data',
                'ok': True,
                'has_data': bool(generation_data),
                'elapsed_ms': int((time.monotonic() - generation_started) * 1000),
            })
        except Exception as exc:
            attempts.append({
                'label': 'trpc_generation_data',
                'ok': False,
                'elapsed_ms': int((time.monotonic() - generation_started) * 1000),
                'error': _safe_exception_text(exc),
            })
            return None

        # Most collection images expose the complete prompt here. Return
        # immediately instead of always waiting for tag.getVotableTags as V51 did.
        resolved = _civitai_generation_detail_to_post(
            image_id, post_id, image_url, generation_data, None,
        )
        if _civitai_prompt_result_usable(resolved):
            if not resolved.get('civitai_prompt_source'):
                resolved['civitai_prompt_source'] = 'trpc_generation_data'
            return resolved

        votable_tags = None
        tag_started = time.monotonic()
        try:
            votable_tags = _civitai_trpc_json(
                'tag.getVotableTags',
                {'id': int(image_id), 'type': 'image'},
                timeout=10, referer_image_id=image_id,
            )
            attempts.append({
                'label': 'trpc_votable_tags',
                'ok': True,
                'count': len(votable_tags) if isinstance(votable_tags, list) else (1 if votable_tags else 0),
                'elapsed_ms': int((time.monotonic() - tag_started) * 1000),
            })
        except Exception as exc:
            attempts.append({
                'label': 'trpc_votable_tags',
                'ok': False,
                'elapsed_ms': int((time.monotonic() - tag_started) * 1000),
                'error': _safe_exception_text(exc),
            })

        resolved = _civitai_generation_detail_to_post(
            image_id, post_id, image_url, generation_data, votable_tags,
        )
        if _civitai_prompt_result_usable(resolved):
            if not resolved.get('civitai_prompt_source'):
                resolved['civitai_prompt_source'] = 'trpc_generation_data'
            return resolved
        return None

    resolved = None
    # Remote favorites are known to be lightweight tRPC collection rows. Avoid
    # spending up to two REST timeouts before trying their native detail endpoint.
    if favorite:
        resolved = try_trpc()
        if resolved:
            return finish_success(resolved, resolved.get('civitai_prompt_source') or 'trpc_generation_data')

    if image_id:
        resolved = try_api('api_imageId', {'imageId': image_id, 'limit': 1})
    if not resolved and post_id:
        resolved = try_api('api_postId', {'postId': post_id, 'limit': 1})
    if resolved:
        return finish_success(resolved, resolved.get('civitai_prompt_source') or 'api')

    if not favorite:
        resolved = try_trpc()
        if resolved:
            return finish_success(resolved, resolved.get('civitai_prompt_source') or 'trpc_generation_data')

    if image_url:
        metadata_started = time.monotonic()
        meta_result = _civitai_extract_prompt_from_image_url(image_url, timeout=12)
        attempts.append({
            'label': 'image_metadata',
            'elapsed_ms': int((time.monotonic() - metadata_started) * 1000),
            **{k: v for k, v in meta_result.items() if k not in ('prompt', 'negativePrompt')},
        })
        if meta_result.get('success') and (meta_result.get('prompt') or meta_result.get('negativePrompt')):
            prompt_tags = _civitai_prompt_to_tagish(meta_result.get('prompt') or '')
            return finish_success({
                'civitai_prompt': meta_result.get('prompt') or '',
                'civitai_negative_prompt': meta_result.get('negativePrompt') or '',
                'civitai_prompt_source': meta_result.get('source') or 'image_metadata',
                'tag_string': prompt_tags,
                'tag_string_general': prompt_tags,
                'tag_string_meta': 'civitai metadata_resolved',
                'civitai_content_tags': prompt_tags,
                'civitai_has_content_tags': bool(prompt_tags),
                'civitai_image_id': image_id,
                'civitai_post_id': post_id,
            }, meta_result.get('source') or 'image_metadata')

    return {
        'success': False,
        'error': 'prompt_not_found',
        'attempts': attempts,
        'elapsed_ms': int((time.monotonic() - started) * 1000),
        'cached': False,
    }


async def _run_civitai_prompt_resolution(cache_key, image_id, post_id, image_url, favorite):
    if hasattr(asyncio, 'to_thread'):
        result = await asyncio.to_thread(
            _resolve_civitai_prompt_sync,
            image_id, post_id, image_url, favorite,
        )
    else:  # Python 3.8 compatibility
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _resolve_civitai_prompt_sync(
                image_id, post_id, image_url, favorite,
            ),
        )
    _civitai_prompt_cache_put(cache_key, result)
    return result


@PromptServer.instance.routes.get("/danbooru_gallery/civitai_prompt")
async def civitai_prompt_route(request):
    """Resolve and cache missing Civitai prompt/tags for one image."""
    try:
        image_id = str(request.query.get('image_id') or request.query.get('id') or '').strip()
        post_id = str(request.query.get('post_id') or '').strip()
        image_url = str(request.query.get('image_url') or '').strip()
        favorite = str(request.query.get('favorite') or '').strip().lower() in ('1', 'true', 'yes', 'on')
        force = str(request.query.get('force') or '').strip().lower() in ('1', 'true', 'yes', 'on')

        # Validate before cache/inflight lookup so an attacker-controlled URL can
        # never reuse or schedule a task without passing the outbound policy.
        if image_url:
            await asyncio.to_thread(
                _validate_url_for_purpose, image_url, 'civitai_prompt',
            )
        cache_key = _civitai_prompt_cache_key(image_id, post_id, image_url)

        if not force:
            cached = _civitai_prompt_cache_get(cache_key)
            if cached is not None:
                return web.json_response(cached)

        task = _CIVITAI_PROMPT_DETAIL_INFLIGHT.get(cache_key) if cache_key else None
        if task is None:
            task = asyncio.create_task(
                _run_civitai_prompt_resolution(
                    cache_key, image_id, post_id, image_url, favorite,
                )
            )
            if cache_key:
                _CIVITAI_PROMPT_DETAIL_INFLIGHT[cache_key] = task

                def _remove_finished(done_task, key=cache_key):
                    if _CIVITAI_PROMPT_DETAIL_INFLIGHT.get(key) is done_task:
                        _CIVITAI_PROMPT_DETAIL_INFLIGHT.pop(key, None)

                task.add_done_callback(_remove_finished)

        # shield keeps the shared request alive when a tooltip disappears or a
        # browser-side AbortController cancels only one waiting caller.
        result = await asyncio.shield(task)
        return web.json_response(result)
    except URLPolicyError as e:
        return web.json_response(
            {"success": False, "error": e.code, "message": e.public_message},
            status=e.http_status,
        )
    except Exception as e:
        logger.error(f"Civitai prompt resolve route error: {_safe_exception_text(e)}")
        return web.json_response({"success": False, "error": "internal_error"}, status=500)


def _diag_civitai_post_image_candidates(post):
    """Return candidate image URLs in the same priority order used by the V23 frontend."""
    if not isinstance(post, dict):
        return []
    raw = [post.get('preview_file_url'), post.get('preview_url'), post.get('thumbnailUrl'), post.get('large_file_url'), post.get('sample_url'), post.get('file_url'), post.get('image_url')]
    seen = set(); out = []
    for value in raw:
        url = str(value or '').strip()
        if not re.match(r'^https?://', url, flags=re.I):
            continue
        if url in seen:
            continue
        seen.add(url); out.append(url)
    return out

def _diag_url_host(url):
    try: return urllib.parse.urlparse(str(url or '')).hostname or ''
    except Exception: return ''

def _diag_file_ext_from_candidates(post, candidates):
    ext = str((post or {}).get('file_ext') or '').strip().lower()
    if ext: return ext
    for url in candidates or []:
        e = _file_ext_from_url(url, fallback='')
        if e: return str(e).lower()
    return ''

def _diag_categorize_image_response(resp):
    if resp is None: return 'no_response'
    status = getattr(resp, 'status_code', None)
    if status != 200: return f'http_{status}'
    ctype = str(getattr(resp, 'headers', {}).get('Content-Type', '') or '').lower()
    if ctype.startswith('image/'): return 'ok_image'
    if _response_looks_like_image(resp): return 'ok_image_by_magic'
    if 'text/html' in ctype:
        try: text = resp.text[:300]
        except Exception: text = ''
        if 'cloudflare' in text.lower() or 'just a moment' in text.lower(): return 'cloudflare_html'
        return 'html_not_image'
    return 'non_image_content'

def _diag_probe_civitai_image_url(url, timeout=12):
    t0 = time.monotonic()
    result = {'url': _diag_redact_url(url), 'host': _diag_url_host(url), 'ok': False, 'status': None, 'category': 'not_run', 'content_type': '', 'bytes': 0, 'elapsed_ms': None, 'error': ''}
    resp = None
    try:
        resp = _fetch_supported_media_url(
            url, timeout=timeout, purpose='civitai_media',
        )
        result['elapsed_ms'] = int((time.monotonic() - t0) * 1000)
        result['status'] = int(getattr(resp, 'status_code', 0) or 0)
        result['content_type'] = str(getattr(resp, 'headers', {}).get('Content-Type', '') or '')[:120]
        result['bytes'] = len(getattr(resp, 'content', b'') or b'')
        result['category'] = _diag_categorize_image_response(resp)
        result['ok'] = result['category'].startswith('ok_image')
    except URLPolicyError as e:
        result['elapsed_ms'] = int((time.monotonic() - t0) * 1000)
        result['category'] = 'url_policy_rejected'
        result['error'] = e.code
    except Exception as e:
        result['elapsed_ms'] = int((time.monotonic() - t0) * 1000)
        result['category'] = 'exception'
        result['error'] = _diag_sanitize_text(str(e))[:500]
    finally:
        if resp is not None:
            _close_outbound_response(resp)
    return result

@PromptServer.instance.routes.get("/danbooru_gallery/diagnose_civitai_favorites")
async def diagnose_civitai_favorites_route(request):
    """Deep diagnosis for Civitai favorites and thumbnail proxy failures."""
    started = time.monotonic()
    search = str(request.query.get('search') or 'civitai:favorites').strip() or 'civitai:favorites'
    if 'civitai:favorites' not in search:
        search = 'civitai:favorites'
    limit = max(1, min(int(request.query.get('limit', '40') or 40), 80))
    probe = str(request.query.get('probe', '1')).lower() not in ('0', 'false', 'no', 'none')
    probe_posts = max(1, min(int(request.query.get('probe_posts', '40') or 40), 80))
    probe_urls_per_post = max(1, min(int(request.query.get('probe_urls_per_post', '3') or 3), 5))
    enabled, collection_raw, default_collection_id, collection_parsed = load_civitai_remote_favorites_settings()
    search_raw, search_parsed = load_civitai_search_headers()
    local_favs = load_civitai_favorites()
    diag = {
        'success': True, 'diagnostic': 'civitai_favorites_v26', 'summary': 'unknown', 'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'input': {'search': search, 'limit': limit, 'probe': probe, 'probe_posts': probe_posts, 'probe_urls_per_post': probe_urls_per_post},
        'settings': {
            'remote_enabled': bool(enabled), 'collection_headers_present': bool(collection_raw), 'collection_headers_parsed_count': len(collection_parsed or {}),
            'collection_has_cookie': bool((collection_parsed or {}).get('Cookie')), 'collection_has_user_agent': bool((collection_parsed or {}).get('User-Agent')),
            'search_headers_present': bool(search_raw), 'search_headers_parsed_count': len(search_parsed or {}),
            'search_has_authorization': bool((search_parsed or {}).get('Authorization') or (search_parsed or {}).get('X-Meili-API-Key')),
            'default_collection_id': str(default_collection_id or ''), 'local_favorites_count': len(local_favs or []), 'civitai_base': CIVITAI_BASE_URL,
            'civitai_fallback_base': CIVITAI_FALLBACK_BASE_URL, 'curl_cffi_available': bool(_CURL_CFFI_AVAILABLE), 'proxy': _get_proxy_url() or '',
        },
        'favorites_fetch': {'ok': False, 'source': '', 'count': 0, 'elapsed_ms': None, 'error': ''},
        'last_search_debug': {}, 'analysis': {}, 'samples': [], 'recommendations': [], 'elapsed_ms': None,
    }
    posts = []; fetch_start = time.monotonic()
    try:
        result_text = _get_civitai_images(tags=search, limit=limit, page=1, rating='', force_refresh=True)
        posts = json.loads(result_text or '[]')
        if not isinstance(posts, list): posts = []
        debug = dict(_CIVITAI_LAST_SEARCH_DEBUG or {})
        diag['last_search_debug'] = debug
        calls = debug.get('calls') if isinstance(debug, dict) else []
        source_label = str(calls[0].get('label') or '') if calls and isinstance(calls[0], dict) else ''
        diag['favorites_fetch'].update({'ok': True, 'source': source_label or 'remote_or_local', 'count': len(posts), 'elapsed_ms': int((time.monotonic() - fetch_start) * 1000)})
    except Exception as e:
        diag['favorites_fetch'].update({'ok': False, 'error': _diag_sanitize_text(str(e))[:1000], 'elapsed_ms': int((time.monotonic() - fetch_start) * 1000)})
    allowed_exts = {'jpg','jpeg','png','webp','bmp','tiff','tif','avif'}
    host_counts = {}; missing_candidates=ext_ok=ext_missing=ext_suspicious=has_any_candidate=0
    for post in posts:
        candidates = _diag_civitai_post_image_candidates(post)
        if candidates: has_any_candidate += 1
        else: missing_candidates += 1
        for u in candidates:
            h = _diag_url_host(u)
            if h: host_counts[h] = host_counts.get(h, 0) + 1
        ext = _diag_file_ext_from_candidates(post, candidates)
        if not ext: ext_missing += 1
        elif ext in allowed_exts: ext_ok += 1
        else: ext_suspicious += 1
    diag['analysis'] = {'total_posts': len(posts), 'has_any_candidate': has_any_candidate, 'missing_candidates': missing_candidates, 'ext_ok': ext_ok, 'ext_missing': ext_missing, 'ext_suspicious': ext_suspicious, 'host_counts': host_counts}
    for post in posts[:probe_posts]:
        candidates = _diag_civitai_post_image_candidates(post)
        sample = {'id': str(post.get('id') or ''), 'civitai_url': str(post.get('civitai_url') or ''), 'post_url': str(post.get('civitai_post_url') or ''), 'file_ext': str(post.get('file_ext') or ''), 'image_width': post.get('image_width'), 'image_height': post.get('image_height'), 'candidate_count': len(candidates), 'candidate_hosts': [_diag_url_host(u) for u in candidates[:8]], 'reason': '' if candidates else 'no_image_candidates_from_posts_metadata', 'probes': []}
        if probe and candidates:
            for idx, url in enumerate(candidates[:probe_urls_per_post]):
                pr = _diag_probe_civitai_image_url(url, timeout=12); pr['label'] = f'candidate_{idx}'; sample['probes'].append(pr)
                if pr.get('ok'): break
        diag['samples'].append(sample)
    if not diag['favorites_fetch']['ok']:
        diag['summary']='favorites_fetch_failed'; diag['recommendations'].append('收藏列表本身没有成功返回；优先检查 Civitai collection headers/Cookie 是否仍有效。')
    elif len(posts)==0:
        diag['summary']='favorites_empty_or_filtered'; diag['recommendations'].append('收藏接口成功但返回 0 条；检查默认收藏夹、Cookie 登录账号、搜索框是否额外带了过滤词。')
    elif missing_candidates==len(posts):
        diag['summary']='posts_have_no_image_urls'; diag['recommendations'].append('/posts 返回了收藏条目，但没有任何可代理图片 URL；需要检查 Civitai image.getInfinite 返回结构是否变化。')
    elif any(any(p.get('ok') for p in (s.get('probes') or [])) for s in diag['samples']):
        diag['summary']='some_image_proxy_ok'; diag['recommendations'].append('至少有部分图片代理可用；未显示的图请看 samples 中失败候选的 HTTP 状态。')
    elif probe and diag['samples']:
        statuses=[str(p.get('category') or '') for s in diag['samples'] for p in (s.get('probes') or [])]
        if any(x in ('http_403','cloudflare_html') for x in statuses):
            diag['summary']='image_proxy_forbidden_or_cloudflare'; diag['recommendations'].append('收藏元数据正常，但图片 CDN 代理被 403/Cloudflare 拦截；重新复制 Civitai 页面请求头 Cookie/User-Agent，或让 ComfyUI 后端走同一代理出口。')
        elif any(x in ('http_404',) for x in statuses):
            diag['summary']='image_urls_not_found'; diag['recommendations'].append('图片 URL 返回 404；可能是 Civitai CDN URL 构造或收藏返回结构变化。')
        elif any(x in ('non_image_content','html_not_image') for x in statuses):
            diag['summary']='image_proxy_returned_non_image'; diag['recommendations'].append('图片代理拿到的不是 image/* 内容；通常是 HTML 登录页、挑战页或错误页。')
        else:
            diag['summary']='image_proxy_all_sample_failed'; diag['recommendations'].append('抽样图片全部代理失败；查看每个 probe 的 category/error。')
    else:
        diag['summary']='favorites_metadata_ok_probe_disabled'
    diag['elapsed_ms'] = int((time.monotonic() - started) * 1000)
    return web.json_response(diag, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, indent=2), headers={'Cache-Control':'no-cache, no-store, must-revalidate','Pragma':'no-cache','Expires':'0'})

@PromptServer.instance.routes.get("/danbooru_gallery/diagnose_civitai")
async def diagnose_civitai_route(request):
    """诊断 Civitai.red / Civitai.com Images/Models/Tags API 行为和 v17 检索计划。"""
    started_all = time.monotonic()
    tags = request.query.get("tags", request.query.get("search", "") or "")
    rating = request.query.get("rating", "")
    plan = _civitai_extract_search_filters(tags, rating=rating)
    tests = []

    def _run(label, base, path, call_params):
        t0 = time.monotonic()
        entry = {"name": label, "base": base, "path": path, "params": dict(call_params), "ok": False, "status": None, "category": "unknown", "elapsed_ms": None, "items": 0, "first_url_host": "", "error": ""}
        try:
            resp = _civitai_request('GET', _civitai_api_url(path, base=base), params=call_params, timeout=15)
            entry["status"] = int(resp.status_code)
            entry["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
            if resp.status_code != 200:
                entry["category"] = "http_" + str(resp.status_code)
                entry["body_head"] = str(resp.text[:240])
                return entry
            data = resp.json()
            items = data.get('items') if isinstance(data, dict) else []
            metadata = data.get('metadata') if isinstance(data, dict) else {}
            entry["items"] = len(items or [])
            entry["ok"] = isinstance(items, list)
            entry["category"] = "ok_json" if entry["ok"] else "json_unexpected"
            if isinstance(metadata, dict):
                entry["has_next_cursor"] = bool(metadata.get('nextCursor'))
                entry["has_next_page"] = bool(metadata.get('nextPage'))
            if items:
                first = items[0] if isinstance(items[0], dict) else {}
                first_url = str(first.get('url') or '')
                entry["first_url_host"] = urllib.parse.urlparse(first_url).hostname or ''
                entry["first_nsfw"] = first.get('nsfw')
                entry["first_nsfwLevel"] = first.get('nsfwLevel')
                entry["first_name"] = first.get('name')
                entry["first_id"] = first.get('id')
        except Exception as e:
            entry["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
            entry["category"] = "exception"
            entry["error"] = str(e)
        return entry

    image_params = dict(plan.get('params') or {})
    image_params.setdefault('limit', 5)
    image_params.setdefault('sort', 'Newest')
    first_term = (plan.get('model_terms') or plan.get('tag_terms') or plan.get('query_terms') or [''])[0]
    for base in [CIVITAI_BASE_URL, CIVITAI_FALLBACK_BASE_URL]:
        tests.append(_run("images_public_newest", base, "/api/v1/images", {"limit": 5, "sort": "Newest"}))
        tests.append(_run("images_from_parsed_search", base, "/api/v1/images", image_params))
        tests.append(_run("images_nsfw_false_control", base, "/api/v1/images", {"limit": 5, "sort": "Newest", "nsfw": "false"}))
        tests.append(_run("images_nsfw_true_control", base, "/api/v1/images", {"limit": 5, "sort": "Newest", "nsfw": "true"}))
        if first_term:
            tests.append(_run("tags_query_first_term", base, "/api/v1/tags", {"limit": 8, "query": first_term}))
            tests.append(_run("models_tag_first_term", base, "/api/v1/models", {"limit": 8, "tag": first_term}))
            tests.append(_run("models_query_first_term", base, "/api/v1/models", {"limit": 8, "query": first_term}))

    # Run the same path as the actual node once, but keep output compact.
    try:
        result_json = _get_civitai_images(tags=tags, limit=20, page=1, rating=rating)
        actual_count = len(json.loads(result_json or '[]'))
    except Exception as e:
        actual_count = 0
        tests.append({"name": "actual_node_search", "ok": False, "category": "exception", "error": str(e)})
    debug = dict(_CIVITAI_LAST_SEARCH_DEBUG or {})
    summary = "ok"
    if not any(t.get("ok") for t in tests):
        summary = "all_failed"
    elif actual_count > 0:
        summary = "actual_search_ok"
    elif any(t.get("base") == CIVITAI_BASE_URL and t.get("ok") for t in tests):
        summary = "red_api_ok_but_actual_empty"
    elif any(t.get("base") == CIVITAI_FALLBACK_BASE_URL and t.get("ok") for t in tests):
        summary = "fallback_com_ok_but_actual_empty"
    return web.json_response({
        "success": True,
        "diagnostic": "civitai_api_v30",
        "summary": summary,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "primary_base": CIVITAI_BASE_URL,
        "fallback_base": CIVITAI_FALLBACK_BASE_URL,
        "input_tags": tags,
        "parsed_plan": {k: plan.get(k) for k in ("params", "local_terms", "tag_terms", "model_terms", "user_terms", "query_terms", "nsfw_mode", "local_nsfw_filter", "structured", "strict_search", "favorite_mode", "has_direct_image_filter")},
        "actual_node_search_count": actual_count,
        "last_search_debug": debug,
        "elapsed_ms": int((time.monotonic() - started_all) * 1000),
        "tests": tests,
        "notes": [
            "v35：Civitai collection.* 请求只带 Cookie，不再把 search-new Authorization 发给 civitai.red；multi-search 只带搜索授权，避免两套认证互相干扰。",
            "v30：不写 sfw/nsfw 时 C站默认 any；多关键词默认严格匹配，只有 loose/mode:loose 才宽松。",
            "Images API 支持 limit、postId、modelId、modelVersionId、username、nsfw、sort、period、page；不提供真正的 prompt/tag 搜索参数。",
            "v17 对普通词先查 /api/v1/tags 和 /api/v1/models，再用 modelId 拉图片；最后才用 Images 最新页做本地 prompt/resource 过滤。",
            "Civitai 收藏夹使用本地收藏快照，可用 civitai:favorites 打开；远程 reactions 接口未在公开 REST 文档中稳定暴露。"
        ]
    }, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, indent=2))

@PromptServer.instance.routes.post("/danbooru_gallery/verify_auth")
async def verify_auth(request):
    """验证用户认证"""
    try:
        data = await request.json()
        username = data.get("username", "")
        api_key = data.get("api_key", "")

        if not username or not api_key:
            return web.json_response({"success": False, "error": "缺少用户名或API Key"})

        is_valid, is_network_error = verify_danbooru_auth(username, api_key)
        return web.json_response({"success": True, "valid": is_valid, "network_error": is_network_error})
    except Exception as e:
        logger.error(f"验证认证接口错误: {e}")
        return web.json_response({"success": False, "error": "网络错误", "network_error": True}, status=500)


@PromptServer.instance.routes.get("/danbooru_gallery/diagnose_danbooru")
async def diagnose_danbooru_route(request):
    """只读诊断 Danbooru 失败原因，不改变搜索/预览/Gelbooru 逻辑。"""
    try:
        tags = request.query.get("tags", "rating:general")
        include_direct_raw = str(request.query.get("include_direct", "1")).lower()
        include_direct = include_direct_raw not in ("0", "false", "no")
        report = await asyncio.to_thread(run_danbooru_diagnostics, tags, include_direct)
        logger.info(f"[DanbooruDiag] {report.get('status')}: {report.get('summary')}")
        for t in report.get("tests", []):
            logger.info(f"[DanbooruDiag] {t.get('label')} mode={t.get('mode')} ua={t.get('ua_label')} status={t.get('status_code')} category={t.get('category')} ok={t.get('ok')}")
        return web.json_response(report, dumps=lambda obj: json.dumps(obj, ensure_ascii=False, indent=2))
    except Exception as e:
        import traceback
        logger.error(f"[DanbooruDiag] 诊断接口失败: {e}")
        logger.error(traceback.format_exc())
        return web.json_response({"success": False, "error": str(e)}, status=500)

# 图片代理并发上限：浏览器一次打开一页会 lazy-load 多张缩略图，没有上限会导致
# 后端同时发出十几个 CDN 请求，配合全局限流会形成长队列；限到 3 并发即可让缩略图
# 平滑流入，又避免瞬时流量把 CF 的 rate rule 触发。


def _response_looks_like_image(resp):
    try:
        if resp is None or resp.status_code != 200:
            return False
        content_type = str(resp.headers.get("Content-Type", "") or "").lower()
        if content_type.startswith("image/"):
            return True
        head = resp.content[:16] if getattr(resp, "content", None) else b""
        return (
            head.startswith(b"\xff\xd8\xff") or
            head.startswith(b"\x89PNG\r\n\x1a\n") or
            head.startswith(b"GIF87a") or
            head.startswith(b"GIF89a") or
            head.startswith(b"RIFF") or
            head.startswith(b"<svg")
        )
    except Exception:
        return False


def _civitai_image_proxy_headers(url, include_credentials=True):
    """Headers for Civitai image CDN requests.

    Browser-visible thumbnails can still fail in the plugin when the backend proxy
    uses a generic script UA. This function builds an image-request-like header set
    and reuses user-copied Civitai browser Cookie/UA when available.
    """
    headers = {
        "User-Agent": DANBOORU_BROWSER_UA,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": CIVITAI_BASE_URL.rstrip("/") + "/",
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }

    if include_credentials:
        try:
            enabled, collection_raw, _default_collection_id, collection_parsed = load_civitai_remote_favorites_settings()
            search_raw, search_parsed = load_civitai_search_headers()
            for parsed in (collection_parsed if enabled else {}, search_parsed or {}):
                if not isinstance(parsed, dict):
                    continue
                for key in ("User-Agent", "Accept-Language", "Cookie"):
                    value = parsed.get(key)
                    if value:
                        headers[key] = value
        except Exception as e:
            logger.debug(f"[ImageProxy] Civitai browser headers not applied: {_safe_exception_text(e)}")

    # Keep image Accept authoritative; copied DevTools headers often contain JSON Accept.
    headers["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
    # Image CDN requests normally should not carry JSON/content headers.
    for k in ("Content-Type", "Origin", "Authorization", "X-Meili-API-Key", "x-meili-api-key"):
        headers.pop(k, None)
    return headers


def _civitai_image_proxy_request(
    url, timeout=20, allow_redirects=False, suppress_credentials=False,
):
    """Robust Civitai image fetch used only by /image_proxy.

    Attempts:
    1. Browser-like image headers through configured proxy.
    2. Browser-like image headers direct.
    3. Existing generic Civitai request path as compatibility fallback.
    4. Optional curl_cffi Chrome impersonation if installed.
    """
    attempts = []
    image_headers = _civitai_image_proxy_headers(
        url, include_credentials=not suppress_credentials,
    )
    if suppress_credentials:
        image_headers = _strip_credential_headers(image_headers)
    attempts.append(("browser_image_proxy", False, image_headers))
    attempts.append(("browser_image_direct", True, image_headers))
    generic_headers = dict(CIVITAI_HEADERS)
    generic_headers["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
    generic_headers.pop("Origin", None)
    if suppress_credentials:
        generic_headers = _strip_credential_headers(generic_headers)
    attempts.append(("generic_civitai_proxy", False, generic_headers))

    last_resp = None
    last_error = None

    for label, force_direct, headers in attempts:
        try:
            resp = _request_with_headers(
                "GET",
                url,
                headers,
                throttle=_civitai_throttle,
                timeout=timeout,
                allow_redirects=allow_redirects,
                _force_direct=force_direct,
                _suppress_credentials=suppress_credentials,
            )
            last_resp = resp
            if int(getattr(resp, "status_code", 0) or 0) in _REDIRECT_STATUSES:
                return resp
            if _response_looks_like_image(resp):
                return resp
            logger.debug(
                f"[ImageProxy:Civitai] {label} returned status={getattr(resp, 'status_code', None)} "
                f"content-type={getattr(resp, 'headers', {}).get('Content-Type', '')}: {url}"
            )
        except requests.exceptions.RequestException as e:
            last_error = e
            logger.debug(f"[ImageProxy:Civitai] {label} failed: {type(e).__name__}: {e}")

    if _CURL_CFFI_AVAILABLE:
        for label, force_direct, headers in (
            ("curl_cffi_proxy", False, image_headers),
            ("curl_cffi_direct", True, image_headers),
        ):
            try:
                resp = _curl_cffi_request_with_headers(
                    "GET",
                    url,
                    headers,
                    throttle=_civitai_throttle,
                    timeout=timeout,
                    allow_redirects=allow_redirects,
                    _force_direct=force_direct,
                    _suppress_credentials=suppress_credentials,
                )
                last_resp = resp
                if int(getattr(resp, "status_code", 0) or 0) in _REDIRECT_STATUSES:
                    return resp
                if _response_looks_like_image(resp):
                    return resp
                logger.debug(
                    f"[ImageProxy:Civitai] {label} returned status={getattr(resp, 'status_code', None)} "
                    f"content-type={getattr(resp, 'headers', {}).get('Content-Type', '')}: {url}"
                )
            except Exception as e:
                last_error = e
                logger.debug(f"[ImageProxy:Civitai] {label} failed: {type(e).__name__}: {e}")

    if last_resp is not None:
        return last_resp
    if last_error:
        raise last_error
    raise requests.exceptions.RequestException("all Civitai image proxy attempts failed")

_image_proxy_semaphore = None

def _get_image_proxy_semaphore():
    global _image_proxy_semaphore
    if _image_proxy_semaphore is None:
        _image_proxy_semaphore = asyncio.Semaphore(3)
    return _image_proxy_semaphore

def _yandere_image_proxy_headers():
    return {
        "User-Agent": DANBOORU_BROWSER_UA,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": YANDERE_BASE_URL.rstrip("/") + "/",
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }


def _yandere_image_proxy_request(
    url, timeout=20, allow_redirects=False, suppress_credentials=False,
):
    """Robust image request for yande.re/files.yande.re.

    This is a fallback path. V28 frontend first tries direct browser image
    loading for Yande.re. If direct loading fails, the proxy still attempts:
      1. requests through configured proxy
      2. requests direct
      3. curl_cffi through proxy
      4. curl_cffi direct
    """
    headers = _yandere_image_proxy_headers()
    last_resp = None
    last_error = None

    for label, force_direct in (("requests_proxy", False), ("requests_direct", True)):
        try:
            resp = _request_with_headers(
                "GET",
                url,
                headers,
                throttle=_yandere_throttle,
                timeout=timeout,
                allow_redirects=allow_redirects,
                _force_direct=force_direct,
                _suppress_credentials=suppress_credentials,
            )
            last_resp = resp
            if int(getattr(resp, "status_code", 0) or 0) in _REDIRECT_STATUSES:
                return resp
            if _response_looks_like_image(resp):
                return resp
            logger.debug(
                f"[ImageProxy:Yande] {label} returned status={getattr(resp, 'status_code', None)} "
                f"content-type={getattr(resp, 'headers', {}).get('Content-Type', '')}: {url}"
            )
        except requests.exceptions.RequestException as e:
            last_error = e
            logger.debug(f"[ImageProxy:Yande] {label} failed: {type(e).__name__}: {e}")

    if _CURL_CFFI_AVAILABLE:
        for label, force_direct in (("curl_cffi_proxy", False), ("curl_cffi_direct", True)):
            try:
                resp = _curl_cffi_request_with_headers(
                    "GET",
                    url,
                    headers,
                    throttle=_yandere_throttle,
                    timeout=timeout,
                    allow_redirects=allow_redirects,
                    _force_direct=force_direct,
                    _suppress_credentials=suppress_credentials,
                )
                last_resp = resp
                if int(getattr(resp, "status_code", 0) or 0) in _REDIRECT_STATUSES:
                    return resp
                if _response_looks_like_image(resp):
                    return resp
                logger.debug(
                    f"[ImageProxy:Yande] {label} returned status={getattr(resp, 'status_code', None)} "
                    f"content-type={getattr(resp, 'headers', {}).get('Content-Type', '')}: {url}"
                )
            except Exception as e:
                last_error = e
                logger.debug(f"[ImageProxy:Yande] {label} failed: {type(e).__name__}: {e}")

    if last_resp is not None:
        return last_resp
    if last_error:
        raise last_error
    raise requests.exceptions.RequestException("all Yande.re image proxy attempts failed")


def _supported_media_request_once(
    url, timeout=20, allow_redirects=False, suppress_credentials=False,
):
    """Dispatch one already-validated media hop to its provider-specific client."""
    host = _normalize_policy_host(urllib.parse.urlsplit(str(url or "")).hostname)
    common_kwargs = {
        "timeout": timeout,
        "allow_redirects": allow_redirects,
        "_suppress_credentials": suppress_credentials,
    }
    if _is_civitai_host(host):
        return _civitai_image_proxy_request(
            url,
            timeout=timeout,
            allow_redirects=allow_redirects,
            suppress_credentials=suppress_credentials,
        )
    if host == "yande.re" or host.endswith(".yande.re"):
        return _yandere_image_proxy_request(
            url,
            timeout=timeout,
            allow_redirects=allow_redirects,
            suppress_credentials=suppress_credentials,
        )
    if host == "gelbooru.com" or host.endswith(".gelbooru.com"):
        return _gelbooru_request("GET", url, **common_kwargs)
    if host == "donmai.us" or host.endswith(".donmai.us"):
        return _danbooru_request("GET", url, **common_kwargs)
    raise URLPolicyError("host_not_allowed", "目标 URL 主机不在允许列表", 403)


def _fetch_supported_media_url(url, timeout=20, purpose="image_proxy"):
    """Fetch supported provider media with DNS and redirect checks on every hop."""
    return _safe_fetch_with_allowlist(
        url,
        purpose,
        lambda target_url, allow_redirects=False, suppress_credentials=False: (
            _supported_media_request_once(
                target_url,
                timeout=timeout,
                allow_redirects=allow_redirects,
                suppress_credentials=suppress_credentials,
            )
        ),
        max_redirects=5,
    )


@PromptServer.instance.routes.get("/danbooru_gallery/image_proxy")
async def image_proxy(request):
    # 浏览器直连 cdn.donmai.us 会被 Cloudflare 按 cross-site <img> 请求挑战并返回 403，
    # 而后端用描述性 UA (DANBOORU_HEADERS) 能过 CF。转发一次即可让前端拿到缩略图。
    url = request.query.get("url", "")
    if not url:
        return web.json_response(
            {"success": False, "error": {"code": "empty_url", "message": "目标 URL 不能为空"}},
            status=400,
        )

    async with _get_image_proxy_semaphore():
        try:
            resp = await asyncio.to_thread(
                _fetch_supported_media_url, url, 20, "image_proxy",
            )
        except URLPolicyError as e:
            return web.json_response(
                {"success": False, "error": {"code": e.code, "message": e.public_message}},
                status=e.http_status,
            )
        except Exception as e:
            logger.warning(f"[ImageProxy] 上游请求失败: {_safe_exception_text(e)}")
            return web.Response(status=502, text="upstream error")

    if resp.status_code != 200:
        logger.debug(f"[ImageProxy] 上游返回 {resp.status_code}: {_redact_url(getattr(resp, 'url', ''))}")
        status_code = resp.status_code
        _close_outbound_response(resp)
        return web.Response(status=status_code)

    content_type = resp.headers.get("Content-Type", "application/octet-stream")
    if not _response_looks_like_image(resp):
        logger.debug(
            f"[ImageProxy] 返回非图片内容 type={content_type}: "
            f"{_redact_url(getattr(resp, 'url', ''))}"
        )
        _close_outbound_response(resp)
        return web.Response(status=502, text="upstream non-image")

    body = resp.content
    _close_outbound_response(resp)
    return web.Response(
        body=body,
        headers={
            "Content-Type": content_type,
            "Cache-Control": "public, max-age=86400",
        },
    )

# --- 保留文件中剩余的其他部分 ---

@PromptServer.instance.routes.post("/danbooru_gallery/selection_state")
async def selection_state_import(request):
    """接收前端选择状态，作为执行时 selection_data 为空的兜底。"""
    try:
        data = await request.json()
        node_id = str(data.get("node_id") or data.get("unique_id") or "__latest__")
        payload = data.get("selection_data")
        if payload is None:
            payload = data.get("selection")
        if payload is None:
            payload = data
        normalized = _normalize_selection_payload(payload)
        with _SELECTION_STATE_LOCK:
            rev = int(_SELECTION_STATE_REV.get(node_id, 0)) + 1
            _SELECTION_STATE_CACHE[node_id] = normalized
            _SELECTION_STATE_REV[node_id] = rev
            _SELECTION_STATE_CACHE["__latest__"] = normalized
            _SELECTION_STATE_REV["__latest__"] = int(_SELECTION_STATE_REV.get("__latest__", 0)) + 1
        return web.json_response({"success": True, "node_id": node_id, "count": len(normalized.get("selections") or []), "rev": rev})
    except Exception as e:
        logger.error(f"[SelectionState] import failed: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.get("/danbooru_gallery/posts")
async def get_posts_for_front(request):
    query = request.query
    tags = query.get("search[tags]", "")
    post_id = query.get("search[id]", "")
    page = query.get("page", "1")
    limit = query.get("limit", "100")
    rating = query.get("search[rating]", "")
    source = query.get("source", "danbooru")
    force_refresh = str(query.get("force_refresh") or query.get("_refresh") or "").lower() not in ("", "0", "false", "none")

    no_cache_headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    try:
        limit_i = int(limit)
        page_i = int(page)
        if limit_i <= 0 or page_i <= 0:
            raise ValueError("limit and page must be positive")
    except (TypeError, ValueError):
        error = LegacyGalleryError(
            "invalid_request", 400, "page 和 limit 必须是正整数", source=str(source or "danbooru")
        )
        return web.json_response({"items": [], "error": error.to_dict()}, status=400, headers=no_cache_headers)

    try:
        if post_id:
            posts_json_str, = await asyncio.to_thread(
                DanbooruGalleryNode.get_post_by_id_internal, post_id=post_id, source=source)
        else:
            posts_json_str, = await asyncio.to_thread(
                DanbooruGalleryNode.get_posts_internal,
                tags=tags, limit=limit_i, page=page_i, rating=rating,
                source=source, force_refresh=force_refresh,
            )
        posts_list = json.loads(posts_json_str)
        if not isinstance(posts_list, list):
            raise LegacyGalleryError(
                "schema_changed", 502, "上游响应结构异常", source=str(source or "danbooru")
            )
        return web.json_response(posts_list, headers=no_cache_headers)
    except LegacyGalleryError as legacy_error:
        # ``except ... as name`` deletes that name when the block ends, so keep the
        # exception in ``error`` for the shared response below.
        error = legacy_error
        logger.error(
            f"[LegacyPosts] source={source} code={error.code} status={error.http_status}: "
            f"{_sanitize_log_text(error.public_message)}"
        )
    except Exception as exc:
        error = _legacy_error_from_exception(str(source or "danbooru"), exc, context="画廊列表请求")
        logger.error(
            f"[LegacyPosts] source={source} code={error.code} status={error.http_status}: "
            f"{_safe_exception_text(exc)}"
        )

    headers = dict(no_cache_headers)
    if error.retry_after_seconds is not None:
        headers["Retry-After"] = str(error.retry_after_seconds)
    return web.json_response(
        {"items": [], "error": error.to_dict()},
        status=error.http_status,
        headers=headers,
    )

@PromptServer.instance.routes.get("/danbooru_gallery/autocomplete")
async def get_autocomplete(request):
    """三层查询机制：数据库 → API → 空结果"""
    try:
        query = request.query.get("query", "")
        limit = int(request.query.get("limit", "20"))
        source = (request.query.get("source", "danbooru") or "danbooru").lower()

        if not query:
            return web.json_response([])

        # Source-aware suggestions must run before the Danbooru local database.
        if source in ("yandere", "yande", "yande.re"):
            rows = _get_yandere_tag_suggestions(query, limit)
            names = [row.get('name') or row.get('tag') or '' for row in rows]
            translations = await _resolve_tag_translations(names)
            for row in rows:
                name = row.get('name') or row.get('tag') or ''
                row['translation'] = translations.get(name)
            return web.json_response(rows)
        if source in ("civitai", "civitai.red", "civitai.com"):
            civitai_results = _get_civitai_tag_suggestions(query, limit)
            if civitai_results:
                names = [row.get('name') or '' for row in civitai_results]
                translations = await _resolve_tag_translations(names)
                for row in civitai_results:
                    row['translation'] = translations.get(row.get('name') or '')
                return web.json_response(civitai_results)
            logger.debug(f"[Autocomplete] Civitai tags unavailable for '{query}', falling back to local Danbooru tags")

        # 加载配置
        config = load_autocomplete_config()

        # ✅ 第1层：查询本地SQLite数据库
        if get_db_manager and config['cache'].get('use_database_query', True):
            try:
                db = get_db_manager()
                db_results = await db.search_tags_by_prefix(query, limit)

                if db_results:
                    names = [tag.get('tag') or '' for tag in db_results]
                    translations = await _resolve_tag_translations(names)
                    # 数据库有结果，转换格式并返回
                    formatted_results = [
                        {
                            'name': tag['tag'],
                            'category': tag['category'],
                            'post_count': tag['post_count'],
                            'translation': translations.get(tag['tag']),
                            'aliases': tag.get('aliases', []),
                            'matched_alias': tag.get('matched_alias')
                        }
                        for tag in db_results
                    ]
                    logger.debug(f"[Autocomplete] 数据库查询成功: '{query}' -> {len(formatted_results)}条结果")
                    return web.json_response(formatted_results)
                else:
                    logger.debug(f"[Autocomplete] 数据库无结果: '{query}'")
            except Exception as e:
                logger.warning(f"[Autocomplete] 数据库查询失败: {e}，尝试API fallback")

        # ✅ 第2层：Fallback到Danbooru API
        if config['offline_mode'].get('fallback_to_remote', True):
            try:
                timeout = config['offline_mode'].get('remote_timeout_ms', 2000) / 1000.0

                tags_url = f"{BASE_URL}/tags.json"
                params = {
                    "search[name_or_alias_matches]": f"{query}*",
                    "search[order]": "count",
                    "limit": limit
                }

                params = _with_danbooru_auth_params(params)

                logger.debug(f"[Autocomplete] 调用远程API: '{query}' (超时: {timeout}s)")
                response = _danbooru_request("GET", tags_url, params=params, timeout=timeout)
                response.raise_for_status()

                result = response.json()

                # 排序确保按热度排列
                if isinstance(result, list):
                    result.sort(key=lambda x: x.get('post_count', 0), reverse=True)
                    names = [tag_data.get('name', '') for tag_data in result]
                    translations = await _resolve_tag_translations(names)
                    for tag_data in result:
                        tag_name = tag_data.get('name', '')
                        tag_data['translation'] = translations.get(tag_name)
                    logger.info(f"[Autocomplete] API查询成功: '{query}' -> {len(result)}条结果")

                return web.json_response(result)

            except requests.Timeout:
                logger.warning(f"[Autocomplete] 远程API超时 (>{timeout}s): '{query}'")
            except requests.exceptions.RequestException as e:
                logger.warning(f"[Autocomplete] 远程API失败: {e}")
            except Exception as e:
                logger.error(f"[Autocomplete] API调用错误: {e}")

        # ✅ 第3层：返回空结果
        logger.debug(f"[Autocomplete] 所有查询方式均无结果: '{query}'")
        return web.json_response([])

    except Exception as e:
        logger.error(f"[Autocomplete] 处理请求时发生错误: {e}")
        return web.json_response([])

@PromptServer.instance.routes.get("/danbooru_gallery/tag_catalog/status")
async def get_tag_catalog_status(request):
    """Report whether the optional WeiLin catalog can be federated safely."""

    bridge = _get_weilin_tag_bridge()
    if bridge is None:
        return web.json_response({
            "success": False,
            "available": False,
            "source": "weilin",
            "error": "WeiLin catalog bridge is unavailable",
        })
    try:
        status = await asyncio.to_thread(bridge.status)
        status["success"] = bool(status.get("available"))
        return web.json_response(status)
    except Exception as exc:
        logger.error(f"[TagCatalog] 状态检查失败: {exc}")
        return web.json_response({
            "success": False,
            "available": False,
            "source": "weilin",
            "error": "WeiLin catalog status check failed",
        })


@PromptServer.instance.routes.get("/danbooru_gallery/tag_catalog/categories")
async def get_tag_catalog_categories(request):
    """Return WeiLin's original group/subgroup tree without copying its rows."""

    bridge = _get_weilin_tag_bridge()
    if bridge is None:
        return web.json_response({
            "success": False,
            "available": False,
            "groups": [],
            "error": "WeiLin catalog bridge is unavailable",
        })
    try:
        status = await asyncio.to_thread(bridge.status)
        if not status.get("available"):
            return web.json_response({
                "success": False,
                "available": False,
                "groups": [],
                "source": "weilin",
                "error": "WeiLin catalog databases are unavailable",
            })
        result = await asyncio.to_thread(bridge.facets)
        result["success"] = True
        return web.json_response(result)
    except (WeiLinCatalogError, ValueError) as exc:
        logger.warning(f"[TagCatalog] 分类请求被拒绝: {exc}")
        return web.json_response({
            "success": False,
            "available": False,
            "groups": [],
            "error": str(exc),
        }, status=400)
    except Exception as exc:
        logger.error(f"[TagCatalog] 分类加载失败: {exc}")
        return web.json_response({
            "success": False,
            "available": False,
            "groups": [],
            "error": "WeiLin catalog categories failed",
        }, status=500)


@PromptServer.instance.routes.get("/danbooru_gallery/tag_catalog/search")
async def search_tag_catalog(request):
    """Page through atomic tags and intact WeiLin prompt phrases."""

    bridge = _get_weilin_tag_bridge()
    if bridge is None:
        return web.json_response({
            "success": False,
            "available": False,
            "items": [],
            "error": "WeiLin catalog bridge is unavailable",
        })
    try:
        result = await asyncio.to_thread(
            bridge.search,
            query=request.query.get("query", ""),
            group_id=request.query.get("group_id"),
            subgroup_id=request.query.get("subgroup_id"),
            kind=request.query.get("kind", "all"),
            page=request.query.get("page", "1"),
            cursor=request.query.get("cursor"),
            limit=request.query.get("limit", "30"),
        )
        result["available"] = True
        return web.json_response(result)
    except (WeiLinCatalogError, ValueError) as exc:
        logger.warning(f"[TagCatalog] 搜索参数被拒绝: {exc}")
        return web.json_response({
            "success": False,
            "available": True,
            "items": [],
            "error": str(exc),
        }, status=400)
    except Exception as exc:
        logger.error(f"[TagCatalog] 搜索失败: {exc}")
        return web.json_response({
            "success": False,
            "available": False,
            "items": [],
            "error": "WeiLin catalog search failed",
        }, status=500)


@PromptServer.instance.routes.get("/danbooru_gallery/tag_catalog/item")
async def get_tag_catalog_item(request):
    """Return one full WeiLin row; long prompt text is never truncated."""

    bridge = _get_weilin_tag_bridge()
    if bridge is None:
        return web.json_response({
            "success": False,
            "available": False,
            "item": None,
            "error": "WeiLin catalog bridge is unavailable",
        })
    try:
        item = await asyncio.to_thread(bridge.get_item, request.query.get("t_uuid", ""))
        if item is None:
            return web.json_response({
                "success": False,
                "available": True,
                "item": None,
                "error": "catalog item not found",
            }, status=404)
        return web.json_response({
            "success": True,
            "available": True,
            "source": "weilin",
            "item": item,
            "preservation": {
                "raw_text_unchanged": True,
                "prompt_text_truncated": False,
            },
        })
    except (WeiLinCatalogError, ValueError) as exc:
        return web.json_response({
            "success": False,
            "available": True,
            "item": None,
            "error": str(exc),
        }, status=400)
    except Exception as exc:
        logger.error(f"[TagCatalog] 单项加载失败: {exc}")
        return web.json_response({
            "success": False,
            "available": False,
            "item": None,
            "error": "WeiLin catalog item failed",
        }, status=500)


@PromptServer.instance.routes.get("/danbooru_gallery/blacklist")
async def get_blacklist(request):
    blacklist = load_blacklist()
    return web.json_response({"blacklist": blacklist})

@PromptServer.instance.routes.post("/danbooru_gallery/blacklist")
async def save_blacklist_route(request):
    try:
        data = await request.json()
        blacklist_items = data.get("blacklist", [])
        success = save_blacklist(blacklist_items)
        return web.json_response({"success": success})
    except Exception as e:
        logger.error(f"保存黑名单接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)})

@PromptServer.instance.routes.get("/danbooru_gallery/language")
async def get_language(request):
    language = load_language()
    return web.json_response({"language": language})

@PromptServer.instance.routes.post("/danbooru_gallery/language")
async def save_language_route(request):
    try:
        data = await request.json()
        language = data.get("language", "zh")
        success = save_language(language)
        return web.json_response({"success": success})
    except Exception as e:
        logger.error(f"保存语言设置接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)})

@PromptServer.instance.routes.get("/danbooru_gallery/filter_tags")
async def get_filter_tags(request):
    filter_tags, filter_enabled = load_filter_tags()
    return web.json_response({"filter_tags": filter_tags, "filter_enabled": filter_enabled})

@PromptServer.instance.routes.post("/danbooru_gallery/filter_tags")
async def save_filter_tags_route(request):
    try:
        data = await request.json()
        filter_tags = data.get("filter_tags", [])
        filter_enabled = data.get("filter_enabled", False)
        success = save_filter_tags(filter_tags, filter_enabled)
        return web.json_response({"success": success})
    except Exception as e:
        logger.error(f"保存提示词过滤设置接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)})

@PromptServer.instance.routes.get("/danbooru_gallery/ui_settings")
async def get_ui_settings(request):
    try:
        ui_settings = load_ui_settings()
        return web.json_response({
            "success": True,
            "settings": ui_settings
        })
    except Exception as e:
        logger.error(f"[UI_SETTINGS] 获取UI设置接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)})

@PromptServer.instance.routes.post("/danbooru_gallery/ui_settings")
async def save_ui_settings_route(request):
    try:
        data = await request.json()
        ui_settings = {
            "autocomplete_enabled": data.get("autocomplete_enabled", True),
            "tooltip_enabled": data.get("tooltip_enabled", True),
            "autocomplete_max_results": data.get("autocomplete_max_results", 20),
            "selected_categories": data.get("selected_categories", ["copyright", "character", "general"]),
            "multi_select_enabled": data.get("multi_select_enabled", False),
            "formatting": data.get("formatting", {"escapeBrackets": True, "replaceUnderscores": True})
        }
        success = save_ui_settings(ui_settings)
        return web.json_response({"success": success})
    except Exception as e:
        logger.error(f"保存UI设置接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)})

# ================================
# Tag翻译API接口
# ================================

@PromptServer.instance.routes.get("/danbooru_gallery/translate_tag")
async def translate_tag_route(request):
    """翻译单个tag"""
    try:
        tag = request.query.get("tag", "").strip()
        if not tag:
            return web.json_response({"success": False, "error": "缺少tag参数"})
        
        translation = (await _resolve_tag_translations([tag])).get(tag)
        return web.json_response({
            "success": True,
            "tag": tag,
            "translation": translation
        })
    except Exception as e:
        logger.error(f"翻译tag接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)})

@PromptServer.instance.routes.post("/danbooru_gallery/translate_tags_batch")
async def translate_tags_batch_route(request):
    """批量翻译tags"""
    try:
        data = await request.json()
        tags = data.get("tags", [])
        
        if not isinstance(tags, list):
            return web.json_response({"success": False, "error": "tags必须是数组"})

        translations = await _resolve_tag_translations(tags)
        return web.json_response({
            "success": True,
            "translations": translations
        })
    except Exception as e:
        logger.error(f"批量翻译tags接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)})

@PromptServer.instance.routes.get("/danbooru_gallery/search_chinese")
async def search_chinese_route(request):
    """中文搜索匹配 - 优先使用FTS5数据库搜索"""
    try:
        query = request.query.get("query", "").strip()
        limit = int(request.query.get("limit", "10"))

        if not query:
            return web.json_response({"success": True, "results": []})

        # 加载配置
        config = load_autocomplete_config()

        # ✅ 优先使用FTS5数据库搜索（速度更快，10-50ms → 2-5ms）
        if get_db_manager and config['cache'].get('use_database_query', True):
            try:
                db = get_db_manager()
                db_results = await db.search_tags_optimized(query, limit, search_type="chinese")

                if db_results:
                    names = [tag.get('tag') or '' for tag in db_results]
                    translations = await _resolve_tag_translations(names)
                    # 转换为前端期望的格式
                    formatted_results = [
                        {
                            'tag': tag['tag'],
                            'translation_cn': translations.get(tag['tag']),
                            'category': tag['category'],
                            'post_count': tag['post_count'],
                            'match_score': tag.get('match_score', 5)
                        }
                        for tag in db_results
                        if tag.get('category') != 1 and translations.get(tag['tag'])
                    ]
                    if formatted_results:
                        logger.debug(f"[SearchChinese] FTS5数据库查询: '{query}' -> {len(formatted_results)}条结果")
                        return web.json_response({
                            "success": True,
                            "query": query,
                            "results": formatted_results
                        })
            except Exception as e:
                logger.warning(f"[SearchChinese] FTS5查询失败: {e}，回退到translation_system")

        # ⚠️ Fallback: 使用旧的translation_system（线性搜索，较慢）
        try:
            static_results = translation_system.search_chinese_tags(query, limit)
            names = [item.get('english') or '' for item in static_results]
            translations = await _resolve_tag_translations(names)
            results = []
            for item in static_results:
                english = item.get('english') or ''
                translation = translations.get(english)
                if not translation:
                    continue
                result = dict(item)
                result['chinese'] = translation
                results.append(result)
            logger.debug(f"[SearchChinese] translation_system查询: '{query}' -> {len(results)}条结果")
            return web.json_response({
                "success": True,
                "query": query,
                "results": results
            })
        except Exception as e:
            logger.error(f"[SearchChinese] translation_system查询失败: {e}")
            return web.json_response({
                "success": False,
                "error": str(e)
            })

    except Exception as e:
        logger.error(f"中文搜索接口错误: {e}")
        return web.json_response({"success": False, "error": str(e)})

@PromptServer.instance.routes.get("/danbooru_gallery/autocomplete_with_translation")
async def get_autocomplete_with_translation(request):
    """带翻译的自动补全API - 三层查询机制：数据库 → API → 空结果"""
    try:
        query = request.query.get("query", "")
        limit = int(request.query.get("limit", "20"))
        source = (request.query.get("source", "danbooru") or "danbooru").lower()

        if not query:
            return web.json_response([])

        # v46: the Chinese UI uses this endpoint even for English tag input.
        # Respect the selected gallery source instead of always returning Danbooru tags.
        if source in ("yandere", "yande", "yande.re"):
            rows = _get_yandere_tag_suggestions(query, limit)
            names = [row.get('name') or row.get('tag') or '' for row in rows]
            translations = await _resolve_tag_translations(names)
            for row in rows:
                name = row.get('name') or row.get('tag') or ''
                row['translation'] = translations.get(name)
            return web.json_response(rows)
        if source in ("civitai", "civitai.red", "civitai.com"):
            civitai_results = _get_civitai_tag_suggestions(query, limit)
            if civitai_results:
                names = [row.get('name') or '' for row in civitai_results]
                translations = await _resolve_tag_translations(names)
                for row in civitai_results:
                    row['translation'] = translations.get(row.get('name') or '')
                return web.json_response(civitai_results)
            logger.debug(f"[AutocompleteTranslation] Civitai tags unavailable for '{query}', falling back to local Danbooru tags")

        # 加载配置
        config = load_autocomplete_config()

        # ✅ 第1层：查询本地SQLite数据库（已包含翻译）
        if get_db_manager and config['cache'].get('use_database_query', True):
            try:
                db = get_db_manager()
                db_results = await db.search_tags_by_prefix(query, limit)

                if db_results:
                    names = [tag.get('tag') or '' for tag in db_results]
                    translations = await _resolve_tag_translations(names)
                    # 数据库有结果，转换格式（已包含translation_cn）
                    formatted_results = [
                        {
                            'name': tag['tag'],
                            'category': tag['category'],
                            'post_count': tag['post_count'],
                            'translation': translations.get(tag['tag']),
                            'aliases': tag.get('aliases', []),
                            'matched_alias': tag.get('matched_alias')
                        }
                        for tag in db_results
                    ]
                    logger.debug(f"[AutocompleteTranslation] 数据库查询成功: '{query}' -> {len(formatted_results)}条结果")
                    return web.json_response(formatted_results)
                else:
                    logger.debug(f"[AutocompleteTranslation] 数据库无结果: '{query}'")
            except Exception as e:
                logger.warning(f"[AutocompleteTranslation] 数据库查询失败: {e}，尝试API fallback")

        # ✅ 第2层：Fallback到Danbooru API（需要手动添加翻译）
        if config['offline_mode'].get('fallback_to_remote', True):
            try:
                timeout = config['offline_mode'].get('remote_timeout_ms', 2000) / 1000.0

                tags_url = f"{BASE_URL}/tags.json"
                params = {
                    "search[name_or_alias_matches]": f"{query}*",
                    "search[order]": "count",
                    "limit": limit
                }

                params = _with_danbooru_auth_params(params)

                logger.debug(f"[AutocompleteTranslation] 调用远程API: '{query}' (超时: {timeout}s)")
                response = _danbooru_request("GET", tags_url, params=params, timeout=timeout)
                response.raise_for_status()

                result = response.json()

                # 为每个tag添加翻译
                if isinstance(result, list):
                    names = [tag_data.get('name', '') for tag_data in result]
                    translations = await _resolve_tag_translations(names)
                    for tag_data in result:
                        tag_name = tag_data.get('name', '')
                        tag_data['translation'] = translations.get(tag_name)

                    logger.info(f"[AutocompleteTranslation] API查询成功: '{query}' -> {len(result)}条结果")

                return web.json_response(result)

            except requests.Timeout:
                logger.warning(f"[AutocompleteTranslation] 远程API超时 (>{timeout}s): '{query}'")
            except requests.exceptions.RequestException as e:
                logger.warning(f"[AutocompleteTranslation] 远程API失败: {e}")
            except Exception as e:
                logger.error(f"[AutocompleteTranslation] API调用错误: {e}")

        # ✅ 第3层：返回空结果
        logger.debug(f"[AutocompleteTranslation] 所有查询方式均无结果: '{query}'")
        return web.json_response([])

    except Exception as e:
        logger.error(f"[AutocompleteTranslation] 处理请求时发生错误: {e}")
        return web.json_response([])

class DanbooruGalleryNode:
    _post_cache = {}

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {},
            "optional": {
                # 兼容前端 bypass 解析：
                # 该节点原本只有 hidden 输入，某些前端 bypass 路径会在无可见输入时抛出
                # "No input found for flattened id ... slot [0]"。
                # 增加可选透传槽位后，bypass 时不会因缺少输入槽而直接报错。
                "bypass_image": ("IMAGE", {"forceInput": True}),
                "bypass_prompts": ("STRING", {"forceInput": True}),
            },
            "hidden": {
                "selection_data": ("STRING", {"default": "{}", "multiline": True, "forceInput": True}),
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "prompts")
    OUTPUT_IS_LIST = (True, True)
    FUNCTION = "get_selected_data"
    CATEGORY = "danbooru"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, selection_data="{}", unique_id=None, **kwargs):
        return f"{selection_data}|{_selection_rev(unique_id)}"

    def get_selected_data(self, selection_data="{}", unique_id=None, **kwargs):
        """处理选中的图片数据，支持单选和多选模式"""
        payload = _normalize_selection_payload(selection_data)
        if not payload.get("selections"):
            payload = _get_cached_selection_payload(unique_id)
        selections = payload.get("selections", [])
        if not selections:
            return ([torch.zeros(1, 1, 1, 3)], [""])

        images = []
        prompts = []

        try:
            for sel in selections:
                prompt = sel.get("prompt", "") or sel.get("tag_string", "") or sel.get("tags", "")
                image_candidates = [
                    sel.get("image_url"),
                    sel.get("file_url"),
                    sel.get("large_file_url"),
                    sel.get("preview_file_url"),
                ]
                prompts.append(prompt)

                loaded = False
                for image_url in [u for u in image_candidates if u]:
                    response = None
                    try:
                        response = _fetch_supported_media_url(
                            str(image_url), timeout=30, purpose="selection_media",
                        )
                        response.raise_for_status()
                        if not _response_looks_like_image(response):
                            raise ValueError("upstream returned non-image content")
                        img = Image.open(io.BytesIO(response.content)).convert("RGB")
                        img_array = np.array(img).astype(np.float32) / 255.0
                        tensor = torch.from_numpy(img_array)[None,]
                        images.append(tensor)
                        loaded = True
                        break
                    except URLPolicyError as e:
                        logger.warning(
                            f"加载图片被 URL 安全策略拒绝 code={e.code}: "
                            f"{_redact_url(image_url)}"
                        )
                    except Exception as e:
                        logger.error(
                            f"加载图片失败 {_redact_url(image_url)}: {_safe_exception_text(e)}"
                        )
                    finally:
                        if response is not None:
                            _close_outbound_response(response)
                if not loaded:
                    images.append(torch.zeros(1, 1, 1, 3))

            if not images:
                return ([torch.zeros(1, 1, 1, 3)], [""])

        except Exception as e:
            logger.error(f"Error processing selection in DanbooruGalleryNode: {e}")
            return ([torch.zeros(1, 1, 1, 3)], [""])

        return (images, prompts)
    
    @staticmethod
    def _get_danbooru_posts(tags: str, limit: int = 100, page: int = 1, rating: str = None):
        posts_url = f"{DANBOORU_BASE_URL}/posts.json"
        tags = _normalize_danbooru_query_tags(tags)

        # 分离 date: 标签和其他标签
        date_tag = ''
        other_tags = []
        for tag in tags.split(' '):
            if tag.strip().startswith('date:'):
                date_tag = tag.strip()
            elif tag.strip():
                other_tags.append(tag.strip())

        # 限制其他标签的数量（Danbooru 匿名/普通账号搜索 tag 数受限）
        if len(other_tags) > 2:
            other_tags = other_tags[:2]

        final_tags = ' '.join(other_tags)
        if date_tag:
            final_tags = f"{final_tags} {date_tag}".strip()

        if rating and rating.lower() != 'all':
            allowed = {'general', 'sensitive', 'questionable', 'explicit', 'g', 's', 'q', 'e'}
            rating_values = [r.strip().lower() for r in rating.split(',') if r.strip()]
            rating_values = [r for r in rating_values if r in allowed]
            if len(rating_values) == 1:
                final_tags = f"{final_tags} rating:{rating_values[0]}".strip()
            elif len(rating_values) > 1:
                or_tags = ' '.join(f"~rating:{r}" for r in rating_values)
                final_tags = f"{final_tags} {or_tags}".strip()

        bridge_settings = load_browser_bridge_settings()
        if bridge_settings.get("enabled") and bridge_settings.get("prefer"):
            logger.info("[Danbooru] 使用浏览器桥接优先模式获取 posts.json")
            return _danbooru_browser_bridge_get_posts(tags=tags, limit=limit, page=page, rating=rating)

        params = _with_danbooru_auth_params({"tags": final_tags.strip(), "limit": limit, "page": page})
        try:
            response = _danbooru_request("GET", posts_url, params=params, timeout=_DANBOORU_TIMEOUT)
            response.raise_for_status()
            return response.text
        except Exception as e:
            if bridge_settings.get("enabled"):
                logger.warning(f"[Danbooru] 常规请求失败，尝试浏览器桥接 fallback: {_safe_exception_text(e)}")
                return _danbooru_browser_bridge_get_posts(tags=tags, limit=limit, page=page, rating=rating)
            raise

    @staticmethod
    def _get_gelbooru_posts(tags: str, limit: int = 100, page: int = 1, rating: str = None):
        """Gelbooru search.

        Primary path: DAPI JSON with user_id/api_key when configured.
        Fallback path: public HTML search page. This keeps Gelbooru usable after a clean
        install where settings.json has no API credentials.
        """
        posts_url = f"{GELBOORU_BASE_URL}/index.php"
        final_tags = _gelbooru_build_tags(tags, rating=rating)
        params = {
            "page": "dapi",
            "s": "post",
            "q": "index",
            "json": "1",
            "tags": final_tags,
            "limit": max(1, min(int(limit or 100), 100)),
            # Gelbooru DAPI uses page number starting from 0.
            "pid": max(int(page or 1) - 1, 0),
        }
        params.update(_load_gelbooru_auth_params())

        try:
            response = _gelbooru_request("GET", posts_url, params=params, timeout=20)
            if response.status_code == 200:
                try:
                    data = response.json()
                    normalized = []
                    for raw_post in _normalize_gelbooru_response(data):
                        post = _gelbooru_post_to_danbooru_shape(raw_post)
                        if post and post.get("preview_file_url"):
                            normalized.append(post)
                    if normalized:
                        return json.dumps(normalized, ensure_ascii=False)
                    logger.warning("[Gelbooru] DAPI 返回 200 但没有可用图片，转 HTML fallback")
                except Exception as e:
                    logger.error(f"[Gelbooru] JSON 解析失败，转 HTML fallback: {_safe_exception_text(e)}")
            elif response.status_code == 401:
                logger.warning("[Gelbooru] DAPI 401：未配置或认证失败，转 HTML fallback")
            elif response.status_code == 403 and _is_cloudflare_challenge(response):
                logger.warning("[Gelbooru] DAPI Cloudflare challenge，转 HTML fallback")
            else:
                logger.warning(f"[Gelbooru] DAPI HTTP {response.status_code}，转 HTML fallback")
        except Exception as e:
            logger.error(f"[Gelbooru] DAPI 请求失败，转 HTML fallback: {_safe_exception_text(e)}")

        posts = _get_gelbooru_posts_html(tags=tags, limit=limit, page=page, rating=rating)
        return json.dumps(posts, ensure_ascii=False)

    @staticmethod
    def get_post_by_id_internal(post_id: str, source: str = "danbooru"):
        source = (source or "danbooru").lower()
        try:
            if source == "civitai":
                # Civitai Images API 没有稳定的 image-id 单图公开端点；用 postId 做 best-effort。
                return (_get_civitai_images(f"post:{str(post_id).strip()}", limit=1, page=1),)
            if source == "yandere":
                return (_get_yandere_post_by_id(post_id),)
            if source == "gelbooru":
                posts_url = f"{GELBOORU_BASE_URL}/index.php"
                params = {
                    "page": "dapi",
                    "s": "post",
                    "q": "index",
                    "json": "1",
                    "id": str(post_id).strip(),
                    "limit": 1,
                }
                params.update(_load_gelbooru_auth_params())
                try:
                    response = _gelbooru_request("GET", posts_url, params=params, timeout=15)
                    if response.status_code == 200:
                        data = response.json()
                        posts = []
                        for raw_post in _normalize_gelbooru_response(data):
                            post = _gelbooru_post_to_danbooru_shape(raw_post)
                            if post:
                                posts.append(post)
                        if posts:
                            return (json.dumps(posts, ensure_ascii=False),)
                    else:
                        logger.warning(f"[Gelbooru] DAPI 获取单图失败 {post_id}: HTTP {response.status_code}，转 HTML fallback")
                except Exception as e:
                    logger.warning(f"[Gelbooru] DAPI 获取单图异常 {post_id}: {_safe_exception_text(e)}，转 HTML fallback")

                post = _get_gelbooru_post_by_id_html(str(post_id).strip())
                return (json.dumps([post] if post else [], ensure_ascii=False),)

            bridge_settings = load_browser_bridge_settings()
            if bridge_settings.get("enabled") and bridge_settings.get("prefer"):
                return (_danbooru_browser_bridge_get_post_by_id(post_id),)
            params = _with_danbooru_auth_params({})
            try:
                response = _danbooru_request("GET", f"{DANBOORU_BASE_URL}/posts/{post_id}.json", params=params, timeout=_DANBOORU_TIMEOUT)
                if response.status_code != 200:
                    logger.error(f"[Danbooru] 获取单图失败 {post_id}: HTTP {response.status_code}")
                    if bridge_settings.get("enabled"):
                        return (_danbooru_browser_bridge_get_post_by_id(post_id),)
                    if response.status_code == 404:
                        return ("[]",)
                    raise _legacy_error_from_response('danbooru', response, context='Danbooru 单图请求')
                return (json.dumps([response.json()], ensure_ascii=False),)
            except Exception as e:
                if bridge_settings.get("enabled"):
                    logger.warning(f"[Danbooru] 常规单图请求失败，尝试浏览器桥接 fallback: {_safe_exception_text(e)}")
                    return (_danbooru_browser_bridge_get_post_by_id(post_id),)
                raise
        except LegacyGalleryError as error:
            logger.error(f"获取单图发生错误 source={source}, id={post_id}: code={error.code}")
            raise
        except Exception as e:
            error = _legacy_error_from_exception(source, e, context="获取单图")
            logger.error(f"获取单图发生错误 source={source}, id={post_id}: {_safe_exception_text(e)}")
            raise error from e

    @staticmethod
    def get_posts_internal(tags: str, limit: int = 100, page: int = 1, rating: str = None, source: str = "danbooru", force_refresh: bool = False):
        settings = load_settings()
        cache_enabled = settings.get("cache_enabled", True)
        max_cache_age = settings.get("max_cache_age", 3600)
        source = (source or settings.get("default_source", "danbooru") or "danbooru").lower()
        if source not in ("danbooru", "gelbooru", "civitai", "yandere"):
            source = "danbooru"

        rating_key = ','.join(sorted(r.strip().lower() for r in (rating or '').split(',') if r.strip()))
        cache_key = f"{source}:{tags}:{limit}:{page}:{rating_key}"

        if cache_enabled and not force_refresh:
            if cache_key in DanbooruGalleryNode._post_cache:
                cached_data, timestamp = DanbooruGalleryNode._post_cache[cache_key]
                if time.time() - timestamp < max_cache_age:
                    return (_validate_legacy_posts_json(cached_data, source),)
        elif force_refresh:
            # Manual refresh must bypass stale cached pages, especially Civitai favorites.
            DanbooruGalleryNode._post_cache.pop(cache_key, None)

        try:
            if source == "gelbooru":
                result_text = DanbooruGalleryNode._get_gelbooru_posts(tags=tags, limit=limit, page=page, rating=rating)
            elif source == "yandere":
                result_text = _get_yandere_posts(tags=tags, limit=limit, page=page, rating=rating)
            elif source == "civitai":
                result_text = _get_civitai_images(tags=tags, limit=limit, page=page, rating=rating, force_refresh=force_refresh)
            else:
                result_text = DanbooruGalleryNode._get_danbooru_posts(tags=tags, limit=limit, page=page, rating=rating)

            result_text = _validate_legacy_posts_json(result_text, source)
            if cache_enabled:
                DanbooruGalleryNode._post_cache[cache_key] = (result_text, time.time())
                if len(DanbooruGalleryNode._post_cache) > 200:
                    oldest_key = min(DanbooruGalleryNode._post_cache.keys(), key=lambda k: DanbooruGalleryNode._post_cache[k][1])
                    del DanbooruGalleryNode._post_cache[oldest_key]
            return (result_text,)
        except LegacyGalleryError as error:
            logger.error(f"[{source}] 网络请求失败: code={error.code} status={error.http_status}")
            raise
        except Exception as e:
            error = _legacy_error_from_exception(source, e, context="画廊列表请求")
            logger.error(f"[{source}] 画廊列表请求失败: {_safe_exception_text(e)}")
            raise error from e

# ComfyUI 必须的字典
def get_node_class_mappings():
    return {
        "DanbooruGalleryNode": DanbooruGalleryNode
    }

def get_node_display_name_mappings():
    return {
        "DanbooruGalleryNode": "D站画廊 (Danbooru Gallery)"
    }

NODE_CLASS_MAPPINGS = get_node_class_mappings()
NODE_DISPLAY_NAME_MAPPINGS = get_node_display_name_mappings()
