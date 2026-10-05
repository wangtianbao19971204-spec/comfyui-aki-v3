"""Build the complete read-only component appendix from the audited inventory."""
import collections
import json
from pathlib import Path

RUN = Path(__file__).resolve().parent
data = json.loads((RUN / 'inventory.json').read_text(encoding='utf-8'))
subgraphs = {g['id']: g for g in data['subgraphs']}
top = {n['id']: n for n in data['nodes'] if n['graph'] == 'TOP'}
branch_names = {b['id']: b['name'] for b in data['branches']}
purposes = {
 'UNETLoader':'加载生成用扩散底模；不是检测器。',
 'CLIPLoader':'加载文本编码器及架构类型；必须与底模配套。',
 'VAELoader':'加载图像与潜空间之间的 VAE 编解码器。',
 'ModelSamplingAuraFlow':'给模型配置 Anima 使用的采样时间/shift 行为；不是第二底模。',
 'Lora Stacker (LoraManager)':'累积 LoRA 列表与权重，供下游 Loader 统一加载。分栏是整理方式，不是局部作用域。',
 'Lora Loader (LoraManager)':'把累计及追加 LoRA 应用于模型/编码器，并输出触发词文本。',
 'LoraLoaderModelOnly':'仅向扩散模型加载指定 LoRA；指令编辑分支使用专门的编辑 LoRA。',
 'WeiLinPromptUI':'主正向提示词编辑入口；连到实际正向编码器。',
 'CLIPTextEncode':'将输入提示词编码为采样条件；连线输入优先于节点内未生效的静态文本。',
 'CR Prompt Text':'文本草稿/转接。类本身不自动翻译、拼接或回写主提示词；须结合连线判断。',
 'PromptCleaningMaid':'整理候选提示词；当前主分支的清理预览不自动替代 00W-1。',
 'PromptSelector':'共享提示词模板/资料选择入口；前端操作可写目标，无输出连线不等于无用途。',
 'DanbooruGalleryNode':'图库浏览与标签候选入口；不等于生成条件自动采用。',
 'DanbooruBrowserImportV05':'导入图库浏览器取得的图片/文本材料；不属于分割识别。',
 'ShowText|pysssss':'文本结果预览，可能作为执行输出根；不是没有消费者就无用。',
 'OlmJoyCaption':'本地视觉语言反推，生成标签、设计描述或自然语言草稿。',
 'PixAITagger':'本地动漫标签识别；不是人体/部位分割模型。',
 'TB_Multi_API_Caption_SmartRunner_V16':'并发调用配置的在线识图服务产生多份候选；有上传隐私、费用和网络依赖。',
 'TB_Anima_Prompt_Judge_API_V16':'对多份在线候选综合判断；输出仍需采用到主提示词。',
 'LoadImage':'加载已上传图片并提供图像及遮罩输出；不同参考图槽职责不同。',
 'ImageScaleToMaxDimension':'按长边限制缩放输入图；不属于 AI 超分。',
 'ResizeImagesByLongerEdge':'为控制预处理统一参考图长边尺寸。',
 'GetImageSize':'读取图像宽高/数量，供尺寸或遮罩生成使用。',
 'EmptyLatentImage':'建立指定尺寸/批量的空潜空间，供文生图使用。',
 'EmptySD3LatentImage':'建立指令编辑使用的目标潜空间尺寸。',
 'easy seed':'外置主采样种子；连到 KSampler 时以此为准，不以 KSampler 的静态备用值为准。',
 'KSampler':'按所选底模、条件、潜空间、种子和降噪进行主采样。',
 'VAEEncode':'把输入图/裁剪图编码为潜空间，供普通图生图重绘。',
 'VAEEncodeForInpaint':'把输入图和遮罩编码为局部修复潜空间。',
 'VAEDecode':'把采样潜空间解码为图像。',
 'DazzleSwitch':'选择或按优先级回退到可用输入；不能把它等同于 Impact 的惰性条件节点。',
 'ImpactConditionalBranch':'按布尔值选择输入；两路输入具备 lazy 标记，未选二放可不执行。',
 'PrimitiveBoolean':'布尔开关。00W 控制出图路径，10P 选择检测器风格；二者语义不同。',
 'PrimitiveFloat':'独立浮点参数；Krea2 用于三种输入模式的降噪。',
 'AIO_Preprocessor':'控制图预处理器，当前用于 Canny/HED/漫画线稿；不是部位检测器。',
 'DepthAnythingV2Preprocessor':'从参考图估计深度图；不是脸/手分割。',
 'AnimaLLLiteApply_sdscripts':'把轻量参考控制注入 Anima 模型；原版 28 层权重不兼容 2.9B 的 40 层。',
 'Krea2ControlLoRALoader':'加载 Krea2 的专用 Depth 控制 LoRA；不是普通风格 LoRA。',
 'Krea2ControlImageEncode':'编码 Krea2 深度控制图。',
 'Krea2ControlApply':'把编码后的深度控制条件应用到 Krea2 模型。',
 'VNCCS_PoseStudio':'交互式姿态/光影参考工具；Anima 可接控制，Krea2 此处主要是参考预览。',
 'MaskToImage':'把遮罩转为可预览或可合成的图像。',
 'SolidMask':'生成指定尺寸/数值的矩形遮罩。',
 'ImageCompositeMasked':'按照遮罩把来源图合成到目标图，用于擦线、回贴或保留原图。',
 'FeatherMask':'对裁剪回贴边缘做羽化，缓和矩形接边。',
 'UltralyticsDetectorProvider':'加载 YOLO 检测权重，输出 bbox/segm 检测器；本身不做扩散修图。',
 'SAMLoader':'加载经典 SAM ViT-B 等轮廓模型，辅助框内蒙版；当前不是 SAM3 文本分割。',
 'ImpactSimpleDetectorSEGS':'先 bbox 定位，再用 SAM 蒙版求交并膨胀，生成局部 SEGS。',
 'SegmDetectorSEGS':'直接用语义实例分割检测器生成 SEGS，不走 bbox+SAM 路线。',
 'ImpactSEGSLabelFilter':'按标签筛选检测区域；模型能识别的类别不等于这里全部启用。',
 'ToBasicPipe':'封装 MODEL/CLIP/VAE/正负条件五项基础输入；不是另一个模型。',
 'DetailerForEach':'逐个区域裁剪、局部采样、羽化回贴；采用输入的生成模型。',
 'DetailerForEachPipe':'从 BasicPipe 读取模型条件做区域重绘；未接 refiner pipe 时不代表使用额外 refiner。',
 'UpscaleModelLoader':'加载 OmniSR 等像素超分网络；与扩散底模分工不同。',
 'UltimateSDUpscale':'先像素放大再分块扩散重绘/缝补，主流程当前最终尺寸倍率 1.5×。',
 'ImageUpscaleWithModel':'纯模型像素超分，不运行扩散采样器。',
 'ImageScaleBy':'普通插值倍率缩放；08 中接在 4× 超分后乘 0.5，最终为输入 2×。',
 'Krea2EditGroundedEncode':'结合原图编码指令编辑条件；正负两路各一份。',
 'Krea2EditModelPatch':'把原图/目标 latent 的编辑信息应用到模型采样路径。',
 'OlmDragCrop':'交互拖动裁剪区域，提供裁剪图与位置信息。',
 'OlmCropInfoInterpreter':'解析裁剪坐标/尺寸供自动回贴。',
 'BiRefNetRMBG':'前景抠图与 Alpha 输出；不是当前未采用的人体分层细化。',
 'ImagePadForOutpaint':'按四边像素数扩展画布并生成待补区域遮罩。',
 'Image Comparer (rgthree)':'交互对比两阶段图像；要核对实际 image_a/image_b，部分当前标题已过期。',
 'SimpleImageCompare':'参考处理前后对比预览。',
 'PreviewImage':'显示图像结果；属于输出用途，无消费者正常。',
 'SaveImage':'保存图像文件，分最终输出与临时控制图；属于执行输出根。',
 'VRAMCleanup':'按设置保留或释放模型/缓存；当前默认保留。',
 'Fast Groups Muter (rgthree)':'前端 SW 工具分组静音开关；控制是否参与输出执行，不是后端缺失。',
 'Fast Groups Bypasser (rgthree)':'前端 FX 细化分组旁路开关；不细化时允许原图继续向后传递。',
 'MarkdownNote':'画布使用说明/提示，无计算用途。未归属分支的三个节点均为此类说明。',
}
upstream = {
 'WeiLinPromptUI':'统一包装 / modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector',
 'PromptSelector':'统一包装 / modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector',
 'Lora Stacker (LoraManager)':'统一包装 / modules/comfyui-lora-manager',
 'Lora Loader (LoraManager)':'统一包装 / modules/comfyui-lora-manager',
 'ShowText|pysssss':'统一包装 / modules/comfyui-custom-scripts',
 'DanbooruGalleryNode':'统一包装 / modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly',
 'PromptCleaningMaid':'统一包装 / modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly',
 'SimpleImageCompare':'统一包装 / modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly',
}

