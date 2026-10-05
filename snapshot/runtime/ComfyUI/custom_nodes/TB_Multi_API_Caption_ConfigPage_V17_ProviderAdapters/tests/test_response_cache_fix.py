import asyncio
import importlib.util
import json
import math
import sys
import types
from pathlib import Path

import numpy as np
import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "nodes.py"
SPEC = importlib.util.spec_from_file_location("tb_multi_api_caption_nodes_test", MODULE_PATH)
tb = importlib.util.module_from_spec(SPEC)
SERVER_STUB = types.ModuleType("server")
SERVER_STUB.PromptServer = None
PREVIOUS_SERVER_MODULE = sys.modules.get("server")
sys.modules["server"] = SERVER_STUB
try:
    SPEC.loader.exec_module(tb)
finally:
    if PREVIOUS_SERVER_MODULE is None:
        sys.modules.pop("server", None)
    else:
        sys.modules["server"] = PREVIOUS_SERVER_MODULE

VALID_PROMPT = (
    "masterpiece, best quality, 1girl, solo, purple hair, blue eyes; "
    "An anime character stands beneath warm orange light. The composition is a close portrait."
)


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    class ForbiddenClientSession:
        def __init__(self, *args, **kwargs):
            raise AssertionError("network access is forbidden in regression tests")

    if tb.aiohttp is not None:
        monkeypatch.setattr(tb.aiohttp, "ClientSession", ForbiddenClientSession)
    tb.clear_runner_cache(None)
    yield
    tb.clear_runner_cache(None)


@pytest.mark.parametrize(
    "value",
    ["IMAGE_NOT_RECEIVED", " image-not-received. ", "image not received!"],
)
def test_exact_missing_image_sentinel_is_detected(value):
    assert tb.response_reports_missing_image(value)


def test_embedded_sentinel_is_not_a_missing_image_result():
    assert not tb.response_reports_missing_image(
        "If no image is attached, output exactly IMAGE_NOT_RECEIVED."
    )


def test_legacy_sentinel_instruction_is_not_sent_to_provider():
    provider = {
        "name": "offline-test",
        "protocol": "openai_chat",
        "base_url": "https://offline.invalid/v1",
    }
    request = tb.build_provider_request(
        provider=provider,
        model="offline-model",
        system_prompt=(
            "Analyze only the actual input image. "
            "If no image is attached or readable, output exactly: IMAGE_NOT_RECEIVED."
        ),
        user_prompt="Analyze the image.",
        temperature=0.2,
        max_tokens=256,
    )
    system_text = request["payload"]["messages"][0]["content"]
    assert system_text == "Analyze only the actual input image."
    assert "IMAGE_NOT_RECEIVED" not in system_text


def test_refusal_is_separate_from_missing_image():
    value = "Sorry, I can't help with that image. Try uploading another image."
    assert tb.response_reports_refusal(value)
    assert not tb.response_reports_missing_image(value)


def test_cleaner_drops_closed_and_unclosed_reasoning():
    assert tb.clean_model_output(f"<think>IMAGE_NOT_RECEIVED</think>\n{VALID_PROMPT}") == VALID_PROMPT
    assert tb.clean_model_output("<think>IMAGE_NOT_RECEIVED") == ""


def test_cleaner_keeps_post_reasoning_sentinel_as_final_answer():
    assert tb.clean_model_output("<think>checking</think>\nIMAGE_NOT_RECEIVED") == "IMAGE_NOT_RECEIVED"


def test_openai_chat_ignores_reasoning_blocks():
    parsed = tb.parse_provider_response("openai_chat", {
        "choices": [{
            "finish_reason": "stop",
            "message": {"content": [
                {"type": "thinking", "text": "IMAGE_NOT_RECEIVED"},
                {"type": "text", "text": VALID_PROMPT},
            ]},
        }],
    })
    assert parsed["text"] == VALID_PROMPT
    assert parsed["finish_reason"] == "stop"
    assert not parsed["invalid_response"]


