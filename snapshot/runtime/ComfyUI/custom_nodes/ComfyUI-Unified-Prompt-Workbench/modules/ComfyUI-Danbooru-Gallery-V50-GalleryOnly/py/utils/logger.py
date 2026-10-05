"""
统一日志管理模块 - 安全轮转版本

特点：
- 追加写入 danbooru_gallery.log，不因插件重新导入丢失故障现场
- 单文件达到20MB时安全轮转
- 默认保留5个历史归档，并记录明确的会话边界
- 专注于稳定可靠的日志记录

使用方法：
    from ..utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("消息")
    logger.debug("调试信息")
    logger.warning("警告")
    logger.error("错误")

日志级别控制（优先级从高到低）：
    1. 环境变量 COMFYUI_LOG_LEVEL (DEBUG/INFO/WARNING/ERROR/CRITICAL)
    2. 代码默认值（INFO）
"""

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import re
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

# 全局配置
_LOG_LEVEL = None
_LOGGERS: Dict[str, logging.Logger] = {}
_INITIALIZED = False

# 插件根目录
PLUGIN_ROOT = Path(__file__).parent.parent.parent

# 日志目录
_LOG_DIR_OVERRIDE = str(os.environ.get("DANBOORU_GALLERY_LOG_DIR", "") or "").strip()
if _LOG_DIR_OVERRIDE and Path(_LOG_DIR_OVERRIDE).expanduser().is_absolute():
    # Delivery tests use an isolated absolute directory so their session and
    # rotation files never mix with the user's diagnostic history.
    LOG_DIR = Path(_LOG_DIR_OVERRIDE).expanduser().resolve()
else:
    LOG_DIR = PLUGIN_ROOT / "logs"

# 日志文件（追加写入并安全轮转）
LOG_FILE = LOG_DIR / "danbooru_gallery.log"
LOG_MAX_BYTES = 20 * 1024 * 1024
LOG_BACKUP_COUNT = 5
LOG_SESSION_ID = f"{datetime.now().strftime('%Y%m%dT%H%M%S.%f')}-pid{os.getpid()}"