def state(n):
    mode = {0:'执行资格',2:'静音',4:'旁路'}.get(n['current_mode'],str(n['current_mode']))
    if n['graph'] == 'TOP':
        if n['branch'] and n['branch'] != data['active_branch']:
            restore = {0:'执行资格',2:'静音',4:'旁路'}.get(n['saved_branch_mode'],str(n['saved_branch_mode']))
            return f"整支未启用；当前 {mode}；启用本分支后恢复为 {restore}"
        return mode + '（不等于必定执行；还取决于输出目标和条件路由）'
    parent = top[n['parent_instances'][0]]
    return f"内部 {mode}；父实例 #{parent['id']} 当前 mode={parent['current_mode']}，父关闭时不执行"

def interaction(n):
    if n['class'] in subgraphs:
        return '常用控制台开关或阶段菜单定位；点子图右上角进入内部。当前没有 proxyWidgets 参数提升。'
    if n['graph'] != 'TOP':
        return '进入所属子图查看/调参；外层只提供该组件开关和接口。'
    if n['class'] in ('MarkdownNote','ShowText|pysssss','PreviewImage'):
        return '只读查看；文本预览若需进入生成，须明确采用/复制到主输入。'
    if n['class'] == 'LoadImage':
        return '完整工作台的任务输入或原节点选图；遮罩/裁剪等专用编辑在画布原节点。'
    if n['class'] in ('UNETLoader','CLIPLoader','VAELoader','UpscaleModelLoader','KSampler','easy seed','EmptyLatentImage','Lora Stacker (LoraManager)','Lora Loader (LoraManager)'):
        return '常用控制台对应字段可调；原节点入口可查看剩余参数。架构配套仍需核对。'
    return '用阶段菜单或原节点入口定位；通过原节点控件/连线使用。'

