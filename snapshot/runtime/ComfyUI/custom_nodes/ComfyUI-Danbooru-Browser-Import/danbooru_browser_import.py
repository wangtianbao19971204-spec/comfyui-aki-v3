import json
import ipaddress
import os
import re
import sqlite3
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit
from aiohttp import web
from server import PromptServer

DATA_FILE = os.path.join(os.path.dirname(__file__), "latest_danbooru_browser_import_v05.json")
LATEST = {}
ROUTE = "/danbooru_browser_import_v05"
VERSION = "0.6"
WORKBENCH_ROUTE = "/unified-workbench/browser-import"
WORKBENCH_EVENT = "unified-workbench-browser-prompt"
MAX_REQUEST_BYTES = 256 * 1024
MAX_STORED_BYTES = 1024 * 1024
TEXT_LIMITS = {"positive": 65536, "negative": 16384, "title": 256, "post_id": 64}
IMPORT_FIELDS = frozenset({"positive", "negative", "source_url", "title", "post_id", "image_url"})
INBOX_LIMIT = 32
ACCEPTED_LIMIT = 128
CLAIM_TTL_SECONDS = 60
# Only public post/image/model pages are source links. Further supported sites
# belong in this explicit registry, not in a permissive arbitrary-URL fallback.
SOURCE_URL_RULES = (
    (("donmai.us",), True, re.compile(r"^/posts/[0-9]+/?$")),
    (("civitai.com", "www.civitai.com", "civitai.red", "www.civitai.red"), False,
     re.compile(r"^/(?:images|models|posts)/[0-9]+(?:/[A-Za-z0-9._~-]+)?/?$")),
    (("pixai.art", "www.pixai.art"), False,
     re.compile(r"^/(?:[A-Za-z]{2}(?:-[A-Za-z]{2})?/)?artwork/[0-9]+/?$")),
    (("yande.re", "www.yande.re"), False, re.compile(r"^/post/show/[0-9]+/?$")),
)
IMAGE_URL_RULES = (
    (("donmai.us",), True),
    (("image.civitai.com",), False),
    (("images-ng.pixai.art", "imagedelivery.net"), False),
    (("files.yande.re", "assets.yande.re"), False),
    (("gelbooru.com",), True),
)


class InvalidBrowserImport(ValueError):
    """Validation failures have fixed codes; never include supplied values."""


