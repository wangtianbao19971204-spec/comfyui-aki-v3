# 2026-10-11：Krea2 默认底模换成非蒸馏 Krea2-Anime v2.0

上一轮对照证明 Krea2 深度控制这条 ControlNet-LoRA 在非蒸馏底模上生效、在当前 Turbo 底模上不可用，且把 Turbo 的 LoRA 强度拉到 4 会把成图打散成噪声。因此把 K2 分支的默认底模换成非蒸馏版，并把采样参数从 Turbo 档位调整到该底模可用的档位。

## 改动（仅 K2 分支）

| 节点 | 参数 | 原值 | 新值 |
|---|---|---|---|
| `1183` UNETLoader | `unet_name` | `…DaSiWa Krea2 - Turbo - Raw…CuteDisaster v2 Turbo UC…BF16` | `krea2\图像生成\Krea2__Krea2-Anime__v2.0__BF16__cv3357716__f3246945.safetensors` |
| `1200` KSampler | `steps` | 8 | 24 |
| `1200` KSampler | `cfg` | 1 | 3.5 |
| `1200` KSampler | `scheduler` | simple | normal |
| `1200` KSampler | `sampler_name` / `denoise` | euler / 1 | 不变 |

换底模必须同步改步数与 CFG：8 步 CFG1 是 Turbo 档位，用在非蒸馏底模上会出烂图。其余一律未动——LoRA 栈（角色/姿势/风格/补充）、提示词、种子、尺寸、控制强度、线稿来源、深度来源开关、其它分支与全部开关默认值保持原值。工具 `production_tools/switch_krea2_base_model.py` 输出逐项 before/after 审计，可直接反推回滚：

```
1183 unet_name  Turbo CuteDisaster v2 → Krea2-Anime v2.0 BF16
1200 steps      8 → 24
1200 cfg        1 → 3.5
1200 scheduler  simple → normal
```

## 隔离验收（新默认配置本身）

用改后的工作流在隔离实例跑"关控制 / 开控制（姿势深度）"各一次，固定提示词、种子与姿势：

| 用例 | 结果 |
|---|---|
| 关控制（原始模型） | 776×1344 正常成图，重复运行逐像素一致（`52947003`） |
| 开控制（姿势深度 `input_02`） | `98a85dc6`，与关控制**平均绝对差 89.12、变化 97.3% 像素** |

画面：关控制是空脸站姿人物；开控制复现姿势深度里的蹲身照料姿势（蓝帽、弯腰、手在花丛/水面）。控制的可见效果与新默认参数一致。

## 部署与运行区实页验收

队列空档（用户任务跑完、队列 0/0）时部署：备份两文件与一致数据库副本，停旧进程 47972，替换后按原命令行重启为 **15244**。重启后运行区两文件 SHA `ceeeee13534dfc767…` 与源码一致；真实前端读取确认 `1183` 已是 `Krea2-Anime v2.0 BF16`、`1200` 为 24 步／CFG 3.5／euler／normal、`130160` 两个输入都已连接、编码器 `control_image` 来自 `130160`、控制 LoRA 强度 1、k2 分支 99 节点。

再用运行区默认提示词与固定种子走一次完整生产链路（控制开、深度来源 `input_02`）：队列 `success`，落盘 `_codex_qa/krea2_default_base_20261011/krea2_00001_.png`（768×1344，`b2c7933d…`），画面为花园中俯身人物，姿势由控制图驱动。未改用户工作流的提示词、种子与其它参数（实页运行未保存文件）。

## 限制

- 只换默认值，未做新底模的完整出图质量评估（步数/CFG/scheduler 取对照中已验证可用的一组，未做扫描）。
- 用户原有的 Turbo 底模仍在库中，随时可切回；回滚只需把上表四下参数改回原值。
- 未改动 ControlNet-LoRA 强度（保持 1）。
- 运行区仍保留 `deployment-base/ROLLBACK.json` 作为该轮的回滚材料（未执行）。
