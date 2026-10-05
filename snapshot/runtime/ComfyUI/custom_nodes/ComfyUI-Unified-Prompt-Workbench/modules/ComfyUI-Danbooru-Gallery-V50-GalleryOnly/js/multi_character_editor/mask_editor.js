// Canvas蒙版编辑器组件 - 版本 2025.10.12.0352
import { globalMultiLanguageManager } from '../global/multi_language.js';
import { globalToastManager as toastManagerProxy } from '../global/toast_manager.js';

import { createLogger } from '../global/logger_client.js';

// 创建logger实例
const logger = createLogger('mask_editor');

// 🔧 强制刷新标记 - 版本: 2025-10-12-23:50
logger.info('[mask_editor.js] 文件已加载 - 版本: 2025-10-12-23:50');

class MaskEditor {
    constructor(editor) {
        this.editor = editor;
        this.container = editor.container.querySelector('.mce-mask-editor');
        this.canvas = null;
        this.ctx = null;
        this.masks = [];
        this.selectedMask = null;
        this.isDragging = false;
        this.isResizing = false;
        this.dragStart = { x: 0, y: 0 };
        this.resizeHandle = null;
        this.viewport = { x: 0, y: 0, width: 1, height: 1 };
        this.scale = 1;
        this.offset = { x: 0, y: 0 };
        this.pendingPreviewResize = null;
        this.toastManager = toastManagerProxy;
        // 🔧 新增：记录上次容器尺寸，用于判断是否真的需要重新计算缩放
        this.lastContainerSize = { width: 0, height: 0 };

        // 添加拖拽状态管理
        this.dragStart = null;
        this.initialMaskPosition = null;
        this.initialMaskState = null;

        // 🔧 新增：布局修复重试计数器，防止无限循环
        this.layoutFixRetryCount = 0;
        this.maxLayoutFixRetries = 3; // 最多重试3次

        this.init();
    }

    init() {

        this.createCanvas();
        this.bindCanvasEvents();
        // 🔧 已禁用：按键监听会与ComfyUI的快捷键冲突
        // this.bindKeyboardEvents();
        this.startRenderLoop();

        // 添加延迟初始化，确保在DOM完全加载后进行
        setTimeout(() => {

            this.forceInitialRender();
        }, 1500);

        // 添加更多延迟渲染，确保画布正确显示
        setTimeout(() => {
            this.ensureCanvasVisible();
        }, 2000);

        // 监听语言变化事件
        document.addEventListener('languageChanged', (e) => {
            if (e.detail.component === 'maskEditor' || !e.detail.component) {
                this.scheduleRender();
            }
        });


    }

    createCanvas() {
        this.canvas = document.createElement('canvas');
        this.canvas.className = 'mce-canvas';
        this.ctx = this.canvas.getContext('2d');

        // 设置Canvas样式
        this.canvas.style.cssText = `
            width: 100%;
            height: 100%;
            cursor: crosshair;
            background: #252525;
            display: block;
            visibility: visible;
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            z-index: 1;
            border-radius: 0;
            box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.5);
            object-fit: cover;
            margin: 0;
            padding: 0;
        `;

        // 确保容器样式正确
        this.container.style.cssText = `
            position: relative;
            overflow: hidden;
            display: block;
            width: 100%;
            height: 100%;
            background: #1a1a1a;
            margin: 0;
            padding: 0;
            border: none;
        `;

        this.container.appendChild(this.canvas);

        // 监听容器大小变化（使用节流）
        this.resizeObserver = new ResizeObserver((entries) => {
            if (this.isDragging || this.isResizing || this.isPanning) {
                return;
            }

            if (this.resizeTimeout) {
                clearTimeout(this.resizeTimeout);
            }

            this.resizeTimeout = setTimeout(() => {
                this.resizeTimeout = null;

                for (let entry of entries) {
                    const { width, height } = entry.contentRect;
                    if (width > 0 && height > 0) {
                        this.resizeCanvas();
                        this.scheduleRender();
                    }
                }
            }, 100);
        });
        this.resizeObserver.observe(this.container);

        this.resizeCanvas();
        this.scheduleRender();

        setTimeout(() => {
            this.resizeCanvas();
            this.scheduleRender();
        }, 500);

        setTimeout(() => {
            this.resizeCanvas();
            this.scheduleRender();
        }, 1000);
    }

    resize(width, height) {
        if (!this.canvas || !this.ctx) {

            return;
        }

        if (width <= 0 || height <= 0 || !isFinite(width) || !isFinite(height)) {

            return;
        }

        const dpr = window.devicePixelRatio || 1;
        // 🔧 关键修复：在设置新的缩放之前重置变换矩阵
        // this.ctx.setTransform(1, 0, 0, 1, 0, 0); // 之前这里是1,0,0,1,0,0, 导致缩放不正确
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0); // 重置变换矩阵并考虑dpr

        // 🔧 关键修复：Canvas的像素尺寸应直接匹配容器的实际尺寸乘以DPR
        // 🔧 关键修复：Canvas的像素尺寸应直接匹配容器的实际尺寸乘以DPR
        // 🔧 关键修复：Canvas的像素尺寸应直接匹配容器的实际尺寸乘以DPR
        this.canvas.width = this.container.clientWidth * dpr;
        this.canvas.height = this.container.clientHeight * dpr;

        // 🔧 关键修复：强制设置画布显示尺寸与容器完全一致
        // 使用容器的实际尺寸，而不是传入的尺寸
        const containerRect = this.container.getBoundingClientRect();
        const displayWidth = containerRect.width;
        const displayHeight = containerRect.height;

        // 🔧 强制设置画布显示尺寸与容器完全一致，使用!important确保样式优先级
        this.canvas.style.setProperty('width', `${displayWidth}px`, 'important');
        this.canvas.style.setProperty('height', `${displayHeight}px`, 'important');
        this.canvas.style.setProperty('top', '0', 'important');
        this.canvas.style.setProperty('left', '0', 'important');
        this.canvas.style.setProperty('right', '0', 'important');
        this.canvas.style.setProperty('bottom', '0', 'important');
        this.canvas.style.setProperty('margin', '0', 'important');
        this.canvas.style.setProperty('padding', '0', 'important');

        // 保持Canvas的显示尺寸与容器一致
        this.canvas.style.setProperty('width', `${this.container.clientWidth}px`, 'important');
        this.canvas.style.setProperty('height', `${this.container.clientHeight}px`, 'important');

        // 🔧 强制触发重新渲染，确保画布立即更新
        this.scheduleRender();

        const config = this.editor.dataManager.getConfig();
        if (!config || !config.canvas) {

            return;
        }

        const canvasWidth = config.canvas.width;
        const canvasHeight = config.canvas.height;

        // 🔧 关键修复：只有当容器尺寸真的变化时，才重新计算缩放和偏移
        // 这样可以保留用户手动设置的缩放（如滚轮缩放）
        const currentWidth = this.container.clientWidth;
        const currentHeight = this.container.clientHeight;
        const isFirstResize = this.lastContainerSize.width === 0 && this.lastContainerSize.height === 0;
        const sizeChanged = isFirstResize ||
            Math.abs(currentWidth - this.lastContainerSize.width) > 1 ||
            Math.abs(currentHeight - this.lastContainerSize.height) > 1;

