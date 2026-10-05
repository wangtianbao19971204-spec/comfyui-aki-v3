import asyncio
import importlib.util
import json
import logging
from pathlib import Path
import socket
import sys
import types

import pytest
import requests


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PLUGIN_ROOT / "py" / "danbooru_gallery" / "danbooru_gallery.py"

# Keep pytest from importing the whole custom-node package during collection. The
# directory name contains hyphens, so loading the backend under an isolated alias is
# both more representative and less likely to initialize unrelated ComfyUI nodes.
_plugin_init = types.ModuleType("__init__")
_plugin_init.__file__ = str(PLUGIN_ROOT / "__init__.py")
_plugin_init.__path__ = [str(PLUGIN_ROOT)]
_plugin_init.__package__ = "__init__"
sys.modules.setdefault("__init__", _plugin_init)


def _package(name, path):
    package = types.ModuleType(name)
    package.__package__ = name
    package.__path__ = [str(path)]
    sys.modules[name] = package
    return package


@pytest.fixture(scope="module")
def gallery_module():
    root_name = "_v53_ssrf_test_plugin"
    _package(root_name, PLUGIN_ROOT)
    _package(f"{root_name}.py", PLUGIN_ROOT / "py")
    _package(f"{root_name}.py.danbooru_gallery", PLUGIN_ROOT / "py" / "danbooru_gallery")
    _package(f"{root_name}.py.utils", PLUGIN_ROOT / "py" / "utils")
    _package(f"{root_name}.py.shared", PLUGIN_ROOT / "py" / "shared")
    _package(f"{root_name}.py.shared.db", PLUGIN_ROOT / "py" / "shared" / "db")

    test_logger = logging.getLogger("v53.ssrf")
    test_logger.handlers.clear()
    test_logger.filters.clear()
    test_logger.propagate = False
    test_logger.setLevel(logging.DEBUG)

    logger_module = types.ModuleType(f"{root_name}.py.utils.logger")
    logger_module.get_logger = lambda _name: test_logger
    sys.modules[logger_module.__name__] = logger_module

    db_module = types.ModuleType(f"{root_name}.py.shared.db.db_manager")
    db_module.get_db_manager = lambda: None
    sys.modules[db_module.__name__] = db_module

    sys.modules.setdefault("folder_paths", types.ModuleType("folder_paths"))

    class Routes:
        @staticmethod
        def get(_path):
            return lambda function: function

        @staticmethod
        def post(_path):
            return lambda function: function

    server_module = types.ModuleType("server")
    server_module.PromptServer = type(
        "PromptServer", (), {"instance": types.SimpleNamespace(routes=Routes())}
    )
    sys.modules.setdefault("server", server_module)

    module_name = f"{root_name}.py.danbooru_gallery.danbooru_gallery"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _dns_answers(*addresses):
    answers = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
        answers.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
    return answers


def _public_dns(_host, _port, **_kwargs):
    return _dns_answers("93.184.216.34", "2606:4700:4700::1111")


class FakeResponse:
    def __init__(self, status_code=200, url="", headers=None, content=b"image"):
        self.status_code = status_code
        self.url = url
        self.headers = dict(headers or {})
        self.content = content
        self.text = ""
        self.history = []
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


@pytest.mark.parametrize(
    ("purpose", "url", "host"),
    [
        ("image_proxy", "https://cdn.donmai.us/data/a.jpg", "cdn.donmai.us"),
        ("image_proxy", "https://img3.gelbooru.com/images/a.jpg", "img3.gelbooru.com"),
        ("image_proxy", "https://files.yande.re/image/a.jpg", "files.yande.re"),
        ("image_proxy", "https://image.civitai.com/x/a.jpeg", "image.civitai.com"),
        ("civitai_prompt", "https://image.civitai.com/x/prompt.png", "image.civitai.com"),
        ("provider_api", "https://danbooru.donmai.us/posts.json", "danbooru.donmai.us"),
        ("provider_api", "https://gelbooru.com/index.php", "gelbooru.com"),
        ("provider_api", "https://yande.re/post.json", "yande.re"),
        ("provider_api", "https://civitai.com/api/v1/images", "civitai.com"),
        ("provider_api", "https://civitai.red/api/v1/images", "civitai.red"),
        ("provider_api", "https://search-new.civitai.com/multi-search", "search-new.civitai.com"),
    ],
)
def test_official_media_and_api_hosts_are_allowed(gallery_module, purpose, url, host):
    target = gallery_module._validate_url_for_purpose(url, purpose, resolver=_public_dns)

    assert target["host"] == host
    assert target["url"] == url
    assert target["addresses"] == ("93.184.216.34", "2606:4700:4700::1111")