def _is_loopback(request):
    try:
        address = ipaddress.ip_address(request.remote or "")
        return address.is_loopback or bool(getattr(address, "ipv4_mapped", None)
                                           and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def _loopback_authority(value):
    """Parse a literal local authority without DNS lookups or forwarded headers."""
    if not isinstance(value, str) or not value or len(value) > 256:
        return None
    if any(character.isspace() or ord(character) < 32 for character in value) or value.endswith(":"):
        return None
    try:
        parsed = urlsplit("//" + value)
        if (not parsed.netloc or parsed.path or parsed.query or parsed.fragment
                or parsed.username is not None or parsed.password is not None):
            return None
        host = (parsed.hostname or "").lower()
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            return None
        if host == "localhost":
            return host, port
        address = ipaddress.ip_address(host)
        if address.is_loopback or (getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback):
            return str(address), port
    except ValueError:
        pass
    return None


def _workbench_request_error(request):
    if not _is_loopback(request):
        return "loopback_required"
    authority = _loopback_authority(request.headers.get("Host", ""))
    if authority is None:
        return "loopback_host_required"
    origin = request.headers.get("Origin")
    # Anonymous GM_xmlhttpRequest and direct local clients may omit Origin.
    # An ordinary page must present exactly this local application's origin.
    if origin is None:
        return None
    if not isinstance(origin, str) or len(origin) > 512:
        return "origin_not_allowed"
    try:
        parsed = urlsplit(origin)
        origin_authority = _loopback_authority(parsed.netloc)
        scheme = request.scheme.lower()
        if (scheme not in {"http", "https"} or parsed.scheme.lower() != scheme
                or parsed.path or parsed.query or parsed.fragment or origin_authority is None):
            return "origin_not_allowed"
        default_port = 443 if scheme == "https" else 80
        if (authority[0], authority[1] or default_port) != (origin_authority[0], origin_authority[1] or default_port):
            return "origin_not_allowed"
    except (AttributeError, ValueError):
        return "origin_not_allowed"
    return None


def _host_matches(host, hosts, include_subdomains):
    return any(host == known or include_subdomains and host.endswith("." + known)
               for known in hosts)


def _public_url(value, *, image=False):
    if not isinstance(value, str) or len(value) > 2048:
        raise InvalidBrowserImport("invalid_url")
    value = value.strip()
    if image and not value:
        return ""
    if not value or any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        raise InvalidBrowserImport("invalid_url")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme.lower() != "https" or parsed.port not in {None, 443}
                or parsed.username is not None or parsed.password is not None):
            raise InvalidBrowserImport("invalid_url")
    except ValueError:
        raise InvalidBrowserImport("invalid_url") from None
    path = parsed.path
    decoded_path = unquote(path)
    if (not path.startswith("/") or path.startswith("//")
            or any(part in {".", ".."} for part in decoded_path.split("/"))
            or any(ord(character) < 32 or character.isspace() for character in decoded_path)
            or "\\" in decoded_path):
        raise InvalidBrowserImport("invalid_url")
    if image:
        accepted = any(_host_matches(host, hosts, subdomains) for hosts, subdomains in IMAGE_URL_RULES)
        if path == "/" or decoded_path.lower().startswith(("/api/", "/login", "/auth/", "/account")):
            accepted = False
    elif host in {"gelbooru.com", "www.gelbooru.com"}:
        values = {}
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key in {"page", "s", "id"}:
                if key in values:
                    raise InvalidBrowserImport("invalid_url")
                values[key] = value
        if (path != "/index.php" or values.get("page") != "post"
                or values.get("s") != "view" or not re.fullmatch(r"[0-9]+", values.get("id", ""))):
            raise InvalidBrowserImport("unsupported_url")
        return "https://gelbooru.com/index.php?page=post&s=view&id=" + values["id"]
    else:
        accepted = any(_host_matches(host, hosts, subdomains) and pattern.fullmatch(path)
                       for hosts, subdomains, pattern in SOURCE_URL_RULES)
    if not accepted:
        raise InvalidBrowserImport("unsupported_url")
    if not image and host in {"pixai.art", "www.pixai.art"}:
        path = "/artwork/" + path.rstrip("/").split("/")[-1]
        host = "pixai.art"
    elif not image and host.startswith("www."):
        host = host[4:]
    # Only Gelbooru's three public post-identity keys survive. Credentials and
    # every other query/fragment never enter storage or the availability event.
    return urlunsplit(("https", host, path, "", ""))


def _text_field(data, key, *, required=False):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > TEXT_LIMITS[key]:
        raise InvalidBrowserImport("invalid_text")
    allowed_controls = "\r\n\t" if key in {"positive", "negative"} else ""
    if any(ord(character) < 32 and character not in allowed_controls for character in value):
        raise InvalidBrowserImport("invalid_text")
    value = value.strip()
    if required and not value:
        raise InvalidBrowserImport("empty_positive")
    return value


def _normalize_browser_import(data):
    if not isinstance(data, dict) or set(data) - IMPORT_FIELDS:
        raise InvalidBrowserImport("invalid_fields")
    positive = _text_field(data, "positive", required=True)
    negative = _text_field(data, "negative")
    title = _text_field(data, "title")
    post_id = data.get("post_id", "")
    if isinstance(post_id, int) and not isinstance(post_id, bool):
        post_id = str(post_id)
    if not isinstance(post_id, str) or len(post_id) > TEXT_LIMITS["post_id"] or post_id and not re.fullmatch(r"[0-9]+", post_id):
        raise InvalidBrowserImport("invalid_post_id")
    return {
        "positive": positive,
        "negative": negative,
        "source_url": _public_url(data.get("source_url")),
        "title": title,
        "post_id": post_id,
        "image_url": _public_url(data.get("image_url", ""), image=True),
    }


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidBrowserImport("invalid_json")
        result[key] = value
    return result


