# 运维与排障

本目录面向已经安装或正在运行的现场环境，提供健康检查、日志、恢复和故障定位顺序。

## 入口

- [完整发行栈排障](release-full-troubleshooting.md)
- [Windows 长路径](windows-long-paths.md)
- [YOLOE / SAM3 排障](yoloe-sam3-troubleshooting.md)

安装与首次启动见 [部署指南](../deployment/README.md)，接口字段见 [API 文档](../api/README.md)。

## 标准排障顺序

1. 确认使用正确的 Windows CPU/NVIDIA profile。
2. 查看 `logs/full-stack/runtime-state.json`。
3. 查看当天 migration、daemon、service 和目标 Worker Profile 日志。
4. 调用 `/api/v1/system/health`，再查看设置页服务与 Worker Topology。
5. 定位业务资源状态、Task/Run 终态和错误详情。
6. 只有在完整停止后才替换配置、Python、模型 runtime 或代码。

不要通过删除状态文件、伪造心跳、直接启动低层 Worker 或增加隐藏重试来绕过故障。
