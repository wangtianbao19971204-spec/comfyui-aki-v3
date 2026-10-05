"""
哈希缓存管理器 - 用于加速模型文件哈希计算

功能：
- 内存LRU缓存（基于文件路径+修改时间）
- JSON持久化存储
- 线程安全操作
- 自动清理过期缓存
"""

import os
import json
import hashlib
import threading
from typing import Dict, Optional, Tuple
from pathlib import Path
from collections import OrderedDict
from ..utils.logger import get_logger

# 初始化logger
logger = get_logger(__name__)


class HashCacheManager:
    """哈希缓存管理器 - 提供高速缓存和持久化支持"""

    # 类级别的单例实例和锁
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, cache_file: str = None, max_memory_entries: int = 100):
        """单例模式，确保全局只有一个缓存实例"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, cache_file: str = None, max_memory_entries: int = 100):
        """
        初始化缓存管理器

        Args:
            cache_file: 缓存文件路径，默认为当前目录下的 hash_cache.json
            max_memory_entries: 内存缓存最大条目数（LRU）
        """
        # 避免重复初始化
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self.max_memory_entries = max_memory_entries
        self._cache_lock = threading.Lock()

        # 设置缓存文件路径
        if cache_file is None:
            current_dir = Path(__file__).parent
            cache_file = current_dir / "hash_cache.json"
        self.cache_file = Path(cache_file)

        # 内存缓存：{(file_path, mtime): hash_value}
        self._memory_cache: OrderedDict[Tuple[str, float], str] = OrderedDict()

        # 统计信息
        self._stats = {
            'hits': 0,
            'misses': 0,
            'disk_loads': 0,
            'disk_saves': 0
        }

        # 从磁盘加载缓存
        self._load_cache_from_disk()

    def _load_cache_from_disk(self):
        """从JSON文件加载缓存"""
        if not self.cache_file.exists():
            return

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                disk_cache = json.load(f)

            # 将磁盘缓存加载到内存，但不超过最大条目数
            loaded_count = 0
            for file_path, cache_data in disk_cache.items():
                if loaded_count >= self.max_memory_entries:
                    break

                # 验证文件是否仍存在且修改时间匹配
                if os.path.exists(file_path):
                    cached_mtime = cache_data.get('mtime')
                    cached_hash = cache_data.get('hash')

                    if cached_mtime and cached_hash:
                        current_mtime = os.path.getmtime(file_path)
                        # 如果文件未修改，加载到内存
                        if abs(current_mtime - cached_mtime) < 1.0:  # 允许1秒误差
                            cache_key = (file_path, current_mtime)
                            self._memory_cache[cache_key] = cached_hash
                            loaded_count += 1

            self._stats['disk_loads'] += 1
            logger.info(f"从磁盘加载了 {loaded_count} 条缓存记录")

        except Exception as e:
            logger.error(f"加载缓存文件失败: {e}")

    def _save_cache_to_disk(self):
        """保存缓存到JSON文件"""
        try:
            # 准备保存的数据
            disk_cache = {}
            for (file_path, mtime), hash_value in self._memory_cache.items():
                disk_cache[file_path] = {
                    'mtime': mtime,
                    'hash': hash_value
                }

            # 确保目录存在
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(disk_cache, f, indent=2, ensure_ascii=False)

            self._stats['disk_saves'] += 1

        except Exception as e:
            logger.error(f"保存缓存文件失败: {e}")

    def get_hash(self, file_path: str) -> Optional[str]:
        """
        获取文件哈希值（优先从缓存）

        Args:
            file_path: 文件路径

        Returns:
            哈希值，如果缓存未命中则返回 None
        """
        if not os.path.exists(file_path):
            return None

        # 获取文件修改时间
        mtime = os.path.getmtime(file_path)
        cache_key = (file_path, mtime)

        with self._cache_lock:
            # 检查内存缓存
            if cache_key in self._memory_cache:
                # LRU: 移动到末尾（最近使用）
                self._memory_cache.move_to_end(cache_key)
                self._stats['hits'] += 1
                return self._memory_cache[cache_key]

            # 检查是否有该文件的旧缓存（不同mtime）
            for (cached_path, cached_mtime), cached_hash in list(self._memory_cache.items()):
                if cached_path == file_path and cached_mtime != mtime:
                    # 文件已修改，删除旧缓存
                    del self._memory_cache[(cached_path, cached_mtime)]

            self._stats['misses'] += 1
            return None

    def set_hash(self, file_path: str, hash_value: str, auto_save: bool = True):
        """
        设置文件哈希值到缓存

        Args:
            file_path: 文件路径
            hash_value: 哈希值
            auto_save: 是否自动保存到磁盘
        """
        if not os.path.exists(file_path):
            return

        mtime = os.path.getmtime(file_path)
        cache_key = (file_path, mtime)

        with self._cache_lock:
            # 如果缓存已满，删除最旧的条目（LRU）
            if len(self._memory_cache) >= self.max_memory_entries:
                self._memory_cache.popitem(last=False)

            # 添加到缓存
            self._memory_cache[cache_key] = hash_value

            # 自动保存到磁盘
            if auto_save:
                self._save_cache_to_disk()

    def calculate_and_cache_hash(self, file_path: str, block_size: int = 128 * 1024) -> str:
        """
        计算文件哈希并缓存

        Args:
            file_path: 文件路径
            block_size: 读取块大小（字节）

        Returns:
            SHA256哈希值（前10位，小写）
        """
        # 先尝试从缓存获取
        cached_hash = self.get_hash(file_path)
        if cached_hash:
            return cached_hash

        # 计算哈希
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(block_size), b""):
                sha256_hash.update(byte_block)

        hash_result = sha256_hash.hexdigest()[:10].lower()

        # 保存到缓存
        self.set_hash(file_path, hash_result)

        return hash_result

    def clear_cache(self, save_to_disk: bool = True):
        """
        清空缓存

        Args:
            save_to_disk: 清空前是否保存到磁盘
        """
        with self._cache_lock:
            if save_to_disk:
                self._save_cache_to_disk()

            self._memory_cache.clear()
            logger.info("缓存已清空")

    def get_stats(self) -> Dict:
        """获取缓存统计信息"""
        with self._cache_lock:
            total_requests = self._stats['hits'] + self._stats['misses']
            hit_rate = (self._stats['hits'] / total_requests * 100) if total_requests > 0 else 0

            return {
                'memory_entries': len(self._memory_cache),
                'max_entries': self.max_memory_entries,
                'hits': self._stats['hits'],
                'misses': self._stats['misses'],
                'hit_rate': f"{hit_rate:.2f}%",
                'disk_loads': self._stats['disk_loads'],
                'disk_saves': self._stats['disk_saves']
            }

    def print_stats(self):
        """打印缓存统计信息"""
        stats = self.get_stats()
        logger.info("\n" + "=" * 50)
        logger.info("📊 哈希缓存统计信息")
        logger.info("=" * 50)
        logger.info(f"内存缓存条目: {stats['memory_entries']} / {stats['max_entries']}")
        logger.info(f"缓存命中: {stats['hits']} 次")
        logger.info(f"缓存未命中: {stats['misses']} 次")
        logger.info(f"命中率: {stats['hit_rate']}")
        logger.info(f"磁盘加载: {stats['disk_loads']} 次")
        logger.info(f"磁盘保存: {stats['disk_saves']} 次")
        logger.info("=" * 50 + "\n")

    def remove_file_cache(self, file_path: str):
        """
        删除指定文件的所有缓存

        Args:
            file_path: 文件路径
        """
        with self._cache_lock:
            keys_to_remove = [
                key for key in self._memory_cache.keys()
                if key[0] == file_path
            ]
            for key in keys_to_remove:
                del self._memory_cache[key]

    def force_save(self):
        """强制保存当前缓存到磁盘"""
        with self._cache_lock:
            self._save_cache_to_disk()
            logger.info("缓存已强制保存到磁盘")


# 全局缓存管理器实例
_global_cache_manager = None
_global_cache_lock = threading.Lock()


def get_cache_manager() -> HashCacheManager:
    """获取全局缓存管理器实例"""
    global _global_cache_manager

    if _global_cache_manager is None:
        with _global_cache_lock:
            if _global_cache_manager is None:
                _global_cache_manager = HashCacheManager()

    return _global_cache_manager
