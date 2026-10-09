# 丝袜纹理节点与引导编辑

文档修订：2026-10-10。

## 职责与来源

在成图上求解受用户引导的织物坐标并叠加纹理，与底模无关。唯一实现为 [插件目录](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/)，[nodes.py](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/nodes.py) 负责节点／张量与临时预览，[engine.py](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/engine.py) 负责 JSON、区域、同步求解和渲染，[前端](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/web/stocking_texture.js) 负责各节点独立的模态编辑器。

上游固定提交 `ad4cc92de86021f20bedcf9de5b27ec0ae574184`，八个 `vendor/*.py` 原样保存，来源及哈希见 [UPSTREAM.json](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/UPSTREAM.json)。`vendor/i18n.py` 是本地无状态格式化适配，非上游原件。保留 MIT 版权／许可，不携带作者示例图、模型或安装器。

## 节点与数据契约

| 节点 | 输入 | 输出 |
|---|---|---|
| `StockingTextureGuides` | IMAGE、guides_json、可选 MASK | 原图、部位 MASK、规范引导 STRING；临时预览 UI |
| `StockingTextureRender` | IMAGE、guides_json、样式／参数／seed、可选 MASK 与 depth IMAGE | 成品 IMAGE、RGBA 透明图层 IMAGE、图层透明度 MASK、问题标记 IMAGE、说明 STRING |

IMAGE 为 `[B,H,W,3/4]`、MASK 为 `[B,H,W]`，float 0–1。外接 MASK 与 depth 可广播单张，否则批次数一致；不自动缩放。MASK 的 1 是覆盖，图层透明度的 1 是不透明；LoadImage 的反向 alpha 需按用途显式反转。成品保留输入第四通道，透明图层固定 RGBA，可直接接 SaveImage。PNG 的 8 位保存有量化误差，节点内 float 图层叠到 RGB 底图的复合误差验收上限为 1e-7。对于非不透明 RGBA 底图，source-over 会提高 alpha，复合后须恢复原图 alpha；处理说明也明确此边界。

引导 schema 1 见[虚构样例](../../../examples/stocking-texture/guides.example.json)：原图像素坐标、参考宽高、最多 32 个唯一部位，部位名称、多边形、所属走向线，以及全局隔开线。空 0×0 文档在执行时绑定图像；已有文档尺寸不符拒绝，不静默缩放。最多 50000 点／4 MiB，有限坐标且在图像内。后来部位拥有重叠区域；多边形为空使用外接 MASK，多边形与外接 MASK 相交。无部位、部位既无多边形也无外接 MASK、无有效走向或未引导分离区域保持原图并给说明。

前端编辑的是多边形和 polyline，不把原图／像素蒙版数组塞进工作流。保存写真实 STRING widget，取消不改节点，撤销／重做在面板内；节点删除关闭面板，新预览使旧面板不可保存。持久化引导可在无浏览器的 API 工作流中执行。预览仅看批量首图，引导应用于整批。

## 算法与资源边界

同步调用上游 `guide_fields.solve_region`，保留遮挡填补、部位重叠、手动隔开线与可选深度自动隔开线。颜色排除沿用上游 Lab 稳健统计。使用 `look.Scene` 与 `knit/tiles/oily` 渲染五样式，按节点 seed 生成局部随机场；不用上游固定全局 seed，也不创建 Document 后台线程。

保持输入原始 float RGB，仅叠加原算法 uint8 结果的增量，并将增量限制在有效覆盖内，避免整张图量化或让亮点越过零 MASK。外接软 MASK 统一作用于最终增量，织纹和亮点都渐弱，不进入上游亮点 alpha>0.5 的二值门限。图层颜色和 alpha 从最终 float 增量计算。隔开线移除全部走向采样时，该部位透传并给调整说明。每个渲染节点最多缓存一份求解结果，变更图像、引导、蒙版、深度或颜色／墙设置失效；改密度、强度和 seed 不必重做坐标求解。batch 逐图执行。

