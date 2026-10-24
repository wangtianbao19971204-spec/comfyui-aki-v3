"""Pre-generate the workbench preview thumbnails outside the running server.

The prompt panel builds a 480x360 WebP thumbnail the first time a preview is
shown (``_ensure_preview_thumbnail`` in prompt_selector.py).  On the current
library only ~26% of the 152k preview files have one, so the first pass over the
Tag card grid pays a JPEG/PNG decode while the user is waiting.  This maintenance
tool walks ``preview/`` and fills ``preview_thumbnails/`` ahead of time with the
same sha1 filename rule, 480x360 box, WEBP output and "thumbnail newer than
source" freshness rule the server uses, so generated files are served as cache
hits and are not invalidated by the server.

Safety: the default is a dry run; ``--apply`` is required to write anything.
Only the thumbnails directory is written (temporary files live there and are
atomically renamed, so an interrupted run leaves no partial WebP).  ``--resume``
continues a previous ``--apply`` run from the recorded prefix.

Examples (from the maintenance repo root, with $comfyPython = runtime python)::

    & $comfyPython -X utf8 -B scripts/pregenerate_preview_thumbnails.py --root <prompt_selector>
    & $comfyPython -X utf8 -B scripts/pregenerate_preview_thumbnails.py --root <prompt_selector> --apply --jobs 4 --fast
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import statistics
import sys
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from PIL import Image, ImageOps

THUMBNAIL_SIZE = (480, 360)
WEBP_QUALITY = 82
WEBP_METHOD = 4         # same settings as the running server
WEBP_METHOD_FAST = 2    # --fast: reduced decode + bilinear, ~-43% wall, ~36 dB PSNR
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tif', '.tiff'}
STATE_FILENAME = '.pregenerate_preview_thumbnails.state.json'
STATE_VERSION = 1
DEFAULT_PROGRESS_EVERY = 500
STATE_SAVE_SECONDS = 30.0


def repository_root():
    return Path(__file__).resolve().parents[1]


def default_store():
    return (repository_root() / 'snapshot' / 'runtime' / 'ComfyUI' / 'custom_nodes'
            / 'ComfyUI-Unified-Prompt-Workbench' / 'modules'
            / 'WeiLin-Comfyui-Tools-V52-FullPromptSelector' / 'user_data' / 'prompt_selector')


def thumbnail_name(filename):
    """Same cache key as ``_ensure_preview_thumbnail``."""
    return hashlib.sha1(filename.encode('utf-8', 'ignore')).hexdigest() + '.webp'


def thumbnail_size(size):
    """Exact size ``Image.thumbnail(THUMBNAIL_SIZE)`` produces, or None to skip."""
    box_x, box_y = THUMBNAIL_SIZE
    if box_x >= size[0] and box_y >= size[1]:
        return None
    aspect = size[0] / size[1]

    def round_aspect(number, key):
        return max(min(math.floor(number), math.ceil(number), key=key), 1)

    if box_x / box_y >= aspect:
        box_x = round_aspect(box_y * aspect, lambda value: abs(aspect - value / box_y))
    else:
        box_y = round_aspect(box_x / aspect, lambda value: 0 if value == 0 else abs(aspect - box_x / value))
    return box_x, box_y


def has_alpha(image):
    return image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info)


def image_orientation(image):
    try:
        return image.getexif().get(274)
    except Exception:  # noqa: BLE001 - malformed EXIF is treated as upright
        return None


def build_thumbnail(source, destination, fast=False):
    """Write one thumbnail; the output contract matches ``_ensure_preview_thumbnail``."""
    temp_path = destination.parent / (destination.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with Image.open(source) as image:
            image.seek(0)
            if fast:
                rotated = image_orientation(image) not in (None, 0, 1)
                if rotated:
                    image = ImageOps.exif_transpose(image)
                original_size = image.size
                final_size = thumbnail_size(original_size)
                if not rotated:
                    image.draft(None, final_size if final_size is not None else original_size)
                mode = 'RGBA' if has_alpha(image) else 'RGB'
                if image.mode != mode:
                    image = image.convert(mode)
                if final_size is not None and image.size != final_size:
                    image = image.resize(final_size, Image.Resampling.BILINEAR, reducing_gap=2.0)
                image.save(temp_path, format='WEBP', quality=WEBP_QUALITY, method=WEBP_METHOD_FAST)
            else:
                image = ImageOps.exif_transpose(image)
                image = image.convert('RGBA' if has_alpha(image) else 'RGB')
                image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                image.save(temp_path, format='WEBP', quality=WEBP_QUALITY, method=WEBP_METHOD)
        os.replace(temp_path, destination)
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def scan_preview(preview_dir):
    """Return sorted image entries, the non-image count and the preview bytes."""
    entries = []
    non_image = 0
    total_bytes = 0
    with os.scandir(preview_dir) as iterator:
        for entry in iterator:
            if not entry.is_file():
                continue
            if os.path.splitext(entry.name)[1].lower() not in IMAGE_EXTENSIONS:
                non_image += 1
                continue
            stat = entry.stat()
            entries.append((entry.name, stat.st_size, stat.st_mtime))
            total_bytes += stat.st_size
    entries.sort(key=lambda entry: entry[0])
    return entries, non_image, total_bytes


def is_fresh(source_mtime, thumbnail_path):
    try:
        return thumbnail_path.is_file() and thumbnail_path.stat().st_mtime >= source_mtime
    except OSError:
        return False


def state_last_name(names, pointer):
    return names[pointer - 1] if pointer > 0 else None


def load_state(path, root):
    try:
        with open(path, encoding='utf-8') as stream:
            state = json.load(stream)
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get('version') != STATE_VERSION:
        return None
    if state.get('root') != str(root):
        return None
    return state


def save_state(path, root, names, pointer, generated, failed, elapsed):
    payload = {
        'version': STATE_VERSION,
        'root': str(root),
        'last': state_last_name(names, pointer),
        'processed': pointer,
        'generated': generated,
        'failed': failed,
        'elapsed_s': round(elapsed, 1),
        'updated': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    temp_path = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with open(temp_path, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def generate_one(source, destination, fast):
    started = time.perf_counter()
    try:
        build_thumbnail(source, destination, fast)
    except Exception as error:  # noqa: BLE001 - one bad preview must not stop the batch
        return {'status': 'failed', 'seconds': time.perf_counter() - started,
                'error': f'{type(error).__name__}: {error}'}
    return {'status': 'generated', 'seconds': time.perf_counter() - started,
            'bytes': destination.stat().st_size}


def format_seconds(seconds):
    if seconds < 90:
        return '%.0fs' % seconds
    if seconds < 5400:
        return '%.1fmin' % (seconds / 60)
    return '%.1fh' % (seconds / 3600)


def plan_work(store, entries, start_index):
    """Fresh thumbnails are already done; everything else needs generating."""
    thumbnail_dir = store / 'preview_thumbnails'
    candidates = []
    processed = set()
    for index in range(start_index, len(entries)):
        name, _size, mtime = entries[index]
        if is_fresh(mtime, thumbnail_dir / thumbnail_name(name)):
            processed.add(index)
        else:
            candidates.append((index, name))
    pointer = start_index
    while pointer in processed:
        pointer += 1
    return candidates, processed, pointer


def print_plan(store, entries, non_image, preview_bytes, start_index, candidates, fresh_count, args):
    print('root:       %s' % store)
    print('preview:    %d image files (%.1f GB) + %d non-image files' % (
        len(entries), preview_bytes / 1e9, non_image))
    print('fresh:      %d thumbnails already up to date%s' % (
        fresh_count, ' after the resume point' if start_index else ''))
    if start_index:
        print('resume:     trusting %d entries recorded by the previous run' % start_index)
    planned = min(len(candidates), args.limit) if args.limit else len(candidates)
    print('plan:       generate %d of %d missing/stale%s' % (
        planned, len(candidates), ' (--limit)' if args.limit and planned < len(candidates) else ''))
    if not args.apply:
        print('mode:       DRY-RUN (nothing is written; pass --apply to generate)')
        return
    print('mode:       APPLY (pipeline=%s, jobs=%d)' % ('fast' if args.fast else 'current', args.jobs))
    print('output:     %s' % (store / 'preview_thumbnails'))
    try:
        free = shutil.disk_usage(store).free
        if free < planned * 40 * 1024 * 2:
            print('warning:    only %.1f GB free; ~%d MB of thumbnails expected' % (
                free / 1e9, planned * 20 / 1024))
    except OSError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=default_store(),
                        help='prompt_selector data dir containing preview/ and preview_thumbnails/ '
                             '(default: repo snapshot runtime path)')
    parser.add_argument('--limit', type=int, default=0,
                        help='generate at most N thumbnails this run (0 = no limit)')
    parser.add_argument('--jobs', type=int, default=2,
                        help='parallel decode/save workers (default 2)')
    parser.add_argument('--apply', action='store_true',
                        help='write thumbnails; without it this is a dry run')
    parser.add_argument('--dry-run', action='store_true',
                        help='explicit dry run (the default); cannot be combined with --apply')
    parser.add_argument('--resume', action='store_true',
                        help='continue after the prefix recorded by a previous --apply run')
    parser.add_argument('--fast', action='store_true',
                        help='use the faster draft+bilinear pipeline (validated ~-43%% wall, '
                             '~36 dB PSNR vs current)')
    parser.add_argument('--progress-every', type=int, default=DEFAULT_PROGRESS_EVERY,
                        help='print progress every N processed thumbnails (default 500)')
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        parser.error('--apply and --dry-run are mutually exclusive')
    if args.jobs < 1:
        parser.error('--jobs must be >= 1')
    if args.limit < 0 or args.progress_every < 1:
        parser.error('--limit and --progress-every must be positive')

    store = args.root.resolve()
    preview_dir = store / 'preview'
    thumbnail_dir = store / 'preview_thumbnails'
    if not preview_dir.is_dir():
        print('error: preview directory not found: %s' % preview_dir, file=sys.stderr)
        print('pass --root <prompt_selector data dir>, e.g. the deployed runtime path', file=sys.stderr)
        return 2
    if thumbnail_dir.resolve() == preview_dir.resolve() or preview_dir.resolve() in thumbnail_dir.resolve().parents:
        print('error: the thumbnails directory must not be the preview directory', file=sys.stderr)
        return 2
    if args.apply:
        thumbnail_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    print('scanning %s ...' % preview_dir)
    entries, non_image, preview_bytes = scan_preview(preview_dir)
    names = [entry[0] for entry in entries]
    name_index = {name: index for index, name in enumerate(names)}

    state_path = thumbnail_dir / STATE_FILENAME
    state = load_state(state_path, store) if args.resume else None
    start_index = 0
    previous_generated = previous_failed = 0
    previous_elapsed = 0.0
    if args.resume:
        if state is None:
            print('resume:     no usable state file; starting a normal run')
        elif state.get('last') in name_index:
            start_index = name_index[state['last']] + 1
            previous_generated = int(state.get('generated') or 0)
            previous_failed = int(state.get('failed') or 0)
            previous_elapsed = float(state.get('elapsed_s') or 0.0)
        else:
            print('resume:     recorded position not found in preview/; starting from the beginning')

    candidates, processed, pointer = plan_work(store, entries, start_index)
    fresh_count = len(processed)
    print_plan(store, entries, non_image, preview_bytes, start_index, candidates, fresh_count, args)
    planned = candidates[:args.limit] if args.limit else candidates
    if not planned:
        print('nothing to do: every thumbnail in the scanned range is fresh')
        if args.apply:
            save_state(state_path, store, names, pointer, previous_generated, previous_failed,
                       previous_elapsed + time.perf_counter() - started)
        return 0
    if not args.apply:
        print('dry run: %d thumbnails would be generated' % len(planned))
        return 0

    progress = {'pointer': pointer, 'generated': 0, 'failed': 0, 'bytes': 0,
                'seconds': [], 'last_save': time.perf_counter()}

    def record(index, result):
        processed.add(index)
        if result['status'] == 'generated':
            progress['generated'] += 1
            progress['bytes'] += result.get('bytes', 0)
            progress['seconds'].append(result['seconds'])
        elif result['status'] == 'failed':
            progress['failed'] += 1
            print('warning: failed %s: %s' % (names[index], result.get('error')), file=sys.stderr)
        while progress['pointer'] in processed:
            progress['pointer'] += 1
        done = progress['generated'] + progress['failed']
        now = time.perf_counter()
        if done and done % args.progress_every == 0:
            rate = done / max(now - started, 1e-6)
            print('[%d/%d] generated=%d failed=%d %.1f/s eta %s' % (
                done, len(planned), progress['generated'], progress['failed'], rate,
                format_seconds((len(planned) - done) / rate)))
        if now - progress['last_save'] >= STATE_SAVE_SECONDS:
            save_state(state_path, store, names, progress['pointer'],
                       previous_generated + progress['generated'],
                       previous_failed + progress['failed'], previous_elapsed + now - started)
            progress['last_save'] = now

    pool = ThreadPoolExecutor(max_workers=args.jobs)
    planned_iterator = iter(enumerate(planned))
    futures = {}
    interrupted = False
    try:
        def submit_batch():
            for _ in range(max(args.jobs * 4, 1)):
                try:
                    position, (index, name) = next(planned_iterator)
                except StopIteration:
                    return
                destination = thumbnail_dir / thumbnail_name(name)
                futures[pool.submit(generate_one, preview_dir / name, destination, args.fast)] = (index, name)

        submit_batch()
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                index, name = futures.pop(future)
                record(index, future.result())
            submit_batch()
    except KeyboardInterrupt:
        interrupted = True
        print('interrupted: cancelling queued work and saving progress ...')
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        elapsed = time.perf_counter() - started
        save_state(state_path, store, names, progress['pointer'],
                   previous_generated + progress['generated'],
                   previous_failed + progress['failed'], previous_elapsed + elapsed)
        last_name = state_last_name(names, progress['pointer'])
        print('state:      last=%r processed_prefix=%d' % (last_name, progress['pointer']))

    elapsed = time.perf_counter() - started
    print('done in %s: generated=%d failed=%d (fresh=%d, non-image=%d)' % (
        format_seconds(elapsed), progress['generated'], progress['failed'], fresh_count, non_image))
    if progress['seconds']:
        average_ms = statistics.mean(progress['seconds']) * 1000
        print('pipeline:   %s, avg %.1f ms/image, wrote %.1f MB' % (
            'fast' if args.fast else 'current', average_ms, progress['bytes'] / 1e6))
        if len(planned) < len(candidates):
            remaining = len(candidates) - len(planned)
            projected = average_ms * remaining / 1000 / args.jobs
            print('projection: %d remaining candidates at --jobs %d ~ %s' % (
                remaining, args.jobs, format_seconds(projected)))
    if interrupted:
        return 130
    return 1 if progress['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
