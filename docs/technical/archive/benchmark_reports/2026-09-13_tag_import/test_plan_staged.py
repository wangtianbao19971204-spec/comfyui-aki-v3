from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

if len(sys.argv) < 2:
    raise SystemExit('usage: python test_tag_import_plan.py ORIGINAL_PACKAGE_DIR')
ORIGINAL_PACKAGE_DIR = Path(sys.argv.pop(1)).resolve()
PACKAGE_NAME = '_tag_preview_test_package'

spec = importlib.util.spec_from_file_location(PACKAGE_NAME + '.tag_library', ORIGINAL_PACKAGE_DIR / 'tag_library.py')
tag_library = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tag_library
spec.loader.exec_module(tag_library)

spec = importlib.util.spec_from_file_location(PACKAGE_NAME + '.tag_import_plan', ORIGINAL_PACKAGE_DIR / 'tag_import_plan.py')
preview_module = importlib.util.module_from_spec(spec)
preview_module.__package__ = PACKAGE_NAME
sys.modules[spec.name] = preview_module
spec.loader.exec_module(preview_module)

TagLibrary = tag_library.TagLibrary
preview_tag_import = preview_module.preview_tag_import


class ImportPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'tags.db'
        conn = sqlite3.connect(self.path)
        conn.executescript('''
            CREATE TABLE tag_groups (id_index INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL, create_time INTEGER NOT NULL, p_uuid TEXT NOT NULL UNIQUE);
            CREATE TABLE tag_subgroups (id_index INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL, create_time INTEGER NOT NULL, group_id INTEGER NOT NULL, g_uuid TEXT NOT NULL UNIQUE, p_uuid TEXT NOT NULL);
            CREATE TABLE tag_tags (id_index INTEGER PRIMARY KEY, subgroup_id INTEGER NOT NULL, text TEXT NOT NULL, desc TEXT NOT NULL, color TEXT NOT NULL, create_time INTEGER NOT NULL, t_uuid TEXT NOT NULL UNIQUE, g_uuid TEXT NOT NULL);
        ''')
        conn.commit(); conn.close()
        self.library = TagLibrary(self.path)
        with self.library.connection() as conn, conn:
            conn.execute("INSERT INTO tag_groups VALUES (1,'G','',1,'group-1')")
            conn.execute("INSERT INTO tag_subgroups VALUES (1,'S','',1,1,'sub-1','group-1')")
            conn.execute("INSERT INTO tag_tags VALUES (1,1,'old','old desc','',1,'tag-1','sub-1')")
            conn.execute("INSERT INTO workbench_tag_meta VALUES ('tag-1',?)", (json.dumps({'favorite': True, 'notes': 'local', 'collection_ids': ['work']}),))

    def tearDown(self):
        self.tmp.cleanup()

    def bundle(self, item=None, groups=None, subgroups=None):
        return {'format': 'weilin-tags-v1',
                'groups': groups if groups is not None else [{'p_uuid':'group-1','name':'G','color':''}],
                'subgroups': subgroups if subgroups is not None else [{'g_uuid':'sub-1','name':'S','color':'','p_uuid':'group-1'}],
                'items': [] if item is None else [item]}

    def preview(self, bundle, overwrite=False, revision='collections-v1:1', known=('default','work')):
        return preview_tag_import(self.path, bundle, overwrite, revision, known)

    def item(self, **extra):
        value = {'t_uuid':'tag-1','text':'old','desc':'old desc','color':'','g_uuid':'sub-1'}
        value.update(extra)
        return value

    def test_metadata_defaults_and_each_change(self):
        defaults = self.preview(self.bundle(self.item(favorite=False, notes='', collection_ids=[])), True)
        self.assertEqual(defaults['items'][0]['changed_fields'], ['favorite', 'notes', 'collection_ids'])
        for key, value in [('favorite', False), ('notes', 'new'), ('collection_ids', ['default'])]:
            result = self.preview(self.bundle(self.item(**{key: value})), True)
            self.assertEqual(result['items'][0]['changed_fields'], [key])
        with self.library.connection() as conn, conn:
            conn.execute("DELETE FROM workbench_tag_meta WHERE tag_uuid='tag-1'")
        defaults = self.preview(self.bundle(self.item(favorite=False, notes='', collection_ids=[])), True)
        self.assertEqual(defaults['items'][0]['disposition'], 'suspected_duplicate')

    def test_combined_metadata_and_overwrite_false_preservation(self):
        result = self.preview(self.bundle(self.item(favorite=False, notes='remote', collection_ids=[])), False)
        self.assertEqual(result['counts']['will_write'], 0)
        self.assertEqual(result['items'][0]['disposition'], 'suspected_duplicate')
        result = self.preview(self.bundle(self.item(text='new', favorite=False, notes='remote')), True)
        self.assertEqual(result['items'][0]['changed_fields'], ['text','favorite','notes'])

    def test_create_category_change_and_category_manifest(self):
        result = self.preview(self.bundle({'t_uuid':'tag-2','text':'new','desc':'','color':'','g_uuid':'sub-1'}))
        self.assertEqual(result['items'][0]['disposition'], 'new')
        changed = self.bundle(self.item(g_uuid='sub-2'), subgroups=[{'g_uuid':'sub-1','name':'S','color':'','p_uuid':'group-1'}, {'g_uuid':'sub-2','name':'S2','color':'','p_uuid':'group-1'}])
        result = self.preview(changed, True)
        self.assertEqual(result['items'][0]['changed_fields'], ['g_uuid'])
        self.assertEqual(result['category_counts']['subgroups']['actions'][1]['source_coordinate'], 'subgroups[1]')

    def test_validation_and_membership(self):
        for bad in [self.item(t_uuid=''), self.item(t_uuid=[])]:
            with self.assertRaises(ValueError):
                self.preview(self.bundle(bad))
        with self.assertRaises((ValueError, KeyError)):
            self.preview(self.bundle(self.item(t_uuid='tag-2', g_uuid='missing')))
        with self.assertRaises(ValueError):
            self.preview(self.bundle(self.item(t_uuid='tag-2', collection_ids=['gone'])))
        ignored = self.preview(self.bundle(self.item(t_uuid='tag-2', extra=1)))
        self.assertEqual(ignored['counts']['unsupported'], 1)
        self.assertEqual(ignored['items'][0]['ignored_field_names'], ['extra'])
        duplicate = self.bundle(self.item())
        duplicate['items'].append(self.item())
        with self.assertRaises(ValueError):
            self.preview(duplicate)

    def test_policy_conflicts_visible_but_not_committable(self):
        before = self.path.read_bytes()
        bundle = self.bundle(self.item(text='changed'))
        blocked = self.preview(bundle, False)
        self.assertFalse(blocked['committable'])
        self.assertEqual(blocked['counts']['version_conflicts'], 1)
        allowed = self.preview(bundle, True)
        self.assertTrue(allowed['committable'])
        self.assertNotEqual(blocked['preflight_token'], allowed['preflight_token'])
        with self.assertRaises(ValueError):
            self.library.update({'operation':'import','bundle':bundle,'overwrite':False}, self.library.revision())
        self.assertEqual(before, self.path.read_bytes())
        category_bundle = self.bundle(self.item(), groups=[{'p_uuid':'group-1','name':'Changed','color':''}])
        category_plan = self.preview(category_bundle, False)
        self.assertFalse(category_plan['committable'])
        self.assertEqual(category_plan['category_counts']['groups']['version_conflicts'], 1)

    def test_success_and_failure_leave_file_revision_and_rows_unchanged(self):
        before_bytes = self.path.read_bytes(); before_revision = self.library.revision()
        with self.library.connection() as conn:
            before_rows = [tuple(row) for row in conn.execute('SELECT * FROM tag_tags')]
        self.preview(self.bundle(self.item(t_uuid='tag-2', text='new')))
        bad = self.bundle()
        bad['items'] = [self.item(t_uuid='tag-2', text='valid'), self.item(t_uuid='tag-3', g_uuid='missing')]
        with self.assertRaises((ValueError, KeyError)):
            self.preview(bad)
        self.assertEqual(before_bytes, self.path.read_bytes())
        self.assertEqual(before_revision, self.library.revision())
        with self.library.connection() as conn:
            self.assertEqual(before_rows, [tuple(row) for row in conn.execute('SELECT * FROM tag_tags')])

    def test_token_determinism_and_bindings(self):
        bundle = self.bundle({'t_uuid':'tag-2','text':'x','desc':'','color':'','g_uuid':'sub-1'})
        first = self.preview(bundle)
        self.assertEqual(first['preflight_token'], self.preview(json.loads(json.dumps(bundle)))['preflight_token'])
        self.assertNotEqual(first['preflight_token'], self.preview(bundle, True)['preflight_token'])
        self.assertNotEqual(first['preflight_token'], self.preview(bundle, revision='collections-v1:2')['preflight_token'])
        altered = self.bundle({'t_uuid':'tag-2','text':'different','desc':'','color':'','g_uuid':'sub-1'})
        self.assertNotEqual(first['preflight_token'], self.preview(altered)['preflight_token'])


if __name__ == '__main__':
    unittest.main()

