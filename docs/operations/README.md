# 运维与排障

本目录面向已经安装或正在运行的环境，保存健康检查、日志、恢复、现场联调和可重复压测方法。

## 入口

- [完整发行栈排障](release-full-troubleshooting.md)
- [Windows 长路径](windows-long-paths.md)
- [PLC / Modbus 联调](plc-modbus.md)
- [YOLOE / SAM3 Workflow 操作](yoloe-sam3-workflow.md)
- [YOLOE / SAM3 排障](yoloe-sam3-troubleshooting.md)
- [YOLOE / SAM3 soak 方法](yoloe-sam3-soak.md)

安装与启动见 [部署](../deployment/README.md)，接口字段见 [API](../api/README.md)。

## 标准顺序

1. 确认发行 profile、bundled Python 和必要系统运行时。
2. 查看 `logs/full-stack/runtime-state.json`。
3. 查看当天 migration、daemon、service 和目标 Worker Profile 日志。
4. 调用 `/api/v1/system/health`，再查看设置页服务状态。
5. 核对业务资源、Task/Run 终态、稳定错误码和结构化 details。
6. 完整停止后再替换配置、Python、模型 runtime 或发行文件。

不要通过删除状态文件、伪造心跳、直接启动低层 Worker、隐藏排队或无限重试绕过故障。
