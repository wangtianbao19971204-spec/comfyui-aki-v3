"""Tests for the optimised preview thumbnail pipeline.

Loads the real ``prompt_selector.py`` with a stub ``server`` module and a
temporary ``__file__`` so its store paths point into the test directory: no
ComfyUI server is started and the production user_data directory is never
touched.  Everything else runs against small PIL fixtures in tempfile dirs.
"""

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

PROMPT_SELECTOR_DIR = Path(__file__).resolve().parents[1]
PROMPT_SELECTOR_FILE = PROMPT_SELECTOR_DIR / 'prompt_selector.py'
BOX = (480, 360)


class _StubRoutes:
    def get(self, path):
        def decorator(handler):
            return handler
        return decorator

    def post(self, path):
        def decorator(handler):
            return handler
        return decorator


def _load_prompt_selector(store_root):
    server = types.ModuleType('server')
    server.PromptServer = types.SimpleNamespace(
        instance=types.SimpleNamespace(routes=_StubRoutes()))
    sys.modules['server'] = server
    package = 'wb_thumbnail_opt_test'
    package_name = package + '.prompt_selector'
    root = types.ModuleType(package)
    root.__path__ = [str(PROMPT_SELECTOR_DIR)]
    sys.modules[package] = root
    subpackage = types.ModuleType(package_name)
    subpackage.__path__ = [str(PROMPT_SELECTOR_DIR)]
    sys.modules[package_name] = subpackage
    spec = importlib.util.spec_from_file_location(package_name + '.prompt_selector', PROMPT_SELECTOR_FILE)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = package_name
    module.__file__ = str(Path(store_root) / 'plugin' / 'prompt_selector.py')
    sys.modules[package_name + '.prompt_selector'] = module
    with mock.patch.dict(os.environ, {'UW_SKIP_LIBRARY_WARMUP': '1'}):
        spec.loader.exec_module(module)
    return module


def _digest_name(filename):
    import hashlib
    return hashlib.sha1(filename.encode('utf-8', errors='ignore')).hexdigest() + '.webp'


class PreviewThumbnailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = tempfile.TemporaryDirectory(prefix='wb-thumbnail-store-')
        cls.addClassCleanup(cls.store.cleanup)
        cls.module = _load_prompt_selector(cls.store.name)

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='wb-thumbnail-case-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.preview_dir = self.root / 'preview'
        self.thumbnail_dir = self.root / 'preview_thumbnails'
        self.preview_dir.mkdir()
        self.thumbnail_dir.mkdir()
        self.module.PREVIEW_DIR = str(self.preview_dir)
        self.module.THUMBNAIL_DIR = str(self.thumbnail_dir)

    def _make(self, name, size, mode='RGB', image_format=None, orientation=None, color=None):
        path = self.preview_dir / name
        image_format = image_format or {
            '.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP',
        }[path.suffix.lower()]
        if color is None:
            color = (128, 64, 32, 200) if mode in ('RGBA', 'LA') else (128, 64, 32)
        pixels = Image.new(mode, size, color)
        if image_format == 'JPEG':
            pixels = pixels.convert('RGB')
            kwargs = {'quality': 90}
            if orientation is not None:
                exif = Image.Exif()
                exif[274] = orientation
                kwargs['exif'] = exif.tobytes()
            pixels.save(path, format='JPEG', **kwargs)
        else:
            pixels.save(path, format=image_format)
        return path

    def _thumbnail(self, name):
        return self.thumbnail_dir / _digest_name(name)

    def _generate(self, name):
        return Path(self.module._ensure_preview_thumbnail(name))

    def _info(self, path):
        with Image.open(path) as image:
            return image.format, image.mode, image.size

    def _temp_leftovers(self):
        return list(self.thumbnail_dir.glob('*.tmp'))

    def test_output_contract_and_exact_dims(self):
        self._make('landscape.jpg', (800, 600), 'RGB')
        self._make('tall.jpg', (753, 1100), 'RGB')
        expected = {'landscape.jpg': (480, 360), 'tall.jpg': (246, 360)}
        for name, expected_size in expected.items():
            output = self._generate(name)
            self.assertEqual(output, self._thumbnail(name))
            image_format, mode, size = self._info(output)
            self.assertEqual(image_format, 'WEBP')
            self.assertEqual(size, expected_size)
            self.assertEqual(size, self.module._thumbnail_size(self._info(self.preview_dir / name)[2]))
            self.assertLessEqual(size[0], BOX[0])
            self.assertLessEqual(size[1], BOX[1])
            self.assertEqual(mode, 'RGB')
            self.assertTrue(output.stat().st_mtime >= (self.preview_dir / name).stat().st_mtime)
        self.assertEqual(self._temp_leftovers(), [])

    def test_alpha_preserved(self):
        self._make('sticker.png', (640, 480), 'RGBA', 'PNG')
        output = self._generate('sticker.png')
        image_format, mode, size = self._info(output)
        self.assertEqual((image_format, mode), ('WEBP', 'RGBA'))
        self.assertEqual(size, (480, 360))

    def test_small_image_is_not_upscaled(self):
        self._make('small.webp', (300, 200), 'RGB', 'WEBP')
        output = self._generate('small.webp')
        self.assertEqual(self._info(output)[2], (300, 200))
        self.assertIsNone(self.module._thumbnail_size((300, 200)))

    def test_exif_orientation_is_applied(self):
        source = self._make('rotated.jpg', (600, 400), 'RGB', 'JPEG', orientation=6)
        output = self._generate('rotated.jpg')
        with Image.open(source) as original:
            upright_size = (original.size[1], original.size[0])
        self.assertEqual(self._info(output)[2], self.module._thumbnail_size(upright_size))
        width, height = self._info(output)[2]
        self.assertGreater(height, width)

    def test_cache_hit_does_not_rewrite(self):
        self._make('cached.jpg', (900, 700), 'RGB')
        output = self._generate('cached.jpg')
        first_mtime = output.stat().st_mtime_ns
        first_bytes = output.read_bytes()
        with mock.patch.object(self.module.Image, 'open', wraps=Image.open) as opened:
            again = self._generate('cached.jpg')
        self.assertEqual(again, output)
        self.assertEqual(output.stat().st_mtime_ns, first_mtime)
        self.assertEqual(output.read_bytes(), first_bytes)
        self.assertEqual(opened.call_count, 0)

    def test_stale_source_regenerates(self):
        source = self._make('stale.jpg', (900, 700), 'RGB')
        output = self._generate('stale.jpg')
        first_mtime = output.stat().st_mtime_ns
        os.utime(source, (output.stat().st_atime + 10, output.stat().st_mtime + 10))
        regenerated = self._generate('stale.jpg')
        self.assertEqual(regenerated, output)
        self.assertNotEqual(output.stat().st_mtime_ns, first_mtime)
        self.assertEqual(self._temp_leftovers(), [])

    def test_corrupt_source_raises_and_leaves_no_temp(self):
        (self.preview_dir / 'broken.jpg').write_bytes(b'not really a jpeg')
        with self.assertRaises(Exception):
            self._generate('broken.jpg')
        self.assertEqual(self._temp_leftovers(), [])
        self.assertFalse(self._thumbnail('broken.jpg').exists())

    def test_missing_or_unsafe_filename_raises(self):
        self._make('ok.jpg', (600, 400), 'RGB')
        for filename in ('missing.jpg', '../ok.jpg', 'sub/ok.jpg', '', '..'):
            with self.assertRaises(FileNotFoundError, msg=filename):
                self.module._ensure_preview_thumbnail(filename)

    def test_thumbnail_size_matches_pillow_thumbnail(self):
        for size in ((753, 1100), (1024, 1024), (832, 1216), (1872, 2736),
                     (800, 600), (640, 480), (300, 200), (480, 360), (1200, 300)):
            with self.subTest(size=size):
                expected = Image.new('RGB', size, (10, 20, 30))
                expected.thumbnail(BOX, Image.Resampling.LANCZOS)
                expected_size = None if expected.size == size else expected.size
                self.assertEqual(self.module._thumbnail_size(size), expected_size)


if __name__ == '__main__':
    unittest.main()
