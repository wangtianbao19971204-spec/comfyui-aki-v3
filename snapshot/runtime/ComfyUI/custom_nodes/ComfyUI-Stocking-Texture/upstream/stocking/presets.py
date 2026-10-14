"""Look presets: named snapshots of the 纹理 settings, kept per user in settings.json, not with an image.

A preset is look.clean_params of the settings it was saved from, so it holds whatever the panel holds (a later
version's new settings come along), the 纹理层 included. An automatic strength is stored as the default: it is worked
out per image.

Saving checks everything. Reading never fails on one bad entry (an unknown style, a value out of range, a key from a
newer version): that entry is listed as unreadable, and the file is not rewritten on read, so presets saved by a newer
version survive a pass through an older one.

A preset can be handed to someone else as a small file (file_text, import_file): JSON holding a format mark, a version,
the name and the settings. Reading one checks everything the same way saving does, and never replaces a preset: a name
that is taken gets a number after it.
"""
import json
import os
import re
import threading

from . import look, settings
from .i18n import tr

KEY = 'look_presets'
MAX_NAME = 40
FORMAT = 'stocking-look-preset'     # the mark of a preset file
VERSION = 1                         # what a file written now says; a file with a higher number is from a newer version
MAX_FILE = 256 * 1024               # bytes: a preset file is well under 1 KB, so anything this big is not one
EXT = '.json'
# A save or delete reads, changes and writes the whole set; settings.update only locks its own write.
_lock = threading.Lock()


def _stored():
    v = settings.get(KEY)
    return v if isinstance(v, dict) else {}


def clean_name(name):
    """The name trimmed; ValueError (with a message for the user) if it is empty, too long or has control characters."""
    name = name.strip() if isinstance(name, str) else ''
    if not name:
        raise ValueError(tr('预设要有一个名字'))
    if len(name) > MAX_NAME:
        raise ValueError(tr('预设的名字最多 {n} 个字', n=MAX_NAME))
    if not name.isprintable():
        raise ValueError(tr('预设的名字里不能有换行之类的控制字符'))
    return name


def snapshot(params):
    """The settings as a preset stores them (look.clean_params, ValueError if they are not valid)."""
    q = look.clean_params(params)
    for layer in (q, *q['layers']):
        if layer['strength_auto']:
            layer['strength'] = look.DEFAULTS['strength']
    return q


def listing():
    """[{'name', 'params'}] in the order saved; params is None for an entry that cannot be read."""
    out = []
    for name, raw in _stored().items():
        try:
            params = look.clean_params(raw)
        except (ValueError, TypeError):
            params = None
        out.append({'name': name, 'params': params})
    return out


def save(name, params):
    """Store the settings under name, replacing a preset of that name (it keeps its place). Returns the listing."""
    name = clean_name(name)
    snap = snapshot(params)
    with _lock:
        presets = dict(_stored())
        presets[name] = snap
        settings.update(**{KEY: presets})
    return listing()


def delete(name):
    """Remove the preset; ValueError if there is none of that name. Returns the listing."""
    with _lock:
        presets = dict(_stored())
        if name not in presets:
            raise ValueError(tr('没有叫“{name}”的预设', name=name))
        del presets[name]
        settings.update(**{KEY: presets})
    return listing()


# ---------------------------------------------------------------- files to hand to someone else

def file_name(name):
    """The file name a preset is offered under: its name with what Windows does not allow in a file name made '_'."""
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name).strip(' .') or 'preset'
    return stem + EXT


def file_text(name):
    """The file of one saved preset, as text: JSON with the format mark, the version, the name and the settings.
    ValueError (with a message for the user) if there is none of that name or it cannot be read."""
    for entry in listing():
        if entry['name'] == name:
            if entry['params'] is None:
                raise ValueError(tr('这个预设读不了（可能是新版本存的），可以删掉它。'))
            data = {'format': FORMAT, 'version': VERSION, 'name': name, 'params': snapshot(entry['params'])}
            return json.dumps(data, ensure_ascii=False, indent=1) + '\n'
    raise ValueError(tr('没有叫“{name}”的预设', name=name))


def _imported_name(raw, path):
    """The name an imported preset goes in under: the file's own, cut to fit if it is long; the file's name when the
    file has none (or only control characters)."""
    name = raw.strip()[:MAX_NAME].strip() if isinstance(raw, str) else ''
    if not name or not name.isprintable():
        name = os.path.splitext(os.path.basename(path))[0].strip()[:MAX_NAME].strip()
    if not name or not name.isprintable():
        raise ValueError(tr('预设要有一个名字'))
    return name


def _free_name(name, taken):
    """name, or name with ' (2)', ' (3)' … after it (the name cut to leave room) when it is taken."""
    if name not in taken:
        return name
    n = 2
    while True:
        tail = f' ({n})'
        candidate = name[:MAX_NAME - len(tail)].rstrip() + tail
        if candidate not in taken:
            return candidate
        n += 1


def read_file(path):
    """(name, settings) of a preset file, checked like a save: ValueError (with a message for the user) if it cannot
    be read, is not a preset file, is from a newer version or holds settings that are not valid. The name is the
    file's own; it has not been made unique."""
    try:
        if os.path.getsize(path) > MAX_FILE:
            raise ValueError(tr('这不是预设文件：{file}', file=os.path.basename(path)))
        with open(path, encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(tr('读不了这个文件：{name}', name=os.path.basename(path))) from e
    except json.JSONDecodeError:
        raise ValueError(tr('这不是预设文件：{file}', file=os.path.basename(path))) from None
    if not isinstance(data, dict) or data.get('format') != FORMAT or not isinstance(data.get('params'), dict):
        raise ValueError(tr('这不是预设文件：{file}', file=os.path.basename(path)))
    version = data.get('version')
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError(tr('这不是预设文件：{file}', file=os.path.basename(path)))
    if version > VERSION:
        raise ValueError(tr('这个预设文件是新版本存的，先更新再导入'))
    return _imported_name(data.get('name'), path), snapshot(data['params'])


def import_file(path):
    """Add the preset in the file. It never replaces one: a name that is taken gets a number after it. Returns
    (listing, the name it went in under, whether that is not the file's own name)."""
    name, params = read_file(path)
    with _lock:
        presets = dict(_stored())
        final = _free_name(name, presets)
        presets[final] = params
        settings.update(**{KEY: presets})
    return listing(), final, final != name
