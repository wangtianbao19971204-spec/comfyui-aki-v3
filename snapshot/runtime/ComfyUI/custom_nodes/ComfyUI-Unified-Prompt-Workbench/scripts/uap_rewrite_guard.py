#!/usr/bin/env python3
"""UAP 静态门禁：R1 禁止把 serialize 结果回灌 loadGraphData；R2 命名导入必须真实导出；R3/R4 只报 WARN。"""
import argparse
import json
import os
import re
import sys

PACK_NAME = "ComfyUI-Unified-Prompt-Workbench"
SKIP_DIRS = {"node_modules", "__pycache__", "user_data", "data", "tests", ".git", "dist", "build"}
SOURCES = (".js", ".mjs")

LOAD_GRAPH = re.compile(r"\bloadGraphData\s*\(")
SERIALIZE = re.compile(r"\bserialize\s*\(")
IMPORT_FROM = re.compile(r"\bimport\s+([^;]*?)\bfrom\s*['\"]([^'\"]+)['\"]")
IMPORT_NAMES = re.compile(r"\{([^}]*)\}")
DECLARED = re.compile(r"\bexport\s+(?:async\s+)?(?:function\s*\*?|class|const|let|var)\s+([A-Za-z_$][\w$]*)")
EXPORT_LIST = re.compile(r"\bexport\s*\{([^}]*)\}")
BARREL = re.compile(r"\bexport\s*\*")
DEFAULT_EXPORT = re.compile(r"\bexport\s+default\b")
MODES_WRITE = re.compile(r"\.modes\[[^\]]*\]\s*(?:[+\-*/%|&]{0,2}=(?!=))")
SET_INTERVAL = re.compile(r"\bsetInterval\s*\(")


def source_files(pack):
    for root, dirs, files in os.walk(pack):
        dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP_DIRS)
        for name in sorted(files):
            if name.endswith(SOURCES):
                yield os.path.join(root, name)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def line_at(src, index):
    return src.count("\n", 0, index) + 1


def call_arguments(src, pattern):
    """括号配平取出实参文本，避免固定窗口把下一句算进来。"""
    for match in pattern.finditer(src):
        depth = 0
        index = match.end() - 1
        while index < len(src):
            char = src[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        yield match.start(), src[match.end():index]


def exports_of(path):
    """模块的具名导出；barrel（export *）返回 None，静态无法穷举。"""
    try:
        src = read(path)
    except OSError:
        return None
    if BARREL.search(src):
        return None
    names = set()
    for match in DECLARED.finditer(src):
        names.add(match.group(1))
        head = src[match.end():].split(";")[0]
        names.update(re.findall(r",\s*([A-Za-z_$][\w$]*)\s*=", head))
    for match in EXPORT_LIST.finditer(src):
        for part in match.group(1).split(","):
            part = part.strip()
            if part:
                names.add(re.split(r"\s+as\s+", part)[-1].strip())
    if DEFAULT_EXPORT.search(src):
        names.add("default")
    return names


def resolve_target(spec, origin, pack):
    """相对路径按引入文件所在目录解析；/extensions/<本插件>/ 前缀落到插件根。"""
    spec = spec.split("?", 1)[0].split("#", 1)[0]
    if spec.startswith("/extensions/"):
        name, _, rest = spec[len("/extensions/"):].partition("/")
        if name != PACK_NAME:
            return None
        return os.path.join(pack, rest.replace("/", os.sep))
    if not spec.startswith(("./", "../")):
        return None
    return os.path.normpath(os.path.join(os.path.dirname(origin), spec.replace("/", os.sep)))


def check_r1(rel, src):
    hits = []
    for start, args in call_arguments(src, LOAD_GRAPH):
        if SERIALIZE.search(args):
            hits.append("%s:%d" % (rel, line_at(src, start)))
    return hits


def check_r2(rel, path, src, pack):
    hits, skipped = [], 0
    for match in IMPORT_FROM.finditer(src):
        braces = IMPORT_NAMES.search(match.group(1))
        if not braces:
            continue  # 默认导入、命名空间导入没有可核对的具名
        wanted = [re.split(r"\s+as\s+", part.strip())[0] for part in braces.group(1).split(",") if part.strip()]
        target = resolve_target(match.group(2), path, pack)
        exported = exports_of(target) if target and os.path.isfile(target) else None
        if not wanted or exported is None:
            skipped += 1
            continue
        missing = [name for name in wanted if name not in exported]
        if missing:
            hits.append("%s:%d 缺 %s (from %s)" % (rel, line_at(src, match.start()), ",".join(missing), match.group(2)))
    return hits, skipped


def scan(pack):
    r1, r2, r3, r4 = [], [], [], []
    skipped = 0
    for path in source_files(pack):
        rel = os.path.relpath(path, pack)
        src = read(path)
        r1.extend(check_r1(rel, src))
        found, skip = check_r2(rel, path, src, pack)
        r2.extend(found)
        skipped += skip
        if re.search(r"\bbranch", src):  # 单复数都算，branches 必然命中
            r3.extend("%s:%d" % (rel, line_at(src, m.start())) for m in MODES_WRITE.finditer(src))
        r4.extend("%s:%d" % (rel, line_at(src, m.start())) for m in SET_INTERVAL.finditer(src))
    return {"pass": not (r1 or r2), "r1": r1, "r2": r2, "r3_warn": r3, "r4_warn": r4, "skipped": skipped}


def report(title, items):
    print("%s: %d" % (title, len(items)))
    for item in items:
        print("   " + item)


def main(argv=None):
    default_pack = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description="UAP 静态门禁：R1/R2 阻断，R3/R4 预警")
    parser.add_argument("--pack", default=default_pack, help="插件根目录，默认取脚本上一级")
    parser.add_argument("--json", action="store_true", dest="as_json", help="输出机器可读结果")
    parser.add_argument("--strict", action="store_true", help="WARN 也计入退出码")
    args = parser.parse_args(argv)

    pack = os.path.abspath(args.pack)
    if not os.path.isdir(pack):
        print("插件目录不存在: %s" % pack)
        return 2
    result = scan(pack)
    result["pass"] = result["pass"] and not (args.strict and (result["r3_warn"] or result["r4_warn"]))
    code = 0 if result["pass"] else 1

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    print("UAP 静态门禁 %s" % pack)
    report("R1 回灌画布(loadGraphData + serialize)", result["r1"])
    report("R2 命名导入未导出", result["r2"])
    report("R3 branches[].modes 运行期写入 (WARN)", result["r3_warn"])
    report("R4 setInterval (WARN)", result["r4_warn"])
    print("不可判定跳过: %d" % result["skipped"])
    print("结论: %s" % ("PASS" if code == 0 else "FAIL"))
    return code


if __name__ == "__main__":
    sys.exit(main())
