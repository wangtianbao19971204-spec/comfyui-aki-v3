// Names, purpose and illustrations share one mapping across the workbench and selectors.
export const toolIdentity = {
    workspace: {title:'工作区 · 编排与生成', purpose:'编辑提示词，检查参数，运行当前工作流。', steps:'提示词 → 参数 → 生成'},
    library: {title:'资料库 · 分类与检索', purpose:'按分类查找提示词与 Tag，收藏后随时复用。', steps:'分类 → 搜索 → 使用'},
    models: {title:'模型 · 选择与组合', purpose:'浏览基础模型、LoRA 与模型组合。', steps:'基础模型 + LoRA'},
    gallery: {title:'图库 · 浏览与收藏', purpose:'浏览图片、查看标签，收藏喜欢的作品。', steps:'图片 → 标签 → 收藏'},
    console: {title:'常用控制台', purpose:'调整当前分支的提示词、尺寸、LoRA 与开关。', steps:'参数调整 · 同步节点'},
    prompts: {title:'提示词 · 选择与组合', purpose:'选择文字片段，组合后插入提示词目标。', steps:'选片段 → 组合 → 插入'},
    tags: {title:'基础 Tag · 词条检索', purpose:'查看标签原文与分类，复制或插入目标。', steps:'找词条 → 查看 → 使用'},
    character: {title:'角色 · 人物身份', purpose:'选择角色名称与外貌特征，确定画面中的人物。', steps:'人物身份 · 外貌特征'},
    clothing: {title:'服装 · 穿着搭配', purpose:'选择衣服、鞋履与配饰，组合角色的穿着。', steps:'衣服 · 鞋履 · 配饰'},
    pose: {title:'姿势 · 动作与体态', purpose:'选择身体姿态、手势与动作描述。', steps:'体态 · 手势 · 动作'},
    artist: {title:'画师 · 绘画风格', purpose:'选择画师风格提示词，组合画面的笔触与表现。', steps:'画师风格 · 笔触表现'},
    background: {title:'背景 · 场景与环境', purpose:'选择地点、景物与环境，构建画面背景。', steps:'地点 · 景物 · 环境'},
    style_quality: {title:'风格 · 媒介与画质', purpose:'选择画风、绘画媒介与质量描述。', steps:'画风 · 媒介 · 画质'},
};

const assetRoot = '/extensions/ComfyUI-Unified-Prompt-Workbench/assets/functions/';
export function mountFunctionIcon(parent, kind) {
    if (!Object.hasOwn(toolIdentity, kind)) return;
    const icon = document.createElement('img');
    icon.className = 'uw-function-icon'; icon.src = assetRoot + kind + '.svg?v=20261005-stickers';
    icon.alt = ''; icon.setAttribute('aria-hidden','true'); icon.draggable = false;
    parent.prepend(icon);
    return icon;
}

export function mountFunctionCard(parent, kind) {
    if (!Object.hasOwn(toolIdentity, kind)) return;
    const info = toolIdentity[kind];
    const card = document.createElement('div');
    card.className = 'uw-function-card'; card.dataset.functionKind = kind;
    mountFunctionIcon(card, kind);
    const title = document.createElement('strong'); title.textContent = info.title;
    const purpose = document.createElement('p'); purpose.textContent = info.purpose;
    const steps = document.createElement('span'); steps.className = 'uw-function-steps'; steps.textContent = info.steps;
    card.append(title, purpose, steps); parent.prepend(card);
    return card;
}
