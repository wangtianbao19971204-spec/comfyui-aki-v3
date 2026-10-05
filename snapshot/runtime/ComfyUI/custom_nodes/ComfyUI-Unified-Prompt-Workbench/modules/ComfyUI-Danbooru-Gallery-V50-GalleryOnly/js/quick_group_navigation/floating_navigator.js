/**
 * 快速组导航器 - 悬浮球和面板UI组件
 * Quick Group Navigation - Floating Ball and Panel UI Component
 *
 * @author 哈雷酱 (大小姐工程师)
 * @version 1.0.0
 */

import { app } from "../../../scripts/app.js";
import { globalToastManager } from "../global/toast_manager.js";

import { createLogger } from '../global/logger_client.js';

// 创建logger实例
const logger = createLogger('floating_navigator');

// 面板尺寸配置常量
const PANEL_SIZE_CONFIG = {
    DEFAULT_WIDTH: 420,
    DEFAULT_HEIGHT: 600,
    MIN_WIDTH: 300,
    MIN_HEIGHT: 280,
    MAX_WIDTH: 800,
    MAX_HEIGHT_RATIO: 0.9
};

/**
 * 悬浮球导航器类
 * 负责悬浮球的创建、拖拽、面板展开等UI交互
 */
export class FloatingNavigator {
    constructor(manager) {
        this.manager = manager;  // QuickGroupNavigationManager实例

        // DOM元素
        this.ballElement = null;
        this.panelElement = null;
        this.contextMenuElement = null;  // 右键菜单元素
        this.tooltipElement = null;  // 快捷键预览 tooltip

        // 状态
        this.isExpanded = false;
        this.isDragging = false;
        this.hasDragged = false;  // 是否真的发生了拖拽（移动距离超过阈值）
        this.dragStartX = 0;
        this.dragStartY = 0;
        this.mouseDownX = 0;  // 鼠标按下时的位置
        this.mouseDownY = 0;

        // 位置（默认右下角）
        this.position = this.loadPosition();

        // 面板尺寸相关
        this.panelSize = this.loadPanelSize();
        this.isResizing = false;
        this.resizeStartX = 0;
        this.resizeStartY = 0;
        this.resizeStartWidth = 0;
        this.resizeStartHeight = 0;

        // Tooltip 相关
        this.tooltipTimeout = null;

        // 初始化
        this.init();
    }

    /**
     * 初始化悬浮球和面板
     */
    init() {
        this.createBall();
        this.createPanel();
        this.createTooltip();
        this.setupEventListeners();

        // 每次进入工作流时，确保面板是折叠状态
        this.collapsePanel();

        logger.info('[QGN] 悬浮球导航器初始化完成');
    }

    /**
     * 创建悬浮球DOM
     */
    createBall() {
        this.ballElement = document.createElement('div');
        this.ballElement.className = 'qgn-floating-ball';
        this.ballElement.innerHTML = '🧭';  // 指南针图标
        this.ballElement.title = '快速组导航器\n点击展开，拖拽移动';

        // 设置初始位置
        this.updateBallPosition();

        // 添加到body
        document.body.appendChild(this.ballElement);
    }

    /**
     * 创建导航面板DOM
     */
    createPanel() {
        this.panelElement = document.createElement('div');
        this.panelElement.className = 'qgn-panel';
        this.panelElement.style.display = 'none';

        this.panelElement.innerHTML = `
            <div class="qgn-panel-header">
                <span class="qgn-panel-title">快速组导航器</span>
                <div class="qgn-panel-controls">
                    <button class="qgn-lock-button" title="双击锁定/解锁（锁定后禁止编辑）">🔓</button>
                    <button class="qgn-close-button" title="关闭面板">×</button>
                </div>
            </div>

            <div class="qgn-search-container">
                <input type="text"
                       class="qgn-search-input"
                       placeholder="🔍 搜索组名..."
                       autocomplete="off">
            </div>

            <div class="qgn-groups-list-container">
                <div class="qgn-groups-list">
                    <!-- 组列表将在这里动态渲染 -->
                </div>
            </div>

            <div class="qgn-panel-footer">
                <button class="qgn-add-group-button">+ 添加导航组</button>
            </div>

            <div class="qgn-resize-handle" title="拖拽调整面板大小"></div>
        `;

        // 添加到body
        document.body.appendChild(this.panelElement);

        // 获取内部元素的引用（方便后续操作）
        this.lockButton = this.panelElement.querySelector('.qgn-lock-button');
        this.closeButton = this.panelElement.querySelector('.qgn-close-button');
        this.searchInput = this.panelElement.querySelector('.qgn-search-input');
        this.groupsList = this.panelElement.querySelector('.qgn-groups-list');
        this.addGroupButton = this.panelElement.querySelector('.qgn-add-group-button');
        this.resizeHandle = this.panelElement.querySelector('.qgn-resize-handle');

        // 应用保存的面板尺寸
        this.applyPanelSize();
    }

