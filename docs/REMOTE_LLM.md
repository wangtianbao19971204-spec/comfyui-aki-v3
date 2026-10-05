# 远端 LLM 启动与私密配置

两个根 BAT 保持原入口：`启动_绘世_自动唤醒远端LLM.bat` 依次执行远端唤醒、后台心跳、本机 8188 检测及绘世启动；`测试_远端LLM心跳.bat` 是前台持续心跳，`Ctrl+C` 停止测试客户端。不是对当前运行服务的自动发布指令。

原 `autodl_power_on.py` 与 `local_heartbeat_client.py` 经过凭证扫描后纳入公开源码，业务代码与原件一致（统一换行）。本轮只外置 BAT 配置，不修改原 API、开机重试、SSH 回退或心跳协议。尤其原 SSH 回退仍沿用原来的 `StrictHostKeyChecking=no`，这不是新加固保证；如需改为受信主机校验，应单独评估已知主机和无人值守行为后修改。

新 `remote_llm_guard/launcher.py` 从以下仓外位置读取 JSON：

`COMFYUI_EXTERNAL_ROOT/private-config/remote-llm/config.json`

未设置变量时，默认运行根同级的 `ComfyUI-local/private-config/remote-llm/config.json`，不写死盘符。公开示例为 `remote_llm_guard/remote-llm.config.example.json`；它不可直接运行，真实 token、实例 ID、远端地址、SSH 配置和本机日志路径只填写到仓外文件。`paths` 中 Python/pythonw/绘世必须为运行根内 `.exe` 相对路径。

JSON 只作为数据解析；禁止 `call .env`、`Invoke-Expression`、`shell=True` 或将凭证拼进命令行。helper 通过白名单子进程环境取值，父环境不被修改，绘世进程不继承这些私密键。后台心跳使用隐藏窗口；本机健康检查添加 5 秒超时，避免检测无限挂起。原 helper 仍可能把服务响应和连接信息写到本机日志，因此日志、原 BAT 备份与私密 JSON 一律不公开。

## 旧本机配置迁移

```powershell
python scripts/extract_remote_llm.py --runtime-root <真实运行根>
python scripts/extract_remote_llm.py --runtime-root <真实运行根> --write
```

默认只读 dry-run；`--write` 只新建仓外 `private-config/remote-llm/`，其中 `originals/` 保留两份逐字节原 BAT，`config.json` 为提取配置，`MIGRATION_RECEIPT.json` 只含哈希与状态。目标必须不存在；有部分失败时保留目录人工核对，不覆盖/清空重试。脚本只解析已知字面 `set` 赋值和已知变量引用，不执行原 BAT、HTTP、SSH、Python helper 或启动器。两个 BAT 共享字段不一致则失败，不能猜测覆盖。

公开文件部署仍由维护流程完成：两个 BAT、`remote_llm_guard/launcher.py`、两份原 helper 和示例。部署前备份运行原件，确认仓外配置就绪，核对使用中的 Python 与绘世位置。此次凭证迁移的离线/mock 测试不代表真实远端开机或 SSH 验收；不因整理 Git 主动唤醒、重启或联网试 key。
