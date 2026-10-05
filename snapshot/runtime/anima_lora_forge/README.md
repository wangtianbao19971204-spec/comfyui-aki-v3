# Anima LoRA Forge

这是与 `character_lora_forge` 配套的可复用 Anima 角色 LoRA 训练项目。

项目内置隔离版 SD-Trainer 与 sd-scripts，提供网页控制台、训练监控和 TensorBoard。
它不会修改绘世/ComfyUI 的 Python 环境。项目默认将 `trainer.allow_execute` 设为
`false`；即使误运行 `train` 或 `submit`，也不会开始正式训练。

## 项目职责

- 预检图片/TXT 配对、触发词、可读性、精确重复图和尺寸；
- 检查 Anima Base、Qwen3 文本编码器、Qwen Image VAE、GPU 与 BF16；
- 为每次炼制生成不可变的 profile 快照、数据集 TOML、命令和运行清单；
- 分离配置生成与正式执行，防止误触发；
- 在浏览器中显示训练日志、GPU/显存、Step/Loss 曲线、任务状态和预览图；
- 保存多个 LoRA checkpoint，供后续固定提示词矩阵、LLM 评分和 Codex 人工抽检；
- 新人物只需复制 profile，不需要重写训练程序。

## 罗莎莎当前入口

```powershell
cd G:\ComfyUI-aki-v3\anima_lora_forge

# 只读预检，不训练
..\python\python.exe anima_lora.py --profile profiles\rosasha.json doctor

# 同时核验三份模型哈希；耗时会更长
..\python\python.exe anima_lora.py --profile profiles\rosasha.json `
  doctor --verify-model-hash

# 生成一次可审计训练包，不训练
..\python\python.exe anima_lora.py --profile profiles\rosasha.json `
  prepare --run-id rosasha_smoke_v1

# 查看训练器最终会收到的命令，不训练
..\python\python.exe anima_lora.py --profile profiles\rosasha.json `
  command --run-id rosasha_command_preview

# 查看运行状态
..\python\python.exe anima_lora.py --profile profiles\rosasha.json status
```

也可以运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\运行_Anima_LoRA.ps1 -Action doctor
```

或双击 `预检_罗莎莎.bat`。

## 可视化训练控制台

双击 [启动_SD-Trainer可视化.bat](启动_SD-Trainer可视化.bat) 启动控制台，然后访问：

- 主界面：<http://127.0.0.1:28000>
- 实时任务监控：<http://127.0.0.1:28000/train-monitor>
- Loss 曲线：<http://127.0.0.1:28000/tensorboard.html>

也可以双击 [打开_训练监控.bat](打开_训练监控.bat) 直接打开监控页和 TensorBoard。
网页显示的是训练器写入的同一份实时状态，因此用户与 Codex 看到的日志、GPU/显存、
Loss 和预览图一致。

只读检查控制台状态：

```powershell
..\python\python.exe anima_lora.py --profile profiles\rosasha.json dashboard
```

`prepare` 会额外生成 `sd_trainer_job.json`。正式解锁后，`submit --run-id <ID>`
才会向网页控制台提交任务；锁定状态下会明确拒绝。

## 正式训练的安全边界

正式训练前必须全部满足：

1. 核验内置 SD-Trainer 与 Anima 后端版本；
2. 在独立便携 Python 中完成依赖测试，不修改绘世运行环境；
3. 先做 50–100 steps 冒烟训练；
4. 确认生成的 `dataset.toml` 和 `train_command.ps1`；
5. 将对应 profile 的 `trainer.allow_execute` 改为 `true`；
6. 显式运行 `train --run-id <已准备的运行 ID>`。

训练器尚未安装时，`doctor` 会把它标为 warning，而不是破坏数据预检。

## 当前罗莎莎基线

- 数据集：120 PNG + 120 TXT；
- 触发词：`rsrs_anima`；
- 底模：Anima Base v1.0；
- 只训练 DiT/UNet LoRA，不训练 LLM Adapter；
- Rank 32、Alpha 16、学习率 `2e-5`；
- 1024 分辨率面积桶、Batch 1、BF16；
- 1000 steps，每 200 steps 保存；
- timestep sampling 使用 `sigmoid`，flow shift 为 `1.0`；
- 使用当前 sd-scripts 的二维 Qwen Image VAE 做 latent 预缓存；
- 随机翻转关闭；
- caption 保留首个触发词；
- 正式选择重点比较 400、600、800、1000 steps，而不是默认使用最后一个。

## 当前候选发布

已完成 50-step 冒烟和 400-step 校准。经五服装、四画风及 `0.6/0.8/1.0`
强度矩阵人工审核，当前选中 400-step 作为
`releases/rosasha_anima_r32_v1/rosasha_anima_r32_v1.safetensors`。
推荐强度 `0.8–1.0`，默认从 `0.9` 开始；300-step checkpoint 保留作柔和备选。

## 新角色复用

1. 复制 `templates/new_character.profile.json` 到 `profiles/<character_id>.json`；
2. 修改人物 ID、显示名称、唯一触发词和训练集路径；
3. 保持 Anima Base/Qwen/VAE 路径，除非底模版本明确升级；
4. 运行 `doctor`；
5. 审核报告后运行 `prepare`；
6. 冒烟训练通过后才能解锁正式执行。

每次运行会写入：

```text
runs/<character_id>/<run_id>/
  config/
    dataset.toml
    sample_prompts.txt
    sd_trainer_job.json
    profile.snapshot.json
    train_command.ps1
  dataset/
    1_<trigger_token>/
  logs/
  samples/
  weights/
  run_manifest.json
```

训练前会把黄金底图以 NTFS 硬链接暂存到本次运行的 `dataset` 目录；若硬链接不可用才复制。
SD-Trainer 只接触暂存目录，不会移动、改名或改写原始 120 张黄金底图。