def test_openai_chat_preserves_structured_refusal():
    parsed = tb.parse_provider_response("openai_chat", {
        "choices": [{
            "finish_reason": "content_filter",
            "message": {"content": None, "refusal": "Request blocked"},
        }],
    })
    assert parsed["text"] == ""
    assert parsed["refusal"] == "Request blocked"
    assert parsed["finish_reason"] == "content_filter"


def test_openai_chat_does_not_turn_malformed_json_into_text():
    parsed = tb.parse_provider_response("openai_chat", {
        "request": {"system": "IMAGE_NOT_RECEIVED"},
        "choices": [],
    })
    assert parsed["text"] == ""
    assert parsed["invalid_response"]


def test_openai_responses_ignores_reasoning_items():
    parsed = tb.parse_provider_response("openai_responses", {
        "status": "completed",
        "output": [
            {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "IMAGE_NOT_RECEIVED"}]},
            {"type": "message", "content": [{"type": "output_text", "text": VALID_PROMPT}]},
        ],
    })
    assert parsed["text"] == VALID_PROMPT


def test_other_protocols_keep_only_visible_text():
    anthropic = tb.parse_provider_response("anthropic_messages", {
        "stop_reason": "end_turn",
        "content": [{"type": "thinking", "text": "hidden"}, {"type": "text", "text": VALID_PROMPT}],
    })
    gemini = tb.parse_provider_response("gemini_generate_content", {
        "candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"thought": True, "text": "hidden"}, {"text": VALID_PROMPT}]},
        }],
    })
    assert anthropic["text"] == VALID_PROMPT
    assert gemini["text"] == VALID_PROMPT


def _call_with_fake_response(monkeypatch, payload):
    class FakeResponse:
        status = 200

        async def text(self):
            return json.dumps(payload)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(tb.aiohttp, "ClientSession", lambda *args, **kwargs: FakeSession())
    provider = {
        "name": "offline-test",
        "protocol": "openai_chat",
        "base_url": "https://offline.invalid/v1",
        "path": "/chat/completions",
        "supports_vision": True,
        "fail_on_missing_image": True,
    }
    return asyncio.run(tb.call_multimodal_provider(
        slot=1,
        provider=provider,
        model="offline-model",
        image=np.zeros((1, 4, 4, 3), dtype=np.float32),
        system_prompt="Return only the final prompt.",
        user_prompt="Analyze the image.",
        timeout_seconds=30,
        temperature=0.2,
        max_tokens=256,
        node_id="offline-node",
        status_state={"models": [{}]},
    ))


def test_provider_call_classifies_sentinel_as_no_image(monkeypatch):
    result = _call_with_fake_response(monkeypatch, {
        "choices": [{"finish_reason": "stop", "message": {"content": "IMAGE_NOT_RECEIVED"}}],
    })
    assert result["status"] == "no_image"
    assert result["error_kind"] == "missing_image"