基础仅需现有 NumPy、SciPy、OpenCV、Pillow、contourpy 与 ComfyUI Torch。无自动安装、联网、模型下载或额外监听端口。可选 depth 是相对近度，近亮原样、近暗转 1-x；不隐含任意模型的原始度量深度契约。按深度亮点／自动墙缺 depth 时明确报错。SAM 点选、PSD I/O、原桌面 autosave、擦除自动墙和像素笔刷留为后续独立范围。

引导节点仅将原图首帧与外接蒙版预览写入 ComfyUI temp 的 UUID 文件，交给 ComfyUI 临时资源生命周期；不写生产图库、资料库、用户配置或 input。PNG 不嵌入引导，workflow JSON／API prompt 保留引导。节点执行不修改 UAP、白名单或已有工作流；生产白名单的授权启用另见部署记录。

## 测试与隔离验收

[CPU 合同测试](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/tests/test_nodes.py) 覆盖五样式、区域外逐像素保持、透明图层复合、空输入透传、确定性／缓存、RGBA／批量、软 MASK、多区归属、深度方向、隔开线、编辑预览和非法输入，以及上游原件哈希。

[前端回归](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/tests/test_editor.cjs) 覆盖引导模型、保存与节点生命周期。使用方法及完整 API 例见[样例导航](../../../examples/stocking-texture/README.md)。在主仓运行：

```powershell
& ..\..\python\python.exe -X utf8 -B -m unittest discover -s snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/tests -p test_nodes.py -v
node snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/tests/test_editor.cjs
```

隔离验收从 seal 后快照物化新树，运行区 Python 以 CPU、独立端口、独立 user/temp/数据库和仅本插件白名单启动；使用合成布料区域，不访问真实提示词库或加载模型。实页需要检查打开／圈选／走向／保存、工作流保存往返和执行结果；登记实际收据后才报告通过。

2026-10-09 实际收据见 [stocking_texture_20261009.json](../../receipts/stocking_texture_20261009.json)：13 项 Python 合同与 10 项前端回归通过；ComfyUI 0.33.0／前端 1.49.6 的隔离 CPU API 跑通五样式，区域外变化为零，RGBA 图层保存正确，PNG 复合最大误差 0.9922/255，重复结果相同。真实页面验证新增／改名部位、圈选、手画走向、撤销重做、缩放、保存和取消；工作流保存、关闭、重新加载后两个部位及走向仍在，编辑后的引导多次执行成功。最终前端保存使用 `widget.element`，保留旧版本兼容；刷新后再验保存且没有新增控制台错误。

隔离树的首次物化收据仅证明初始快照；后续精确插件覆盖由最终逐文件 SHA 核对证明。原始工作流、截图、API／身份与清理收据留在仓外，本收据仅保存摘要和哈希。验收结束前核对测试进程身份和空队列，仅停止本次临时服务。真实插画画质和所有画布操作组合尚未验收。

## 部署与限制

初版已按用户“部署生产后实测验收”的授权部署到运行区及 production 白名单。随后 24 例 API 与实页复测发现近黑袜默认三种织纹逐像素无变化，故初版画质验收失败，不能用接口成功代替有效纹理。2026-10-10 修复已完成限定部署，见 [修复验收收据](../../receipts/stocking_texture_fix_20261010.json)：9 个插件文件更新、26 文件与主仓哈希一致，77 个范围外受保护文件未改，保留 5 个数据库一致副本。通过原绘世启动器重新加载，启动参数值和父进程关系保持；生产工作台 5 模块／76 节点就绪。回滚仅处理同批明确插件源码，不覆盖用户引导、工作流、输出或数据库。

用户随后明确要求“部署生产后实测验收”，本次部署候选限定为本插件 23 文件及 production_tools/profiles.json 的 production 新增项。原绘世启动器停止／启动用于保持进程管理关系；部署前保留当前哈希、队列／服务身份、一致数据库备份及同批回滚材料，真实验收完成后另登记现场结果。原图和已有工作流不覆盖，媒体留在仓外。

