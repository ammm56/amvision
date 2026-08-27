# AMVision 文档

AMVision 是面向本地工作站、工控机和边缘设备的工业视觉服务平台。本目录只保存当前可执行的说明、稳定的架构约束和可复用参考。未经接受的实施计划、会话结论、一次性审计结果与重复接口清单不属于正式文档；经 ADR 接受的跨子系统实施基线可以在 `development/` 暂存，并必须明确标注尚未落地的部分。

## 从这里开始

| 目标 | 入口 |
| --- | --- |
| 理解产品定位、模块关系和完整链路 | [平台总览](architecture/system-overview.md) |
| 查看项目目录和代码分层 | [项目结构](architecture/project-structure.md) |
| 完整启动源码开发环境 | [开发环境启动](deployment/development-environment.md) |
| 组装并启动生产发行包 | [生产环境](deployment/production-environment.md) |
| 调用 REST、WebSocket、ZeroMQ 或 SDK | [API 与集成](api/README.md) |
| 核对模型和数据格式支持范围 | [参考资料](reference/README.md) |
| 开发 Core Node、Custom Node 或 Node Pack | [节点扩展](nodes/README.md) |
| 配置 YOLOE / SAM3 Node Pack 与本地模型资产 | [YOLOE / SAM3 资产](architecture/workflows/yoloe-sam3-assets.md) |
| 排查日志、服务和现场集成 | [运维与排障](operations/README.md) |
| 查看关键设计取舍 | [架构决策记录](decisions/README.md) |
| 查看已接受但尚未落地的跨子系统实施基线 | [源码开发](development/README.md) |
| 查看前端产品和界面规范 | [前端设计](design/frontend/README.md) |

## 信息架构

```text
docs/
├─ architecture/   系统设计、模块边界、运行时和稳定不变量
├─ api/            公开 API、协议、SDK、请求语义和调试入口
├─ reference/      数据格式、模型支持范围和参数规则
├─ development/    源码开发、代码检查、测试和迁移门禁
├─ deployment/     开发启动、发行组装、生产启动和运行时布局
├─ operations/     日志、健康检查、现场操作、恢复和故障处理
├─ nodes/          节点定义、Node Pack、runtime hook 和扩展示例
├─ decisions/      仍然有效的 ADR
├─ design/         当前产品、信息架构、设计系统和页面规格
├─ examples/       可复用 Workflow 与协议示例
└─ legal/          第三方来源与许可证说明
```

目录职责互斥：架构文档不保存操作步骤，参考文档不宣称运行时状态，开发文档不重复产品设计，运维文档不承担安装教程。

## 唯一事实来源

| 内容 | 事实来源 |
| --- | --- |
| 产品范围与技术约束 | [AGENTS.md](../AGENTS.md) |
| 模块关系和运行拓扑 | [平台总览](architecture/system-overview.md) 与当前代码 |
| REST 字段与 endpoint | backend-service 生成的 `/openapi.json`；专题文档只解释语义 |
| Workflow 节点与端口 | 运行时 Node Catalog；Template 不复制节点定义 |
| 模型/任务组合 | [模型支持矩阵](reference/models/support-matrix.md) 与模型注册表 |
| 数据集格式 | [数据格式参考](reference/datasets/README.md) 与格式注册表 |
| 数据库结构 | SQLAlchemy ORM 与 Alembic head |
| 开发和生产启动命令 | [开发环境](deployment/development-environment.md) 与 [生产环境](deployment/production-environment.md) |
| 可复用 Workflow | `docs/examples/workflows/` 及其自动化测试 |

## 当前运行形态

- `backend-service` 提供 REST、WebSocket、前端静态资源和控制面，不消费后台任务队列。
- `inference daemon` 独立托管 DeploymentInstance 与推理进程。
- Worker Supervisor 启动数据集导入、导出、训练、转换、评估和异步推理六个 Profile。
- Workflow App 发布为不可变版本；稳定 Runtime/Trigger id 通过 revision 与 generation 切换实现。
- LocalBufferBroker、mmap 和 ZeroMQ 构成本机高性能图片数据面；大图不在进程间反复复制 Base64 JSON。
- 训练遥测已迁移到通用 LocalMessage EventRing，Inference daemon 已迁移到通用 LocalMessage RpcMailbox；Workflow Trigger 的后续原子迁移边界见 [ADR-0009](decisions/ADR-0009-local-message-channel.md)。
- 生产日志按本地日期写入 `*-YYYYMMDD.log`，避免单文件无限增长。

可复用 Workflow 清单见 [docs/examples/workflows/README.md](examples/workflows/README.md)。

## 维护规则

- 架构、API、部署和运维专题只描述当前行为；尚未实现的决策必须标明状态并记录在 ADR，跨子系统的详细步骤只在一个 `development/` 实施基线中维护。
- 同一事实只在一个专题完整定义，其他页面只给摘要和链接。
- 已完成计划的稳定结论合并到正式专题后，删除计划、批次记录和日期流水账。
- 命令、路径、端口和 profile 必须与源码或发行脚本一致。
- 公共契约、schema、启动拓扑或目录变化时，同一提交更新代码、测试和文档。
- `projectsrc/` 只用于参考审计，不是运行时依赖或公开契约来源。