@pytest.mark.parametrize(
    ("url", "expected_code"),
    [
        ("http://image.civitai.com/a.jpg", "https_required"),
        ("https:///a.jpg", "empty_host"),
        ("https://user:password@image.civitai.com/a.jpg", "userinfo_forbidden"),
        ("https://image.civitai.com:8443/a.jpg", "port_not_allowed"),
        ("https://127.0.0.1/a", "non_public_address"),
        ("https://10.0.0.1/a", "non_public_address"),
        ("https://172.16.0.1/a", "non_public_address"),
        ("https://192.168.1.1/a", "non_public_address"),
        ("https://169.254.169.254/latest/meta-data", "non_public_address"),
        ("https://224.0.0.1/a", "non_public_address"),
        ("https://240.0.0.1/a", "non_public_address"),
        ("https://0.0.0.0/a", "non_public_address"),
        ("https://[::1]/a", "non_public_address"),
        ("https://2130706433/a", "host_not_allowed"),
        ("https://0x7f000001/a", "host_not_allowed"),
        ("https://127.0.0.1.nip.io/a", "host_not_allowed"),
        ("https://image.civitai.com.evil.test/a", "host_not_allowed"),
        ("https://.image.civitai.com/a", "invalid_host"),
        ("https://image..civitai.com/a", "invalid_host"),
    ],
)
def test_ssrf_syntax_ip_and_hostname_confusion_vectors_are_rejected(
    gallery_module, url, expected_code,
):
    with pytest.raises(gallery_module.URLPolicyError) as raised:
        gallery_module._validate_url_for_purpose(url, "image_proxy", resolver=_public_dns)

    assert raised.value.code == expected_code
    assert raised.value.http_status in (400, 403)


@pytest.mark.parametrize(
    "answers",
    [
        ("127.0.0.1",),
        ("10.2.3.4",),
        ("169.254.169.254",),
        ("93.184.216.34", "192.168.20.5"),
        ("2606:4700:4700::1111", "fe80::1"),
    ],
)
def test_every_dns_answer_must_be_public(gallery_module, answers):
    resolver = lambda *_args, **_kwargs: _dns_answers(*answers)

    with pytest.raises(gallery_module.URLPolicyError) as raised:
        gallery_module._validate_url_for_purpose(
            "https://image.civitai.com/a.jpg", "image_proxy", resolver=resolver,
        )

    assert raised.value.code == "non_public_address"


def test_redirect_target_is_validated_before_second_request(gallery_module, monkeypatch):
    monkeypatch.setattr(gallery_module.socket, "getaddrinfo", _public_dns)
    calls = []
    redirect = FakeResponse(
        302,
        "https://image.civitai.com/a.jpg",
        {"Location": "https://169.254.169.254/latest/meta-data"},
    )

    def request_once(url, allow_redirects=False, suppress_credentials=False):
        calls.append((url, allow_redirects, suppress_credentials))
        return redirect

    with pytest.raises(gallery_module.URLPolicyError) as raised:
        gallery_module._safe_fetch_with_allowlist(
            "https://image.civitai.com/a.jpg", "image_proxy", request_once,
        )

    assert raised.value.code == "non_public_address"
    assert calls == [("https://image.civitai.com/a.jpg", False, False)]
    assert redirect.closed is True


def test_cross_origin_redirect_drops_credentials_permanently(gallery_module, monkeypatch):
    monkeypatch.setattr(gallery_module.socket, "getaddrinfo", _public_dns)
    calls = []
    first = FakeResponse(
        302,
        "https://cdn.donmai.us/a.jpg",
        {"Location": "https://img3.gelbooru.com/b.jpg"},
    )
    second = FakeResponse(
        302,
        "https://img3.gelbooru.com/b.jpg",
        {"Location": "https://cdn.donmai.us/c.jpg"},
    )
    final = FakeResponse(200, "https://cdn.donmai.us/c.jpg", {"Content-Type": "image/jpeg"})
    responses = iter((first, second, final))

    def request_once(url, allow_redirects=False, suppress_credentials=False):
        calls.append((url, allow_redirects, suppress_credentials))
        return next(responses)

    response = gallery_module._safe_fetch_with_allowlist(
        "https://cdn.donmai.us/a.jpg", "image_proxy", request_once,
    )

    assert response is final
    assert [entry[2] for entry in calls] == [False, True, True]
    assert all(entry[1] is False for entry in calls)
    assert first.closed and second.closed


def test_explicit_default_port_is_same_origin(gallery_module, monkeypatch):
    monkeypatch.setattr(gallery_module.socket, "getaddrinfo", _public_dns)
    calls = []
    responses = iter((
        FakeResponse(
            302,
            "https://image.civitai.com/a.jpg",
            {"Location": "https://image.civitai.com:443/b.jpg"},
        ),
        FakeResponse(200, "https://image.civitai.com/b.jpg", {"Content-Type": "image/jpeg"}),
    ))

    def request_once(url, allow_redirects=False, suppress_credentials=False):
        calls.append((url, suppress_credentials))
        return next(responses)

    gallery_module._safe_fetch_with_allowlist(
        "https://image.civitai.com/a.jpg", "civitai_prompt", request_once,
    )

    assert calls == [
        ("https://image.civitai.com/a.jpg", False),
        ("https://image.civitai.com/b.jpg", False),
    ]


