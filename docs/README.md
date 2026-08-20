# AMVision 文档

本目录只保存当前可执行的使用说明、长期稳定的架构约束和仍然有效的参考资料。已经完成的实施计划、阶段清单、临时审计记录和重复说明不再保留为正式文档。

## 快速入口

| 目标 | 入口 |
| --- | --- |
| 第一次了解项目 | [平台总览](architecture/system-overview.md) → [当前实现](architecture/current-implementation-status.md) |
| 搭建开发环境 | [开发指南](development/README.md) |
| 启动 API 与前端 | [开发环境启动](deployment/development-environment.md) |
| 组装和部署发行包 | [部署指南](deployment/README.md) |
| 核对系统边界 | [架构文档](architecture/README.md) |
| 调用 REST、WebSocket、ZeroMQ 或 SDK | [API 文档](api/README.md) |
| 开发节点或 Node Pack | [节点扩展](nodes/README.md) |
| 排查现场问题 | [运维与排障](operations/README.md) |
| 查看关键设计取舍 | [架构决策记录](decisions/README.md) |

## 文档分层

```text
docs/
├─ architecture/   当前系统结构、边界、契约和运行时设计
├─ api/            已公开的 API、协议、SDK 和调用示例
├─ development/    开发环境、代码检查、测试和专项验证
├─ deployment/     发行包、运行时、启动、升级和首次部署
├─ operations/     日志、健康检查、恢复和现场排障
├─ nodes/          Node Pack、Custom Node 和扩展接口
├─ decisions/      仍然有效的 ADR；记录“为什么这样设计”
├─ design/         前端产品与视觉设计规范
├─ examples/       可复用的输入、Workflow 和协议示例
└─ legal/          第三方来源与许可证说明
```

`architecture/` 不保存开发任务单，`development/` 不重复架构正文，`operations/` 不承担安装教程。目录入口负责导航，专题文档负责完整说明。

## 当前运行形态

AMVision 当前采用模块化单体与独立执行器：

- `backend-service` 提供 REST API、WebSocket、静态前端和控制面，不消费后台任务队列。
- `inference daemon` 独立托管 DeploymentInstance、预热和推理进程。
- 六个严格 Worker Profile 分别处理数据集导入、数据集导出、训练、转换、评估和异步推理。
- full Supervisor 是完整运行拓扑的唯一所有者，负责数据库迁移、组件启动、健康检查、按 Profile 恢复和停止。
- Workflow App 发布为不可变版本；稳定的 Runtime 与 Trigger id 通过 revision/generation 切换版本，不要求第三方更换调用地址。
- 生产日志按本地日期写入 `*-YYYYMMDD.log`，不会持续追加到一个无限增长的单文件。

更完整的实现状态见 [当前实现](architecture/current-implementation-status.md)。

## 维护规则

- 文档描述当前行为；未来方案只在仍需决策时保留，并明确标记为“未实现”。
- 已完成的计划要把稳定结论合并到架构或开发文档，然后删除计划和阶段记录。
- 命令必须从仓库根目录或发行目录实测，路径、参数和输出名称与代码保持一致。
- 公共 API、持久化结构、启动拓扑或发布目录变化时，同一提交同步更新对应文档。
- 时间点验收只保留可复用的测试入口和通过标准，不在架构正文累计每轮执行流水账。
- 参考源码只用于审计和比对，不能写成运行时依赖。

项目级约束、技术基线和完成标准见 [AGENTS.md](../AGENTS.md)。