async def _read_browser_request(request):
    if request.content_type != "application/json":
        raise InvalidBrowserImport("json_required")
    if request.content_length is not None and request.content_length > MAX_REQUEST_BYTES:
        raise InvalidBrowserImport("payload_too_large")
    body = bytearray()
    async for block in request.content.iter_chunked(8192):
        if len(body) + len(block) > MAX_REQUEST_BYTES:
            raise InvalidBrowserImport("payload_too_large")
        body.extend(block)
    try:
        return json.loads(body.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeError, ValueError, RecursionError):
        raise InvalidBrowserImport("invalid_json") from None


def _canonical_uuid(value):
    try:
        return isinstance(value, str) and len(value) == 36 and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _no_links(path):
    for candidate in [*reversed(path.parents), path]:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                or stat.S_ISREG(info.st_mode) and info.st_nlink > 1):
            raise InvalidBrowserImport("unsafe_external_path")


def _inbox_path():
    # In a deployed plugin this is <runtime>/ComfyUI/custom_nodes/<plugin>.
    # Source-checkout execution must configure an external root when its default
    # sibling would fall inside Git; mutable prompts can never become sources.
    module_path = Path(__file__).absolute()
    runtime_root = module_path.parents[3]
    value = os.environ.get("COMFYUI_EXTERNAL_ROOT")
    root = Path(value) if value else runtime_root.parent / "ComfyUI-local"
    if (not root.is_absolute() or ".." in root.parts or str(root).startswith(("\\\\", "//"))
            or root == Path(root.anchor) or any(ord(c) < 32 for c in str(root))
            or any(":" in part or part.rstrip(" .") != part or part.casefold() == ".git" for part in root.parts[1:])):
        raise InvalidBrowserImport("unsafe_external_path")
    _no_links(root)
    root = root.resolve()
    checkouts = [ancestor.resolve() for ancestor in module_path.parents if (ancestor / ".git").exists()]
    maintained = runtime_root / "maintenance" / "comfyui"
    if (maintained / ".git").exists():
        checkouts.append(maintained.resolve())
    if any(root == checkout or root.is_relative_to(checkout) for checkout in checkouts):
        raise InvalidBrowserImport("external_state_inside_public_checkout")
    path = root / "mutable-data" / "browser-import" / "inbox.sqlite3"
    for candidate in (path, *(Path(str(path) + suffix) for suffix in ("-journal", "-wal", "-shm"))):
        _no_links(candidate)
    return path


INBOX_DDL = """
CREATE TABLE IF NOT EXISTS inbox (
    import_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at REAL NOT NULL,
    receiver_id TEXT, claim_token TEXT, claim_expires_at REAL
);
CREATE TABLE IF NOT EXISTS accepted (
    import_id TEXT PRIMARY KEY, receiver_id TEXT NOT NULL,
    claim_token TEXT NOT NULL, accepted_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS state (
    id INTEGER PRIMARY KEY CHECK (id = 1), payload_json TEXT NOT NULL,
    received_at_ns INTEGER NOT NULL
);
"""


