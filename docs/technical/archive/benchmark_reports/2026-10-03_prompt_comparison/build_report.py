import html,json,pathlib,shutil,statistics
from PIL import Image,ImageDraw,ImageFont
from manage import OUT
from experiment import SCENES,SEEDS

results=json.loads((OUT/'results.json').read_text('utf8'))
review=json.loads((OUT/'visual_review.json').read_text('utf8'))
scores={r['job']:r for r in review['rows']}
summary=json.loads((OUT/'generation_summary.json').read_text('utf8'))
report=OUT/'report';assets=report/'assets';assets.mkdir(parents=True,exist_ok=True)
for r in results:shutil.copy2(r['image'],assets/(r['id']+'.png'))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
example=Image.new('RGB',(2064,816),'#1c2634');draw=ImageDraw.Draw(example)
for i,v in enumerate(['A','B']):
    name=f'duo_{SEEDS[0]}_{v}'
    with Image.open(assets/(name+'.png')) as im:example.paste(im.convert('RGB'),(i*1040,48))
    draw.text((i*1040+12,12),f'{v} | {"TAG PHRASES" if v=="A" else "FULL SENTENCES"} | seed {SEEDS[0]}',font=font,fill='white')
example.save(OUT/'duo_comparison.jpg',quality=95)
text='''第三阶段：提示词小规模对照完成；显存释放已改为可选

上线内容
UAP v2 全部 9 个出图分支、生产套件 01–03、扩展 04–09 和对应模板，默认保留模型。常用控制台的“单张完成 · 释放模型和缓存”是主动选项，立即释放按钮和专用 99 释放流程保留。节点标题改为“可选显存释放（默认保留模型）”。共 10 份工作流 + 10 份模板 + README；未修改核心显存管理，也未关闭 ComfyUI 按需卸载机制。
已有未保存会话保留原状态；重新打开已保存的 v2 文件使用新默认。历史 UAP v1 保留。切换模型或结束工作时可按需手动释放，驻留会继续占用显存。

实验结论
本轮不支持把所有提示词统一改写成完整句。保留可编辑的标签/短语骨架，关键构图词与人物属性所属关系应明确；复杂空间关系可另加短句，但混合写法尚未测试。

1. 单人全身：A 标签与 B 完整句都仅 1/3 保住头顶到靴底完整构图。右手持伞为 A 1/3 明确正确（1 张错误、1 张握手被遮挡），B 2/3。单张优势不稳定。
2. 双人绑定：两组的左右人物、黑/金发色、红/蓝服装与白/黄围巾均 3/3 对应正确。A 全身 3/3；B 全身 0/3，全部变为半身。A 使用了 full body，B 使用 visible from head to shoes；这是整套措辞差异，不能把结果单独归因于“标签语法优于自然语言”。
3. 几何关系：两组红物体在蓝物体左侧、黄物体在蓝物体后方均 3/3。部分图的球体/圆锥体积表意弱，平视镜头也不稳定；不能只凭颜色与位置正确就说几何全部通过。
4. 背景照明：两组都能画出中央拱窗、双侧书架、左灯与右植物。A 3/3、B 2/3 有较明确的蓝橙照明并置；B 另 1 张主要体现灯罩颜色。B 有 2 张把植物放在地面；原句未严格限定台面，因此记录为布局差异，不判作违反提示。需要台面摆放时应明确写 on the counter。

角色一致性仅检查重复种子下的发色/服装等属性，不是固定身份、参考图或 LoRA 一致性测试。风格均保持动漫插画，但人物表情、线条与明暗有变化。手部多有遮挡或缩小，无法据此宣称任一方案改善手脸结构。逐图观察和不可判定项见 visual_review.json。

方法
AnimaYume v1.5；UNET animayume_v15Base.safetensors；文本编码器 anima_baseV10_txt.safetensors / stable_diffusion；qwen_image_vae.safetensors。
1024×768，30 步，CFG 7，res_multistep / beta，AuraFlow shift 3，batch 1；负向固定 blurry, low contrast。
4 个中性场景 × 3 个种子（314159265、271828182、161803398）× 2 套表达 = 24 张。每一对只改正向表达与输出文件名；A/B 先后顺序交替。无 LoRA、score tags、二放或采样器变动。
同模型全程保留，测试批次边界手动释放；不采用跨模型手册的“每张前后卸载”，原因是本轮为单模型提示词比较且用户要求释放可选。两组执行相同驻留策略。
模型视觉审阅了全部 24 张原图；没有人类盲评，不报告统计显著性，也不做通用优劣排名。长度和词汇随表达方案改变，因此不是严格只改变标点/语法的实验。

资源记录
24 张全部成功且像素互不相同，采样器每张都实际执行。A 单张墙钟中位数约 12.34 秒，B 约 12.12 秒；包含冷/热加载与其他 GPU 活动，不将小差异解释为提示词速度收益。设备总显存峰值 14262 MiB，约 13.9 GiB，包含其他进程。

使用建议
保留当前标签拼接入口和可直接编辑的最终提示词。优先保住 full body 等明确构图词；两个人物分别写“谁、在哪里、什么发色/服装”，别把所有颜色堆成无所属的列表。物体承载位置明确写 on the counter / on the floor，不仅写 on its right side。
下一轮候选是“关键标签 + 关系短句”，针对双人全身与台面摆放做同种子对照；这是候选建议，尚未验证，不自动替换正式提示词或资料库条目。

证据与回退
report/index.html：全部 A/B 原图、提示词、逐图观察；config.json：完整矩阵；raw：24 份 API、history、提交回执与遥测；model_manifest.json：本轮重新计算的模型 SHA256；before：正式文件精确备份。
在 G:\\ComfyUI-aki-v3 下执行 python\\python.exe -X utf8 benchmark_reports\\2026-10-03_prompt_comparison\\manage.py rollback 可恢复本轮默认值与 README；会核对当前文件哈希并在出现后续改动时停止，不覆盖并行成果。
最终状态、保护文件检查和资源就绪以 FINAL_DELIVERY.json 为准。
'''
(OUT/'交付说明.txt').write_text(text,encoding='utf8')
parts=['''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>提示词对照 · 24 张完整结果</title><style>
body{font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;background:#101823;color:#e6edf7;margin:0}main{max-width:1440px;margin:auto;padding:36px}h1{font-size:34px;line-height:1.25}h2{margin-top:52px}h3{margin:0}p{max-width:1050px;color:#b9c8db}a{color:#83dcd0}.badge{color:#83dcd0;font-size:13px;letter-spacing:2px}.lead{font-size:20px}.callout,details{background:#192536;border:1px solid #304156;border-radius:12px;padding:18px;margin:18px 0}.pairs{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:12px 0 34px}figure{margin:0;background:#192536;border:1px solid #304156;border-radius:10px;overflow:hidden}figure img{width:100%;display:block}figcaption{padding:14px}small{color:#a8bdd4}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit;font-size:14px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:12px;border-bottom:1px solid #304156}nav{display:flex;gap:18px;flex-wrap:wrap}li{margin:7px 0}@media(max-width:780px){main{padding:18px}.pairs{grid-template-columns:1fr}h1{font-size:27px}}
</style><main><div class="badge">ANIMAYUME · 4 SCENES · 3 SEEDS · 2 PROMPTS</div><h1>保留关键标签，慎做整段改写</h1><p class="lead">24 张原图全部保留。两套方案都能完成属性绑定；双人全身构图在本次标签写法中更稳定。</p><div class="callout"><strong>显存释放已改为可选。</strong> UAP v2、生产套件 01–03、扩展 04–09 默认保留模型。需要时主动选择释放，或使用立即释放 / 专用 99 流程。旧的未保存会话不会被覆盖。</div><nav>''']
parts.extend(f'<a href="#{s["id"]}">{html.escape(s["name"])}</a>' for s in SCENES)
parts.append('''</nav><h2>结果要点</h2><table><tr><th>项目</th><th>A 标签短语</th><th>B 完整句</th></tr><tr><td>单人完整全身</td><td>1/3</td><td>1/3</td></tr><tr><td>双人完整全身</td><td>3/3</td><td>0/3</td></tr><tr><td>双人颜色与左右绑定</td><td>3/3</td><td>3/3</td></tr><tr><td>几何物体左右 / 前后关系</td><td>3/3</td><td>3/3</td></tr><tr><td>明确蓝橙照明并置</td><td>3/3</td><td>2/3</td></tr></table><p>不是通用排名：B 双人方案把 full body 改写成 visible from head to shoes，长度和用词也改变。结果不能单独归因于语法。几何体积、遮挡的手和裤子有不可判定项。由模型审阅全部原图，没有人类盲评。</p><details><summary>固定参数与资源边界</summary><p>1024×768 · 30 步 · CFG 7 · res_multistep / beta · shift 3 · 无 LoRA / 二放 / score tags。每对仅改变正向措辞和文件名，A/B 顺序交替，同模型连续驻留。</p><p>墙钟中位数 A 12.34 秒 / B 12.12 秒；不是提示词速度收益证据。设备总显存峰值约 13.9 GiB，包含其他进程。</p></details>''')
for scene in SCENES:
    parts.append(f'<section id="{scene["id"]}"><h2>{html.escape(scene["name"])}</h2><details><summary>查看两套完整提示词</summary>')
    for v in ['A','B']:parts.append(f'<h3>{v}</h3><pre>{html.escape(scene[v])}</pre>')
    parts.append('</details>')
    for seed in SEEDS:
        parts.append(f'<h3>Seed {seed}</h3><div class="pairs">')
        for v in ['A','B']:
            name=f'{scene["id"]}_{seed}_{v}';r=next(x for x in results if x['id']==name);s=scores[name]
            parts.append(f'<figure><a href="assets/{name}.png"><img loading="lazy" src="assets/{name}.png" alt="{html.escape(scene["name"])} {v} seed {seed}"></a><figcaption><strong>{v} · {"标签短语" if v=="A" else "完整句"}</strong><small> · {r["wall_seconds"]:.2f} 秒</small><p>{html.escape(s["composition"])}</p><small>{html.escape(s["hands_faces_or_geometry"])}</small><details><summary>逐项检查</summary><ul>')
            for label,value in zip(scene['checks'],s['checks']):parts.append(f'<li>{html.escape(label)}：{ {1:"满足",0:"未满足",None:"不可判定"}[value]}</li>')
            parts.append('</ul></details></figcaption></figure>')
        parts.append('</div>')
    parts.append('</section>')
parts.append('<h2>后续候选</h2><p>保留 full body 等关键标签，再用短句明确人物属性所属、左右关系，以及 on the counter / on the floor 等承载位置。此混合写法尚未测试，不自动替换正式提示词。</p><p><a href="../交付说明.txt">完整说明与回退</a> · <a href="../config.json">提示词与实验矩阵</a> · <a href="../visual_review.json">逐图审阅记录</a> · <a href="../FINAL_DELIVERY.json">最终验收</a></p></main></html>')
(report/'index.html').write_text(''.join(parts),encoding='utf8')
assert len(list(assets.glob('*.png')))==24
print('Report, 24 original assets and comparison image saved')