# 日志格式（包含日期时间）
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 控制台彩色输出（仅在支持的终端）
COLOR_CODES = {
    'DEBUG': '\033[36m',      # 青色
    'INFO': '\033[32m',       # 绿色
    'WARNING': '\033[33m',    # 黄色
    'ERROR': '\033[31m',      # 红色
    'CRITICAL': '\033[35m',   # 紫色
    'RESET': '\033[0m'        # 重置
}


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器（仅在支持的终端生效）"""

    def __init__(self, use_colors=True):
        super().__init__(LOG_FORMAT, LOG_DATE_FORMAT)
        self.use_colors = use_colors and self._supports_color()

    def _supports_color(self) -> bool:
        """检查终端是否支持彩色输出"""
        if os.name == 'nt':
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                return True
            except:
                return False
        return hasattr(sys.stderr, 'isatty') and sys.stderr.isatty()

    def _shorten_name(self, name: str) -> str:
        """缩短日志名称，只保留最后一段模块名"""
        # 如果包含插件根目录路径，先去掉
        plugin_root_str = str(PLUGIN_ROOT)
        if plugin_root_str in name:
            name = name.replace(plugin_root_str, '').lstrip('\\/')

        # 如果以 "danbooru_gallery." 开头，去掉前缀
        if name.startswith('danbooru_gallery.'):
            name = name[len('danbooru_gallery.'):]

        # 如果包含点号（模块路径），提取最后一段
        if '.' in name:
            parts = name.split('.')
            return parts[-1] if parts else name

        return name

    def format(self, record):
        # 缩短logger名称
        original_name = record.name
        record.name = self._shorten_name(original_name)

        # 应用颜色
        if self.use_colors and hasattr(record, 'levelname'):
            color_code = COLOR_CODES.get(record.levelname, '')
            reset_code = COLOR_CODES['RESET']
            # 为整条记录添加颜色
            formatted = super().format(record)
            return f"{color_code}{formatted}{reset_code}"

        # 恢复原始名称（避免影响其他handler）
        result = super().format(record)
        record.name = original_name

        return result


class SafeRotatingFileHandler(RotatingFileHandler):
    """
    追加写入并保留有限历史的轮转文件处理器。

    特点：
    - 默认使用追加模式，后续导入不会截断已有诊断记录
    - 达到大小限制后由标准库原子式关闭/重命名/重开
    - 只保留固定数量归档，避免日志无限增长
    """

    def __init__(
        self,
        filename,
        max_bytes=LOG_MAX_BYTES,
        backup_count=LOG_BACKUP_COUNT,
        mode='a',
        encoding='utf-8',
    ):
        """
        初始化文件处理器

        Args:
            filename: 日志文件路径
            max_bytes: 文件大小限制（字节），默认20MB
            backup_count: 保留的轮转归档数量，默认5个
            mode: 文件打开模式，固定使用'a'（追加）
            encoding: 文件编码，默认'utf-8'
        """
        if mode != 'a':
            raise ValueError("SafeRotatingFileHandler only supports append mode")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if backup_count < 1:
            raise ValueError("backup_count must be at least 1")
        super().__init__(
            filename,
            mode='a',
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding=encoding,
            delay=True,
        )


# Backward-compatible name for callers/tests that imported the old handler.
SimpleFileHandler = SafeRotatingFileHandler


class ErrorConsoleFormatter(logging.Formatter):
    """
    ERROR级别控制台格式化器

    专门用于ERROR级别的控制台输出，使用简洁的插件前缀
    格式: [Danbooru-Gallery] 消息内容
    无时间戳，保持简洁
    """

    def __init__(self, use_colors=True):
        super().__init__()
        self.use_colors = use_colors and self._supports_color()

    def _supports_color(self) -> bool:
        """检查终端是否支持彩色输出"""
        if os.name == 'nt':
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                return True
            except:
                return False
        return hasattr(sys.stderr, 'isatty') and sys.stderr.isatty()

    def format(self, record):
        """
        格式化日志记录

        格式: [Danbooru-Gallery] 消息内容
        无时间戳，保持简洁，全部无色
        """
        # 获取消息内容
        message = record.getMessage()

        # 返回格式化后的消息（无时间戳，无颜色）
        return f"[Danbooru-Gallery] {message}"


def _get_log_level() -> int:
    """
    获取日志级别

    优先级：
    1. 环境变量 COMFYUI_LOG_LEVEL
    2. 默认值（INFO）

    Returns:
        int: logging 模块的日志级别常量
    """
    global _LOG_LEVEL

    if _LOG_LEVEL is not None:
        return _LOG_LEVEL

    # 1. 检查环境变量
    env_level = os.environ.get('COMFYUI_LOG_LEVEL', '').upper()
    if hasattr(logging, env_level):
        _LOG_LEVEL = getattr(logging, env_level)
        print(f"[Logger] 🔧 使用环境变量日志级别: {env_level}", file=sys.stderr)
        return _LOG_LEVEL

    # 2. 使用默认值
    _LOG_LEVEL = logging.INFO
    return _LOG_LEVEL


def setup_logging():
    """
    初始化安全日志系统（追加写入与有限轮转）

    特点：
    - 每次启动追加会话边界，不截断已有日志
    - 文件超过20MB时轮转并保留5个历史归档
    - 专注于稳定可靠的日志记录
    """
    global _INITIALIZED

    if _INITIALIZED:
        return

    _INITIALIZED = True

    # 确保日志目录存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 获取日志级别
    level = _get_log_level()

    # 创建插件专属的logger
    plugin_logger = logging.getLogger('danbooru_gallery')
    plugin_logger.setLevel(logging.DEBUG)  # 接受所有级别，由 handler 控制
    plugin_logger.propagate = False  # 不传播到根logger，避免影响其他插件

    # 关闭并清除现有处理器（避免重复，同时释放 Windows 文件句柄）
    for existing_handler in list(plugin_logger.handlers):
        plugin_logger.removeHandler(existing_handler)
        try:
            existing_handler.close()
        except Exception:
            pass

    # 只保留ERROR级别的控制台处理器（输出到 stderr）
    # 文件已写入所有日志，控制台只显示ERROR级别的重要信息
    error_console_handler = logging.StreamHandler(sys.stderr)
    error_console_handler.setLevel(logging.ERROR)  # 只处理ERROR和CRITICAL
    error_console_handler.setFormatter(ErrorConsoleFormatter(use_colors=True))
    plugin_logger.addHandler(error_console_handler)

    # 3. 追加式轮转处理器（保留有限历史，避免重新导入丢失现场）
    try:
        file_handler = SafeRotatingFileHandler(
            LOG_FILE,
            max_bytes=LOG_MAX_BYTES,
            backup_count=LOG_BACKUP_COUNT,
            mode='a',
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别（包括 DEBUG）
        file_handler.setFormatter(ColoredFormatter(use_colors=False))
        plugin_logger.addHandler(file_handler)
        print(f"[Logger] ✅ 日志系统已初始化，文件: {LOG_FILE.name}", file=sys.stderr)
    except Exception as e:
        print(f"[Logger] ⚠️ 无法创建日志文件处理器: {e}", file=sys.stderr)

    # 输出简洁的初始化信息（写入文件，不显示在控制台）
    logger = get_logger(__name__)
    logger.info("=" * 60)
    logger.info(f"会话开始: {LOG_SESSION_ID}")
    logger.info("ComfyUI-Danbooru-Gallery 安全日志系统已初始化")
    logger.info(f"日志级别: {logging.getLevelName(level)}")
    logger.info(f"日志文件: {LOG_FILE.name}")
    logger.info(
        f"日志策略: 追加写入 | {LOG_MAX_BYTES // 1024 // 1024}MB安全轮转 | "
        f"保留{LOG_BACKUP_COUNT}个历史文件 | 仅ERROR输出到控制台"
    )
    logger.info("=" * 60)


def get_logger(name: str) -> logging.Logger:
    """
    获取或创建 logger

    ⚠️ 重要：所有logger都在'danbooru_gallery'层级下，不影响其他插件

    Args:
        name: logger 名称（通常使用 __name__）

    Returns:
        logging.Logger: logger 实例
    """
    # 确保日志系统已初始化
    if not _INITIALIZED:
        setup_logging()

    # 创建子logger名称
    full_name = f'danbooru_gallery.{name}'

    # 获取或创建logger
    logger = logging.getLogger(full_name)

    # 缓存logger（避免重复创建）
    if full_name not in _LOGGERS:
        _LOGGERS[full_name] = logger

    return logger
