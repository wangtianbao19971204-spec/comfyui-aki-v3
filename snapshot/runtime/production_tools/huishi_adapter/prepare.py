"""Prepare a private, reviewable Huishi delivery packet; never deploy or launch.

The default is a read-only plan. ``--prepare`` writes only a new external
directory, containing exact candidate bytes, rollback bytes and a receipt.
Vendor binaries and machine paths belong to that private packet, never Git.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat


class DeliveryError(ValueError):
    """The inputs cannot produce an unambiguous, reviewed delivery packet."""


@dataclass(frozen=True)
class VendorPins:
    bootstrap: str = "8652f7a83144b8faa18a5b5d0c75444e4da2004933b645a9636e9b4ae914229e"
    gui: str = "c6b569a1c7f00be362512ed4047a43ff20945baa47d1e2898ccbc052df2bfc2e"
    libgit: str = "3ca98bc5046b42f8583e1d9265943a9ba791086e81d669a5f271307f8271b143"
    native_git: str = "76b97b411e73b7487825dd0f98cba7ce7f008bef3cbe8a35bf1af8c651a0f4a0"


PINS = VendorPins()
CORE_BASELINE = "cc0fc21fea7a6a82f568362b15b7fbd713b419c1"
ADAPTER = "production_tools/huishi_adapter"
HOOK_NAME = "Huishi.SingleGit.StartupHook.dll"
VENDOR_FILES = {
    "bootstrap": "绘世启动器.exe",
    "gui": ".launcher/StableDiffusionWebUILauncher.dll",
    "libgit": ".launcher/LibGit2Sharp.dll",
    "native_git": ".launcher/git2-e632535.dll",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _absolute(value: Path | str) -> Path:
    raw = os.fspath(value)
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts:
        raise DeliveryError("Paths must be absolute and contain no parent traversal.")
    # Windows device/UNC paths, ADS, short names and trailing-dot aliases are not
    # portable deployment identities. Resolve does not reject all these aliases.
    if os.name == "nt":
        if raw.startswith(("\\\\", "//")) or not re.fullmatch(r"[A-Za-z]:", path.drive):
            raise DeliveryError("Only ordinary local drive paths are accepted.")
        for part in path.parts[1:]:
            if ":" in part or part.endswith((".", " ")) or re.search(r"~\d", part):
                raise DeliveryError("Ambiguous Windows path spelling is rejected.")
    _no_links(path)
    resolved = path.resolve(strict=False)
    if os.path.normcase(str(path)) != os.path.normcase(str(resolved)):
        raise DeliveryError("Path aliases are rejected.")
    return path


def _no_links(path: Path) -> None:
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise DeliveryError("Linked/reparse paths are rejected.")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise DeliveryError("Hard-linked files are rejected.")


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _read(path: Path, identities: dict[tuple[int, int], tuple[Path, str]]) -> bytes:
    _no_links(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise DeliveryError("Expected an ordinary single-link file.")
    identity = (before.st_dev, before.st_ino)
    if identity in identities and identities[identity][0] != path:
        raise DeliveryError("Two inputs refer to the same physical file.")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != identity or opened.st_nlink != 1:
            raise DeliveryError("File identity changed while reading.")
        data = stream.read()
        after = os.fstat(stream.fileno())
    final = path.stat()
    if (before.st_size, before.st_mtime_ns, identity) != (
            after.st_size, after.st_mtime_ns, (after.st_dev, after.st_ino)) or (
            final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
        raise DeliveryError("Input changed while reading; prepare a fresh packet.")
    identities[identity] = (path, digest(data))
    return data


def _file_record(data: bytes | None) -> dict:
    return {"missing": data is None, "sha256": None if data is None else digest(data),
            "size": 0 if data is None else len(data)}


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def prepare_packet(repository: Path | str, runtime: Path | str, hook_build: Path | str,
                   entry_executable: Path | str, output: Path | str, *,
                   write: bool = False, _pins: VendorPins = PINS) -> dict:
    """Inspect fixed inputs and optionally materialize a private packet.

    ``_pins`` is solely an internal dependency for synthetic fixture tests; the
    CLI has no pin-override switch. There is deliberately no apply operation.
    """
    repository, runtime, hook_build, entry_executable, output = map(_absolute,
        (repository, runtime, hook_build, entry_executable, output))
    if repository != runtime / "maintenance/comfyui":
        raise DeliveryError("The repository must be runtime/maintenance/comfyui.")
    for directory in (repository, runtime, hook_build):
        if not directory.is_dir():
            raise DeliveryError("A required input directory is missing.")
    if output.exists():
        raise DeliveryError("Output must be a new directory; existing packets are preserved.")
    if not output.parent.is_dir():
        raise DeliveryError("The external output parent must already exist.")
    for protected in (runtime, repository, hook_build, entry_executable):
        if _inside(output, protected) or _inside(protected, output):
            raise DeliveryError("The packet must not overlap any input or runtime tree.")
    if _inside(hook_build, runtime) or _inside(entry_executable, runtime):
        raise DeliveryError("Compiled binaries must come from an external build directory.")
    for retired in (runtime / ".git", runtime / "ComfyUI/.git"):
        _no_links(retired)
        if retired.exists():
            raise DeliveryError("A runtime Git remains; resolve the sole-repository boundary first.")

    # Never read a pre-existing private settings body or overwrite a preserved
    # vendor original. Re-preparation of an installed instance needs a separate
    # reviewed migration, rather than implicitly assuming the initial layout.
    for forbidden in (runtime / "绘世启动器原版.exe", runtime / ADAPTER / "entry.local.json"):
        _no_links(forbidden)
        if forbidden.exists():
            raise DeliveryError("An adapter/original already exists; no private config was read.")
    identities: dict[tuple[int, int], tuple[Path, str]] = {}
    vendor = {}
    observations = []
    for role, relative in VENDOR_FILES.items():
        data = _read(runtime / relative, identities)
        if digest(data) != getattr(_pins, role):
            raise DeliveryError("Pinned vendor version changed: " + role)
        vendor[role] = data
        observations.append({"target": relative, **_file_record(data), "role": role})

    source_root = repository / "snapshot/runtime"
    candidates = {
        "绘世启动器.exe": _read(entry_executable, identities),
        "绘世启动器原版.exe": vendor["bootstrap"],
        "ComfyUI/main.py": _read(source_root / "ComfyUI/main.py", identities),
        ADAPTER + "/runtime_start.py": _read(source_root / ADAPTER / "runtime_start.py", identities),
        ADAPTER + "/bin/" + HOOK_NAME: _read(hook_build / HOOK_NAME, identities),
        ADAPTER + "/bin/0Harmony.dll": _read(hook_build / "0Harmony.dll", identities),
    }
    try:
        build = json.loads(_read(hook_build / "build.receipt.json", identities))
    except (OSError, ValueError) as error:
        raise DeliveryError("The Hook build receipt is missing or invalid.") from error
    expected_sources = {}
    for name in ("StartupHook.cs", "NativeGuards.cs", "ProcessPolicy.cs"):
        expected_sources[name] = digest(_read(source_root / ADAPTER / name, identities))
    if not isinstance(build, dict) or build.get("source_sha256") != expected_sources:
        raise DeliveryError("Hook build sources differ from the current maintenance sources.")
    if build.get("assembly_sha256") != digest(candidates[ADAPTER + "/bin/" + HOOK_NAME]):
        raise DeliveryError("Hook bytes differ from their build receipt.")
    dependencies = build.get("dependency_sha256")
    if not isinstance(dependencies, dict) or dependencies.get("0Harmony.dll") != digest(
            candidates[ADAPTER + "/bin/0Harmony.dll"]) or dependencies.get("LibGit2Sharp.dll") != _pins.libgit:
        raise DeliveryError("Hook build dependencies differ from the pinned runtime.")
    if build.get("runtime_target") != "net6.0" or build.get("deployed") is not False:
        raise DeliveryError("The build receipt has an unsupported target/state.")
    try:
        entry_build = json.loads(_read(entry_executable.parent / "build.receipt.json", identities))
    except (OSError, ValueError) as error:
        raise DeliveryError("The entry build receipt is missing or invalid.") from error
    entry_source = digest(_read(source_root / ADAPTER / "Entry.cs", identities))
    if not isinstance(entry_build, dict) or entry_build.get("source_sha256") != {"Entry.cs": entry_source}:
        raise DeliveryError("Entry build source differs from the current maintenance source.")
    if entry_build.get("executable_sha256") != digest(candidates["绘世启动器.exe"]):
        raise DeliveryError("Entry bytes differ from their build receipt.")
    if entry_build.get("runtime_target") != "net48" or entry_build.get("deployed") is not False:
        raise DeliveryError("The entry build receipt has an unsupported target/state.")

    settings = {"mode": "managed", "maintenance_repo": str(repository),
        "hook": str(runtime / ADAPTER / "bin" / HOOK_NAME),
        "hook_sha256": digest(candidates[ADAPTER + "/bin/" + HOOK_NAME]),
        "harmony_sha256": digest(candidates[ADAPTER + "/bin/0Harmony.dll"]),
        "core_baseline": CORE_BASELINE,
        "main_sha256": digest(candidates["ComfyUI/main.py"]),
        "runtime_start_sha256": digest(candidates[ADAPTER + "/runtime_start.py"]),
        "log": str(output / "huishi-adapter.log")}
    candidates[ADAPTER + "/entry.local.json"] = _json_bytes(settings)
    previous = {}
    targets = []
    for relative, after in candidates.items():
        destination = runtime / relative
        _no_links(destination)
        before = _read(destination, identities) if destination.exists() else None
        previous[relative] = before
        targets.append({"target": relative, "before": _file_record(before),
                        "after": _file_record(after), "operation": "create" if before is None else "replace"})
    # An individually stable read does not establish a consistent packet across
    # many files. Reject an input that changed while later inputs were inspected.
    for path, expected in tuple(identities.values()):
        if digest(_read(path, identities)) != expected:
            raise DeliveryError("An input changed during packet preparation.")
    receipt = {"schema": "huishi-delivery-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "prepared": write, "deployed": False, "runtime_root": str(runtime),
        "maintenance_repo": str(repository), "output": str(output), "core_baseline": CORE_BASELINE,
        "vendor_observations": observations, "hook_build": build, "entry_build": entry_build, "targets": targets,
        "required_before_apply": ["explicit_deployment_authorization", "current_target_hashes_and_links",
            "empty_queue", "service_pid_start_time_and_port_owner", "consistent_database_backup",
            "accepted_gui_and_start_stop_lifecycle"],
        "verified_by_this_tool": ["input_paths", "vendor_pins", "hook_build_source_identity",
            "exact_candidate_and_rollback_bytes"],
        "service_started": False, "database_read": False, "runtime_written": False}
    if write:
        # Validation above completes before creating anything. mkdir remains
        # exclusive; a colliding packet is never reused or deleted on failure.
        _no_links(output.parent)
        output.mkdir()
        for side, content in (("after", candidates), ("before", previous)):
            for relative, data in content.items():
                if data is None:
                    continue
                destination = output / side / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as stream:
                    stream.write(data)
        with (output / "receipt.json").open("xb") as stream:
            stream.write(_json_bytes(receipt))
        with (output / "ROLLBACK.md").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(_ROLLBACK)
    return receipt


_ROLLBACK = """# 绘世适配候选与回滚包

