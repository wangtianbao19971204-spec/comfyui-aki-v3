"""Apply the existing production profile to the original GUI's Python child.

This is an opt-in argument boundary, not a replacement launcher. It keeps GUI
memory, device and preview choices and never infers a core version from the
maintenance repository's HEAD. Without the marker it does no filesystem I/O.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import MutableMapping, MutableSequence


PROFILE_ENV = "AKI_HUISHI_PROFILE"
_CONTROLLED = {
    "--listen", "--port", "--auto-launch", "--disable-auto-launch",
    "--disable-all-custom-nodes", "--whitelist-custom-nodes",
}
_REDIRECTS = {
    "--base-directory", "--models-directory", "--extra-model-paths-config",
    "--input-directory", "--output-directory", "--temp-directory",
    "--user-directory", "--database-url", "--front-end-root",
    "--front-end-version", "--profile", "--root", "--workspace",
}
_CONFLICTS = {
    "--enable-manager", "--enable-manager-legacy-ui",
    "--enable-all-custom-nodes", "--disable-whitelist-custom-nodes",
}
_PROTECTED = _CONTROLLED | _REDIRECTS | _CONFLICTS
_NODE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


class StartupPolicyError(ValueError):
    """A GUI option conflicts with the reviewed production boundary."""


def _production_names(root: Path) -> list[str]:
    try:
        config = json.loads((root / "production_tools/profiles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StartupPolicyError("无法读取现行生产插件清单，请先修复运行区配置。") from error
    names = config.get("production") if isinstance(config, dict) else None
    if not isinstance(names, list) or not names:
        raise StartupPolicyError("生产插件清单必须是非空列表。")
    if any(not isinstance(name, str) or not _NODE_NAME.fullmatch(name) for name in names):
        raise StartupPolicyError("生产插件清单含无效名称或目录跳转。")
    if len({name.casefold() for name in names}) != len(names):
        raise StartupPolicyError("生产插件清单含重复名称。")
    for name in names:
        if not (root / "ComfyUI/custom_nodes" / name).is_dir():
            raise StartupPolicyError("生产插件缺失：" + name + "；请按主仓部署说明补齐。")
    return names


def _scalar_value(arguments: list[str], index: int, inline: str | None) -> tuple[str, int]:
    if inline is not None:
        return inline, index + 1
    if index + 1 >= len(arguments) or arguments[index + 1].startswith("-"):
        raise StartupPolicyError("受控启动参数缺少明确取值。")
    return arguments[index + 1], index + 2


def _review_arguments(arguments: list[str], names: list[str]) -> tuple[list[str], bool]:
    retained = [arguments[0]]
    seen: dict[str, object] = {}
    index = 1
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            raise StartupPolicyError("受控启动不接受停止参数解析的 -- 标记。")
        option, separator, inline_value = token.partition("=")
        inline = inline_value if separator else None
        if option.startswith("--") and option not in _PROTECTED:
            # ComfyUI uses argparse abbreviations. Do not let an abbreviated
            # protected option bypass the boundary; other flags remain intact.
            if any(protected.startswith(option) for protected in _PROTECTED):
                raise StartupPolicyError("涉及运行边界的参数必须使用完整名称。")
        if option in _REDIRECTS:
            raise StartupPolicyError("绘世受控入口不允许重定向工作区、资料或数据库；请使用主仓维护流程。")
        if option in _CONFLICTS:
            raise StartupPolicyError("绘世参数与现行生产插件或本地启动范围冲突；请在高级选项中移除冲突参数。")
        if option not in _CONTROLLED:
            retained.append(token)
            index += 1
            continue

        if option in {"--listen", "--port"}:
            value, next_index = _scalar_value(arguments, index, inline)
            if option == "--listen":
                valid = value == "127.0.0.1"
            else:
                try:
                    valid = int(value) == 8188
                except ValueError:
                    valid = False
            if not valid:
                raise StartupPolicyError("绘世受控入口固定使用 127.0.0.1:8188，请移除监听或端口覆盖。")
            reviewed: object = value
        elif option == "--whitelist-custom-nodes":
            values = [inline] if inline is not None else []
            next_index = index + 1
            while next_index < len(arguments) and not arguments[next_index].startswith("-"):
                values.append(arguments[next_index])
                next_index += 1
            if len(values) != len(names) or set(values) != set(names):
                raise StartupPolicyError("绘世参数中的插件白名单与现行生产清单不一致。")
            reviewed = tuple(sorted(values))
        else:
            if inline is not None:
                raise StartupPolicyError("受控开关不接受覆盖取值。")
            reviewed = True
            next_index = index + 1
        if option in seen and seen[option] != reviewed:
            raise StartupPolicyError("受控启动参数存在重复且不一致的取值。")
        seen[option] = reviewed
        index = next_index
    if "--auto-launch" in seen and "--disable-auto-launch" in seen:
        raise StartupPolicyError("自动打开浏览器的启用和关闭参数不能同时指定。")
    return retained, "--auto-launch" in seen


def apply_gui_profile(
    root: str | Path,
    argv: MutableSequence[str],
    environ: MutableMapping[str, str],
) -> bool:
    """Validate first, then apply production arguments and consume its marker.

    ``root`` is derived from main.py, never from a GUI/environment path override.
    A failed check leaves both argv and environ unchanged. Ordinary launches
    return immediately, even if the supplied root or profiles file is absent.
    """
    if PROFILE_ENV not in environ:
        return False
    if environ[PROFILE_ENV] != "production":
        raise StartupPolicyError("绘世受控入口只支持现行 production 配置。")
    if not argv or any(not isinstance(argument, str) for argument in argv):
        raise StartupPolicyError("绘世启动参数格式无效。")
    names = _production_names(Path(root))
    retained, auto_launch = _review_arguments(list(argv), names)
    retained.extend([
        "--listen", "127.0.0.1", "--port", "8188",
        "--auto-launch" if auto_launch else "--disable-auto-launch",
        "--disable-all-custom-nodes", "--whitelist-custom-nodes", *names,
    ])
    argv[:] = retained
    del environ[PROFILE_ENV]
    return True
