from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(
        self,
        base_url: str,
        comfy_root: str | Path | None = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.comfy_root = Path(comfy_root).resolve() if comfy_root else None
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> bytes:
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout or self.timeout,
            ) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ComfyError(f"ComfyUI HTTP {exc.code}: {body[:2000]}") from exc
        except urllib.error.URLError as exc:
            raise ComfyError(f"无法连接 ComfyUI: {exc.reason}") from exc

    def get_json(self, path: str) -> dict[str, Any]:
        return json.loads(self._request(path).decode("utf-8"))

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        return json.loads(
            self._request(
                path,
                method="POST",
                payload=payload,
                timeout=timeout,
            ).decode("utf-8")
        )

    def system_stats(self) -> dict[str, Any]:
        return self.get_json("/system_stats")

    def object_info(self) -> dict[str, Any]:
        return self.get_json("/object_info")

    def history(
        self,
        prompt_id: str | None = None,
        max_items: int = 20,
    ) -> dict[str, Any]:
        if prompt_id:
            return self.get_json(f"/history/{urllib.parse.quote(prompt_id)}")
        return self.get_json(f"/history?max_items={int(max_items)}")

    def queue_prompt(self, graph: dict[str, Any]) -> str:
        response = self.post_json(
            "/prompt",
            {"prompt": graph, "client_id": self.client_id},
        )
        prompt_id = response.get("prompt_id")
        if not prompt_id:
            raise ComfyError(f"ComfyUI 未返回 prompt_id: {response}")
        return str(prompt_id)

    def wait_for_prompt(
        self,
        prompt_id: str,
        *,
        timeout_seconds: int = 1800,
        poll_seconds: float = 1.5,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            history = self.history(prompt_id=prompt_id)
            record = history.get(prompt_id)
            if record:
                status = record.get("status", {})
                if status.get("completed"):
                    if status.get("status_str") != "success":
                        messages = status.get("messages", [])
                        raise ComfyError(
                            f"ComfyUI 任务失败 {prompt_id}: "
                            f"{json.dumps(messages, ensure_ascii=False)[:3000]}"
                        )
                    return record
            time.sleep(poll_seconds)
        raise ComfyError(f"ComfyUI 任务超时: {prompt_id}")

    def copy_to_input(
        self,
        source: str | Path,
        relative_path: str,
    ) -> str:
        if self.comfy_root is None:
            raise ComfyError("未配置 comfyui.root，无法写入参考图")
        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise ComfyError(f"参考图不存在: {source_path}")
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ComfyError(f"非法 ComfyUI input 相对路径: {relative_path}")
        destination = (self.comfy_root / "input" / relative).resolve()
        input_root = (self.comfy_root / "input").resolve()
        if input_root not in destination.parents:
            raise ComfyError(f"参考图目标超出 input 目录: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        return destination.relative_to(input_root).as_posix()

    def copy_output_image(
        self,
        image: dict[str, Any],
        destination: str | Path,
    ) -> Path:
        destination_path = Path(destination).resolve()
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        filename = str(image.get("filename") or "")
        subfolder = str(image.get("subfolder") or "")
        image_type = str(image.get("type") or "output")

        if self.comfy_root is not None:
            root_name = "temp" if image_type == "temp" else "output"
            source = (self.comfy_root / root_name / subfolder / filename).resolve()
            allowed_root = (self.comfy_root / root_name).resolve()
            if allowed_root in source.parents and source.is_file():
                shutil.copy2(source, destination_path)
                return destination_path

        query = urllib.parse.urlencode(
            {
                "filename": filename,
                "subfolder": subfolder,
                "type": image_type,
            }
        )
        destination_path.write_bytes(self._request(f"/view?{query}"))
        return destination_path


def output_images(record: dict[str, Any]) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for output in (record.get("outputs") or {}).values():
        images.extend(output.get("images") or [])
    return images