def test_unexpected_automatic_redirect_history_is_rejected(gallery_module, monkeypatch):
    monkeypatch.setattr(gallery_module.socket, "getaddrinfo", _public_dns)
    hop = FakeResponse(
        302,
        "https://image.civitai.com/a.jpg",
        {"Location": "https://127.0.0.1/admin"},
    )
    final = FakeResponse(200, "https://image.civitai.com/final.jpg")
    final.history = [hop]

    with pytest.raises(gallery_module.URLPolicyError) as raised:
        gallery_module._safe_fetch_with_allowlist(
            "https://image.civitai.com/a.jpg",
            "civitai_prompt",
            lambda *_args, **_kwargs: final,
        )

    assert raised.value.code == "non_public_address"


def test_suppressed_request_headers_remove_all_credentials(gallery_module, monkeypatch):
    captured = {}

    class FakeSession:
        trust_env = True

        def request(self, method, url, headers=None, **kwargs):
            captured.update(method=method, url=url, headers=dict(headers or {}), kwargs=kwargs)
            return FakeResponse(200, url)

        def close(self):
            captured["session_closed"] = True

    monkeypatch.setattr(gallery_module.requests, "Session", FakeSession)
    monkeypatch.setattr(gallery_module, "_get_proxy_url", lambda: None)
    monkeypatch.setattr(
        gallery_module,
        "_apply_danbooru_cookie_headers",
        lambda *_args, **_kwargs: pytest.fail("credential injector must not run"),
    )

    response = gallery_module._request_with_headers(
        "GET",
        "https://cdn.donmai.us/a.jpg",
        {
            "Authorization": "Bearer secret",
            "Cookie": "session=secret",
            "Proxy-Authorization": "Basic secret",
            "X-Meili-API-Key": "secret",
            "X-API-Key": "secret",
            "X-Test": "kept",
        },
        _suppress_credentials=True,
        allow_redirects=False,
        auth=("user", "secret"),
    )

    lowered = {key.lower(): value for key, value in captured["headers"].items()}
    assert not gallery_module._CREDENTIAL_HEADER_NAMES.intersection(lowered)
    assert lowered["x-test"] == "kept"
    assert captured["kwargs"]["allow_redirects"] is False
    assert "auth" not in captured["kwargs"]
    gallery_module._close_outbound_response(response)
    assert captured["session_closed"] is True


def test_image_proxy_rejects_before_fetch_and_returns_sanitized_status(
    gallery_module, monkeypatch,
):
    def should_not_fetch(*_args, **_kwargs):
        pytest.fail("blocked URL reached the provider requester")

    monkeypatch.setattr(gallery_module, "_supported_media_request_once", should_not_fetch)
    request = types.SimpleNamespace(query={"url": "https://169.254.169.254/latest/meta-data"})

    response = asyncio.run(gallery_module.image_proxy(request))
    payload = json.loads(response.text)

    assert response.status == 403
    assert payload["error"]["code"] == "non_public_address"
    assert "169.254.169.254" not in response.text


def test_civitai_prompt_rejects_url_before_cache_or_task(gallery_module, monkeypatch):
    monkeypatch.setattr(
        gallery_module,
        "_civitai_prompt_cache_get",
        lambda *_args, **_kwargs: pytest.fail("blocked URL reached prompt cache"),
    )
    request = types.SimpleNamespace(query={
        "image_id": "42",
        "image_url": "https://127.0.0.1/admin?token=secret",
    })

    response = asyncio.run(gallery_module.civitai_prompt_route(request))
    payload = json.loads(response.text)

    assert response.status == 403
    assert payload["error"] == "non_public_address"
    assert "127.0.0.1" not in response.text
    assert "secret" not in response.text


def test_selection_media_rejects_user_url_without_network(gallery_module, monkeypatch):
    def should_not_fetch(*_args, **_kwargs):
        pytest.fail("blocked selection URL reached the provider requester")

    monkeypatch.setattr(gallery_module, "_supported_media_request_once", should_not_fetch)
    node = gallery_module.DanbooruGalleryNode()
    images, prompts = node.get_selected_data(json.dumps({
        "selections": [{"prompt": "safe prompt", "image_url": "http://127.0.0.1/a.png"}],
    }))

    assert prompts == ["safe prompt"]
    assert len(images) == 1
    assert tuple(images[0].shape) == (1, 1, 1, 3)