油光保持试验标识；抗摩尔纹是局部频率减弱与多级贴图过滤，不保证任意输入或后续缩放零摩尔纹。合成样例／接口成功不代表真实插画跨姿态画质通过。

## 更新记录

- 2026-10-10：对照固定提交完整 `Document → fields/coverage → look.Scene → export` 和 `static/look.js`。修复移植时漏掉的手动强度关闭自动联动；新建节点恢复亮部亮点 100%，已保存的 0 保留。深度亮点仍默认 0，因 ComfyUI 没有隐式深度模型。坐标恢复原工具“float32 求解结果装入 float64 全图”的精度次序，避免少量亮色像素在相位计算后相差 1 个色阶。新增可关闭的暗部适配与实际强度／8 位无变化诊断；见下节。

- 2026-10-09：新增独立引导编辑与五样式渲染，接入可选 MASK／depth、固定 seed、单节点缓存和透明图层；固定上游来源，增加合同／前端回归与虚构样例。修复隔开线移除全部走向采样和软 MASK 下亮点消失的边界，明确 RGBA 复合限制；完成合成 API 与实页编辑／工作流保存往返验收，随后按授权部署；近黑真实图验收未通过。

## 近黑无效果修复与原版对照

旧默认在亮度约 19/255 的固定输入上，选中／求解 20323 像素，但暗部乘性衰减与 shader 内部 uint8 舍入使三种织纹全部消失。原工具同参数也复现；不是通道反转、蒙版接线或求解丢失。原工具默认亮点可留下少量变化，却不能代替有方向的织纹。

[rendering.py](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/rendering.py) 独立适配调用固定 shader 的 `dark` 参数，将三种织纹的暗部平滑衰减区间从 0.03–0.30 改为 0–0.12。保持频率抑制、贴图滤波、颜色、覆盖和亮点顺序，不修改八份上游原件，不做全局 monkey patch。中亮度和浅色输入（局部 HSV 明度 ≥0.30）不变；纯黑乘性纹理仍为零。`dark_adapt` 是末尾新增 optional BOOLEAN，默认 true，旧工作流无需补端口；false 回到原版路径。加濑风和油光沿用原版。

[compare_upstream.py](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/tests/compare_upstream.py) 以独立上游源码、指定原图及引导、新建证据目录为参数，实际创建上游 Document，执行原求解与 Scene；不启动其服务器或深度模型。第二轮黑袜与亮布各 35 例：几何／覆盖一致，兼容模式五样式×亮点开关与上游有效区域逐像素一致；黑袜关闭亮点时，适配后细线／针织／斜单线分别有 13698／14506／10477 像素变化，原版均为 0。强度／密度复测含零强度与强制重算，区域外零变化，float 图层复合误差 <1e-7。19 项 CPU 合同、11 项前端回归覆盖近黑、纯黑、亮色、颜色、过密抑制、显式亮点关闭和手动联动。原作者私有 PSD 夹具未获得，未声称跑过其全部测试。

此测试只认证指定插画和控制样本。默认暗部效果克制；推荐 100% 局部观察，按图调整密度／手动强度，不能以变化像素数量单独断言所有画质通过。原始媒体、失败轮次和逐例输出留在仓外验收包；提交只携带摘要／哈希。

最终 CPU 隔离和生产实例各跑 14 组固定图 API 用例及 1 个加载／保存基准；对应结果逐像素一致，区域外变化 0，PNG 图层复合最大误差 0.9922/255。实页分别执行 2／3 次，验证手动强度联动、保存及隔离页刷新往返。生产界面中重新输入相同数字不会触发值变更回调；实际改变数值会关闭自动强度，API 仍须显式关闭。新建独立验收工作流供查看，旧工作流未改。测试不运行扩散模型。原有 ComfyApp 初始化／Vite 错误仍存在，未将全前端标为无错误。
