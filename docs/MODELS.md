# 模型与 LoRA：下载、放置和维护

换机器或他人拉取后，从[下载来源清单](MODEL_SOURCES.md)补资源。权重留在 Git 外；主仓保存来源网址、确切版本、文件身份、相对位置、配套和备注。自训成品、已失效的转换文件和暂未确认的来源，仍需独立备份原权重。

## 清单各负责什么

| 清单 | 用途 |
|---|---|
| [models.json](../snapshot/inventory/models.json) | 首次捕获的 384 项权重路径、大小和时间基线；不因新来源记录而改写旧事实 |
| [model_sources.json](../snapshot/inventory/model_sources.json)／[易读表](MODEL_SOURCES.md) | 全部基线及 11 个特殊配套的来源、版本、上游文件名、声明摘要、配套和当前盘点；以后在这里修订来源 |
| [workflow_models.json](../snapshot/inventory/workflow_models.json) | 捕获时保存工作流的静态引用；历史关系不代表当前每条流程都可执行 |

来源清单另绑定正式 UAP v2 原文件摘要，重新检查当前引用。“正式 UAP 所需”包括可选分支的静态引用，不代表所有资源每次都加载，也不改变分支、LoRA、种子或参数。节点还可能按目录或内置默认值加载 PixAI、BiRefNet 等资源，需查看备注与配套。

## 换机怎么补

1. 按[恢复方法](RESTORE.md)先物化源码到全新运行根，查自己要用的分支，再查其他 LoRA／工具。所有 `ComfyUI/...` 和插件路径均相对这个运行根，不把权重加入主仓 `snapshot/runtime/`。
2. 打开稳定来源页，选择记录的版本／提交及上游原文件名。Civitai 按 model/version/file ID 和声明 SHA 选文件；一个版本有多种精度时，默认下载入口可能不是所需文件。未确认默认文件的条目只给版本页，下载链接留空。
3. 放到记录的完整相对路径，保留本地名和家族子目录。上游原名不同的文件，按已确认的身份改成工作流使用的本地名称。例如 `anima_baseV10_txt.safetensors` 的同摘要上游原名为 `qwen_3_06b_base.safetensors`；中文检测模型也记录各自上游原名。不能只凭相近名称认定别名。
4. 核对大小并计算取得文件的 SHA-256。先与本机 `local_sha256` 比较，再与确切上游文件的 `declared_sha256` 比较；不相同就保留原件和候选，查版本、格式和来源，不自动替换。`null` 不表示验证成功。
5. 完整迁移配套。目录型模型保留同版本 config、tokenizer、processor、标签映射、分片 index 和全部 shard，审查其 Python 模型代码。PixAI／BiRefNet／衣服分割不能只下权重，视觉 GGUF 需要对应 mmproj。特殊文件见 [runtime-support.json](../governance/runtime-support.json)；不为清点而反序列化 `.pkl`／`.pt`。
6. 自训条目单独迁移成品权重；继续训练还要保留原项目、图片／caption、配置和检查点。训练器源码不能重建同一成品。历史 intrinsic 转换文件当前上游目录已不含原文件，要备份现件；原作者其他格式不能直接代替。
7. 登录／许可在网站完成，认证配置留在自己的仓外目录。清单不加 token、Cookie、账户配置或签名链接。社区镜像的同摘要只证明内容一致，不代替原作者许可审查。网址可能失效，网上资源也建议保留完整备份。
8. 依赖齐全后，在隔离目录和端口验收具体流程、加载器与 GPU 推理。静态检查或服务启动成功不等于画质验收。

校验自己取得的单个文件（使用本机实际路径）：

```powershell
$comfyAsset = 'D:\ComfyUI-runtime\ComfyUI\models\text_encoders\anima_baseV10_txt.safetensors'
(Get-Item -LiteralPath $comfyAsset).Length
(Get-FileHash -LiteralPath $comfyAsset -Algorithm SHA256).Hash.ToLowerInvariant()
```

这只读取指定文件，不下载、替换或执行工作流。本机私有根路径不作为公共默认值。

