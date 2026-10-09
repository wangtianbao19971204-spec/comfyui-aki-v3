# 丝袜纹理节点与引导编辑

文档修订：2026-10-09。

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

引导节点仅将原图首帧与外接蒙版预览写入 ComfyUI temp 的 UUID 文件，交给 ComfyUI 临时资源生命周期；不写生产图库、资料库、用户配置或 input。PNG 不嵌入引导，workflow JSON／API prompt 保留引导。不会修改 UAP、生产白名单或已有工作流。

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

本轮是新增源码，尚未部署到运行区。源码落盘不会越过 production profile 白名单；启用／生产部署另按 [MAINTENANCE](../../MAINTENANCE.md) 的明确范围执行。回滚范围是本插件源码及其后续明确部署登记，不覆盖用户引导、工作流、输出或数据库。

油光保持试验标识；抗摩尔纹是局部频率减弱与多级贴图过滤，不保证任意输入或后续缩放零摩尔纹。合成样例／接口成功不代表真实插画跨姿态画质通过。

## 更新记录

- 2026-10-09：新增独立引导编辑与五样式渲染，接入可选 MASK／depth、固定 seed、单节点缓存和透明图层；固定上游来源，增加合同／前端回归与虚构样例。修复隔开线移除全部走向采样和软 MASK 下亮点消失的边界，明确 RGBA 复合限制；完成合成 API 与实页编辑／工作流保存往返验收。生产尚未部署。
