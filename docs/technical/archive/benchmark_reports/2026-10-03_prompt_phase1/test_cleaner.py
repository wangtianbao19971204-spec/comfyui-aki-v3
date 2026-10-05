import ast
import json
import pathlib
import unittest

OUT = pathlib.Path(__file__).parent
ROOT = OUT.parents[1]
FORMATTER = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/py/utils/prompt_formatter.py'
SOURCE = OUT / 'staged/prompt_cleaning_maid.py'
namespace = {'__name__': 'isolated_cleaner_test'}
exec(compile(FORMATTER.read_text('utf8'), str(FORMATTER), 'exec'), namespace)
tree = ast.parse(SOURCE.read_text('utf8'))
tree.body = [n for n in tree.body if not isinstance(n, ast.ImportFrom)]
exec(compile(tree, str(SOURCE), 'exec'), namespace)
maid = namespace['PromptCleaningMaid']


class CleanerTests(unittest.TestCase):
    def test_syntax_and_idempotence(self):
        cases = [
            ('score_9, score_8_up, blue_hair', 'score_9, score_8_up, blue hair'),
            ('<lora:traveler_v2:0.8>, blue_hair', '<lora:traveler_v2:0.8>, blue hair'),
            ('embedding:portraits/clear_v2.pt, blue_hair', 'embedding:portraits/clear_v2.pt, blue hair'),
            ('__weather/today__, blue_hair', '__weather/today__, blue hair'),
            ('sign reads "OPEN_24,  NOW (", blue_hair', 'sign reads "OPEN_24,  NOW (", blue hair'),
            ("sign reads 'OPEN_24', blue_hair", "sign reads 'OPEN_24', blue hair"),
            (r'blue_hair:1.2, traveler \(series\)', r'(blue hair:1.2), traveler \(series\)'),
            ('(blue_hair:1.2), score_7', '(blue hair:1.2), score_7'),
            ('MASK_SIZE(1024 1024) blue_hair AND MASK(0 0 1 1) red_hair', 'MASK_SIZE(1024 1024) blue hair AND MASK(0 0 1 1) red hair'),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(maid.process(source)[0], expected)
                self.assertEqual(maid.process(expected)[0], expected)

    def test_explicit_trigger(self):
        options = {'保留原文 (protected_literals)': 'character_trigger_v2\nBlue_Hair'}
        self.assertEqual(maid.process('character_trigger_v2, Blue_Hair, blue_hair', **options)[0], 'character_trigger_v2, Blue_Hair, blue hair')

    def test_verbatim(self):
        source = 'Keep the sign "OPEN_24".\nMove the adult traveler left (keep coat).  '
        self.assertEqual(maid.process(source, **{'清洗模式 (cleaning_mode)': '自然语言 / 编辑指令 (verbatim)', '清理换行 (cleanup_newlines)': '逗号 (comma)'})[0], source)

    def test_explicit_remove(self):
        self.assertEqual(maid.process('<lora:traveler_v2:0.8>, blue_hair', **{'移除LoRA标签 (remove_lora_tags)': True})[0], 'blue hair')

    def test_non_formatter_options_preserve_quotes(self):
        self.assertEqual(maid.process('"a_ b,  c (", blue_hair', **{'提示词格式化 (prompt_formatting)': False})[0], '"a_ b,  c (", blue_hair')

    def test_schema_backwards_compatible(self):
        old = ast.parse((OUT / 'before/prompt_cleaning_maid.py').read_text('utf8'))
        old.body = [n for n in old.body if not isinstance(n, ast.ImportFrom)]
        previous = dict(namespace)
        exec(compile(old, 'old_cleaner', 'exec'), previous)
        self.assertEqual(maid.INPUT_TYPES()['required'], previous['PromptCleaningMaid'].INPUT_TYPES()['required'])
        self.assertEqual(maid.process(None), ('',))


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CleanerTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    (OUT / 'cleaner_tests.json').write_text(json.dumps({'passed': result.wasSuccessful(), 'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'method': 'staged production source with unchanged formatter; neutral synthetic inputs'}), encoding='utf8')
    raise SystemExit(not result.wasSuccessful())