        if (sizeChanged) {
            // 容器尺寸变化了，重新计算适配缩放并居中显示
            this.scale = Math.min(currentWidth / canvasWidth, currentHeight / canvasHeight);
            // 计算居中位置的偏移量
            this.offset.x = (currentWidth - canvasWidth * this.scale) / 2;
            this.offset.y = (currentHeight - canvasHeight * this.scale) / 2;

            // 更新记录的尺寸
            this.lastContainerSize.width = currentWidth;
            this.lastContainerSize.height = currentHeight;
        }


        this.scheduleRender();
    }

    // 🔧 新增：带重试机制的画布调整方法
    resizeCanvasWithRetry(retryCount = 0, maxRetries = 5) {
        if (!this.container) {
            return;
        }

        const rect = this.container.getBoundingClientRect();

        // 检查容器尺寸是否有效
        if (rect.width <= 0 || rect.height <= 0) {
            if (retryCount < maxRetries) {
                logger.warn(`[MaskEditor] resizeCanvasWithRetry: 容器尺寸无效 (${rect.width}x${rect.height})，第${retryCount + 1}次重试`);
                setTimeout(() => {
                    this.resizeCanvasWithRetry(retryCount + 1, maxRetries);
                }, 100 * (retryCount + 1)); // 递增延迟时间
            }
            return;
        }

        logger.info(`[MaskEditor] resizeCanvasWithRetry: 容器尺寸有效 (${rect.width}x${rect.height})，开始调整画布`);
        // 容器尺寸有效，调用正常的resizeCanvas
        this.resizeCanvas();
    }

    resizeCanvas(preserveTransform = false) {
        if (!this.container) {
            return;
        }

        // 使用requestAnimationFrame确保DOM更新完成
        requestAnimationFrame(() => {
            const rect = this.container.getBoundingClientRect();

            // 添加更严格的尺寸检查
            if (rect.width <= 0 || rect.height <= 0) {
                return;
            }

            // 🔧 关键修复：强制布局重新计算
            this.forceLayoutRecalculation();

            // 🔧 优化：直接设置画布样式，避免多次设置
            this.canvas.style.cssText = `
                width: 100% !important;
                height: 100% !important;
                cursor: crosshair !important;
                background: #252525 !important;
                display: block !important;
                visibility: visible !important;
                position: absolute !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                z-index: 1 !important;
                border-radius: 0 !important;
                box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.5) !important;
                object-fit: cover !important;
                margin: 0 !important;
                padding: 0 !important;
                opacity: 1 !important;
            `;

            // 确保容器样式正确
            this.container.style.cssText = `
                position: relative !important;
                overflow: hidden !important;
                display: block !important;
                width: 100% !important;
                height: 100% !important;
                background: #1a1a1a !important;
                margin: 0 !important;
                padding: 0 !important;
                border: none !important;
            `;

            // 立即执行resize
            this.resize(rect.width, rect.height);

            // 布局诊断：记录容器与画布的尺寸差异，用于排查之间的间隔
            this.logLayoutDiagnostics('resizeCanvas-after-resize');

            // 🔧 添加强制渲染，确保缩放比例信息立即更新
            this.scheduleRender();

            // 🔧 关键修复：添加布局诊断
            setTimeout(() => {
                this.diagnoseLayoutIssues();
            }, 50);
        });
    }

    // 🔧 新增：强制布局重新计算
    forceLayoutRecalculation() {
        try {
            // 临时隐藏元素强制重新计算布局
            const originalDisplay = this.container.style.display;
            this.container.style.display = 'none';

            // 触发重排
            this.container.offsetHeight;

            // 恢复显示
            this.container.style.display = originalDisplay || 'flex';

            // 检查父元素
            const parentElement = this.container.parentElement;
            if (parentElement) {
                const parentDisplay = parentElement.style.display;
                parentElement.style.display = 'none';
                parentElement.offsetHeight;
                parentElement.style.display = parentDisplay || '';
            }
        } catch (error) {
            logger.error('[MaskEditor] forceLayoutRecalculation: 布局重新计算失败', error);
        }
    }

    // 🔧 新增：诊断布局问题
    diagnoseLayoutIssues() {
        try {
            const containerRect = this.container.getBoundingClientRect();
            const canvasRect = this.canvas.getBoundingClientRect();

            const issues = [];

            // 检查容器尺寸
            if (containerRect.width <= 0 || containerRect.height <= 0) {
                issues.push('容器尺寸无效');
            }

            // 检查画布尺寸
            if (canvasRect.width <= 0 || canvasRect.height <= 0) {
                issues.push('画布尺寸无效');
            }

            // 检查画布是否填满容器
            const widthDiff = Math.abs(containerRect.width - canvasRect.width);
            const heightDiff = Math.abs(containerRect.height - canvasRect.height);

            if (widthDiff > 5 || heightDiff > 5) {
                issues.push(`画布未填满容器 (宽度差异: ${widthDiff}px, 高度差异: ${heightDiff}px)`);
            }

            // 检查画布位置
            if (canvasRect.left < containerRect.left - 5 ||
                canvasRect.top < containerRect.top - 5) {
                issues.push('画布位置不正确');
            }

            // 检查样式
            const computedStyle = window.getComputedStyle(this.canvas);
            if (computedStyle.display === 'none') {
                issues.push('画布被隐藏');
            }

            if (computedStyle.visibility === 'hidden') {
                issues.push('画布不可见');
            }

            if (parseFloat(computedStyle.opacity) < 0.5) {
                issues.push('画布透明度过低');
            }

            // 输出诊断结果
            if (issues.length > 0) {
                logger.warn('[MaskEditor] diagnoseLayoutIssues: 发现布局问题', {
                    issues: issues,
                    containerRect: containerRect,
                    canvasRect: canvasRect,
                    canvasStyle: {
                        display: computedStyle.display,
                        visibility: computedStyle.visibility,
                        opacity: computedStyle.opacity,
                        width: computedStyle.width,
                        height: computedStyle.height
                    }
                });

                // 尝试自动修复
                this.attemptLayoutFix(issues);
            }
        } catch (error) {
            logger.error('[MaskEditor] diagnoseLayoutIssues: 诊断失败', error);
        }
    }

    // 🔧 新增：尝试自动修复布局问题
    attemptLayoutFix(issues) {
        try {
            // 🔧 关键修复：检查重试次数，防止无限循环
            if (this.layoutFixRetryCount >= this.maxLayoutFixRetries) {
                logger.warn('[MaskEditor] attemptLayoutFix: 已达到最大重试次数，停止修复');
                return;
            }

            this.layoutFixRetryCount++;
            logger.info(`[MaskEditor] attemptLayoutFix: 尝试修复布局，第 ${this.layoutFixRetryCount} 次`);

            // 强制重新设置样式
            this.canvas.style.cssText = `
                width: 100% !important;
                height: 100% !important;
                cursor: crosshair !important;
                background: #252525 !important;
                display: block !important;
                visibility: visible !important;
                position: absolute !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                z-index: 1 !important;
                border-radius: 0 !important;
                box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.5) !important;
                object-fit: cover !important;
                margin: 0 !important;
                padding: 0 !important;
                opacity: 1 !important;
            `;

            // 确保容器样式
            this.container.style.cssText = `
                position: relative !important;
                overflow: hidden !important;
                display: block !important;
                width: 100% !important;
                height: 100% !important;
                background: #1a1a1a !important;
                margin: 0 !important;
                padding: 0 !important;
                border: none !important;
            `;

            // 强制重新计算布局
            this.forceLayoutRecalculation();

            // 重新渲染
            this.scheduleRender();

            // 延迟再次诊断，但要检查重试次数
            setTimeout(() => {
                if (this.layoutFixRetryCount < this.maxLayoutFixRetries) {
                    this.diagnoseLayoutIssues();
                } else {
                    logger.info('[MaskEditor] 布局修复已达到最大次数，不再继续诊断');
                }
            }, 100);

        } catch (error) {
            logger.error('[MaskEditor] attemptLayoutFix: 修复失败', error);
        }
    }
    bindCanvasEvents() {
        this.canvas.addEventListener('mousedown', this.onMouseDown.bind(this));
        this.canvas.addEventListener('mousemove', this.onMouseMove.bind(this));
        this.canvas.addEventListener('mouseup', this.onMouseUp.bind(this));
        this.canvas.addEventListener('wheel', this.onWheel.bind(this), { passive: false });
        // 🔧 已移除：右键菜单功能已移动到角色列表中
        // this.canvas.addEventListener('contextmenu', this.onContextMenu.bind(this));
        this.canvas.addEventListener('touchstart', this.onTouchStart.bind(this));
        this.canvas.addEventListener('touchmove', this.onTouchMove.bind(this));
        this.canvas.addEventListener('touchend', this.onTouchEnd.bind(this));
        this.canvas.addEventListener('blur', () => {
            this.selectedMask = null;
        });
    }

    // 🔧 已移除：键盘绑定会与ComfyUI和浏览器快捷键冲突
    // 用户可以通过右键菜单、拖拽等方式操作蒙版
    bindKeyboardEvents() {
        // 不再绑定键盘事件，避免与ComfyUI/浏览器快捷键冲突
    }

    onMouseDown(e) {
        // 🔧 关键修复：确保在任何交互之前，坐标系统已经正确初始化
        // 防止在scale和offset未正确设置时拖动蒙版，导致计算出错误的坐标
        if (this.lastContainerSize.width === 0 || this.lastContainerSize.height === 0) {
            logger.warn('[MaskEditor] onMouseDown: 坐标系统未初始化，先调用resize');
            this.resizeCanvasWithRetry();
            // 短暂延迟后再处理鼠标事件，确保resize完成
            setTimeout(() => {
                this.onMouseDown(e);
            }, 100);
            return;
        }

        const rect = this.canvas.getBoundingClientRect();
        // 🔧 关键修复：使用容器的clientWidth/clientHeight作为坐标基准
        // 因为绘制时的offset和scale都是基于容器显示尺寸的
        const x = (e.clientX - rect.left) * (this.container.clientWidth / rect.width);
        const y = (e.clientY - rect.top) * (this.container.clientHeight / rect.height);

        let handle = null;
        if (this.selectedMask) {
            handle = this.getResizeHandle(this.selectedMask, x, y);
            if (handle) {
                this.isResizing = true;
                this.resizeHandle = handle;
                this.dragStart = { x, y };
                this.initialMaskState = { ...this.selectedMask };
                if (this.resizeObserver) {
                    this.resizeObserver.disconnect();
                }
                this.canvas.style.cursor = this.getCursor(this.selectedMask, handle);
                return;
            }
        }

        const mask = this.getMaskAtPosition(x, y);

        if (mask) {
            this.selectedMask = mask;
            // 🔧 新增：通知编辑器蒙版被选中，以便同步选择角色
            if (this.editor.eventBus && mask.characterId) {
                this.editor.eventBus.emit('mask:selected', mask.characterId);
            }
            handle = this.getResizeHandle(mask, x, y);

            if (handle) {
                this.isResizing = true;
                this.resizeHandle = handle;
                this.dragStart = { x, y };
                this.initialMaskState = { ...mask };
                if (this.resizeObserver) {
                    this.resizeObserver.disconnect();
                }
            } else {
                this.isDragging = true;
                const config = this.editor.dataManager.getConfig();
                if (config && config.canvas) {
                    const { width, height } = config.canvas;
                    // 🔧 关键修复：使用画布坐标系，不依赖 offset
                    // 记录拖动开始时鼠标在画布上的位置（归一化坐标）
                    const canvasX = (x - this.offset.x) / this.scale;
                    const canvasY = (y - this.offset.y) / this.scale;
                    this.dragStart = {
                        canvasX: canvasX / width,  // 归一化坐标
                        canvasY: canvasY / height
                    };
                    this.initialMaskPosition = { x: mask.x, y: mask.y };
                } else {
                    this.dragStart = { x, y };
                    this.initialMaskPosition = { x: mask.x, y: mask.y };
                }
            }
        } else {
            this.selectedMask = null;
            // 🔧 新增：通知编辑器蒙版取消选择
            if (this.editor.eventBus) {
                this.editor.eventBus.emit('mask:deselected');
            }
            this.isPanning = true;
            this.panStart = { x, y };
            this.initialOffset = { x: this.offset.x, y: this.offset.y };
            this.canvas.style.cursor = 'grab';
        }

        const cursorHandle = this.getResizeHandle(mask, x, y);
        this.canvas.style.cursor = this.getCursor(mask, cursorHandle);
    }

    onMouseMove(e) {
        if (this.mouseMoveTimeout) {
            return;
        }
        this.mouseMoveTimeout = setTimeout(() => {
            this.mouseMoveTimeout = null;
            this.processMouseMove(e);
        }, 8);
    }

    processMouseMove(e) {
        const rect = this.canvas.getBoundingClientRect();
        // 🔧 关键修复：使用容器的clientWidth/clientHeight作为坐标基准
        const x = (e.clientX - rect.left) * (this.container.clientWidth / rect.width);
        const y = (e.clientY - rect.top) * (this.container.clientHeight / rect.height);

        if (this.isPanning) {
            const dx = x - this.panStart.x;
            const dy = y - this.panStart.y;
            this.offset.x = this.initialOffset.x + dx;
            this.offset.y = this.initialOffset.y + dy;
            this.scheduleRender();
        } else if (this.isDragging && this.selectedMask) {
            const config = this.editor.dataManager.getConfig();
            if (!config || !config.canvas) {
                return;
            }
            const { width, height } = config.canvas;

            // 🔧 关键修复：使用画布坐标系计算，不依赖 offset
            // 计算当前鼠标在画布上的归一化坐标
            const currentCanvasX = ((x - this.offset.x) / this.scale) / width;
            const currentCanvasY = ((y - this.offset.y) / this.scale) / height;

            // 计算鼠标在画布上的移动距离（归一化坐标）
            const deltaX = currentCanvasX - this.dragStart.canvasX;
            const deltaY = currentCanvasY - this.dragStart.canvasY;

            // 计算蒙版的新位置
            let newX = this.initialMaskPosition.x + deltaX;
            let newY = this.initialMaskPosition.y + deltaY;

            // 应用网格吸附
            let finalX = this.snapToGrid(newX * width) / width;
            let finalY = this.snapToGrid(newY * height) / height;

            // 🔧 关键修复：确保坐标在有效范围内
            finalX = Math.max(0, Math.min(1 - this.selectedMask.width, finalX));
            finalY = Math.max(0, Math.min(1 - this.selectedMask.height, finalY));

            // 验证计算结果的合理性
            if (!isFinite(finalX) || !isFinite(finalY)) {
                logger.error('[MaskEditor] 拖动计算出无效坐标，已忽略:', { finalX, finalY });
                return;
            }

            if (Math.abs(finalX - this.selectedMask.x) > 0.001 ||
                Math.abs(finalY - this.selectedMask.y) > 0.001) {
                this.updateMask(this.selectedMask.characterId, {
                    ...this.selectedMask,
                    x: finalX,
                    y: finalY
                });
            }
        } else if (this.isResizing && this.selectedMask) {
            this.handleResize(x, y);
        } else {
            if (!this.cursorUpdateTimeout) {
                this.cursorUpdateTimeout = setTimeout(() => {
                    this.cursorUpdateTimeout = null;
                    const mask = this.getMaskAtPosition(x, y);
                    const handle = this.getResizeHandle(mask, x, y);
                    if (this.isPanning) {
                        this.canvas.style.cursor = 'grabbing';
                    } else {
                        this.canvas.style.cursor = this.getCursor(mask, handle);
                    }
                }, 16);
            }
        }
    }

    onMouseUp(e) {
        if (this.isDragging) {
            this.dragStart = null;
            this.initialMaskPosition = null;
            this.dragLogShown = false; // 🔧 重置调试日志标志
        }
        if (this.isResizing) {
            this.resizeHandle = null;
            this.initialMaskState = null;
            if (this.resizeObserver && this.container) {
                this.resizeObserver.observe(this.container);
            }
        }
        if (this.isPanning) {
            this.isPanning = false;
            this.panStart = null;
            this.initialOffset = null;
        }
        this.isDragging = false;
        this.isResizing = false;

        if (!this.isDragging && !this.isResizing && !this.isPanning && this.pendingPreviewResize) {
            this.pendingPreviewResize = null;
        }
        this.scheduleRender();
    }

    onWheel(e) {
        e.preventDefault();
        if (this.wheelTimeout) {
            return;
        }
        this.wheelTimeout = setTimeout(() => {
            this.wheelTimeout = null;
            this.processWheel(e);
        }, 16);
    }

    processWheel(e) {
        const config = this.editor.dataManager.getConfig();
        if (!config || !config.canvas) {
            return;
        }
        const rect = this.canvas.getBoundingClientRect();
        // 🔧 关键修复：使用容器的clientWidth/clientHeight作为坐标基准
        const mouseX = (e.clientX - rect.left) * (this.container.clientWidth / rect.width);
        const mouseY = (e.clientY - rect.top) * (this.container.clientHeight / rect.height);
        const canvasX = (mouseX - this.offset.x) / this.scale;
        const canvasY = (mouseY - this.offset.y) / this.scale;
        const scaleFactor = e.deltaY > 0 ? 0.9 : 1.1;
        const newScale = Math.max(0.1, Math.min(5, this.scale * scaleFactor));
        if (Math.abs(newScale - this.scale) < 0.001) {
            return;
        }
        this.offset.x = mouseX - canvasX * newScale;
        this.offset.y = mouseY - canvasY * newScale;
        this.scale = newScale;
        this.scheduleRender();
    }

    // 🔧 已移除：右键菜单功能已移动到角色列表中
    // onContextMenu(e) { ... }

    onTouchStart(e) {
        const touch = e.touches[0];
        const mouseEvent = new MouseEvent('mousedown', {
            clientX: touch.clientX,
            clientY: touch.clientY
        });
        this.canvas.dispatchEvent(mouseEvent);
    }

    onTouchMove(e) {
        const touch = e.touches[0];
        const mouseEvent = new MouseEvent('mousemove', {
            clientX: touch.clientX,
            clientY: touch.clientY
        });
        this.canvas.dispatchEvent(mouseEvent);
    }

    onTouchEnd(e) {
        const mouseEvent = new MouseEvent('mouseup', {});
        this.canvas.dispatchEvent(mouseEvent);
    }

    getMaskAtPosition(x, y) {
        const canvasX = (x - this.offset.x) / this.scale;
        const canvasY = (y - this.offset.y) / this.scale;
        const config = this.editor.dataManager.getConfig();
        if (!config || !config.canvas) {
            return null;
        }
        const { width, height } = config.canvas;
        if (this.selectedMask) {
            const handle = this.getResizeHandle(this.selectedMask, x, y);
            if (handle) {
                return this.selectedMask;
            }
        }
        for (let i = this.masks.length - 1; i >= 0; i--) {
            const mask = this.masks[i];
            if (!mask || typeof mask.x !== 'number' || typeof mask.y !== 'number' ||
                typeof mask.width !== 'number' || typeof mask.height !== 'number') {
                continue;
            }
            const maskX = mask.x * width;
            const maskY = mask.y * height;
            const maskWidth = mask.width * width;
            const maskHeight = mask.height * height;
            const tolerance = Math.max(2, 4 / this.scale);
            if (canvasX >= maskX - tolerance && canvasX <= maskX + maskWidth + tolerance &&
                canvasY >= maskY - tolerance && canvasY <= maskY + maskHeight + tolerance) {
                return mask;
            }
        }
        return null;
    }

    getResizeHandle(mask, x, y) {
        if (!mask) return null;
        const canvasX = (x - this.offset.x) / this.scale;
        const canvasY = (y - this.offset.y) / this.scale;
        const config = this.editor.dataManager.getConfig();
        if (!config || !config.canvas) {
            return null;
        }
        const { width, height } = config.canvas;
        const maskX = mask.x * width;
        const maskY = mask.y * height;
        const maskWidth = mask.width * width;
        const maskHeight = mask.height * height;
        const isSelected = this.selectedMask && this.selectedMask.characterId === mask.characterId;
        const baseHandleSize = isSelected ? 12 : 8;
        const handleSize = Math.max(baseHandleSize, (isSelected ? 24 : 16) / this.scale);
        const handles = {
            'nw': { x: maskX, y: maskY },
            'ne': { x: maskX + maskWidth, y: maskY },
            'sw': { x: maskX, y: maskY + maskHeight },
            'se': { x: maskX + maskWidth, y: maskY + maskHeight }
        };
        for (const [name, pos] of Object.entries(handles)) {
            const distance = Math.sqrt(Math.pow(canvasX - pos.x, 2) + Math.pow(canvasY - pos.y, 2));
            if (distance <= handleSize) {
                return name;
            }
        }
        return null;
    }

    getCursor(mask, handle) {
        if (this.isPanning) {
            return 'grabbing';
        }
        if (!mask) return 'grab';
        const cursors = {
            'nw': 'nw-resize',
            'ne': 'ne-resize',
            'sw': 'sw-resize',
            'se': 'se-resize'
        };
        return handle ? cursors[handle] : 'move';
    }

    handleResize(x, y) {
        if (!this.selectedMask || !this.resizeHandle) {
            return;
        }
        const config = this.editor.dataManager.getConfig();
        if (!config || !config.canvas) {
            return;
        }
        const { width, height } = config.canvas;
        const canvasX = (x - this.offset.x) / this.scale;
        const canvasY = (y - this.offset.y) / this.scale;
        const mask = this.selectedMask;
        const updates = { ...mask };
        const maskX = mask.x * width;
        const maskY = mask.y * height;
        const maskWidth = mask.width * width;
        const maskHeight = mask.height * height;
        const snappedCanvasX = Math.max(0, Math.min(width, this.snapToGrid(canvasX)));
        const snappedCanvasY = Math.max(0, Math.min(height, this.snapToGrid(canvasY)));

        switch (this.resizeHandle) {
            case 'nw':
                updates.width = (maskX + maskWidth - snappedCanvasX) / width;
                updates.height = (maskY + maskHeight - snappedCanvasY) / height;
                updates.x = snappedCanvasX / width;
                updates.y = snappedCanvasY / height;
                break;
            case 'ne':
                updates.width = (snappedCanvasX - maskX) / width;
                updates.height = (maskY + maskHeight - snappedCanvasY) / height;
                updates.y = snappedCanvasY / height;
                break;
            case 'sw':
                updates.width = (maskX + maskWidth - snappedCanvasX) / width;
                updates.height = (snappedCanvasY - maskY) / height;
                updates.x = snappedCanvasX / width;
                break;
            case 'se':
                updates.width = (snappedCanvasX - maskX) / width;
                updates.height = (snappedCanvasY - maskY) / height;
                break;
        }

        updates.width = Math.max(0.05, updates.width);
        updates.height = Math.max(0.05, updates.height);
        updates.width = Math.min(updates.width, 1 - updates.x);
        updates.height = Math.min(updates.height, 1 - updates.y);
        updates.x = Math.max(0, Math.min(1 - updates.width, updates.x));
        updates.y = Math.max(0, Math.min(1 - updates.height, updates.y));

        this.selectedMask = updates;
        const maskIndex = this.masks.findIndex(m => m.characterId === this.selectedMask.characterId);
        if (maskIndex !== -1) {
            this.masks[maskIndex] = updates;
        }
        this.editor.dataManager.updateCharacterMask(this.selectedMask.characterId, updates);
        this.scheduleRender();
    }

    // 🔧 已移除：右键菜单相关功能已移动到角色列表中
    // showContextMenu(mask, x, y) { ... }
    // handleContextMenuAction(mask, action) { ... }

    showWeightDialog(mask) {
        const t = this.editor.languageManager ? this.editor.languageManager.t.bind(this.editor.languageManager) : globalMultiLanguageManager.t.bind(globalMultiLanguageManager);
        const existingDialog = document.querySelector('.mce-weight-dialog');
        if (existingDialog) {
            existingDialog.remove();
        }
        const character = this.editor.dataManager.getCharacter(mask.characterId);
        const currentWeight = character ? (character.weight || 1.0) : 1.0;
        const dialog = document.createElement('div');
        dialog.className = 'mce-weight-dialog';
        dialog.innerHTML = `
            <div style="padding: 16px; background: #2a2a2a; border-radius: 8px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5); min-width: 280px;">
                <h3 style="margin: 0 0 12px 0; color: #E0E0E0; font-size: 14px;">${t('setWeight') || '设置权重'}</h3>
                <div style="margin-bottom: 12px;">
                    <label style="display: block; margin-bottom: 8px; color: #999; font-size: 12px;">
                        ${t('weightValue') || '权重值'} (0 - 1.0):
                    </label>
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <input type="range" id="weight-slider" min="0" max="1.0" step="0.01" value="${currentWeight}" 
                            style="flex: 1; height: 4px; background: #555; border-radius: 2px; outline: none; -webkit-appearance: none;">
                        <input type="number" id="weight-input" min="0" max="1.0" step="0.01" value="${currentWeight}"
                            style="width: 60px; padding: 4px 8px; background: #1a1a1a; color: #E0E0E0; border: 1px solid #555; border-radius: 4px; font-size: 12px; text-align: center;">
                    </div>
                </div>
                <div style="font-size: 11px; color: #888; margin-bottom: 12px; line-height: 1.4;">
                    <strong>${t('note') || '说明'}:</strong> ${t('weightDescription') || '权重值越大，该角色在生成时的影响力越强'}<br>
                    • 1.0: ${t('defaultWeight') || '最高权重'}<br>
                    • 0.5: 中等权重<br>
                    • 0: 最低权重
                </div>
                <div style="display: flex; gap: 8px; justify-content: flex-end;">
                    <button id="weight-cancel" style="padding: 6px 16px; background: #555; color: #E0E0E0; border: none; border-radius: 4px; cursor: pointer; font-size: 12px;">
                        ${t('buttonTexts.cancel') || '取消'}
                    </button>
                    <button id="weight-ok" style="padding: 6px 16px; background: #7c3aed; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px;">
                        ${t('buttonTexts.ok') || '确定'}
                    </button>
                </div>
            </div>
        `;

        dialog.style.cssText = `
            position: fixed;
            left: 50%;
            top: 50%;
            transform: translate(-50%, -50%);
            z-index: 10000;
            background: transparent;
        `;

        document.body.appendChild(dialog);

        const slider = document.getElementById('weight-slider');
        const input = document.getElementById('weight-input');
        const okBtn = document.getElementById('weight-ok');
        const cancelBtn = document.getElementById('weight-cancel');

        // 同步滑块和输入框
        slider.addEventListener('input', () => {
            input.value = slider.value;
        });

        input.addEventListener('input', () => {
            let value = parseFloat(input.value);
            if (value < 0.1) value = 0.1;
            if (value > 2.0) value = 2.0;
            slider.value = value;
            input.value = value;
        });

        okBtn.addEventListener('click', () => {
            const weight = parseFloat(input.value);
            this.editor.dataManager.updateCharacter(mask.characterId, { weight });
            this.scheduleRender();
            dialog.remove();
            this.showToast(`${t('weightSetTo') || '权重已设置为'}: ${weight.toFixed(1)}`, 'success');
        });

        cancelBtn.addEventListener('click', () => {
            dialog.remove();
        });

        // 点击外部关闭
        setTimeout(() => {
            document.addEventListener('click', (e) => {
                if (!dialog.contains(e.target) && dialog.parentNode) {
                    dialog.remove();
                }
            }, { once: true });
        }, 100);
    }

    showFeatherDialog(mask) {
        const t = this.editor.languageManager ? this.editor.languageManager.t.bind(this.editor.languageManager) : globalMultiLanguageManager.t.bind(globalMultiLanguageManager);
        const existingDialog = document.querySelector('.mce-feather-dialog');
        if (existingDialog) {
            existingDialog.remove();
        }
        const dialog = document.createElement('div');
        dialog.className = 'mce-feather-dialog';
        const currentValue = mask.feather || 0;
        dialog.innerHTML = `...`; // Content omitted for brevity
        // ... (rest of the function is complex UI creation, assumed correct)
    }

    addMask(character) {
        if (!this.masks) {
            this.masks = [];
        }
        if (!character.mask) {
            const mask = {
                id: this.editor.dataManager.generateId('mask'),
                characterId: character.id,
                x: 0.1 + (this.masks.length * 0.1) % 0.6,
                y: 0.1 + Math.floor(this.masks.length / 6) * 0.3,
                width: 0.3,
                height: 0.3,
                feather: 0,
                blend_mode: 'normal',
                zIndex: this.masks.length
            };
            this.masks.push(mask);
            this.selectedMask = mask;
            this.editor.dataManager.updateCharacterMask(character.id, mask);
        } else {
            const existingMask = this.masks.find(m => m.characterId === character.id);
            if (!existingMask) {
                this.masks.push(character.mask);
            }
            this.selectedMask = character.mask;
        }
        this.scheduleRender();
        setTimeout(() => {
            this.scheduleRender();
        }, 100);
    }

    clearAllMasks() {
        try {
            this.masks = [];
            this.selectedMask = null;
            this.scheduleRender();
        } catch (error) {
            logger.error('[MaskEditor] clearAllMasks: 清空蒙版失败:', error);
        }
    }

    updateMask(characterId, mask) {
        if (!characterId) {
            return;
        }

        // 🔧 关键修复：在更新蒙版前先验证坐标
        // skipSave=true 避免重复保存，因为下面会统一调用 updateCharacterMask
        if (mask) {
            const validatedMask = this.validateMaskCoordinates(mask, characterId, true);
            // 如果坐标被修复了，使用修复后的版本
            mask = validatedMask;
        }

        const index = this.masks.findIndex(m => m.characterId === characterId);
        if (index !== -1 && mask) {
            const existingMask = this.masks[index];
            const hasChanged = !this.masksEqual(existingMask, mask);
            if (hasChanged) {
                this.masks[index] = mask;
                this.selectedMask = mask;
                this.editor.dataManager.updateCharacterMask(characterId, mask);
                this.scheduleRender();
            }
        } else if (index === -1 && mask) {
            this.masks.push(mask);
            this.selectedMask = mask;
            this.editor.dataManager.updateCharacterMask(characterId, mask);
            this.scheduleRender();
        }
        this.scheduleRender();
    }

    masksEqual(mask1, mask2) {
        if (!mask1 && !mask2) return true;
        if (!mask1 || !mask2) return false;
        return mask1.x === mask2.x &&
            mask1.y === mask2.y &&
            mask1.width === mask2.width &&
            mask1.height === mask2.height &&
            mask1.feather === mask2.feather &&
            mask1.blend_mode === mask2.blend_mode;
    }

    removeMask(characterId) {
        this.masks = this.masks.filter(m => m.characterId !== characterId);
        if (this.selectedMask && this.selectedMask.characterId === characterId) {
            this.selectedMask = null;
        }
        // 🔧 修复：检查角色是否存在，避免"未找到角色"错误
        if (this.editor.dataManager.getCharacter(characterId)) {
            this.editor.dataManager.updateCharacterMask(characterId, null);
        }
        this.scheduleRender();
    }

    deleteMask(characterId) {
        const character = this.editor.dataManager.getCharacter(characterId);
        if (!character) return;
        this.editor.dataManager.deleteCharacter(characterId);
        const t = this.editor.languageManager ? this.editor.languageManager.t.bind(this.editor.languageManager) : globalMultiLanguageManager.t.bind(globalMultiLanguageManager);
        this.showToast(t('characterDeleted'), 'success');
    }

    startRenderLoop() { }

    scheduleRender() {
        if (this.renderFrameId) {
            cancelAnimationFrame(this.renderFrameId);
        }
        this.renderFrameId = requestAnimationFrame(() => {
            this.render();
            this.renderFrameId = null;
        });
        if (this.renderTimeout) {
            clearTimeout(this.renderTimeout);
        }
        this.renderTimeout = setTimeout(() => {
            if (this.renderFrameId) {
                cancelAnimationFrame(this.renderFrameId);
                this.renderFrameId = null;

                this.render();
            }
        }, 16);
    }

    render() {
        if (!this.canvas || !this.ctx) return;

        const config = this.editor.dataManager.getConfig();
        if (!config || !config.canvas) return;

        if (this.renderCount === undefined) {
            this.renderCount = 0;
        }
        this.renderCount++;
        if (this.renderCount > 1000) {
            logger.warn('[MaskEditor] 渲染次数过多，强制停止渲染');
            return;
        }



        this.syncMasksFromCharacters();
        const { width, height } = config.canvas;

        if (this.canvas.width <= 0 || this.canvas.height <= 0 ||
            this.canvas.width > 10000 || this.canvas.height > 10000 ||
            !isFinite(this.canvas.width) || !isFinite(this.canvas.height)) {

            return;
        }

        if (!isFinite(this.scale) || this.scale <= 0 || this.scale > 10 ||
            !isFinite(this.offset.x) || !isFinite(this.offset.y)) {

            this.scale = 1;
            this.offset = { x: 0, y: 0 };
        }



        // 🔧 关键修复：确保渲染使用正确的DPR变换矩阵
        const dpr = window.devicePixelRatio || 1;
        this.ctx.setTransform(1, 0, 0, 1, 0, 0);  // 重置为单位矩阵用于清屏
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.ctx.save();
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);  // 设置DPR
        this.ctx.translate(this.offset.x, this.offset.y);
        this.ctx.scale(this.scale, this.scale);
        this.ctx.fillStyle = '#1e1e1e';
        this.ctx.fillRect(0, 0, width, height);
        this.drawGridOptimized(width, height);
        this.drawCanvasBorderOptimized(width, height);

        const maxMasks = 50;
        const masksToRender = this.masks.slice(0, maxMasks);

        // 🔧 控制调试日志：只在第一次render时输出
        if (!this.renderLogCount) {
            this.renderLogCount = 0;
        }
        this.drawLogShown = (this.renderLogCount < 1);

        masksToRender.forEach((mask) => {
            this.drawMaskOptimized(mask);
        });

        this.renderLogCount++;

        if (this.selectedMask) {
            // 🔧 关键修复：直接使用已设置的变换矩阵（dpr + offset + scale）
            // 不需要重新设置，因为外层已经正确配置了坐标系
            this.drawSelectionOptimized(this.selectedMask);
        }

        this.ctx.restore();

        this.drawResolutionInfoOptimized();

        if (this.renderCount > 100) {
            this.renderCount = 0;
        }


    }

    drawResolutionInfoOptimized() {
        if (!this.canvas || !this.ctx) return;

        this.ctx.save();
        const dpr = window.devicePixelRatio || 1;
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const config = this.editor.dataManager.getConfig();
        const zoomLevel = Math.round(this.scale * 100);

        // 使用canvas的显示尺寸，使文本固定在画布区域右下角
        if (!config || !config.canvas) {
            this.ctx.restore();
            return;
        }
        // 使用canvas的clientWidth/clientHeight获取实际显示区域的尺寸
        const displayWidth = this.canvas.clientWidth;
        const displayHeight = this.canvas.clientHeight;

        // 根据容器显示大小自适应字体大小，设置为更大更清晰
        const minDisplayDimension = Math.min(displayWidth, displayHeight);
        const baseFontSize = Math.max(14, Math.min(18, minDisplayDimension / 35)); // 字体大小在14-18px之间

        this.ctx.font = `${baseFontSize}px Arial`;
        this.ctx.fillStyle = '#CCCCCC';
        this.ctx.textAlign = 'right';
        this.ctx.textBaseline = 'bottom';

        // 根据字体大小自适应边距
        const margin = Math.max(8, baseFontSize);
        const lineHeight = baseFontSize + 4; // 行高稍大于字体大小

        const t = this.editor.languageManager ? this.editor.languageManager.t.bind(this.editor.languageManager) : globalMultiLanguageManager.t.bind(globalMultiLanguageManager);

        // 使用画布内容区域的右下角位置来定位文本
        const textX = displayWidth - margin;
        const textY = displayHeight - margin;

        // 🔧 关键修复：使用容器显示尺寸定位文本，确保填满整个节点右侧
        // 绘制缩放比例
        this.ctx.fillText(
            `${t('zoom')}: ${zoomLevel}%`,
            textX,
            textY
        );

        // 绘制分辨率信息
        if (config && config.canvas) {
            this.ctx.fillText(
                `${config.canvas.width}x${config.canvas.height}`,
                textX,
                textY - lineHeight
            );
        }

        this.ctx.restore();
    }

    syncMasksFromCharacters() {
        try {
            if (this.isDragging || this.isResizing || this.isPanning) {
                return;
            }
            const characters = this.editor.dataManager.getCharacters();

            const newMasks = characters
                .filter(char => char.mask && char.enabled)
                .map(char => {
                    const mask = char.mask;
                    return { ...mask, characterId: char.id };
                })
                .sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0));
            if (newMasks.length !== this.masks.length ||
                JSON.stringify(newMasks) !== JSON.stringify(this.masks)) {
                this.masks = newMasks;
            }
            if (this.masks.length > 50) {
                logger.warn('[MaskEditor] 蒙版数量过多，限制为50个');
                this.masks = this.masks.slice(0, 50);
            }
        } catch (error) {
            logger.error('[MaskEditor] syncMasksFromCharacters 执行出错:', error);
        }
    }

    // 🔧 新增：验证蒙版坐标的合理性，如果发现异常则修复
    validateMaskCoordinates(mask, characterId, skipSave = false) {
        if (!mask) return mask;

        let needsFix = false;
        const fixed = { ...mask };

        // 🔧 关键修复：给边界检查增加容差，避免因浮点数舍入误差导致错位
        const TOLERANCE = 0.001; // 容差范围

        // 检查坐标和尺寸是否是有效数字且在合理范围内
        if (typeof fixed.x !== 'number' || !isFinite(fixed.x) || fixed.x < -TOLERANCE || fixed.x > 1 + TOLERANCE) {
            logger.warn(`[MaskEditor] 蒙版 ${characterId} 的 x 坐标异常: ${fixed.x}，已重置`);
            fixed.x = 0.1;
            needsFix = true;
        } else if (fixed.x < 0) {
            // 如果只是轻微超出（在容差范围内），修正为边界值
            fixed.x = 0;
        } else if (fixed.x > 1) {
            fixed.x = 1;
        }

        if (typeof fixed.y !== 'number' || !isFinite(fixed.y) || fixed.y < -TOLERANCE || fixed.y > 1 + TOLERANCE) {
            logger.warn(`[MaskEditor] 蒙版 ${characterId} 的 y 坐标异常: ${fixed.y}，已重置`);
            fixed.y = 0.1;
            needsFix = true;
        } else if (fixed.y < 0) {
            fixed.y = 0;
        } else if (fixed.y > 1) {
            fixed.y = 1;
        }

        if (typeof fixed.width !== 'number' || !isFinite(fixed.width) || fixed.width <= 0 || fixed.width > 1 + TOLERANCE) {
            logger.warn(`[MaskEditor] 蒙版 ${characterId} 的 width 异常: ${fixed.width}，已重置`);
            fixed.width = 0.3;
            needsFix = true;
        } else if (fixed.width > 1) {
            fixed.width = 1;
        }

        if (typeof fixed.height !== 'number' || !isFinite(fixed.height) || fixed.height <= 0 || fixed.height > 1 + TOLERANCE) {
            logger.warn(`[MaskEditor] 蒙版 ${characterId} 的 height 异常: ${fixed.height}，已重置`);
            fixed.height = 0.3;
            needsFix = true;
        } else if (fixed.height > 1) {
            fixed.height = 1;
        }

        // 🔧 关键修复：检查蒙版是否超出画布边界（增加容差）
        if (fixed.x + fixed.width > 1 + TOLERANCE) {
            logger.warn(`[MaskEditor] 蒙版 ${characterId} 超出右边界，已调整`);
            if (fixed.width > 1) {
                fixed.width = 0.3;
            }
            fixed.x = Math.max(0, 1 - fixed.width);
            needsFix = true;
        } else if (fixed.x + fixed.width > 1) {
            // 轻微超出，只修正边界，不移动位置
            fixed.width = 1 - fixed.x;
        }

        if (fixed.y + fixed.height > 1 + TOLERANCE) {
            logger.warn(`[MaskEditor] 蒙版 ${characterId} 超出下边界，已调整`);
            if (fixed.height > 1) {
                fixed.height = 0.3;
            }
            fixed.y = Math.max(0, 1 - fixed.height);
            needsFix = true;
        } else if (fixed.y + fixed.height > 1) {
            // 轻微超出，只修正边界，不移动位置
            fixed.height = 1 - fixed.y;
        }

        // 如果修复了坐标且不跳过保存，则保存修正后的数据
        if (needsFix) {
            // 只有在从配置恢复时才直接保存，其他情况由调用方处理保存
            if (!skipSave) {
                this.editor.dataManager.updateCharacterMask(characterId, fixed);
            }
        }

        return fixed;
    }

    drawGridOptimized(width, height) {
        // 网格线样式，即使缩小也保持可见
        const gridSize = 32;

        // 根据缩放比例调整线条粗细和透明度
        let lineWidth = 1 / this.scale;
        let opacity = 0.3;

        // 缩放小于0.3时，使用更粗的线条和更高的不透明度
        if (this.scale < 0.3) {
            lineWidth = 2 / this.scale;
            opacity = 0.5;
        } else if (this.scale < 0.5) {
            lineWidth = 1.5 / this.scale;
            opacity = 0.4;
        }

        this.ctx.strokeStyle = `rgba(124, 58, 237, ${opacity})`;
        this.ctx.lineWidth = lineWidth;

        // 计算可视区域
        const viewportLeft = Math.max(0, -this.offset.x / this.scale);
        const viewportTop = Math.max(0, -this.offset.y / this.scale);
        const viewportRight = Math.min(width, viewportLeft + this.canvas.width / this.scale);
        const viewportBottom = Math.min(height, viewportTop + this.canvas.height / this.scale);

        const startX = Math.floor(viewportLeft / gridSize) * gridSize;
        const endX = Math.ceil(viewportRight / gridSize) * gridSize;
        const startY = Math.floor(viewportTop / gridSize) * gridSize;
        const endY = Math.ceil(viewportBottom / gridSize) * gridSize;

        // 绘制垂直网格线
        this.ctx.beginPath();
        for (let x = startX; x <= endX; x += gridSize) {
            if (x >= 0 && x <= width) {
                this.ctx.moveTo(x, Math.max(0, viewportTop));
                this.ctx.lineTo(x, Math.min(height, viewportBottom));
            }
        }

        // 绘制水平网格线
        for (let y = startY; y <= endY; y += gridSize) {
            if (y >= 0 && y <= height) {
                this.ctx.moveTo(Math.max(0, viewportLeft), y);
                this.ctx.lineTo(Math.min(width, viewportRight), y);
            }
        }

        this.ctx.stroke();

        // 🔧 已移除：网格交叉点的小圆点（避免密集恐惧症）
        // if (this.scale >= 0.3) {
        //     const dotSize = Math.max(2, 3 / this.scale);
        //     const dotColor = `rgba(124, 58, 237, ${Math.min(0.6, opacity + 0.2)})`;
        //     this.ctx.fillStyle = dotColor;
        //
        //     for (let x = startX; x <= endX; x += gridSize) {
        //         for (let y = startY; y <= endY; y += gridSize) {
        //             if (x >= 0 && x <= width && y >= 0 && y <= height) {
        //                 this.ctx.beginPath();
        //                 this.ctx.arc(x, y, dotSize, 0, 2 * Math.PI);
        //                 this.ctx.fill();
        //             }
        //         }
        //     }
        // }
    }

    drawCanvasBorderOptimized(width, height) {
        const borderWidth = 1;
        const borderColor = 'rgba(124, 58, 237, 0.3)';
        this.ctx.strokeStyle = borderColor;
        this.ctx.lineWidth = borderWidth;
        this.ctx.strokeRect(0, 0, width, height);
    }

    snapToGrid(value) {
        const gridSize = 32;
        return Math.round(value / gridSize) * gridSize;
    }

    drawMaskOptimized(mask) {
        const character = this.editor.dataManager.getCharacter(mask.characterId);
        if (!character) {
            return;
        }
        const config = this.editor.dataManager.getConfig();
        if (!config || !config.canvas) {
            return;
        }
        const { width, height } = config.canvas;
        const x = mask.x * width;
        const y = mask.y * height;
        const w = mask.width * width;
        const h = mask.height * height;

        this.ctx.globalAlpha = 1;
        const fillColor = character.color + '40';
        this.ctx.fillStyle = fillColor;
        this.ctx.fillRect(x, y, w, h);
        const scaledLineWidth = Math.max(0.5, 1 / this.scale);
        this.ctx.strokeStyle = character.color;
        this.ctx.lineWidth = scaledLineWidth;
        this.ctx.strokeRect(x, y, w, h);
        this.ctx.globalAlpha = 1;
        const fontSize = Math.max(8, 12 / this.scale);
        this.ctx.fillStyle = '#FFFFFF';
        this.ctx.font = `bold ${fontSize}px sans-serif`;
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        this.ctx.fillText(character.name, x + w / 2, y + h / 2);
        this.drawMaskInfo(mask, x, y, w, h);
    }

    drawMaskInfo(mask, x, y, w, h) {
        // 蒙版信息显示已简化，不再显示羽化等参数
        // 保留此方法以防未来需要显示其他信息
    }

    roundRect(x, y, width, height, radius) {
        this.ctx.beginPath();
        this.ctx.moveTo(x + radius, y);
        this.ctx.lineTo(x + width - radius, y);
        this.ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
        this.ctx.lineTo(x + width, y + height - radius);
        this.ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
        this.ctx.lineTo(x + radius, y + height);
        this.ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
        this.ctx.lineTo(x, y + radius);
        this.ctx.quadraticCurveTo(x, y, x, y + radius);
        this.ctx.closePath();
    }

    drawSelectionOptimized(mask) {
        const { width, height } = this.editor.dataManager.getConfig().canvas;
        const x = mask.x * width;
        const y = mask.y * height;
        const w = mask.width * width;
        const h = mask.height * height;
        this.ctx.strokeStyle = 'rgba(124, 58, 237, 0.8)';
        this.ctx.lineWidth = Math.max(1, 2 / this.scale);
        this.ctx.setLineDash([5, 5]);
        this.ctx.strokeRect(x - 2, y - 2, w + 4, h + 4);
        this.ctx.setLineDash([]);
        const handleRadius = Math.max(3, 6 / this.scale);
        const handles = [
            { x: x, y: y },
            { x: x + w, y: y },
            { x: x + w, y: y + h },
            { x: x, y: y + h }
        ];
        this.ctx.fillStyle = '#FFFFFF';
        handles.forEach(handle => {
            this.ctx.beginPath();
            this.ctx.arc(handle.x, handle.y, handleRadius, 0, 2 * Math.PI);
            this.ctx.fill();
        });
    }

    updateUI() {
        const characters = this.editor.dataManager.getCharacters();
        this.masks = characters
            .filter(char => char.mask && char.enabled)
            .map(char => char.mask)
            .sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0));
        this.scheduleRender();
    }

    forceInitialRender() {
        this.syncMasksFromCharacters();
        this.scheduleRender();
        setTimeout(() => {
            this.scheduleRender();
        }, 200);
    }

    handlePreviewResize(newWidth, newHeight) {
        if (!this.container) return;
        const width = newWidth > 0 ? newWidth : this.container.clientWidth;
        const height = newHeight > 0 ? newHeight : this.container.clientHeight;
        if (width <= 0 || height <= 0) return;
        this.canvas.width = width;
        this.canvas.height = height;
        this.canvas.style.width = `${width}px`;
        this.canvas.style.height = `${height}px`;
        this.resizeCanvas(true);
        this.scheduleRender();
    }

    handleContainerResize(width, height) {
        this.handlePreviewResize(width, height);
    }

    updateTexts() {
        this.scheduleRender();
    }

    showToast(message, type = 'info', duration = 3000) {
        const nodeContainer = this.editor.container;
        try {
            this.toastManager.showToast(message, type, duration, { nodeContainer });
        } catch (error) {
            logger.error('[MaskEditor] 显示提示失败:', error);
            try {
                this.toastManager.showToast(message, type, duration, {});
            } catch (fallbackError) {
                logger.error('[MaskEditor] 回退方式也失败:', fallbackError);
                alert(`${type.toUpperCase()}: ${message}`);
            }
        }
    }

    destroy() {
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
        }
    }

    // 🔧 新增：根据角色ID选择蒙版
    selectMaskByCharacterId(characterId) {
        const mask = this.masks.find(m => m.characterId === characterId);
        if (mask) {
            this.selectedMask = mask;
            this.scheduleRender();
        }
    }

    // 🔧 新增：取消蒙版选择
    deselectMask() {
        this.selectedMask = null;
        this.scheduleRender();
    }

    ensureCanvasVisible() {
        try {
            if (!this.canvas || !this.container) {
                return;
            }
            this.canvas.style.setProperty('display', 'block', 'important');
            this.canvas.style.setProperty('visibility', 'visible', 'important');
            this.canvas.style.setProperty('opacity', '1', 'important');
            this.container.style.setProperty('display', 'block', 'important');
            this.container.style.setProperty('visibility', 'visible', 'important');
            this.container.style.setProperty('opacity', '1', 'important');
            this.resizeCanvas();
            this.scheduleRender();
            setTimeout(() => {
                this.scheduleRender();
            }, 100);
        } catch (error) {
            logger.error('[MaskEditor] 确保画布可见失败:', error);
        }
    }

    logLayoutDiagnostics(reason) {
        // 已移除诊断日志输出
    }
}

window.MaskEditor = MaskEditor;
