# ComfyUI 实际输出 / Real output examples

每张图从左到右是 **原图 → 手工修正后的选区（双腿分开）→ 插件实际输出**。这是完整可见袜体的演示，选区经过检查和修边；不表示 SAM 能自动得到同样的结果。此前不完整的局部选区图不再用作展示。

Each panel shows **input → corrected selection, with separate legs → actual plugin output**. These examples use manually reviewed masks covering the visible fabric. They do not claim automatic selection accuracy.

## 交叉腿 · 新版油光 / Crossed legs · revised oily rendering

![交叉腿：原图、完整双腿选区与真实油光输出](docs/images/black-crossed-before-mask-after.png)

前景袜内足部也纳入选区，沿真实遮挡边界分开两腿，并补充膝部隔开线。密度 75，手动强度 35。此工程在实际 ComfyUI 编辑器中应用到节点，由两个 SaveImage 输出成品和透明图层；保存的工作流重新载入执行后结果一致。

The foreground fabric-covered foot is included. Regions follow the curved overlap, with a knee divider. Density 75, manual strength 35. This project was applied from the real ComfyUI editor, saved through two SaveImage nodes and rerun from the saved workflow with identical output.

## 弯腿 · 细线圈 / Bent legs · fine coil

![弯腿：原图、完整可见袜体选区与真实线圈输出](docs/images/white-bent-before-mask-after.png)

密度 90，手动强度 25。采用较细、较弱的织纹，整图缩小时差异较轻；点击图片可查看更大尺寸。

Density 90, manual strength 25. The fine, restrained weave is subtle in an overview; open the image for a larger view.

## 近黑袜 · 柔和油光 / Near-black socks · subdued oily rendering

![站姿：原图、袜口到鞋边的双袜选区与真实输出](docs/images/nearblack-standing-before-mask-after.png)

选区从袜口覆盖到鞋边，排除皮肤与鞋子。密度 75，手动强度 35；近黑织纹本来就不明显，此例主要展示连续的柔和高光。

The selection covers both socks from the tops to the shoes, excluding skin and shoes. Density 75, manual strength 35. Near-black weave remains subtle; this example mainly shows continuous soft sheen.

## 来源、参数与边界 / Provenance and limits

- 渲染基于上游 `f74c8ac0190ec43b2cdfcb13db86f35a83283311`；相同输入、选区、走向和参数与独立原版逐像素一致。原算法、编辑器及纹理样式归 [Silvermoong 与原项目贡献者](https://github.com/silvermoong/stocking-texture-tool)。
- 三例均关闭暗部适配、亮点与摩尔纹，便于查看基础织纹和新版油光。新增摩尔纹已接入并另做 108 组对照，这三张图不作为摩尔纹开启效果的演示。
- 油光仍属于原版试验功能。选区边缘、袜口、交叉遮挡和参数需要按图片人工检查；逐像素一致不保证任意图片的视觉效果。
- 仅公开这三张选定的对照图；不附原始图片集合、用户工程、模型权重或私有路径。PNG 不含工作流或其他文本元数据。文件摘要与参数见 [SHOWCASE.json](SHOWCASE.json)。

All examples use upstream `f74c8ac`, with dark adaptation, sparkles and moire **off**. They illustrate base texture and revised oily rendering; moire was checked separately in 108 comparisons. Oily remains experimental and masks still require manual inspection. Only the three selected comparison panels are distributed, without embedded workflow metadata, project assets or weights. See [SHOWCASE.json](SHOWCASE.json) for hashes and settings, and the [integration guide](README.md) for validation scope.
