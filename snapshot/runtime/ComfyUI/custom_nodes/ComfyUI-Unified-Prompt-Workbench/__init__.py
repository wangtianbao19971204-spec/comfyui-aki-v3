"""Unified prompt workbench with compatible node and extension identities."""
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path

import nodes
from aiohttp import web
from server import PromptServer

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / 'modules.json').read_text(encoding='utf-8'))
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
MODULE_STATUS = []
WEB_DIRECTORY = './web'
logger = logging.getLogger(__name__)


@PromptServer.instance.routes.get('/unified-workbench/status')
async def unified_workbench_status(request):
    return web.json_response({'name': '统一工作台', 'version': MANIFEST['version'],
        'modules': MODULE_STATUS, 'nodes': len(NODE_CLASS_MAPPINGS), 'resource_owner': 'weilin',
        'degraded': any(not item['ready'] for item in MODULE_STATUS)})


def _load_module(entry):
    directory = ROOT / 'modules' / entry['directory']
    module_name = __name__ + '.' + entry['key']
    web_before = dict(nodes.EXTENSION_WEB_DIRS)
    loaded_before = dict(nodes.LOADED_MODULE_DIRS)
    # aiohttp's table is not frozen until ComfyUI finishes loading extensions.
    route_items = PromptServer.instance.routes._items
    route_count = len(route_items)
    module_keys = set(sys.modules)
    # Module imports register owner callbacks and prompt handlers on this singleton.
    # Loading is synchronous: preserve all registrations of prior successful modules.
    server_instance = PromptServer.instance
    server_before = dict(vars(server_instance))
    prompt_handlers = getattr(server_instance, 'on_prompt_handlers', None)
    handlers_before = list(prompt_handlers) if isinstance(prompt_handlers, list) else None
    try:
        spec = importlib.util.spec_from_file_location(module_name, directory / '__init__.py',
            submodule_search_locations=[str(directory)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as error:
        for name in set(vars(server_instance)) - set(server_before):
            delattr(server_instance, name)
        for name, value in server_before.items():
            setattr(server_instance, name, value)
        if handlers_before is not None:
            prompt_handlers[:] = handlers_before
        del route_items[route_count:]
        nodes.EXTENSION_WEB_DIRS.clear()
        nodes.EXTENSION_WEB_DIRS.update(web_before)
        nodes.LOADED_MODULE_DIRS.clear()
        nodes.LOADED_MODULE_DIRS.update(loaded_before)
        for name in set(sys.modules) - module_keys:
            if name == module_name or name.startswith(module_name + '.'):
                sys.modules.pop(name, None)
        MODULE_STATUS.append({'key': entry['key'], 'label': entry['label'], 'nodes': 0,
            'ready': False, 'error_type': type(error).__name__,
            'error': '模块未能加载，请查看启动日志并修复依赖后重启。'})
        logger.exception('Workbench module %s failed to load; independent modules remain available', entry['key'])
        return
    classes = getattr(module, 'NODE_CLASS_MAPPINGS', {})
    duplicates = set(classes) & set(NODE_CLASS_MAPPINGS)
    if duplicates:
        raise RuntimeError('Duplicate unified node identities: ' + ', '.join(sorted(duplicates)))
    NODE_CLASS_MAPPINGS.update(classes)
    NODE_DISPLAY_NAME_MAPPINGS.update(getattr(module, 'NODE_DISPLAY_NAME_MAPPINGS', {}))
    if getattr(module, 'WEB_DIRECTORY', None):
        nodes.EXTENSION_WEB_DIRS[entry['directory']] = os.path.abspath(directory / module.WEB_DIRECTORY)
    nodes.LOADED_MODULE_DIRS[entry['directory']] = str(directory)
    MODULE_STATUS.append({'key': entry['key'], 'label': entry['label'], 'nodes': len(classes), 'ready': True})


for entry in MANIFEST['modules']:
    _load_module(entry)

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