@contextmanager
def _inbox_connection(*, write=False):
    path = _inbox_path()
    if not write and not path.exists():
        yield None
        return
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        _no_links(path)
    connection = sqlite3.connect(str(path) if write else path.as_uri() + "?mode=ro",
                                 timeout=5, uri=not write)
    connection.row_factory = sqlite3.Row
    try:
        schema = connection.execute("PRAGMA user_version").fetchone()[0]
        if write and schema == 0:
            if connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone():
                raise InvalidBrowserImport("storage_schema_failed")
            connection.executescript(INBOX_DDL)
            connection.execute("PRAGMA user_version = 1")
        elif schema != 1:
            raise InvalidBrowserImport("storage_schema_failed")
        if write:
            connection.execute("BEGIN IMMEDIATE")
        else:
            connection.execute("BEGIN")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _stored_payload(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_STORED_BYTES:
        raise InvalidBrowserImport("storage_read_failed")
    data = json.loads(raw, object_pairs_hook=_unique_json_object)
    if (not isinstance(data, dict) or set(data) != IMPORT_FIELDS | {"import_id", "destination"}
            or data.get("destination") != "workbench" or not _canonical_uuid(data.get("import_id"))):
        raise InvalidBrowserImport("storage_read_failed")
    normalized = _normalize_browser_import({key: data[key] for key in IMPORT_FIELDS})
    if any(data[key] != normalized[key] for key in IMPORT_FIELDS):
        raise InvalidBrowserImport("storage_read_failed")
    return data


def _legacy_mtime_ns():
    try:
        return os.stat(DATA_FILE).st_mtime_ns
    except FileNotFoundError:
        return 0


def _state_latest(connection):
    if connection is None:
        return None, 0
    row = connection.execute("SELECT payload_json, received_at_ns FROM state WHERE id = 1").fetchone()
    if row is None:
        return None, 0
    return _stored_payload(row["payload_json"]), row["received_at_ns"]


def _load_workbench_inbox():
    with _inbox_connection() as connection:
        if connection is None:
            return [], None
        rows = connection.execute("SELECT payload_json FROM inbox ORDER BY created_at, rowid LIMIT ?",
                                  (INBOX_LIMIT + 1,)).fetchall()
        if len(rows) > INBOX_LIMIT:
            raise InvalidBrowserImport("storage_read_failed")
        items = [_stored_payload(row["payload_json"]) for row in rows]
        latest, received_at_ns = _state_latest(connection)
    return items, latest if received_at_ns > _legacy_mtime_ns() else None


def _load_workbench_latest():
    return _load_workbench_inbox()[1]


def _legacy_compatible(payload):
    return {**payload, "merged_tags": payload["positive"], "prompt": payload["positive"],
            "negative_prompt": payload["negative"], "_route": WORKBENCH_ROUTE,
            "_plugin_version": VERSION}


def _store_workbench(payload):
    global LATEST
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with _inbox_connection(write=True) as connection:
        if connection.execute("SELECT count(*) FROM inbox").fetchone()[0] >= INBOX_LIMIT:
            raise InvalidBrowserImport("inbox_full")
        now_ns = time.time_ns()
        connection.execute("INSERT INTO inbox(import_id,payload_json,created_at) VALUES(?,?,?)",
                           (payload["import_id"], raw, now_ns / 1_000_000_000))
        connection.execute("INSERT OR REPLACE INTO state VALUES(1,?,?)", (raw, now_ns))
    LATEST = _legacy_compatible(payload)


def _load_latest(force=False):
    global LATEST
    if LATEST and not force:
        return LATEST
    try:
        latest = _load_workbench_latest()
        if latest is not None:
            LATEST = _legacy_compatible(latest)
            return LATEST
    except Exception:
        LATEST = {"_error": "failed_to_read_latest_import"}
        return LATEST
    LATEST = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                LATEST = json.load(f)
        except Exception:
            LATEST = {"_error": "failed_to_read_latest_import"}
    return LATEST


def _save_latest(data):
    global LATEST
    saved = data or {}
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(saved, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)
    LATEST = saved


def _mtime_token():
    try:
        with _inbox_connection() as connection:
            latest, received_at_ns = _state_latest(connection)
        return str(max(_legacy_mtime_ns(), received_at_ns)) if latest or os.path.exists(DATA_FILE) else "no-file"
    except Exception:
        return "no-file"


def _cors_json(data, status=200):
    resp = web.json_response(data, status=status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Requested-With"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


def _workbench_json(data, status=200):
    # GM_xmlhttpRequest sends directly without browser CORS permission. Do not
    # grant arbitrary webpages access to the workbench draft/recovery payload.
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


@PromptServer.instance.routes.post(WORKBENCH_ROUTE)
async def unified_workbench_browser_import_post(request):
    request_error = _workbench_request_error(request)
    if request_error:
        return _workbench_json({"ok": False, "error": request_error}, status=403)
    try:
        normalized = _normalize_browser_import(await _read_browser_request(request))
    except InvalidBrowserImport as error:
        code = str(error)
        status = 413 if code == "payload_too_large" else 415 if code == "json_required" else 400
        return _workbench_json({"ok": False, "error": code}, status=status)
    except Exception:
        return _workbench_json({"ok": False, "error": "invalid_request"}, status=400)
    payload = {"import_id": str(uuid.uuid4()), **normalized, "destination": "workbench"}
    try:
        _store_workbench(payload)
    except InvalidBrowserImport as error:
        if str(error) == "inbox_full":
            return _workbench_json({"ok": False, "delivery": "failed", "error": "inbox_full"}, status=409)
        return _workbench_json({"ok": False, "delivery": "failed", "error": "storage_write_failed"}, status=500)
    except Exception:
        return _workbench_json({"ok": False, "delivery": "failed", "error": "storage_write_failed"}, status=500)
    try:
        PromptServer.instance.send_sync(WORKBENCH_EVENT, payload)
    except Exception:
        return _workbench_json({
            "ok": True, "delivery": "stored", "realtime_notified": False,
            "realtime_error": "notification_failed", "payload": payload,
        }, status=202)
    return _workbench_json({"ok": True, "delivery": "stored", "realtime_notified": True, "payload": payload})


@PromptServer.instance.routes.get(WORKBENCH_ROUTE)
async def unified_workbench_browser_import_get(request):
    request_error = _workbench_request_error(request)
    if request_error:
        return _workbench_json({"ok": False, "error": request_error}, status=403)
    try:
        items, latest = _load_workbench_inbox()
    except Exception:
        return _workbench_json({"ok": False, "error": "storage_read_failed"}, status=500)
    return _workbench_json({"ok": True, "items": items, "latest": latest})


def _claim_body(data, action):
    fields = {"import_id", "receiver_id"} | ({"claim_token"} if action != "claim" else set())
    if not isinstance(data, dict) or set(data) != fields:
        raise InvalidBrowserImport("invalid_fields")
    if not all(_canonical_uuid(data[key]) for key in fields):
        raise InvalidBrowserImport("invalid_id")
    return data


def _lease_action(data, action):
    import_id, receiver_id = data["import_id"], data["receiver_id"]
    with _inbox_connection(write=True) as connection:
        accepted = connection.execute("SELECT * FROM accepted WHERE import_id = ?", (import_id,)).fetchone()
        if accepted:
            if action == "claim" or (accepted["receiver_id"] == receiver_id
                                      and accepted["claim_token"] == data["claim_token"]):
                return {"ok": True, "delivery": "accepted", "import_id": import_id}, 200
            return {"ok": False, "error": "claim_mismatch"}, 409
        row = connection.execute("SELECT * FROM inbox WHERE import_id = ?", (import_id,)).fetchone()
        if row is None:
            return {"ok": False, "error": "import_not_found"}, 404
        now = time.time()
        live = bool(row["claim_token"] and row["claim_expires_at"] > now)
        if action == "claim":
            if live and row["receiver_id"] != receiver_id:
                return {"ok": False, "error": "already_claimed", "claim_expires_at": row["claim_expires_at"],
                        "retry_after_ms": max(1, int((row["claim_expires_at"] - now) * 1000) + 1)}, 409
            token = row["claim_token"] if live else str(uuid.uuid4())
            expires = row["claim_expires_at"] if live else now + CLAIM_TTL_SECONDS
            payload = _stored_payload(row["payload_json"])
            connection.execute("UPDATE inbox SET receiver_id=?,claim_token=?,claim_expires_at=? WHERE import_id=?",
                               (receiver_id, token, expires, import_id))
            return {"ok": True, "delivery": "claimed", "payload": payload,
                    "claim_token": token, "claim_expires_at": expires}, 200
        if not live:
            return {"ok": False, "error": "claim_expired"}, 409
        if row["receiver_id"] != receiver_id or row["claim_token"] != data["claim_token"]:
            return {"ok": False, "error": "claim_mismatch"}, 409
        if action == "release":
            connection.execute("UPDATE inbox SET receiver_id=NULL,claim_token=NULL,claim_expires_at=NULL WHERE import_id=?",
                               (import_id,))
            return {"ok": True, "delivery": "released", "import_id": import_id}, 200
        connection.execute("INSERT INTO accepted VALUES(?,?,?,?)", (import_id, receiver_id, data["claim_token"], now))
        connection.execute("DELETE FROM inbox WHERE import_id=?", (import_id,))
        connection.execute("DELETE FROM accepted WHERE import_id NOT IN "
                           "(SELECT import_id FROM accepted ORDER BY accepted_at DESC,rowid DESC LIMIT ?)",
                           (ACCEPTED_LIMIT,))
        return {"ok": True, "delivery": "accepted", "import_id": import_id}, 200


async def _workbench_lease_request(request, action):
    request_error = _workbench_request_error(request)
    if request_error:
        return _workbench_json({"ok": False, "error": request_error}, status=403)
    try:
        data = _claim_body(await _read_browser_request(request), action)
    except InvalidBrowserImport as error:
        code = str(error)
        status = 413 if code == "payload_too_large" else 415 if code == "json_required" else 400
        return _workbench_json({"ok": False, "error": code}, status=status)
    except Exception:
        return _workbench_json({"ok": False, "error": "invalid_request"}, status=400)
    try:
        result, status = _lease_action(data, action)
    except Exception:
        return _workbench_json({"ok": False, "delivery": "failed", "error": "storage_write_failed"}, status=500)
    return _workbench_json(result, status=status)


@PromptServer.instance.routes.post(WORKBENCH_ROUTE + "/claim")
async def unified_workbench_browser_import_claim(request):
    return await _workbench_lease_request(request, "claim")


@PromptServer.instance.routes.post(WORKBENCH_ROUTE + "/ack")
async def unified_workbench_browser_import_ack(request):
    return await _workbench_lease_request(request, "ack")


@PromptServer.instance.routes.post(WORKBENCH_ROUTE + "/release")
async def unified_workbench_browser_import_release(request):
    return await _workbench_lease_request(request, "release")


@PromptServer.instance.routes.options(WORKBENCH_ROUTE)
@PromptServer.instance.routes.options(WORKBENCH_ROUTE + "/claim")
@PromptServer.instance.routes.options(WORKBENCH_ROUTE + "/ack")
@PromptServer.instance.routes.options(WORKBENCH_ROUTE + "/release")
async def unified_workbench_browser_import_options(request):
    request_error = _workbench_request_error(request)
    if request_error:
        return _workbench_json({"ok": False, "error": request_error}, status=403)
    return _workbench_json({"ok": True})


@PromptServer.instance.routes.get(ROUTE)
async def danbooru_browser_import_get_v05(request):
    latest = _load_latest(force=True)
    workbench_data = isinstance(latest, dict) and latest.get("destination") == "workbench"
    if workbench_data:
        request_error = _workbench_request_error(request)
        if request_error:
            return _workbench_json({"ok": False, "error": request_error}, status=403)
    response = {
        "ok": True,
        "plugin": "ComfyUI-Danbooru-Browser-Import",
        "version": VERSION,
        "route": ROUTE,
        "method": "GET",
        "latest": latest,
        "mtime": _mtime_token(),
    }
    return _workbench_json(response) if workbench_data else _cors_json(response)


@PromptServer.instance.routes.post(ROUTE)
async def danbooru_browser_import_post_v05(request):
    current = _load_latest(force=True)
    if isinstance(current, dict) and current.get("destination") == "workbench":
        request_error = _workbench_request_error(request)
        if request_error:
            return _workbench_json({"ok": False, "error": request_error}, status=403)
    try:
        data = await request.json()
    except Exception:
        text = await request.text()
        data = {"raw_text": text}
    if not isinstance(data, dict):
        data = {"raw_payload": data}
    data["_received_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    data["_route"] = ROUTE
    data["_plugin_version"] = VERSION
    _save_latest(data)
    return _cors_json({
        "ok": True,
        "plugin": "ComfyUI-Danbooru-Browser-Import",
        "version": VERSION,
        "route": ROUTE,
        "method": "POST",
        "received_keys": sorted(list(data.keys())),
        "post_id": data.get("post_id", ""),
        "merged_tags_preview": str(data.get("merged_tags", ""))[:240],
        "mtime": _mtime_token(),
    })


@PromptServer.instance.routes.options(ROUTE)
async def danbooru_browser_import_options_v05(request):
    return _cors_json({"ok": True, "plugin": "ComfyUI-Danbooru-Browser-Import", "version": VERSION, "route": ROUTE, "method": "OPTIONS"})


@PromptServer.instance.routes.get("/danbooru_browser_import_v05_status")
async def danbooru_browser_import_status_v05(request):
    return _cors_json({
        "ok": True,
        "plugin": "ComfyUI-Danbooru-Browser-Import",
        "version": VERSION,
        "route": ROUTE,
        "data_file": DATA_FILE,
        "exists": os.path.exists(DATA_FILE),
        "mtime": _mtime_token(),
    })


class DanbooruBrowserImportV05:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"refresh_token": ("INT", {"default": 0, "min": 0, "max": 999999999})}}

    @classmethod
    def IS_CHANGED(cls, refresh_token=0):
        # Important: the data is updated by an external browser POST, not by graph inputs.
        # This token tells ComfyUI to re-run the node when the received JSON file changes.
        return f"{refresh_token}:{_mtime_token()}"

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "merged_tags",
        "artist_tags",
        "character_tags",
        "copyright_tags",
        "general_tags",
        "meta_tags",
        "source_url",
        "image_url",
        "post_id",
        "raw_json",
    )
    FUNCTION = "read_latest"
    CATEGORY = "Danbooru/Browser Import"

    def read_latest(self, refresh_token=0):
        d = _load_latest(force=True) or {}
        def s(key):
            val = d.get(key, "")
            if isinstance(val, list):
                return ", ".join([str(x) for x in val if str(x).strip()])
            if isinstance(val, dict):
                return json.dumps(val, ensure_ascii=False)
            return str(val or "")
        raw = json.dumps(d, ensure_ascii=False, indent=2) if d else "No Danbooru browser import received yet. Open a Danbooru post page and click Send Tags to ComfyUI v0.5."
        return (
            s("merged_tags"),
            s("artist_tags"),
            s("character_tags"),
            s("copyright_tags"),
            s("general_tags"),
            s("meta_tags"),
            s("source_url"),
            s("image_url"),
            s("post_id"),
            raw,
        )


NODE_CLASS_MAPPINGS = {"DanbooruBrowserImportV05": DanbooruBrowserImportV05}
NODE_DISPLAY_NAME_MAPPINGS = {"DanbooruBrowserImportV05": "Danbooru Browser Import v0.6 · Tags/URL"}