@pytest.mark.parametrize(
    ("payload", "error_kind"),
    [
        ({"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}, "empty_response"),
        ({"choices": [{"finish_reason": "length", "message": {"content": VALID_PROMPT}}]}, "truncated"),
        ({"choices": [{"finish_reason": "content_filter", "message": {"content": None, "refusal": "blocked"}}]}, "refusal"),
        ({"error": {"message": "upstream failed"}}, "provider_error"),
    ],
)
def test_provider_call_rejects_non_success_responses(monkeypatch, payload, error_kind):
    result = _call_with_fake_response(monkeypatch, payload)
    assert result["status"] == "error"
    assert result["error_kind"] == error_kind


def test_provider_call_uses_final_text_not_reasoning_for_missing_image(monkeypatch):
    result = _call_with_fake_response(monkeypatch, {
        "choices": [{
            "finish_reason": "stop",
            "message": {"content": [
                {"type": "thinking", "text": "I cannot see the image"},
                {"type": "text", "text": VALID_PROMPT},
            ]},
        }],
    })
    assert result["status"] == "success"
    assert result["text"] == VALID_PROMPT


def _runner_kwargs(image, requested_slots="1", force=False, run_id=1, enable_2=False):
    return {
        "image": image,
        "system_prompt": "system",
        "user_prompt": "user",
        "enable_1": True,
        "slot_1_provider": "offline-test",
        "slot_1_model": "model-1",
        "enable_2": enable_2,
        "slot_2_provider": "offline-test",
        "slot_2_model": "model-2",
        "enable_3": False,
        "slot_3_provider": "offline-test",
        "slot_3_model": "<manual>",
        "enable_4": False,
        "slot_4_provider": "offline-test",
        "slot_4_model": "<manual>",
        "enable_5": False,
        "slot_5_provider": "offline-test",
        "slot_5_model": "<manual>",
        "requested_slots": requested_slots,
        "accumulate_results": True,
        "timeout_seconds": 30,
        "temperature": 0.2,
        "max_tokens": 256,
        "force_always_run": force,
        "run_id": run_id,
        "unique_id": "runner-cache-test",
        "prompt": None,
    }


def _install_fake_runner_provider(monkeypatch, statuses=None):
    calls = []
    provider = {
        "name": "offline-test",
        "protocol": "openai_chat",
        "base_url": "https://offline.invalid/v1",
        "supports_vision": True,
    }
    monkeypatch.setattr(tb, "get_provider", lambda name: provider if name == "offline-test" else None)

    async def fake_call(**kwargs):
        calls.append((kwargs["slot"], float(np.asarray(kwargs["image"]).mean())))
        status = statuses.pop(0) if statuses else "success"
        text = f"slot-{kwargs['slot']}-call-{len(calls)}" if status == "success" else "IMAGE_NOT_RECEIVED"
        return {
            "slot": kwargs["slot"],
            "enabled": True,
            "provider": "offline-test",
            "model": kwargs["model"],
            "protocol": "openai_chat",
            "status": status,
            "seconds": 0.01,
            "text": text,
        }

    monkeypatch.setattr(tb, "call_multimodal_provider", fake_call)
    return calls


def test_force_and_run_id_bypass_the_right_cache_layer(monkeypatch):
    calls = _install_fake_runner_provider(monkeypatch)
    runner = tb.TB_Multi_API_Caption_SmartRunner_V16()
    image = np.zeros((1, 2, 2, 3), dtype=np.float32)

    first = runner.run(**_runner_kwargs(image, run_id=1))
    second = runner.run(**_runner_kwargs(image, run_id=1))
    bumped = runner.run(**_runner_kwargs(image, run_id=2))
    forced = runner.run(**_runner_kwargs(image, force=True, run_id=2))

    assert len(calls) == 3
    assert first[0] == second[0]
    assert bumped[0] != second[0]
    assert forced[0] != bumped[0]
    assert math.isnan(tb.TB_Multi_API_Caption_SmartRunner_V16.IS_CHANGED(force_always_run=True))
    assert math.isnan(tb.TB_Anima_Prompt_Judge_API_V16.IS_CHANGED(force_always_run=True))


def test_failed_attempt_is_not_cached(monkeypatch):
    calls = _install_fake_runner_provider(monkeypatch, statuses=["no_image", "success"])
    runner = tb.TB_Multi_API_Caption_SmartRunner_V16()
    image = np.zeros((1, 2, 2, 3), dtype=np.float32)

    runner.run(**_runner_kwargs(image))
    result = runner.run(**_runner_kwargs(image))

    assert len(calls) == 2
    assert result[0].startswith("slot-1-call-2")


def test_non_target_cache_is_kept_only_for_the_same_context(monkeypatch):
    _install_fake_runner_provider(monkeypatch)
    runner = tb.TB_Multi_API_Caption_SmartRunner_V16()
    image_a = np.zeros((1, 2, 2, 3), dtype=np.float32)
    image_b = np.ones((1, 2, 2, 3), dtype=np.float32)

    runner.run(**_runner_kwargs(image_a, requested_slots="2", enable_2=True))
    same_context = runner.run(**_runner_kwargs(image_a, requested_slots="1", run_id=2, enable_2=True))
    same_slots = [item["slot"] for item in json.loads(same_context[5])]
    assert same_slots == [1, 2]

    changed_context = runner.run(**_runner_kwargs(image_b, requested_slots="1", run_id=3, enable_2=True))
    changed_slots = [item["slot"] for item in json.loads(changed_context[5])]
    assert changed_slots == [1]
