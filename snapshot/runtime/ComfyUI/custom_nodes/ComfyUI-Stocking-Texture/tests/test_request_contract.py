"""Compare upstream Pydantic request fields with reads in each adapter handler.

Parse the pristine server; never import its global services. Missing/new routes,
fields and stale exemptions fail. Pixel/validation behavior lives in test_issue3.
STOCKING_ADAPTER_SOURCE selects a saved old adapter for the required red/green run.
"""
import ast
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOC = "/api/doc/{doc_id}/"

# Select a function followed by exact nested branch conditions. Inspect only the
# selected if-body, not its elif/else siblings, so another route cannot cover it.
HANDLERS = {
    ("POST", "/api/lang"): ("action", ("path", "api/lang"), ("method", "POST")),
    ("PUT", "/api/look/presets"): ("action", ("path", "api/look/presets"), ("method", "PUT")),
    ("DELETE", "/api/look/presets"): ("action", ("path", "api/look/presets"), ("method", "DELETE")),
    ("POST", DOC + "regions"): ("edit_document", ("action", "regions")),
    ("PATCH", DOC + "regions/{rid}"): ("edit_document", ("method", "PATCH")),
    ("POST", DOC + "strokes"): ("edit_document", ("action", "strokes")),
    ("POST", DOC + "dividers"): ("edit_document", ("action", "dividers")),
    ("POST", DOC + "walls/remove"): ("edit_document", ("action", "walls/remove")),
    ("POST", DOC + "segment/cycle"): ("edit_document", ("action", "segment/cycle")),
    ("POST", DOC + "segment/select"): ("edit_document", ("action", "segment/select")),
    ("PUT", DOC + "coverage/exclude"): ("edit_document", ("action", "coverage/exclude")),
    ("POST", DOC + "export"): ("export_document",),
    **{("POST", DOC + "regions/{rid}/" + name): ("edit_document", ("op", name))
       for name in ("paint", "segment", "split", "merge", "mirror")},
}
UNSUPPORTED = {
    ("POST", "/api/open/path"): {"path": "Browser upload replaces arbitrary server filesystem paths."},
    ("POST", DOC + "export/ask"): {"kind": "The browser chooses the download location; native save dialogs are not hosted."},
    ("POST", DOC + "export"): {"path": "Exports use adapter-owned generated paths and browser downloads; caller paths are intentionally ignored."},
}


def upstream_requests(source):
    tree = ast.parse(source)
    models = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any(isinstance(b, ast.Name) and b.id == "BaseModel" for b in node.bases):
            models[node.name] = {n.target.id for n in node.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    requests = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        fields = set()
        for arg in (*node.args.args, *node.args.kwonlyargs):
            if arg.annotation:
                for name in ast.walk(arg.annotation):
                    if isinstance(name, ast.Name):
                        fields.update(models.get(name.id, set()))
        if not fields:
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app"
                    and dec.args and isinstance(dec.args[0], ast.Constant)):
                requests[(dec.func.attr.upper(), dec.args[0].value)] = fields
    if not requests:
        raise AssertionError("No upstream request models found; review the source parser")
    return requests


def handler_fields(tree, selector):
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == selector[0]]
    if len(functions) != 1:
        raise AssertionError("Adapter handler changed: " + str(selector))
    block = ast.Module(body=functions[0].body, type_ignores=[])
    for key, value in selector[1:]:
        branches = []
        for node in ast.walk(block):
            if isinstance(node, ast.If) and any(
                isinstance(c, ast.Compare) and isinstance(c.left, ast.Name) and c.left.id == key
                and len(c.ops) == 1 and isinstance(c.ops[0], ast.Eq)
                and isinstance(c.comparators[0], ast.Constant) and c.comparators[0].value == value
                for c in ast.walk(node.test)
            ):
                branches.append(node)
        if len(branches) != 1:
            raise AssertionError("Adapter branch changed: " + str(selector))
        block = ast.Module(body=branches[0].body, type_ignores=[])
    fields = set()
    for node in ast.walk(block):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "body" and isinstance(node.slice, ast.Constant):
            fields.add(node.slice.value)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "body"
                and node.func.attr in ("get", "pop") and node.args and isinstance(node.args[0], ast.Constant)):
            fields.add(node.args[0].value)
    return fields


def check_contract(upstream_source, adapter_source):
    requests = upstream_requests(upstream_source)
    tree = ast.parse(adapter_source)
    errors = []
    for route in (HANDLERS.keys() | UNSUPPORTED.keys()) - requests.keys():
        errors.append("stale route mapping: " + str(route))
    for route, fields in requests.items():
        skipped = UNSUPPORTED.get(route, {})
        if any(not reason.strip() for reason in skipped.values()) or skipped.keys() - fields:
            errors.append("stale/undocumented exemption: " + str(route))
        handled = handler_fields(tree, HANDLERS[route]) if route in HANDLERS else set()
        for field in sorted(fields - handled - skipped.keys()):
            errors.append(f"{route[0]} {route[1]}: unhandled field {field}")
    return errors


class RequestContract(unittest.TestCase):
    def test_upstream_body_fields_are_handled_or_explicitly_exempted(self):
        upstream = (ROOT / "upstream/stocking/server.py").read_text(encoding="utf-8")
        adapter = Path(os.environ.get("STOCKING_ADAPTER_SOURCE", ROOT / "studio_api.py")).read_text(encoding="utf-8")
        self.assertEqual(check_contract(upstream, adapter), [])


if __name__ == "__main__":
    unittest.main()
