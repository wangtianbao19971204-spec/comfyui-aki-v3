"""
Extension module - Krita扩展主类
"""

import tempfile
import os
import sys
import time
from pathlib import Path
from krita import Extension, Krita, Document
from PyQt5.QtCore import QFileSystemWatcher, QTimer
from .communication import get_communication
from .logger import get_logger

# Windows窗口激活支持
if sys.platform == "win32":
    try:
        import ctypes
        from ctypes import wintypes
        HAS_WIN32 = True
    except ImportError:
        HAS_WIN32 = False
else:
    HAS_WIN32 = False


class OpenInKritaExtension(Extension):
    """Open In Krita扩展 - 处理与ComfyUI的交互"""

    def __init__(self, parent):
        super().__init__(parent)

        # 安全获取logger
        try:
            self.logger = get_logger()
            print("[OpenInKrita] ✓ Extension获取logger成功")
        except Exception as e:
            print(f"[OpenInKrita] ✗ Extension获取logger失败: {e}")
            # 创建一个最简单的fallback
            class SimplePrintLogger:
                def info(self, msg): print(f"[OpenInKrita] {msg}")
                def warning(self, msg): print(f"[OpenInKrita] WARNING: {msg}")
                def error(self, msg): print(f"[OpenInKrita] ERROR: {msg}")
                def get_log_path(self): return "无（print模式）"
            self.logger = SimplePrintLogger()

        self.comm = get_communication()
        self.watcher = None
        self.monitor_dir = Path(tempfile.gettempdir()) / "open_in_krita"
        self.monitor_dir.mkdir(exist_ok=True)
        self.processed_files = set()  # 跟踪已处理的文件，避免重复打开
        self.opened_documents = {}  # 映射：文件路径 -> 文档对象（用于fetch请求）
        self.processed_requests = set()  # 跟踪已处理的请求文件名，避免重复处理

        self.logger.info("扩展已初始化")
        self.logger.info(f"监控目录: {self.monitor_dir}")
        self.logger.info(f"日志文件: {self.logger.get_log_path()}")

    def setup(self):
        """设置扩展（当Krita启动时调用）"""
        self.logger.info("开始设置扩展...")

        # 🔥 清理所有旧的请求文件（这些都是一次性请求，不应该跨会话保留）
        self._cleanup_old_request_files()

        # 启动目录监控
        self._setup_directory_watcher()
        self.logger.info("目录监控器已启动")

        # 🔥 监听Krita文档打开事件（用于命令行启动）
        self._setup_document_listener()
        self.logger.info("文档打开监听器已启动")

        # 🔥 创建插件加载完成标志文件，让ComfyUI知道可以发送请求了
        try:
            plugin_loaded_flag = self.monitor_dir / "_plugin_loaded.txt"
            with open(plugin_loaded_flag, 'w', encoding='utf-8') as f:
                f.write(f"Plugin loaded at: {time.time()}\n")
            self.logger.info(f"✓ 插件加载标志文件已创建: {plugin_loaded_flag.name}")
        except Exception as e:
            self.logger.error(f"✗ 创建插件加载标志文件失败: {e}")

    def _cleanup_old_request_files(self):
        """清理所有旧的请求文件（启动时调用）"""
        try:
            self.logger.info("===== 清理旧请求文件 =====")

            # 清理所有类型的请求文件
            request_patterns = ["open_*.request", "fetch_*.request", "check_document_*.request"]
            total_cleaned = 0

            for pattern in request_patterns:
                files = list(self.monitor_dir.glob(pattern))
                for f in files:
                    try:
                        f.unlink()
                        total_cleaned += 1
                        self.logger.info(f"✓ 已删除旧请求: {f.name}")
                    except Exception as e:
                        self.logger.warning(f"⚠ 删除失败: {f.name} - {e}")

            if total_cleaned > 0:
                self.logger.info(f"✓ 共清理 {total_cleaned} 个旧请求文件")
            else:
                self.logger.info("无需清理（没有旧请求文件）")

            self.logger.info("===== 清理完成 =====")

        except Exception as e:
            self.logger.error(f"✗ 清理旧请求文件时出错: {e}")
            import traceback
            traceback.print_exc()

    def _setup_directory_watcher(self):
        """设置目录监控"""
        if self.watcher is None:
            self.watcher = QFileSystemWatcher()
            self.watcher.addPath(str(self.monitor_dir))
            self.watcher.directoryChanged.connect(self._on_directory_changed)
            self.logger.info(f"正在监控目录: {self.monitor_dir}")

    def _setup_document_listener(self):
        """设置文档打开监听器（用于命令行启动）"""
        try:
            # 获取Krita的Notifier实例
            app = Krita.instance()
            notifier = app.notifier()

            # 监听viewCreated事件（当打开文档时会创建视图）
            notifier.viewCreated.connect(self._on_view_created)
            self.logger.info("✓ 已连接viewCreated事件监听器")

        except Exception as e:
            self.logger.error(f"✗ 设置文档监听器失败: {e}")
            import traceback
            traceback.print_exc()

    def _on_view_created(self):
        """当新视图创建时触发（文档被打开）"""
        try:
            self.logger.info("===== 检测到视图创建事件 =====")

            # 🔥 延迟500ms后激活图层，确保文档完全加载
            QTimer.singleShot(500, self._auto_activate_layer)

        except Exception as e:
            self.logger.error(f"✗ 处理viewCreated事件失败: {e}")
            import traceback
            traceback.print_exc()

    def _auto_activate_layer(self):
        """自动激活背景图层"""
        try:
            self.logger.info("===== 开始自动激活图层 =====")

            app = Krita.instance()
            doc = app.activeDocument()

            if not doc:
                self.logger.warning("⚠ 没有活动文档，跳过图层激活")
                return

            self.logger.info(f"当前文档: {doc.name()}")

            # 获取所有图层
            child_nodes = doc.rootNode().childNodes()
            if not child_nodes:
                self.logger.warning("⚠ 文档没有图层")
                return

            # 🔥 优先查找背景图层（名为"Background"或"背景"）
            target_node = None
            for node in child_nodes:
                node_name_lower = node.name().lower()
                if 'background' in node_name_lower or '背景' in node.name():
                    target_node = node
                    self.logger.info(f"✓✓ 找到背景图层: {node.name()}")
                    break

            # 如果没有背景图层，优先查找绘画图层
            if not target_node:
                for node in child_nodes:
                    if node.type() == "paintlayer":
                        target_node = node
                        self.logger.info(f"✓ 找到第一个绘画图层: {node.name()}")
                        break

            # 如果没有绘画图层，使用第一个节点
            if not target_node:
                target_node = child_nodes[0]
                self.logger.info(f"使用第一个节点: {target_node.name()} (类型: {target_node.type()})")

            # 激活图层
            self.logger.info(f"正在激活图层: {target_node.name()}")

            # 第1步：通过Document设置活动节点
            doc.setActiveNode(target_node)
            self.logger.info("  步骤1: 已调用 doc.setActiveNode()")

            # 第2步：通过View设置活动节点和选择工具
            window = app.activeWindow()
            if window:
                active_view = window.activeView()
                if active_view and active_view.document() == doc:
                    self.logger.info("  步骤2: 正在通过View确认并激活...")

                    # 🔥 设置当前节点（确保View和Document同步）
                    try:
                        active_view.setCurrentNode(target_node)
                        self.logger.info("    ✓ View的当前节点已设置")
                    except AttributeError:
                        self.logger.info("    ⚠ View.setCurrentNode不可用，使用Document方式")

                    # 🔥 激活选择工具（确保图层被选中并可编辑）
                    try:
                        app.action('KritaShape/KisToolSelectRectangular').trigger()
                        self.logger.info("    ✓ 已激活矩形选择工具")
                    except:
                        try:
                            app.action('KritaShape/KisToolBrush').trigger()
                            self.logger.info("    ✓ 已激活画笔工具")
                        except:
                            self.logger.info("    ⚠ 工具激活失败（非关键）")

                    self.logger.info("  ✓ View设置完成")
                else:
                    self.logger.warning("  步骤2跳过: activeView为空或文档不匹配")
            else:
                self.logger.warning("  步骤2跳过: 没有活动窗口")

            self.logger.info("===== 图层激活完成 =====")

        except Exception as e:
            self.logger.error(f"✗ 自动激活图层失败: {e}")
            import traceback
            traceback.print_exc()

    def _activate_krita_window(self):
        """激活Krita窗口（Windows）"""
        self.logger.info("===== 开始激活Krita窗口 =====")

        if not HAS_WIN32:
            self.logger.warning("窗口激活功能仅支持Windows平台")
            return False

        try:
            # 获取Windows API函数
            FindWindow = ctypes.windll.user32.FindWindowW
            SetForegroundWindow = ctypes.windll.user32.SetForegroundWindow
            ShowWindow = ctypes.windll.user32.ShowWindow
            IsIconic = ctypes.windll.user32.IsIconic
            GetForegroundWindow = ctypes.windll.user32.GetForegroundWindow

            # 记录激活前的前台窗口
            current_foreground = GetForegroundWindow()
            self.logger.info(f"当前前台窗口句柄: {current_foreground}")

            # 尝试多个可能的窗口类名
            window_classes = ["Qt5QWindowIcon", "Qt5152QWindowIcon", None]  # None表示任意类名
            self.logger.info(f"将尝试以下窗口类名: {window_classes}")

            hwnd = None
            for wclass in window_classes:
                self.logger.info(f"尝试查找窗口类: {wclass if wclass else '任意类名'}")
                if wclass:
                    hwnd = FindWindow(wclass, None)
                    if hwnd and hwnd != 0:
                        self.logger.info(f"✓ 通过类名 '{wclass}' 找到窗口: {hwnd}")
                    else:
                        self.logger.info(f"× 类名 '{wclass}' 未找到窗口")
                else:
                    # 简化：直接尝试通过标题查找
                    self.logger.info("尝试通过标题'Krita'查找窗口...")
                    FindWindowEx = ctypes.windll.user32.FindWindowExW
                    hwnd = FindWindowEx(None, None, None, "Krita")
                    if hwnd and hwnd != 0:
                        self.logger.info(f"✓ 通过标题找到窗口: {hwnd}")
                    else:
                        self.logger.info("× 通过标题未找到窗口")

                if hwnd and hwnd != 0:
                    break

            if not hwnd or hwnd == 0:
                self.logger.warning("✗ 未找到Krita窗口句柄")
                return False

            self.logger.info(f"✓ 最终找到Krita窗口句柄: {hwnd}")

            # 检查窗口是否最小化
            is_minimized = IsIconic(hwnd)
            self.logger.info(f"窗口是否最小化: {bool(is_minimized)}")

            if is_minimized:
                SW_RESTORE = 9
                self.logger.info("正在恢复最小化窗口...")
                ShowWindow(hwnd, SW_RESTORE)
                self.logger.info("✓ 窗口已恢复")
                time.sleep(0.1)

            # 激活窗口
            self.logger.info(f"正在调用SetForegroundWindow({hwnd})...")
            result = SetForegroundWindow(hwnd)
            self.logger.info(f"SetForegroundWindow返回值: {result}")

            # 验证窗口是否真的被激活
            time.sleep(0.05)  # 短暂等待让窗口系统响应
            new_foreground = GetForegroundWindow()
            self.logger.info(f"激活后前台窗口句柄: {new_foreground}")

            if new_foreground == hwnd:
                self.logger.info("✓✓✓ Krita窗口已成功激活（验证通过）")
                return True
            else:
                self.logger.warning(f"✗ 激活可能失败：预期前台窗口={hwnd}，实际前台窗口={new_foreground}")
                return False

        except Exception as e:
            self.logger.error(f"✗✗✗ 激活窗口时出错: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _setup_layers(self, doc):
        """设置文档图层：使所有图层可见并激活第一个图层"""
        self.logger.info("===== 开始设置图层 =====")

        try:
            if not doc:
                self.logger.error("✗ 文档对象为空")
                return False

            # 🔍 详细的文档状态调试信息
            self.logger.info(f"文档名称: {doc.name()}")
            self.logger.info(f"文档路径: {doc.fileName()}")
            self.logger.info(f"文档已修改: {doc.modified()}")

            # 当前活动图层信息
            current_active = doc.activeNode()
            if current_active:
                self.logger.info(f"当前活动图层: {current_active.name()} (类型: {current_active.type()})")
            else:
                self.logger.warning("当前没有活动图层")

            # 获取根节点
            root_node = doc.rootNode()
            if not root_node:
                self.logger.warning("✗ 无法获取根节点")
                return False

            # 获取所有子节点
            child_nodes = root_node.childNodes()
            if not child_nodes or len(child_nodes) == 0:
                self.logger.warning("✗ 文档没有图层")
                return False

            # 记录所有图层信息
            self.logger.info(f"文档共有 {len(child_nodes)} 个图层:")
            for i, node in enumerate(child_nodes):
                self.logger.info(f"  图层{i}: 名称='{node.name()}', 类型={node.type()}, 可见={node.visible()}")

            # ✅ 步骤1：使所有图层可见
            self.logger.info("正在设置所有图层可见...")
            visible_count = 0
            for node in child_nodes:
                if not node.visible():
                    node.setVisible(True)
                    visible_count += 1
                    self.logger.info(f"  ✓ 已显示图层: {node.name()}")

            if visible_count > 0:
                self.logger.info(f"✓ 已显示 {visible_count} 个图层")
            else:
                self.logger.info("所有图层已可见，无需修改")

            # ✅ 步骤2：激活第一个图层
            # 🔥 优先查找背景图层（名为"Background"或"背景"或包含这些关键词）
            target_node = None
            for node in child_nodes:
                node_name_lower = node.name().lower()
                if 'background' in node_name_lower or '背景' in node.name():
                    target_node = node
                    self.logger.info(f"✓✓ 找到背景图层: {node.name()}")
                    break

            # 如果没有背景图层，优先查找绘画图层
            if not target_node:
                for node in child_nodes:
                    if node.type() == "paintlayer":
                        target_node = node
                        self.logger.info(f"✓ 找到第一个绘画图层: {node.name()}")
                        break

            # 如果没有绘画图层，使用第一个节点
            if not target_node:
                target_node = child_nodes[0]
                self.logger.info(f"未找到特定图层，使用第一个节点: {target_node.name()} (类型: {target_node.type()})")

            # 🔥 多步骤激活图层（通过Document和View双重设置）
            self.logger.info(f"正在激活图层: {target_node.name()}")

            # 第1步：通过Document设置活动节点
            doc.setActiveNode(target_node)
            self.logger.info("  步骤1: 已调用 doc.setActiveNode()")

            # 第2步：通过View设置活动节点和选择工具
            app = Krita.instance()
            window = app.activeWindow()
            if window:
                active_view = window.activeView()
                if active_view and active_view.document() == doc:
                    self.logger.info("  步骤2: 正在通过View确认并激活...")

                    # 🔥 设置当前节点（确保View和Document同步）
                    try:
                        # 强制刷新视图以同步选择
                        active_view.setCurrentNode(target_node)
                        self.logger.info("    ✓ View的当前节点已设置")
                    except AttributeError:
                        # 某些Krita版本可能没有这个方法
                        self.logger.info("    ⚠ View.setCurrentNode不可用，使用Document方式")

                    # 🔥 激活选择工具（确保图层被选中并可编辑）
                    try:
                        # 尝试激活KritaShape/DefaultTool（选择工具）
                        app.action('KritaShape/KisToolSelectRectangular').trigger()
                        self.logger.info("    ✓ 已激活矩形选择工具")
                    except:
                        try:
                            # 如果矩形选择工具失败，尝试激活画笔工具
                            app.action('KritaShape/KisToolBrush').trigger()
                            self.logger.info("    ✓ 已激活画笔工具")
                        except:
                            self.logger.info("    ⚠ 工具激活失败（非关键）")

                    self.logger.info("  ✓ View设置完成")
                else:
                    self.logger.warning("  步骤2跳过: activeView为空或文档不匹配")
            else:
                self.logger.warning("  步骤2跳过: activeWindow为空")

            # 🔥 多重刷新确保UI更新
            try:
                # 第3步：刷新文档投影
                doc.refreshProjection()
                self.logger.info("  步骤3: 文档投影已刷新")

                # 第4步：等待文档操作完成
                doc.waitForDone()
                self.logger.info("  步骤4: 文档操作已完成")

                # 第5步：强制激活窗口和视图
                if window:
                    self.logger.info("  步骤5: 正在激活窗口和视图...")
                    try:
                        # 激活窗口
                        window.activate()
                        self.logger.info("    ✓ 窗口已激活")

                        # 重新设置活动文档（确保UI同步）
                        app.setActiveDocument(doc)
                        self.logger.info("    ✓ 文档已重新设置为活动")
                    except Exception as e2:
                        self.logger.warning(f"    激活操作警告: {e2}")

            except Exception as e:
                self.logger.warning(f"刷新操作失败: {e}")
                import traceback
                traceback.print_exc()

            # 验证激活结果
            time.sleep(0.1)
            new_active = doc.activeNode()
            if new_active:
                self.logger.info(f"✓✓✓ 图层设置成功 - 活动图层: {new_active.name()}")
                return True
            else:
                self.logger.warning("⚠ 无法验证活动图层，但设置可能已生效")
                return True

        except Exception as e:
            self.logger.error(f"✗✗✗ 设置图层时出错: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _handle_fetch_request(self, request_file: Path):
        """处理fetch请求文件"""
        try:
            self.logger.info(f"===== 处理fetch请求: {request_file.name} =====")

            # 🔥 立即重命名请求文件为.processing，避免重复处理
            processing_file = request_file.with_suffix('.processing')
            try:
                request_file.rename(processing_file)
                self.logger.info(f"✓ 请求文件已标记为处理中")
            except FileNotFoundError:
                # 文件已被处理或删除，直接返回
                self.logger.info(f"⚠ 请求文件已被处理，跳过")
                return
            except Exception as e:
                self.logger.warning(f"⚠ 重命名请求文件失败: {e}，继续处理")
                processing_file = request_file  # 如果重命名失败，继续用原文件

            # 解析文件名：fetch_{node_id}_{timestamp}.request
            filename = processing_file.stem.replace('.processing', '')  # 移除.processing扩展名
            parts = filename.split('_')

            if len(parts) < 3:
                self.logger.error(f"✗ 请求文件名格式错误: {processing_file.name}")
                processing_file.unlink(missing_ok=True)
                return

            # 提取node_id和timestamp
            node_id = parts[1]
            timestamp = parts[2]
            self.logger.info(f"Node ID: {node_id}, Timestamp: {timestamp}")

            # 调用communication获取当前Krita数据
            self.logger.info("正在获取当前Krita数据...")
            image_path, mask_path = self.comm.get_current_krita_data()

            if not image_path:
                self.logger.error("✗ 获取Krita数据失败")
                processing_file.unlink(missing_ok=True)
                return

            # 创建响应文件
            response_file = self.monitor_dir / f"fetch_{node_id}_{timestamp}.response"
            self.logger.info(f"创建响应文件: {response_file.name}")

            import json
            response_data = {
                "status": "success",
                "image_path": str(image_path) if image_path else None,
                "mask_path": str(mask_path) if mask_path else None
            }

            with open(response_file, 'w', encoding='utf-8') as f:
                json.dump(response_data, f, ensure_ascii=False, indent=2)

            self.logger.info(f"✓ 响应文件已创建: {response_file.name}")
            self.logger.info(f"  图像路径: {response_data['image_path']}")
            self.logger.info(f"  蒙版路径: {response_data['mask_path']}")

            # 删除处理中的文件
            processing_file.unlink(missing_ok=True)
            self.logger.info(f"✓ 请求文件已删除")
            self.logger.info(f"===== fetch请求处理完成 =====")

        except Exception as e:
            self.logger.error(f"✗ 处理fetch请求时出错: {e}")
            import traceback
            traceback.print_exc()
            # 清理处理中的文件
            try:
                processing_file.unlink(missing_ok=True)
            except:
                pass

    def _on_directory_changed(self, path):
        """目录内容改变时的回调"""
        # 使用延迟检查，避免文件正在写入时就打开
        QTimer.singleShot(300, self._check_new_files)

    def _handle_check_document_request(self, request_file: Path):
        """处理check_document请求文件，返回是否有活动文档"""
        try:
            self.logger.info(f"===== 处理check_document请求: {request_file.name} =====")

            # 解析文件名：check_document_{node_id}_{timestamp}.request
            filename = request_file.stem  # 移除.request扩展名
            parts = filename.split('_')

            if len(parts) < 4:
                self.logger.error(f"✗ 请求文件名格式错误: {request_file.name}")
                request_file.unlink(missing_ok=True)
                return

            # 提取node_id和timestamp (check_document_{node_id}_{timestamp})
            node_id = parts[2]
            timestamp = parts[3]
            self.logger.info(f"Node ID: {node_id}, Timestamp: {timestamp}")

            # 检查是否有活动文档
            app = Krita.instance()
            active_doc = app.activeDocument()
            has_active_document = active_doc is not None

            self.logger.info(f"活动文档检查结果: {'有文档' if has_active_document else '无文档'}")

            # 创建响应文件
            response_file = self.monitor_dir / f"check_document_{node_id}_{timestamp}.response"
            self.logger.info(f"创建响应文件: {response_file.name}")

            import json
            response_data = {
                "has_active_document": has_active_document
            }

            with open(response_file, 'w', encoding='utf-8') as f:
                json.dump(response_data, f, ensure_ascii=False, indent=2)

            self.logger.info(f"✓ 响应文件已创建: {response_file.name}")

            # 删除请求文件
            request_file.unlink(missing_ok=True)
            self.logger.info(f"✓ 请求文件已删除")
            self.logger.info(f"===== check_document请求处理完成 =====")

        except Exception as e:
            self.logger.error(f"✗ 处理check_document请求时出错: {e}")
            import traceback
            traceback.print_exc()
            # 清理请求文件
            try:
                request_file.unlink(missing_ok=True)
            except:
                pass

    def _handle_open_request(self, request_file: Path):
        """处理open请求文件，主动打开指定图像"""
        try:
            # 🔥 首先检查是否已经处理过这个请求（防止重复处理）
            request_name = request_file.name
            if request_name in self.processed_requests:
                self.logger.info(f"⚠ 请求已处理过，跳过: {request_name}")
                return

            # 🔥 立即标记为已处理（在处理之前，防止并发）
            self.processed_requests.add(request_name)
            self.logger.info(f"===== 处理open请求: {request_name} =====")

            # 🔥 立即重命名请求文件为.processing，避免重复处理
            processing_file = request_file.with_suffix('.processing')
            try:
                request_file.rename(processing_file)
                self.logger.info(f"✓ 请求文件已标记为处理中")
            except FileNotFoundError:
                # 文件已被处理或删除，直接返回
                self.logger.info(f"⚠ 请求文件已被处理，跳过")
                return
            except Exception as e:
                self.logger.warning(f"⚠ 重命名请求文件失败: {e}，继续处理")
                processing_file = request_file  # 如果重命名失败，继续用原文件

            # 读取请求内容
            import json
            with open(processing_file, 'r', encoding='utf-8') as f:
                request_data = json.load(f)

            image_path_str = request_data.get("image_path")
            node_id = request_data.get("node_id")

            if not image_path_str:
                self.logger.error("✗ 请求中缺少image_path")
                processing_file.unlink(missing_ok=True)
                return

            image_path = Path(image_path_str)
            if not image_path.exists():
                self.logger.error(f"✗ 图像文件不存在: {image_path}")
                processing_file.unlink(missing_ok=True)
                return

            self.logger.info(f"节点ID: {node_id}")
            self.logger.info(f"图像路径: {image_path}")

            # 🔥 检查是否已经打开了相同的图像（避免重复打开）
            file_key = str(image_path.resolve())
            if file_key in self.opened_documents:
                existing_doc = self.opened_documents[file_key]
                # 检查文档是否仍然有效（未被关闭）
                if existing_doc and existing_doc.name():
                    self.logger.info(f"⚠ 图像已打开，跳过重复打开: {image_path.name}")
                    self.logger.info(f"✓ 已跳过请求，删除处理文件")
                    processing_file.unlink(missing_ok=True)
                    return

            # 🔥 主动打开图像（与_check_new_files中的逻辑相同）
            app = Krita.instance()

            # 启用批处理模式（禁止自动保存弹窗）
            original_batchmode = app.batchmode()
            app.setBatchmode(True)
            self.logger.info("✓ 已启用批处理模式（打开文档）")

            try:
                # 打开文件
                doc = app.openDocument(str(image_path))
                if doc:
                    # 🔥 立即清理自动保存文件，避免恢复对话框
                    try:
                        autosave_file = Path(str(image_path) + "~")
                        if autosave_file.exists():
                            autosave_file.unlink()
                            self.logger.info(f"✓ 已删除自动保存文件: {autosave_file.name}")
                    except Exception as e:
                        self.logger.warning(f"⚠ 删除自动保存文件失败: {e}")

                    # 获取窗口（优先使用activeWindow，如果为None则使用windows()[0]）
                    window = app.activeWindow()
                    if not window:
                        self.logger.warning("⚠ activeWindow返回None，尝试使用windows()[0]")
                        windows_list = app.windows()
                        if windows_list:
                            window = windows_list[0]
                            self.logger.info(f"✓ 使用windows()[0]获取窗口")
                        else:
                            self.logger.error("✗ windows()列表为空，无法获取Krita窗口")

                    if window:
                        window.addView(doc)
                        self.logger.info(f"✓ 已打开: {image_path.name}")

                        # 存储文档映射（用于后续fetch请求）
                        file_key = str(image_path.resolve())
                        self.opened_documents[file_key] = doc
                        self.logger.info(f"✓ 已存储文档映射: {file_key}")

                        # 标记为已处理，避免重复打开
                        self.processed_files.add(image_path)

                        # ⭐ 延迟设置图层（2秒后，确保文档完全加载）
                        def delayed_setup():
                            try:
                                self.logger.info(f"===== 延迟设置开始: {doc.name()} =====")

                                # 激活窗口，确保Krita窗口处于前台
                                if window:
                                    window.activate()
                                    self.logger.info("✓ 窗口已激活")

                                # 设置活动文档
                                app.setActiveDocument(doc)
                                self.logger.info("✓ 文档已设置为活动")

                                # 设置图层
                                self._setup_layers(doc)

                            except Exception as e:
                                self.logger.error(f"延迟设置图层失败: {e}")
                                import traceback
                                traceback.print_exc()

                        QTimer.singleShot(2000, delayed_setup)  # ⏱️ 增加到2秒
                    else:
                        self.logger.error(f"✗ 无法获取Krita窗口，无法显示文档: {image_path.name}")
                else:
                    self.logger.error(f"✗ 打开失败: {image_path.name}")

            finally:
                # 恢复批处理模式
                app.setBatchmode(original_batchmode)
                self.logger.info("✓ 已恢复批处理模式")

            # 删除处理中的文件
            processing_file.unlink(missing_ok=True)
            self.logger.info(f"✓ 请求文件已删除")
            self.logger.info(f"===== open请求处理完成 =====")

        except Exception as e:
            self.logger.error(f"✗ 处理open请求时出错: {e}")
            import traceback
            traceback.print_exc()
            # 清理处理中的文件
            try:
                processing_file.unlink(missing_ok=True)
            except:
                pass

    def _check_new_files(self):
        """检查新文件并自动打开，以及处理fetch请求"""
        try:
            # ===== 处理check_document请求文件 =====
            check_request_files = list(self.monitor_dir.glob("check_document_*.request"))
            for request_file in check_request_files:
                self.logger.info(f"检测到check_document请求: {request_file.name}")
                self._handle_check_document_request(request_file)

            # ===== 处理fetch请求文件 =====
            request_files = list(self.monitor_dir.glob("fetch_*.request"))
            for request_file in request_files:
                self.logger.info(f"检测到fetch请求: {request_file.name}")
                self._handle_fetch_request(request_file)

            # ===== 处理open请求文件 =====
            open_request_files = list(self.monitor_dir.glob("open_*.request"))
            for request_file in open_request_files:
                self.logger.info(f"检测到open请求: {request_file.name}")
                self._handle_open_request(request_file)

            # ===== 处理PNG图像文件（已禁用，改用open请求机制） =====
            # 🔥 2025-11-01: 完全禁用PNG自动打开，避免误打开旧文件
            # 现在只通过明确的open_*.request来打开图像，更可靠且不会有意外
            # 如果需要重新启用，取消下面代码的注释

            # current_time = time.time()
            # max_age = 300  # 只处理最近5分钟内的文件（秒）
            #
            # png_files = [
            #     f for f in self.monitor_dir.glob("comfyui_*.png")
            #     if "_mask" not in f.name and f not in self.processed_files
            #     and (current_time - f.stat().st_mtime) < max_age
            # ]
            #
            # if not png_files:
            #     return
            #
            # png_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            #
            # for png_file in png_files[:1]:

            # PNG自动监控已禁用，不做任何处理
            return

            # 以下代码已不会执行（保留用于参考）
            for png_file in []:  # 空列表，不会执行
                file_age = current_time - png_file.stat().st_mtime
                self.logger.info(f"检测到新文件: {png_file.name} (创建于 {file_age:.1f}秒前)")
                self.processed_files.add(png_file)

                # 窗口激活功能暂时禁用（技术限制）
                # self._activate_krita_window()
                # time.sleep(0.2)  # 等待窗口激活

                # ✅ 打开文档前启用批处理模式（禁止自动保存弹窗）
                app = Krita.instance()
                original_batchmode = app.batchmode()
                app.setBatchmode(True)
                self.logger.info("✓ 已启用批处理模式（打开文档）")

                try:
                    # 打开文件
                    doc = app.openDocument(str(png_file))
                    if doc:
                        # 🔥 修复：获取窗口（优先使用activeWindow，如果为None则使用windows()[0]）
                        window = app.activeWindow()
                        if not window:
                            self.logger.warning("⚠ activeWindow返回None，尝试使用windows()[0]")
                            windows_list = app.windows()
                            if windows_list:
                                window = windows_list[0]
                                self.logger.info(f"✓ 使用windows()[0]获取窗口")
                            else:
                                self.logger.error("✗ windows()列表为空，无法获取Krita窗口")

                        if window:
                            window.addView(doc)
                            self.logger.info(f"✓ 已打开: {png_file.name}")

                            # 存储文档映射（用于后续fetch请求）
                            file_key = str(png_file.resolve())
                            self.opened_documents[file_key] = doc
                            self.logger.info(f"✓ 已存储文档映射: {file_key}")

                            # ✅ 延迟设置图层
                            # 使用QTimer延迟执行，确保文档完全加载
                            def delayed_setup():
                                self.logger.info(f"===== 延迟设置开始: {doc.name()} =====")
                                self._setup_layers(doc)

                            QTimer.singleShot(1000, delayed_setup)  # 1秒后执行，确保文档完全加载
                        else:
                            self.logger.error(f"✗ 无法获取Krita窗口，无法显示文档: {png_file.name}")
                    else:
                        self.logger.error(f"✗ 打开失败: {png_file.name}")

                finally:
                    # ✅ 恢复批处理模式
                    app.setBatchmode(original_batchmode)
                    self.logger.info("✓ 已恢复批处理模式")

        except Exception as e:
            self.logger.error(f"检查新文件时出错: {e}")
            import traceback
            traceback.print_exc()

    def createActions(self, window):
        """创建菜单动作（空实现，不创建任何菜单）"""
        pass

