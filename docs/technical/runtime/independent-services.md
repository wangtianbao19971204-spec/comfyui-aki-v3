# 独立实验实例与本地辅助工具

文档修订：2026-10-06.1。本文补上此前只在项目地图里一句话带过的部分：独立 Qwen 实验实例、`tools/` 辅助脚本和运行根启动入口。它们都不是生产 8188 服务的一部分。

## 职责与边界

| 范围 | 位置 | 是什么 |
|---|---|---|
| 独立 Qwen 实验实例 | `snapshot/runtime/qwen21_lab/` | 自己的 ComfyUI 源码树与启停脚本，默认端口 8189，与生产 8188 互不影响 |
| 本地辅助脚本 | `snapshot/runtime/tools/` | 手工拉起 ComfyUI、启动 llama.cpp 视觉服务、下载本地语言模型 |
| 运行根启动入口 | `snapshot/runtime/启动_*.cmd`、`停止_ComfyUI_生产.cmd`、`测试_远端LLM心跳.bat`、`启动_绘世_自动唤醒远端LLM.bat` | 双击即用的封装，实际逻辑仍在 `production_tools/launch.py` 与 `remote_llm_guard/launcher.py` |
| 一次性排查脚本 | `_img1.py`、`_t3.py`、`qwen_direct_test.py` | 排查提示词库字段与本地 Qwen VL 加载时留下的临时脚本 |

这些目录受同一主 Git 维护，但不进入 production 白名单，也不随生产启动。改它们不需要动 8188 的启动参数，反之亦然。

## 独立 Qwen 实验实例

[README.txt](../../../snapshot/runtime/qwen21_lab/README.txt) 是现场说明，[boot.py](../../../snapshot/runtime/qwen21_lab/boot.py) 启动服务，[control.py](../../../snapshot/runtime/qwen21_lab/control.py) 提供 `start`/`stop`/`status`/`unload` 四个动作；`start.ps1`、`stop.ps1`、`unload.ps1` 只是入口封装。`control.py` 用保存的 PID 加创建时间核对进程身份，不匹配就拒绝停止，避免误杀其他 Python 进程。

它的 ComfyUI 是**独立的一份源码**（约 1,221 个文件），放在 `qwen21_lab/ComfyUI/`，不是生产树的链接。权重没有搬动：主模型、编码器和 VAE 仍放在原 `ComfyUI/models` 目录，独立实例只读取。`workflows_api/` 保存该实例实际使用的 API 图形。

现场记录的三条工作流（人物去背景、双手蒙版、外套蒙版）在 `README.txt` 中列明。同一份记录也写清了限制：只测过一张完全着装样图，直接要求“只提取外套”会返回整个人物，所以它是**指令式蒙版候选，不是已验证的 YOLO+SAM 替代**——没有类别置信度，也没有独立实例列表。本轮证据在 `benchmark_reports/2026-10-04_qwen21_instruct_deployment/`（`model_manifest.json`、`models_verified.json`、`runs/`、`segmentation_comparison.png`、`FINAL_DELIVERY.json`）。BF16 单次约 25–27 秒、峰值显存约 30 GiB，验证后已请求卸载模型。

## 本地辅助脚本

`tools/start_comfyui.ps1` 用固定参数直接拉起本体（与生产启动参数接近），供批处理出图使用。`tools/llama.cpp/start_vl_server.ps1` 把本地 Qwen VL 以 llama-server 形式暴露给批处理判图；`download_qwen38_27b.ps1` 只负责取模型；`LICENSE-LLVM-OpenMP` 是该目录引入的第三方许可证声明，随源码保留。

这些脚本**不是生产启动路径**：正式启动始终走 `production_tools/launch.py` 的白名单 profile，免得出现绕过白名单的第二个服务。

## 运行根启动入口

| 脚本 | 对应动作 |
|---|---|
| `启动_ComfyUI_生产.cmd` | `launch.py production --memory-mode original --preview-method auto --cuda-malloc --reserve-vram 4` |
| `启动_ComfyUI_轻量.cmd` | `launch.py lean` |
| `启动_ComfyUI_诊断.cmd` | `launch.py diagnostic` |
| `启动_ComfyUI_Anima.cmd` | `launch.py anima` |
| `启动_ComfyUI_Krea2.cmd` | `launch.py krea` |
| `停止_ComfyUI_生产.cmd` | `launch.py --stop`（先核对进程身份与空队列，不匹配就拒绝） |
| `测试_远端LLM心跳.bat` | `remote_llm_guard/launcher.py heartbeat`，前台运行，Ctrl+C 只停测试客户端 |
| `启动_绘世_自动唤醒远端LLM.bat` | `remote_llm_guard/launcher.py start`，配置读仓外 `private-config/remote-llm/config.json` |

白名单、端口和参数以 `production_tools/profiles.json` 为准，脚本本身不复制一份节点清单。

## 机器路径说明

本范围里的若干脚本和文档写有本机绝对路径（`G:\ComfyUI-aki-v3`、用户目录）。这是**本机维护记录**的有意选择，不是凭证：[workspace_audit.py](../../../scripts/workspace_audit.py) 能把全仓的机器路径暴露统计成清单，且该工具只输出文件名与计数、不输出命中正文。迁移到别的机器时要按运行根重新定位，不能把这些路径当成公共默认值。

## 验证与限制

本文描述的是源码与现场记录，**不是冷启动或出图验收**。独立实例、llama.cpp 服务和两条 BAT 都没有在本次维护中被重新启动或重跑。使用前按各自入口单独验收，并注意独立实例、llama.cpp 与生产 8188 会同时占用显存。

## 更新记录

- 2026-10-06：新建本页，把独立 Qwen 实验实例、`tools/` 辅助脚本、运行根启动入口和一次性排查脚本纳入分层技术档案；同时明确机器路径属于本机记录、由 `workspace_audit.py` 统计而不输出正文。未启动任何服务、未改白名单、未改生产参数。