本目录是私有准备包，尚未部署。after 是候选，before 是原字节；
receipt.json 逐项记录相对运行目标、摘要、长度与原来是否缺失。
原版绘世保存到 after/绘世启动器原版.exe；未修改其 EXE、GUI DLL 或 Git 库。

## 应用前

本工具不提供自动应用。须另行明确授权部署，核对全部 before 摘要、路径无链接、
队列为空、当前服务 PID/启动时间/端口占用及一致数据库备份，并完成图形界面和
启动/停止生命周期验收。任一文件发生变化，保留现场并重新审查，不能强制覆盖。
本包未读取数据库或既有认证配置，未启动或停止任何服务。

## 回滚

回滚也须核对队列、服务身份、路径及当前目标摘要。目标须仍与 receipt 的 after
摘要相同；若已有后续修改，先保护现场，不能直接使用本包回退。
before.missing=false 的目标用 before 中同一相对路径的原字节恢复；
before.missing=true 的新增目标仅在摘要完全匹配后移除。别删除整个目录或私密配置。
原根入口会由 before/绘世启动器.exe 恢复；原 main.py 也按同批备份恢复。
本包只回滚精确文件，不回滚数据库、模型、图像、运行参数或维护 Git。
入口和 main.py 必须成批处理，禁止把新入口与旧 runtime_start.py 混装。
回滚后再次核对摘要、原 GUI、版本来源和实际服务状态，再记录验收收据。
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--hook-build", required=True, type=Path)
    parser.add_argument("--entry-executable", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prepare", action="store_true", help="Write a new private packet; never deploy.")
    arguments = parser.parse_args(argv)
    try:
        result = prepare_packet(arguments.repository, arguments.runtime, arguments.hook_build,
                                arguments.entry_executable, arguments.output, write=arguments.prepare)
    except (DeliveryError, OSError) as error:
        parser.exit(2, "Preparation refused: " + str(error) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
