# 远端 LLM 启动与私密配置

文档修订：2026-10-05.1。

## 实现入口

[launcher.py](../../../snapshot/runtime/remote_llm_guard/launcher.py)是公开统一封装；根 BAT 不保存 key。[REMOTE_LLM](../../REMOTE_LLM.md)定义本地 JSON 配置与启动/心跳流程。[安全示例](../../../snapshot/runtime/remote_llm_guard/remote-llm.config.example.json)仅表达格式，真实配置在仓外 `private-config/remote-llm/config.json`。

## 凭证边界

读取配置不等于验证远端可达或认证有效；解析 JSON 不将它当脚本执行。日志、错误和参数不得回显 key、Cookie 或私钥。旧 helper 和原 BAT 的含凭证原件仅私有保留，不能随技术归档公开。

## 验证与运行影响

[test_remote_llm_config.py](../../../tests/test_remote_llm_config.py)验证解析与安全处理。真实开机、SSH、远端请求/心跳属于外部动作，需要当前任务授权；整理文档或检查 Git 不会触发这些操作。

配置副本不会自动同步应用后来的改动。需要迁机时重新登记本机路径和访问权限，不把本地仓外目录当成加密备份。

## 更新记录

- 2026-10-05：公开启动脚本与真实凭证分离，保存原件和窄部署校验；本轮技术归档未连接远端验证 key。