    /**
     * 设置事件监听器
     */
    setupEventListeners() {
        // 悬浮球点击 - 只展开面板，不关闭（避免拖拽时误触）
        this.ballElement.addEventListener('click', (e) => {
            // 如果刚刚拖拽过，不展开面板
            if (!this.hasDragged && !this.isExpanded) {
                this.expandPanel();
            }
        });

        // 悬浮球右键菜单
        this.ballElement.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            this.showContextMenu(e.clientX, e.clientY);
        });

        // 悬浮球拖拽
        this.ballElement.addEventListener('mousedown', (e) => {
            this.startDrag(e);
        });

        // 悬浮球 hover 显示快捷键预览 tooltip
        this.ballElement.addEventListener('mouseenter', () => {
            // 如果面板已展开，不显示 tooltip
            if (this.isExpanded) return;

            // 延迟 300ms 显示
            this.tooltipTimeout = setTimeout(() => {
                this.showTooltip();
            }, 300);
        });

        this.ballElement.addEventListener('mouseleave', () => {
            clearTimeout(this.tooltipTimeout);
            this.hideTooltip();
        });

        // 关闭按钮
        this.closeButton.addEventListener('click', () => {
            this.collapsePanel();
        });

        // 锁定按钮（双击切换）
        this.lockButton.addEventListener('dblclick', () => {
            this.manager.toggleLock();
            this.updateLockButton();
        });

        // 搜索框输入（防抖）
        let searchTimeout;
        this.searchInput.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this.filterGroups(e.target.value);
            }, 300);
        });

        // 添加组按钮
        this.addGroupButton.addEventListener('click', () => {
            this.showAddGroupDialog();
        });

        // Resize handle 拖拽事件
        this.resizeHandle.addEventListener('mousedown', (e) => {
            this.startResize(e);
        });

        // 全局拖拽事件
        document.addEventListener('mousemove', (e) => {
            if (this.isDragging) {
                this.onDrag(e);
            }
            if (this.isResizing) {
                this.onResize(e);
            }
        });

        document.addEventListener('mouseup', (e) => {
            if (this.isDragging) {
                this.stopDrag(e);
            }
            if (this.isResizing) {
                this.stopResize(e);
            }
        });

        // 监听窗口大小变化,确保悬浮球始终在可见范围内
        window.addEventListener('resize', () => {
            const ballSize = 60;
            const maxX = window.innerWidth - ballSize;
            const maxY = window.innerHeight - ballSize;

            // 如果悬浮球超出屏幕,自动调整位置
            let needsUpdate = false;
            if (this.position.x > maxX) {
                this.position.x = maxX;
                needsUpdate = true;
            }
            if (this.position.y > maxY) {
                this.position.y = maxY;
                needsUpdate = true;
            }

            // 更新位置并保存
            if (needsUpdate) {
                this.updateBallPosition();
                this.savePosition();

                // 如果面板展开,也更新面板位置
                if (this.isExpanded) {
                    this.updatePanelPosition();
                }
            }

            // 约束面板尺寸
            this.constrainPanelSize();
        });
    }

    /**
     * 开始拖拽
     */
    startDrag(e) {
        this.isDragging = true;
        this.hasDragged = false;  // 重置拖拽标志
        this.dragStartX = e.clientX - this.position.x;
        this.dragStartY = e.clientY - this.position.y;
        this.mouseDownX = e.clientX;  // 记录鼠标按下位置
        this.mouseDownY = e.clientY;

        this.ballElement.style.cursor = 'grabbing';
        e.preventDefault();
    }

    /**
     * 拖拽中
     */
    onDrag(e) {
        if (!this.isDragging) return;

        // 检测是否真的发生了拖拽（移动距离超过5px）
        const dx = e.clientX - this.mouseDownX;
        const dy = e.clientY - this.mouseDownY;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance > 5) {
            this.hasDragged = true;  // 标记为真正的拖拽
        }

        // 计算新位置
        let newX = e.clientX - this.dragStartX;
        let newY = e.clientY - this.dragStartY;

        // 边界检测
        const ballSize = 60;
        const maxX = window.innerWidth - ballSize;
        const maxY = window.innerHeight - ballSize;

        newX = Math.max(0, Math.min(newX, maxX));
        newY = Math.max(0, Math.min(newY, maxY));

        this.position = { x: newX, y: newY };
        this.updateBallPosition();

        // 如果面板展开，更新面板位置
        if (this.isExpanded) {
            this.updatePanelPosition();
        }
    }

    /**
     * 停止拖拽
     */
    stopDrag(e) {
        if (!this.isDragging) return;

        this.isDragging = false;
        this.ballElement.style.cursor = 'move';

        // 保存位置
        this.savePosition();

        // 延迟重置hasDragged标志，确保click事件能检测到
        // （click事件在mouseup之后触发）
        setTimeout(() => {
            this.hasDragged = false;
        }, 100);
    }

    /**
     * 更新悬浮球位置
     */
    updateBallPosition() {
        // 使用 transform 代替 top/left 以获得更好的性能
        this.ballElement.style.transform = `translate(${this.position.x}px, ${this.position.y}px)`;
    }

    /**
     * 切换面板展开/收起
     */
    togglePanel() {
        if (this.isExpanded) {
            this.collapsePanel();
        } else {
            this.expandPanel();
        }
    }

    /**
     * 展开面板
     */
    expandPanel() {
        this.isExpanded = true;
        this.panelElement.style.display = 'flex';  // 使用 flex 而不是 block
        this.updatePanelPosition();

        // 隐藏快捷键预览 tooltip
        clearTimeout(this.tooltipTimeout);
        this.hideTooltip();

        // 更新组列表
        this.renderGroupsList();

        // 动画效果
        requestAnimationFrame(() => {
            this.panelElement.classList.add('qgn-panel-visible');
            // 强制更新列表容器高度
            this.updateListContainerHeight();
        });
    }

    /**
     * 更新列表容器高度（确保滚动条正常工作）
     */
    updateListContainerHeight() {
        const listContainer = this.panelElement.querySelector('.qgn-groups-list-container');
        if (!listContainer) return;

        const panelHeight = this.panelElement.offsetHeight;
        const header = this.panelElement.querySelector('.qgn-panel-header');
        const search = this.panelElement.querySelector('.qgn-search-container');
        const footer = this.panelElement.querySelector('.qgn-panel-footer');

        const headerHeight = header ? header.offsetHeight : 0;
        const searchHeight = search ? search.offsetHeight : 0;
        const footerHeight = footer ? footer.offsetHeight : 0;

        const availableHeight = panelHeight - headerHeight - searchHeight - footerHeight;
        listContainer.style.height = `${Math.max(100, availableHeight)}px`;
        listContainer.style.maxHeight = `${Math.max(100, availableHeight)}px`;
    }

    /**
     * 收起面板
     */
    collapsePanel() {
        this.isExpanded = false;
        this.panelElement.classList.remove('qgn-panel-visible');

        // 等待动画完成后隐藏
        setTimeout(() => {
            if (!this.isExpanded) {
                this.panelElement.style.display = 'none';
            }
        }, 200);

        // 清空搜索
        this.searchInput.value = '';
    }

    /**
     * 更新面板位置（相对于悬浮球）
     * 智能计算位置，确保面板不会超出屏幕边界
     */
    updatePanelPosition() {
        const ballSize = 60;
        // 使用实际面板尺寸（动态获取或使用保存的值）
        const panelWidth = this.panelSize?.width || PANEL_SIZE_CONFIG.DEFAULT_WIDTH;
        const panelHeight = this.panelSize?.height || PANEL_SIZE_CONFIG.DEFAULT_HEIGHT;
        const gap = 10;
        const edgeMargin = 20;  // 距离屏幕边缘的最小间距

        // ========== 水平方向位置计算 ==========
        // 判断应该显示在左侧还是右侧
        const shouldShowOnLeft = (this.position.x + ballSize + gap + panelWidth) > window.innerWidth;

        let panelLeft;
        if (shouldShowOnLeft) {
            // 显示在左侧
            panelLeft = this.position.x - panelWidth - gap;
            // 确保不超出左边界
            if (panelLeft < edgeMargin) {
                panelLeft = edgeMargin;
            }
        } else {
            // 显示在右侧
            panelLeft = this.position.x + ballSize + gap;
            // 确保不超出右边界
            if (panelLeft + panelWidth > window.innerWidth - edgeMargin) {
                panelLeft = window.innerWidth - panelWidth - edgeMargin;
            }
        }

        // ========== 垂直方向位置计算 ==========
        let panelTop = this.position.y;

        // 检测面板是否会超出底部
        const wouldExceedBottom = (this.position.y + panelHeight) > (window.innerHeight - edgeMargin);

        if (wouldExceedBottom) {
            // 面板会超出底部，尝试向上对齐悬浮球底部
            panelTop = this.position.y + ballSize - panelHeight;

            // 确保不超出顶部
            if (panelTop < edgeMargin) {
                panelTop = edgeMargin;
            }
        }

        // 应用计算后的位置
        this.panelElement.style.left = `${panelLeft}px`;
        this.panelElement.style.top = `${panelTop}px`;
    }

    /**
     * 渲染组列表
     */
    renderGroupsList() {
        const groups = this.manager.getNavigationGroups();
        const locked = this.manager.isLocked();

        // 清空列表
        this.groupsList.innerHTML = '';

        if (groups.length === 0) {
            // 空状态提示
            const emptyState = document.createElement('div');
            emptyState.className = 'qgn-empty-state';
            emptyState.innerHTML = `
                <div class="qgn-empty-icon">📭</div>
                <div class="qgn-empty-text">还没有添加任何导航组</div>
                <div class="qgn-empty-hint">点击下方按钮添加常用的组</div>
            `;
            this.groupsList.appendChild(emptyState);
            return;
        }

        // 渲染每个组
        groups.forEach((group, index) => {
            const groupItem = this.createGroupItem(group, index, locked);
            this.groupsList.appendChild(groupItem);
        });
    }

    /**
     * 创建组条目DOM
     */
    createGroupItem(group, index, locked) {
        const item = document.createElement('div');
        item.className = 'qgn-group-item';
        item.dataset.groupId = group.id;

        // 获取组颜色
        const groupColor = this.getGroupColor(group.groupName);

        const zoomScale = group.zoomScale ?? 100;
        item.innerHTML = `
            <div class="qgn-group-color" style="background-color: ${groupColor}"></div>
            <div class="qgn-group-info">
                <div class="qgn-group-name">${this.escapeHtml(group.groupName)}</div>
                <div class="qgn-group-shortcut">
                    ${group.shortcutKey ? `快捷键: ${group.shortcutKey}` : '未设置快捷键'}
                </div>
            </div>
            <div class="qgn-group-actions">
                <button class="qgn-set-shortcut-button" title="设置快捷键" ${locked ? 'disabled' : ''}>⚡</button>
                <div class="qgn-zoom-control" title="跳转后缩放幅度">
                    <button class="qgn-zoom-btn qgn-zoom-minus" ${locked ? 'disabled' : ''}>−</button>
                    <input type="number" class="qgn-zoom-input" value="${zoomScale}"
                           min="10" max="500" step="10" ${locked ? 'disabled' : ''}>
                    <span class="qgn-zoom-unit">%</span>
                    <button class="qgn-zoom-btn qgn-zoom-plus" ${locked ? 'disabled' : ''}>+</button>
                </div>
                <button class="qgn-navigate-button" title="导航到此组">➤</button>
                ${!locked ? '<button class="qgn-remove-group-button" title="移除">×</button>' : ''}
            </div>
        `;

        // 绑定事件
        const setShortcutButton = item.querySelector('.qgn-set-shortcut-button');
        const navigateButton = item.querySelector('.qgn-navigate-button');
        const removeButton = item.querySelector('.qgn-remove-group-button');

        // 缩放控件事件
        const zoomInput = item.querySelector('.qgn-zoom-input');
        const zoomMinus = item.querySelector('.qgn-zoom-minus');
        const zoomPlus = item.querySelector('.qgn-zoom-plus');

        const updateZoom = (value) => {
            const newValue = Math.max(10, Math.min(500, value));
            zoomInput.value = newValue;
            this.manager.updateGroupZoomScale(group.id, newValue);
        };

        zoomInput?.addEventListener('change', (e) => {
            updateZoom(parseInt(e.target.value) || 100);
        });

        zoomMinus?.addEventListener('click', () => {
            updateZoom((parseInt(zoomInput.value) || 100) - 10);
        });

        zoomPlus?.addEventListener('click', () => {
            updateZoom((parseInt(zoomInput.value) || 100) + 10);
        });

        setShortcutButton?.addEventListener('click', () => {
            this.showShortcutRecorder(group);
        });

        navigateButton.addEventListener('click', () => {
            this.manager.navigateToGroup(group.groupName);
        });

        removeButton?.addEventListener('click', () => {
            this.manager.removeNavigationGroup(group.id);
            this.renderGroupsList();
        });

        return item;
    }

    /**
     * 获取工作流中组的颜色
     */
    getGroupColor(groupName) {
        if (!app.graph || !app.graph._groups) return '#888';

        const group = app.graph._groups.find(g => g.title === groupName);
        if (group && group.color) {
            return group.color;
        }

        return '#888';  // 默认灰色
    }

    /**
     * 显示添加组对话框
     */
    showAddGroupDialog() {
        // 获取工作流中所有组
        const allGroups = this.getAllWorkflowGroups();
        const existingGroupNames = this.manager.getNavigationGroups().map(g => g.groupName);

        // 过滤掉已添加的组
        const availableGroups = allGroups.filter(g => !existingGroupNames.includes(g.title));

        if (availableGroups.length === 0) {
            this.showNotification('所有组都已添加到导航列表', 'info');
            return;
        }

        // 创建下拉选择对话框
        const dialog = document.createElement('div');
        dialog.className = 'qgn-dialog-overlay';
        dialog.innerHTML = `
            <div class="qgn-dialog">
                <div class="qgn-dialog-header">
                    <span class="qgn-dialog-title">选择要添加的组</span>
                    <button class="qgn-dialog-close">×</button>
                </div>
                <div class="qgn-dialog-body">
                    <input type="text"
                           class="qgn-dialog-search"
                           placeholder="搜索组名..."
                           autocomplete="off">
                    <div class="qgn-dialog-groups-list">
                        ${availableGroups.map(g => `
                            <div class="qgn-dialog-group-item" data-group-name="${this.escapeHtml(g.title)}">
                                <div class="qgn-group-color" style="background-color: ${g.color || '#888'}"></div>
                                <span>${this.escapeHtml(g.title)}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(dialog);

        // 对话框事件
        const closeDialog = () => {
            dialog.remove();
        };

        dialog.querySelector('.qgn-dialog-close').addEventListener('click', closeDialog);
        dialog.addEventListener('click', (e) => {
            if (e.target === dialog) closeDialog();
        });

        // 搜索功能
        const searchInput = dialog.querySelector('.qgn-dialog-search');
        searchInput.addEventListener('input', (e) => {
            const searchTerm = e.target.value.toLowerCase();
            const items = dialog.querySelectorAll('.qgn-dialog-group-item');

            items.forEach(item => {
                const groupName = item.dataset.groupName.toLowerCase();
                item.style.display = groupName.includes(searchTerm) ? 'flex' : 'none';
            });
        });

        // 选择组
        dialog.querySelectorAll('.qgn-dialog-group-item').forEach(item => {
            item.addEventListener('click', () => {
                const groupName = item.dataset.groupName;
                this.manager.addNavigationGroup(groupName);
                this.renderGroupsList();
                closeDialog();
                this.showNotification(`已添加组: ${groupName}`, 'success');
            });
        });

        // 聚焦搜索框
        searchInput.focus();
    }

    /**
     * 显示快捷键录制器
     */
    showShortcutRecorder(group) {
        const recorder = document.createElement('div');
        recorder.className = 'qgn-shortcut-recorder-overlay';
        recorder.innerHTML = `
            <div class="qgn-shortcut-recorder">
                <div class="qgn-recorder-icon">⌨️</div>
                <div class="qgn-recorder-title">设置快捷键</div>
                <div class="qgn-recorder-group">${this.escapeHtml(group.groupName)}</div>
                <div class="qgn-recorder-hint">请按下你想要的快捷键...</div>
                <div class="qgn-recorder-current">${group.shortcutKey || '未设置'}</div>
                <button class="qgn-recorder-cancel">取消</button>
            </div>
        `;

        document.body.appendChild(recorder);

        // 取消按钮
        const cancelButton = recorder.querySelector('.qgn-recorder-cancel');
        const closeRecorder = () => {
            recorder.remove();
            document.removeEventListener('keydown', keyHandler);
        };

        cancelButton.addEventListener('click', closeRecorder);
        recorder.addEventListener('click', (e) => {
            if (e.target === recorder) closeRecorder();
        });

        // 监听按键
        const keyHandler = (e) => {
            e.preventDefault();
            e.stopPropagation();

            // 忽略Shift、Ctrl、Alt等修饰键单独按下
            if (['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) {
                return;
            }

            // 转换按键为大写（统一格式）
            const key = e.key.toUpperCase();

            // 检查冲突
            const conflict = this.manager.checkShortcutConflict(key, group.id);
            if (conflict) {
                this.showNotification(`快捷键 "${key}" 已被 "${conflict}" 使用`, 'warning');
                closeRecorder();
                return;
            }

            // 设置快捷键
            this.manager.setShortcut(group.id, key);
            this.renderGroupsList();
            this.showNotification(`已设置快捷键: ${key}`, 'success');
            closeRecorder();
        };

        document.addEventListener('keydown', keyHandler);
    }

    /**
     * 过滤组列表
     */
    filterGroups(searchTerm) {
        const items = this.groupsList.querySelectorAll('.qgn-group-item');
        const term = searchTerm.toLowerCase();

        items.forEach(item => {
            const groupName = item.querySelector('.qgn-group-name').textContent.toLowerCase();
            item.style.display = groupName.includes(term) ? 'flex' : 'none';
        });
    }

    /**
     * 更新锁定按钮状态
     */
    updateLockButton() {
        const locked = this.manager.isLocked();
        this.lockButton.textContent = locked ? '🔒' : '🔓';
        this.lockButton.title = locked ?
            '双击解锁（当前已锁定）' :
            '双击锁定（锁定后禁止编辑）';

        // 更新添加按钮状态
        this.addGroupButton.disabled = locked;

        // 重新渲染列表（更新编辑按钮状态）
        this.renderGroupsList();
    }

    /**
     * 获取所有工作流组
     */
    getAllWorkflowGroups() {
        if (!app.graph) {
            logger.warn('[QGN] app.graph 不存在');
            return [];
        }
        if (!app.graph._groups) {
            logger.warn('[QGN] app.graph._groups 不存在');
            return [];
        }
        const groups = app.graph._groups.filter(g => g && g.title);
        logger.info(`[QGN] 找到 ${groups.length} 个工作流组`);
        return groups;
    }

    /**
     * 显示通知 - 使用全局 Toast 管理器
     */
    showNotification(message, type = 'info') {
        globalToastManager.showToast(message, type, 3000);
    }

    /**
     * HTML转义（防止XSS）
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * 保存悬浮球位置到localStorage
     */
    savePosition() {
        try {
            localStorage.setItem('qgn_floating_ball_position', JSON.stringify(this.position));
        } catch (e) {
            logger.warn('[QGN] 保存位置失败:', e);
        }
    }

    /**
     * 从localStorage加载悬浮球位置
     * 增加边界检查,确保悬浮球永远在屏幕可见范围内
     */
    loadPosition() {
        const ballSize = 60;  // 悬浮球大小
        const defaultPadding = 20;  // 默认边距

        let position = null;

        try {
            const saved = localStorage.getItem('qgn_floating_ball_position');
            if (saved) {
                position = JSON.parse(saved);
            }
        } catch (e) {
            logger.warn('[QGN] 加载位置失败:', e);
        }

        // 如果没有保存的位置,使用默认位置
        if (!position) {
            position = {
                x: window.innerWidth - ballSize - defaultPadding,
                y: window.innerHeight - ballSize - 90
            };
        }

        // 边界检查和修正（关键修复:防止悬浮球跑到屏幕外）
        const maxX = window.innerWidth - ballSize;
        const maxY = window.innerHeight - ballSize;

        position.x = Math.max(0, Math.min(position.x, maxX));
        position.y = Math.max(0, Math.min(position.y, maxY));

        return position;
    }

    /**
     * 显示右键菜单
     */
    showContextMenu(x, y) {
        // 删除旧的菜单（如果存在）
        this.removeContextMenu();

        // 创建菜单元素
        const menu = document.createElement('div');
        menu.className = 'qgn-context-menu';
        menu.innerHTML = `
            <div class="qgn-context-menu-item" data-action="hide">
                <span class="qgn-context-menu-icon">🙈</span>
                <span>隐藏悬浮球</span>
            </div>
        `;

        // 计算菜单位置（智能边界检测）
        const menuWidth = 180;
        const menuHeight = 40;
        const padding = 10;

        let menuX = x;
        let menuY = y;

        // 右侧边界检测
        if (menuX + menuWidth > window.innerWidth - padding) {
            menuX = window.innerWidth - menuWidth - padding;
        }

        // 底部边界检测
        if (menuY + menuHeight > window.innerHeight - padding) {
            menuY = window.innerHeight - menuHeight - padding;
        }

        menu.style.left = `${menuX}px`;
        menu.style.top = `${menuY}px`;

        // 添加到页面
        document.body.appendChild(menu);
        this.contextMenuElement = menu;

        // 显示动画
        requestAnimationFrame(() => {
            menu.classList.add('qgn-context-menu-visible');
        });

        // 点击菜单项
        const hideItem = menu.querySelector('[data-action="hide"]');
        hideItem.addEventListener('click', () => {
            this.hideFloatingBall();
        });

        // 点击外部关闭菜单
        const closeMenu = (e) => {
            if (!menu.contains(e.target)) {
                this.removeContextMenu();
                document.removeEventListener('click', closeMenu);
            }
        };
        setTimeout(() => {
            document.addEventListener('click', closeMenu);
        }, 100);

        logger.info('[QGN] 右键菜单已显示');
    }

    /**
     * 移除右键菜单
     */
    removeContextMenu() {
        if (this.contextMenuElement) {
            this.contextMenuElement.remove();
            this.contextMenuElement = null;
        }
    }

    /**
     * 隐藏悬浮球
     */
    async hideFloatingBall() {
        this.removeContextMenu();

        // 显示确认对话框
        const confirmMessage = `确定要隐藏快速组导航器悬浮球吗？

隐藏后，您可以通过以下方式重新开启：
1. 打开插件目录下的 config.json 文件
2. 添加或修改配置项：
   "quick_group_navigation": {
     "show_floating_ball": true
   }
3. 重新加载ComfyUI页面`;

        if (!confirm(confirmMessage)) {
            return;
        }

        logger.info('[QGN] 用户确认隐藏悬浮球');

        try {
            // 调用API保存配置
            const response = await fetch('/danbooru/config/update', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    path: 'quick_group_navigation.show_floating_ball',
                    value: false
                })
            });

            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    logger.info('[QGN] ✅ 配置已保存，隐藏悬浮球');

                    // 显示Toast提示
                    this.showNotification('悬浮球已隐藏，可通过 config.json 重新开启', 'info', 5000);

                    // 隐藏悬浮球和面板
                    this.ballElement.remove();
                    this.panelElement.remove();
                } else {
                    throw new Error(data.error || '配置保存失败');
                }
            } else {
                throw new Error(`HTTP错误: ${response.status}`);
            }
        } catch (error) {
            logger.error('[QGN] 保存配置失败:', error);
            this.showNotification('保存配置失败，请稍后重试', 'error');
        }
    }

    // ==================== Resize 相关方法 ====================

    /**
     * 开始调整面板大小
     */
    startResize(e) {
        e.preventDefault();
        e.stopPropagation();

        this.isResizing = true;
        this.resizeStartX = e.clientX;
        this.resizeStartY = e.clientY;
        this.resizeStartWidth = this.panelElement.offsetWidth;
        this.resizeStartHeight = this.panelElement.offsetHeight;

        this.panelElement.classList.add('qgn-resizing');
        document.body.style.cursor = 'nwse-resize';
        document.body.style.userSelect = 'none';
    }

    /**
     * 调整面板大小中
     */
    onResize(e) {
        if (!this.isResizing) return;

        const dx = e.clientX - this.resizeStartX;
        const dy = e.clientY - this.resizeStartY;

        let newWidth = this.resizeStartWidth + dx;
        let newHeight = this.resizeStartHeight + dy;

        // 应用约束
        const maxHeight = window.innerHeight * PANEL_SIZE_CONFIG.MAX_HEIGHT_RATIO;

        newWidth = Math.max(PANEL_SIZE_CONFIG.MIN_WIDTH,
                   Math.min(newWidth, PANEL_SIZE_CONFIG.MAX_WIDTH));
        newHeight = Math.max(PANEL_SIZE_CONFIG.MIN_HEIGHT,
                    Math.min(newHeight, maxHeight));

        // 边界检查：确保面板不超出屏幕
        const panelRect = this.panelElement.getBoundingClientRect();
        const maxAllowedWidth = window.innerWidth - panelRect.left - 20;
        const maxAllowedHeight = window.innerHeight - panelRect.top - 20;

        newWidth = Math.min(newWidth, maxAllowedWidth);
        newHeight = Math.min(newHeight, maxAllowedHeight);

        // 应用尺寸
        this.panelElement.style.width = `${newWidth}px`;
        this.panelElement.style.height = `${newHeight}px`;

        // 实时更新列表容器高度
        this.updateListContainerHeight();
    }

    /**
     * 停止调整面板大小
     */
    stopResize(e) {
        if (!this.isResizing) return;

        this.isResizing = false;
        this.panelElement.classList.remove('qgn-resizing');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';

        // 保存新尺寸
        this.panelSize = {
            width: this.panelElement.offsetWidth,
            height: this.panelElement.offsetHeight
        };
        this.savePanelSize();

        // 更新列表容器高度
        this.updateListContainerHeight();

        logger.info(`[QGN] 面板尺寸已调整为 ${this.panelSize.width}x${this.panelSize.height}`);
    }

    /**
     * 应用面板尺寸
     */
    applyPanelSize() {
        if (this.panelSize) {
            this.panelElement.style.width = `${this.panelSize.width}px`;
            this.panelElement.style.height = `${this.panelSize.height}px`;
        }
    }

    /**
     * 约束面板尺寸（窗口大小变化时）
     */
    constrainPanelSize() {
        if (!this.panelSize) return;

        const maxHeight = window.innerHeight * PANEL_SIZE_CONFIG.MAX_HEIGHT_RATIO;
        let needsUpdate = false;

        if (this.panelSize.width > PANEL_SIZE_CONFIG.MAX_WIDTH) {
            this.panelSize.width = PANEL_SIZE_CONFIG.MAX_WIDTH;
            needsUpdate = true;
        }
        if (this.panelSize.height > maxHeight) {
            this.panelSize.height = Math.floor(maxHeight);
            needsUpdate = true;
        }

        if (needsUpdate) {
            this.applyPanelSize();
            this.savePanelSize();
        }
    }

    /**
     * 保存面板尺寸到 localStorage
     */
    savePanelSize() {
        try {
            localStorage.setItem('qgn_panel_size', JSON.stringify(this.panelSize));
        } catch (e) {
            logger.warn('[QGN] 保存面板尺寸失败:', e);
        }
    }

    /**
     * 从 localStorage 加载面板尺寸
     */
    loadPanelSize() {
        try {
            const saved = localStorage.getItem('qgn_panel_size');
            if (saved) {
                const size = JSON.parse(saved);
                // 验证有效性
                if (size.width >= PANEL_SIZE_CONFIG.MIN_WIDTH &&
                    size.height >= PANEL_SIZE_CONFIG.MIN_HEIGHT) {
                    return size;
                }
            }
        } catch (e) {
            logger.warn('[QGN] 加载面板尺寸失败:', e);
        }

        // 返回默认尺寸
        return {
            width: PANEL_SIZE_CONFIG.DEFAULT_WIDTH,
            height: PANEL_SIZE_CONFIG.DEFAULT_HEIGHT
        };
    }

    // ==================== Tooltip 相关方法 ====================

    /**
     * 创建快捷键预览 Tooltip
     */
    createTooltip() {
        this.tooltipElement = document.createElement('div');
        this.tooltipElement.className = 'qgn-shortcuts-tooltip';
        document.body.appendChild(this.tooltipElement);
    }

    /**
     * 显示快捷键预览 Tooltip
     */
    showTooltip() {
        // 获取有快捷键的组
        const groups = this.manager.getNavigationGroups()
            .filter(g => g.shortcutKey);

        // 渲染内容
        if (groups.length === 0) {
            this.tooltipElement.innerHTML = `
                <div class="qgn-tooltip-title">快捷键一览</div>
                <div class="qgn-tooltip-empty">暂无快捷键设置</div>
                <div class="qgn-tooltip-hint">点击展开设置快捷键</div>
            `;
        } else {
            this.tooltipElement.innerHTML = `
                <div class="qgn-tooltip-title">快捷键一览</div>
                ${groups.map(g => `
                    <div class="qgn-tooltip-item">
                        <span class="qgn-tooltip-key">${g.shortcutKey}</span>
                        <span class="qgn-tooltip-name">${this.escapeHtml(g.groupName)}</span>
                    </div>
                `).join('')}
                <div class="qgn-tooltip-hint">点击展开完整面板</div>
            `;
        }

        // 计算位置（在悬浮球旁边）
        this.updateTooltipPosition();

        // 显示
        this.tooltipElement.classList.add('qgn-tooltip-visible');
    }

    /**
     * 隐藏快捷键预览 Tooltip
     */
    hideTooltip() {
        if (this.tooltipElement) {
            this.tooltipElement.classList.remove('qgn-tooltip-visible');
        }
    }

    /**
     * 更新 Tooltip 位置
     */
    updateTooltipPosition() {
        const ballSize = 60;
        const gap = 10;

        // 先让 tooltip 可见但透明，以便获取其尺寸
        this.tooltipElement.style.visibility = 'hidden';
        this.tooltipElement.style.display = 'block';
        const tooltipRect = this.tooltipElement.getBoundingClientRect();
        this.tooltipElement.style.visibility = '';
        this.tooltipElement.style.display = '';

        // 默认显示在悬浮球右侧
        let left = this.position.x + ballSize + gap;
        let top = this.position.y;

        // 右侧空间不足，显示在左侧
        if (left + tooltipRect.width > window.innerWidth - 20) {
            left = this.position.x - tooltipRect.width - gap;
        }

        // 底部空间不足，向上调整
        if (top + tooltipRect.height > window.innerHeight - 20) {
            top = window.innerHeight - tooltipRect.height - 20;
        }

        this.tooltipElement.style.left = `${Math.max(10, left)}px`;
        this.tooltipElement.style.top = `${Math.max(10, top)}px`;
    }

    /**
     * 销毁（清理）
     */
    destroy() {
        this.removeContextMenu();
        clearTimeout(this.tooltipTimeout);
        this.ballElement?.remove();
        this.panelElement?.remove();
        this.tooltipElement?.remove();
        logger.info('[QGN] 悬浮球导航器已销毁');
    }
}
