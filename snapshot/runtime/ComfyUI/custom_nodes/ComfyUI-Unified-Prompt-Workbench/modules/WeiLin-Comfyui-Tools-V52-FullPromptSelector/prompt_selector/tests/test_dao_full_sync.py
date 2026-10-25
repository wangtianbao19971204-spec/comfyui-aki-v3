"""Tag 用户库写连接的 durability pragma 测试（隔离导入 dao.py，不碰生产/工作树 user_data）。

行为约束：
- tags 用户库（权威数据）的连接是 WAL + `synchronous=FULL`：提交返回即落盘，断电不丢最后提交；
- history/danbooru 维持 NORMAL（可从历史记录/上游字典重建，写入频繁）；
- 断线重连（_reconnect_after_error）后仍然保持 FULL。
"""

import asyncio
import atexit
import contextlib
import importlib.util
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = TESTS_DIR.parent
PLUGIN_DIR = PACKAGE_DIR.parent
DAO_SOURCE = PLUGIN_DIR / 'app' / 'server' / 'dao' / 'dao.py'
PACKAGE_BASE = 'dao_full_sync_pkg'


class _FakeResponse:
    text = ''

    def raise_for_status(self):
        return None

    def json(self):
        return []


class _FakeRequestException(Exception):
    pass


def _requests_stub():
    module = types.ModuleType('requests')
    module.get = lambda *args, **kwargs: _FakeResponse()
    module.RequestException = _FakeRequestException
    return module


def _stub_package(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)] if path is not None else []
    sys.modules[name] = module
    return module


def _load_dao(root):
    """把 dao.py 复制进一份临时包结构后加载，让它按 __file__ 推导的 user_data 落在临时目录。"""
    base = PACKAGE_BASE
    dao_dir = root / 'app' / 'server' / 'dao'
    dao_dir.mkdir(parents=True, exist_ok=True)
    target = dao_dir / 'dao.py'
    shutil.copy2(DAO_SOURCE, target)
    for name in (base, base + '.app', base + '.app.server', base + '.app.server.dao',
                 base + '.app.server.cloud_warehouse', base + '.app.server.user_init'):
        _stub_package(name, root)
    save_history = types.ModuleType(base + '.app.server.cloud_warehouse.save_history')
    save_history.save_package_path = lambda *args, **kwargs: None
    sys.modules[base + '.app.server.cloud_warehouse.save_history'] = save_history
    sys.modules[base + '.app.server.cloud_warehouse'].save_history = save_history
    user_init = types.ModuleType(base + '.app.server.user_init.user_init')
    user_init.read_init_file = lambda: {}
    sys.modules[base + '.app.server.user_init.user_init'] = user_init
    sys.modules[base + '.app.server.user_init'].user_init = user_init

    spec = importlib.util.spec_from_file_location(base + '.app.server.dao.dao', target)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = base + '.app.server.dao'
    sys.modules[base + '.app.server.dao.dao'] = module
    with mock.patch.dict(sys.modules, {'requests': _requests_stub()}), \
            mock.patch('locale.getdefaultlocale', return_value=('en_US', 'UTF-8')):
        spec.loader.exec_module(module)
    return module


async def _close_pool(dao):
    for connection in list(dao._connection_pool.values()):
        try:
            await connection.close()
        except Exception:  # noqa: BLE001 - best effort in tests
            pass
    dao._connection_pool.clear()


class DaoFullSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='dao-full-sync-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.dao = _load_dao(Path(cls.directory.name))
        atexit.unregister(cls.dao._close_connections)
        cls.addClassCleanup(lambda: [sys.modules.pop(name) for name in list(sys.modules)
                                     if name.startswith(PACKAGE_BASE)])

    def setUp(self):
        asyncio.run(_close_pool(self.dao))

    @classmethod
    def tearDownClass(cls):
        asyncio.run(_close_pool(cls.dao))

    def test_write_synchronous_policy_is_scoped(self):
        self.assertEqual(self.dao.write_synchronous_pragma('tags'), 'FULL')
        self.assertEqual(self.dao.write_synchronous_pragma('history'), 'NORMAL')
        self.assertEqual(self.dao.write_synchronous_pragma('danbooru'), 'NORMAL')
        self.assertEqual(self.dao.write_synchronous_pragma('unknown'), 'NORMAL')
        self.assertTrue(self.dao.tags_db_path.endswith('user_data\\userdatas_en_US_tags.db')
                        or self.dao.tags_db_path.endswith('user_data/userdatas_en_US_tags.db'))

    def test_tags_pool_connection_is_wal_full_and_commit_survives_reopen(self):
        async def scenario():
            tags = await self.dao._get_connection('tags')
            sync = (await (await tags.execute('PRAGMA synchronous')).fetchone())[0]
            journal = (await (await tags.execute('PRAGMA journal_mode')).fetchone())[0]
            await self.dao.execute_query(
                'tags',
                'INSERT INTO tag_groups (name, color, create_time, p_uuid) VALUES (?,?,?,?)',
                ('full-sync-probe', '', 1, 'uuid-full-sync-probe'))
            return sync, journal
        sync, journal = asyncio.run(scenario())
        self.assertEqual(journal, 'wal')
        self.assertEqual(sync, 2)  # 2 = SQLITE_SYNC_FULL
        with contextlib.closing(sqlite3.connect(self.dao.tags_db_path)) as check:
            found = check.execute("SELECT name FROM tag_groups WHERE p_uuid='uuid-full-sync-probe'").fetchone()
        self.assertEqual(found, ('full-sync-probe',))

    def test_history_and_danbooru_keep_normal_and_reconnect_keeps_full(self):
        async def scenario():
            history = await self.dao._get_connection('history')
            history_sync = (await (await history.execute('PRAGMA synchronous')).fetchone())[0]
            await self.dao._get_connection('tags')
            with mock.patch.object(self.dao, 'force_repair_database', return_value=True):
                reconnected = await self.dao._reconnect_after_error('tags')
            reconnect_sync = (await (await reconnected.execute('PRAGMA synchronous')).fetchone())[0]
            journal = (await (await reconnected.execute('PRAGMA journal_mode')).fetchone())[0]
            return history_sync, reconnect_sync, journal
        history_sync, reconnect_sync, journal = asyncio.run(scenario())
        self.assertEqual(history_sync, 1)  # 1 = SQLITE_SYNC_NORMAL
        self.assertEqual(journal, 'wal')
        self.assertEqual(reconnect_sync, 2)


if __name__ == '__main__':
    unittest.main()
