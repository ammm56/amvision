# 平台基础架构

本目录说明不依赖具体模型或 Workflow 的平台基础能力。

- [后端服务](backend-service.md)：FastAPI 控制面、依赖注入、Repository 和 Unit of Work。
- [任务系统](task-system.md)：持久任务、Worker Profile 和状态回写。
- [数据和文件](data-and-files.md)：ObjectStore、路径、临时文件与生命周期。
- [运行时与打包](runtime-packaging.md)：源码运行、bundled Python 和发行目录。
- [WebSocket](websocket.md)：公开增量事件面和恢复规则。
- [LocalBufferBroker](local-buffer-broker.md)：本机大对象租约与 mmap 数据面。
- [Inference mailbox v1](inference-mailbox-v1.md)：固定 descriptor、overflow page chain、所有权与回收。
- [图片数据面](image-data-plane.md)：ObjectStore、BufferRef、FrameRef、Base64 与 ZeroMQ 的边界。

系统级入口见 [平台总览](../system-overview.md)。启动与排障分别见 [部署](../../deployment/README.md) 和 [运维](../../operations/README.md)。