## 记录精度怎么读

| 字段／状态 | 含义 |
|---|---|
| `version_metadata` | 已存公开模型／版本资料，可含文件 ID 和声明摘要；未宣称当前站点可访问 |
| `upstream_mapping` | 节点声明、作者发布或上游文件记录提供来源；具体证据与本机摘要是否匹配见备注 |
| `local_derivative` | 本机自训／本地转换，需要原件或完整转换材料；父模型网址不等于成品下载 |
| `unresolved` | 缺可靠来源，保留位置与指纹，迁移原件后继续补查，不猜网址 |
| `sources[].declared_sha256` | 上游／保存元数据声称的摘要，不是本轮读取本机权重的结果 |
| `local_sha256` | 本轮实际完整计算的本机摘要；采集时间见清单，文件变化后必须重算 |
| `sources[].availability` | 实际核验范围；远端元数据存在不等于已下载、获许可或 GPU 通过 |

首轮没有为全部大模型重算摘要。“存在”与大小只代表采集时点，离线 `check` 不读取权重，也不证明新机器已经装好。新取得／替换的重要资源应记录实际 SHA，并复核远端版本和许可。

原版 Anima LoRA／LLLite 与 Anima 2.9B 架构不同，转换或适配必须有自己的过程和验证，不混用原件与转换件。Krea2 的量化形式、Heretic 编码器和自定义 VAE 也不能换成相似命名的官方包后宣称同一实例。

## 以后更新留在同一主仓

新增、替换或查清来源时，修订 `snapshot/inventory/model_sources.json` 对应项，保持原相对路径／本地名，填写来源页、版本／提交、原文件名、大小、配套、家族证据与备注。`evidence` 留可公开的代码／文档或原侧车相对位置，不复制原缓存或自由备注正文。新增资产设 `captured_in_inventory: false`，不伪装成首版资源。原资产删除后保留记录，设 `observed_present: false`，当前 `local_sha256` 清空，旧摘要仍在 Git 历史。

来源页允许 Civitai 的数字 `modelVersionId` 参数，下载地址不得含 query。需要格式选择时，从稳定版本页手动选文件，不保存鉴权或签名 URL。未知来源保持 `unresolved`；不能把 sidecar 摘要填进 `local_sha256`。统计字段 `summary` 按实际条目更新；校验器会拒绝错误统计。

使用已按[开始使用](GETTING_STARTED.md)选择的 `$comfyPython`，在主仓执行：

```powershell
& $comfyPython -X utf8 -B scripts\model_sources.py render
if ($LASTEXITCODE -ne 0) { throw 'Model source render failed' }
& $comfyPython -X utf8 -B scripts\model_sources.py check
if ($LASTEXITCODE -ne 0) { throw 'Model source catalogue check failed' }
```

`render` 只重建本仓易读 MD，不联网、不扫描权重、不部署。`check` 验证路径／URL／摘要格式、384 项基线覆盖、统计与正式工作流摘要，并核对易读表同步。工作流改动使绑定失效时，先按新版重新审查引用和配套，再更新 `workflow_sha256`，不能只改摘要跳过审查。

来源 JSON 属快照 metadata：修订后在 `snapshot/manifest.json` 的 `metadata_files` 中只更新 `inventory/model_sources.json` 的字节数与 SHA，不顺带重认旧库、其他 inventory 或 payload。运行 `snapshot.py verify`、相关测试和暂存门禁，精确提交本批文件，更新[模型技术档案](technical/runtime/models.md)与 CHANGELOG。普通提交不加版本，不自动下载、部署或推送。

字段标注见[模型来源样例](../examples/external-assets/model-source.example.json)，外部放置、目录配套与许可边界见[外部资源](EXTERNAL_ASSETS.md)。

## 更新记录

- 2026-10-07：补迁移来源、精确文件身份、配套与本机别名，增加离线校验和易读表生成，保留自训／历史转换原件及未实测边界；实际覆盖见[本轮收据](receipts/model_sources_20261007.json)。