lines = [
 'UAP 全部组件附录（只读审计）',
 '正式图 SHA256: '+data['workflow_sha256'],
 f"合计 {len(data['nodes'])} 节点：293 顶层 + 178 子图内部；22 个子图实例/定义；71 种非子图节点类型。",
 '节点类来源来自当前后端 object_info；cnr_id/ver 是图内保存的来源提示，不等于安装状态的独立认证。',
 '未列出任何正式提示词正文。参数仍须以连线/浏览器导出的实际值为准，尤其主 seed。',
 '执行资格不等于必定执行；父组件、分支、lazy 路由、任务输出范围都会影响调度。',
 '', '一、来源与功能词典',
]
unknown = []
for t in data['types']:
    if t['embedded_subgraph']:
        continue
    if t['type'] not in purposes:
        unknown.append(t['type'])
    lines.extend([f"{t['type']} | 数量 {t['count']} | {t['source']}",
                  '  作用：'+purposes.get(t['type'],'待补充'),
                  '  实现归属：'+upstream.get(t['type'],t['source'])])
lines.extend(['','二、逐节点明细'])
graph_order = ['TOP'] + [g['name']+'/'+g['id'] for g in data['subgraphs']]
for graph in graph_order:
    lines.extend(['', '='*60, graph])
    for n in (n for n in data['nodes'] if n['graph']==graph):
        name = subgraphs[n['class']]['name'] if n['class'] in subgraphs else n['name']
        lines.extend([f"\n#{n['id']} {name}",
            f"  分支：{branch_names.get(n['branch'],'全局说明')} | 分组：{n['group'] or '子图内部'}",
            f"  实现：{n['class']} | 来源：{upstream.get(n['class'],n['source'])}",
            f"  保存来源提示：cnr_id={n['cnr_id']}；ver={n['source_version']}",
            '  状态：'+state(n),
            '  作用：'+('封装 '+name if n['class'] in subgraphs else purposes.get(n['class'],'待补充')),
            '  交互：'+interaction(n),
            '  输入：'+(', '.join(f"{i['name']}←#{i['node']}[{i['slot']}]" for i in n['inputs']) or '无已连接输入'),
            '  消费者：'+(', '.join(f"#{o['node']}[{o['slot']}]" for o in n['consumers']) or '无下游连线；须结合输出/UI用途判断'),
        ])
        if n['models']:
            lines.append('  模型/加载设置：'+json.dumps(n['models'],ensure_ascii=False))
        if n['parameters']:
            safe = {k:v for k,v in n['parameters'].items() if not any(s in k.lower() for s in ('wildcard','prompt','text','caption'))}
            lines.append('  保存参数（不含提示词）：'+json.dumps(safe,ensure_ascii=False))

lines.extend(['','三、22 子图接口'])
for g in data['subgraphs']:
    lines.extend([f"{g['name']} | {g['id']} | 父节点 {g['instances']} | {g['node_count']} 内部节点",
                  '  输入：'+', '.join(i['name']+':'+i['type'] for i in g['inputs']),
                  '  输出：'+(', '.join(i['name']+':'+i['type'] for i in g['outputs']) or '无外层输出，内部显示候选'),
                  '  proxyWidgets：'+str(g['proxyWidgets'])])
lines.extend(['','四、相关 20 个独立文件'])
for item in data['related_workflows']:
    template = '无同名模板' if not item['template_exists'] else '模板一致' if item['template_matches'] else '模板不同'
    lines.append(f"{item['name']} | {item['top_nodes']} 顶层节点 | {item['subgraphs']} 子图 | {template} | SHA {item['sha256']}")
lines.extend(['','五、113 分组归属与导航'])
for g in data['groups']:
    lines.append(f"{g['name']} | 节点 {g['assigned_nodes']} | 导航 {g['navigation']}")
assert not unknown, unknown
out = RUN / 'ALL_COMPONENTS.txt'
out.write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'file':str(out),'nodes':len(data['nodes']),'classified_types':len(purposes),'lines':len(lines)},ensure_ascii=False))
