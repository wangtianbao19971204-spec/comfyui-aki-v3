"""Check saved PromptSelector output against the old category/prompt ordering contract."""

import ast
from pathlib import Path


source = Path('ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/'
              'WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector/prompt_selector.py')
tree = ast.parse(source.read_text(encoding='utf-8'))
resolver = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == '_resolve_saved_selection')
library = {
    'settings': {'separator': ' | '},
    'categories': [
        {'name': 'B', 'prompts': [{'prompt': 'second'}, {'prompt': 'first'}]},
        {'name': 'A', 'prompts': [{'prompt': 'alpha'}, {'prompt': 'missing'}]},
    ],
}
scope = {'_reviewed_library_data': lambda: library, '_revision': lambda _: 'test-revision'}
exec(compile(ast.Module(body=[resolver], type_ignores=[]), str(source), 'exec'), scope)
resolve = scope['_resolve_saved_selection']

result = resolve({'A': ['alpha'], 'B': {'first': True, 'second': True},
                  'unknown': ['unused']},
                 {'B': {'first': 1.25, 'second': 0}, 'A': {'alpha': 1}})
assert result == {'output': 'second | (first:1.25) | alpha', 'revision': 'test-revision'}
assert resolve({}, {})['output'] == ''
try:
    resolve(['invalid'], {})
except ValueError:
    pass
else:
    raise AssertionError('invalid selection shape was accepted')
print('saved selection order, weights, missing entries, and input shape: passed')
