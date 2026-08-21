# Workflow App 版本管理

本文描述已经实现的 Workflow App 发布、Runtime 选版、Trigger 稳定调用和 Run 追溯契约。

## 设计目标

- 编辑中的草稿可以持续修改，不影响已经运行的生产实例。
- 发布结果不可变、可比较、可归档、可恢复和可回滚。
- Runtime 与 Trigger id 保持稳定；切换版本不要求第三方重新下载配置或修改调用地址。
- 一个 Workflow App 可以创建多个 Runtime，并让不同 Runtime 选择不同版本。
- 并发发布、切换、启动、停止、健康检查和旧 worker 回调不能互相覆盖。
- 请求和 Run 必须精确记录实际执行的版本与 worker epoch。

## 资源关系

```text
Workflow App Draft
  ├─ Application document
  └─ Template document
          │ publish
          ▼
WorkflowAppVersion (immutable)
          │ selected by
          ▼
WorkflowAppRuntime (stable id)
  ├─ desired_revision_id
  ├─ active_revision_id
  └─ revision_generation
          │
          └─ WorkflowRuntimeRevision (immutable generation)
                    │
                    ├─ WorkflowRun provenance
                    └─ TriggerSource keeps stable runtime id
```

## 核心不变量

1. 已发布版本的 snapshot、fingerprint 和依赖清单不原地修改。
2. Runtime id 与 Trigger id 是稳定调用标识，版本 id 和 revision id 是不可变来源标识。
3. revision generation 单调递增，回滚通过创建指向历史版本的新 generation 完成，不回退数字。
4. 只有 `published` 版本可以创建新 Runtime 或成为新的切换目标。
5. `archived` 版本仍可支撑已经引用它的 Runtime、Trigger 和历史 Run，但不能新选；恢复为 `published` 后才能再次选择。
6. 切换使用 `expected_generation` CAS；过时请求返回冲突，不隐式重试。
7. 请求开始后固定 revision、version、generation、snapshot fingerprint 和 worker instance。
8. 旧 generation、旧 revision 或旧 worker instance 的状态、heartbeat、结果和取消回调都不能更新当前 Runtime。
9. 活动 Run、启用的 Trigger 或不满足停机条件时，删除和切换必须明确拒绝。

## 草稿保存

编辑器通过一个 Application PUT 保存 Application + Template bundle，不再先后发送两个互不关联的写请求。

保存过程：

1. 获取 Project mutation admission。
2. 按固定顺序获取 Application 与 Template lifecycle claim。
3. 交叉校验 Application 对 Template 的引用和两份文档。
4. 写入持久 bundle journal，保存四个权威对象的原像和 operation id。
5. 按 Template → Application 写入主 JSON 与 sidecar。
6. 提交 journal，再释放 claim。

进程在任一步崩溃时，启动期先恢复未提交 journal，再恢复普通 lifecycle。journal 无法严格清理时启动必须停止并保留 claim，不能把残留恢复记录当作成功。

共享 Template 的独立保存、删除、复制和引用 App 发布使用同一 Template claim。冲突立即返回，不排队、不轮询。

## 发布

发布固定以下内容：

- Application snapshot
- Template snapshot
- 输入与输出契约
- 节点依赖与 Node Pack/Custom Node 实现身份
- 模型、部署和其他稳定 binding
- snapshot fingerprint 与 dependency fingerprint

发布过程先在短事务中创建 `publishing` 记录并占用内容去重键，再写 staging、校验产物、原子移动到最终目录并转为 `published`。失败会进入 `failed`、释放去重占位并清理 staging；启动恢复会收敛未完成发布和孤儿 staging。

同一 App 的普通发布以内容 fingerprint 去重。并发 loser 返回 409，不等待。显式允许重复发布时不占内容去重键。

版本状态：

```text
publishing → published ⇄ archived
     └────→ failed
```

- archive：`published → archived` 的 expected-state CAS。
- restore：`archived → published` 的 expected-state CAS。
- archive/restore 不删除 snapshot、不改 fingerprint、不破坏已有 Runtime。

## Runtime 创建与切换

创建 Runtime 必须明确提供以下二者之一：

- `workflow_app_version_id`
- `application_id`，由服务基于当前一致草稿生成不可变初始版本

两个 selector 同时提供或同时缺失都会被拒绝。

创建时生成 generation 1 revision。切换遵循停机流程：

1. Runtime 必须停止，且没有活动 Run 或启用 Trigger 阻断。
2. 读取目标 `published` 版本并做契约比较。
3. 请求携带当前 `expected_generation`。
4. 最终短事务内再次 fence 目标版本仍为 `published`。
5. CAS 更新 desired pointer/generation，并插入新的 immutable revision。
6. 启动新 worker，校验 revision、generation、fingerprint 和 worker instance。
7. 启动成功后激活 revision；失败则该 revision 标为 `failed`，Runtime 保持可恢复状态。

失败后可以 reset，重新选择同一版本会创建新的 generation，不被前端当成无操作。

回滚与普通切换使用同一流程：目标选择历史 `published` 版本，generation 继续递增。

## 请求、Worker 和并发边界

Runtime manager 为每个稳定 Runtime 使用 lifecycle lock。控制操作按同一顺序获取 lifecycle lock 和 request lock；真正执行请求时不长时间持有数据库事务。

每个 worker handle 固定：

- `workflow_runtime_revision_id`
- `runtime_generation`
- `snapshot_fingerprint`
- `worker_instance_id`

invoke 在进入 worker 前和获得 request lock 后都核对 handle 仍是当前对象。worker command、startup state、heartbeat 和 response 都携带相同身份，manager 再次校验响应。

健康查询为纯读合并，不在同步调用热路径用整对象 UPDATE 覆盖 Runtime 指针。后台状态只通过带 generation/revision/worker-instance fence 的字段级更新持久化。

## Run 追溯

WorkflowRun 保存：

- `workflow_runtime_revision_id`
- `workflow_app_version_id`
- `runtime_generation`
- `snapshot_fingerprint`
- `worker_instance_id`

这些字段创建后不可被后续切换改写。同步 full record 在 worker 不可用、ServiceError、取消或未知异常时收敛为 `failed` 或 `cancelled`，不能永久停在 `dispatching`。

异步 Run 从固定来源、写入 `queued` 到 manager 登记位于同一 lifecycle admission。同步 minimal/none 使用 manager 内存 reservation 阻止并发删除，不增加数据库写、业务队列或自动重试。执行完成或异常时 reservation 必须释放。

## TriggerSource

TriggerSource 只绑定稳定 `workflow_runtime_id`。Runtime 选版不修改 Trigger id、endpoint 或 SDK 配置。

启动顺序保证 Runtime 恢复 ready 后才恢复 enabled Trigger。恢复时验证 revision、version、generation 和 contract fingerprint；`workflow_result`、accepted-then-query 和 event-only 使用各自明确的结果映射语义。

Runtime 仍绑定 Trigger 时，删除返回 409 并列出阻断的 TriggerSource id。

## Project 与 Application 生命周期

Project 使用持久 sentinel/tombstone 协调删除和 project-scoped 写入。Application、Template、版本、Runtime、Trigger、任务、数据集、模型和 Deployment 的控制面 mutation 在短 admission 边界内核对 Project 未删除。

Application lifecycle 使用数据库 CAS、generation 和 operation id。save、copy、publish、archive、restore 和 delete 不持有长数据库事务；ObjectStore I/O 在 claim 后执行，完成时用同一 operation id 收敛。

Project 删除先 claim deleting sentinel，再确认没有活动 mutation，移动文件并在最终事务中删除相关版本、revision、Runtime 和 lifecycle 记录，同时保留 deleted tombstone。迟到写入不能重新创建已删除 Project。

## 持久化对象

主要表：

- `workflow_app_versions`
- `workflow_app_runtimes`
- `workflow_runtime_revisions`
- `workflow_runs`
- `workflow_application_lifecycles`

关键唯一性和外键由 Alembic 管理。默认 SQLite，迁移实现同时保持 MySQL/PostgreSQL 的约束、Boolean、nullable unique 和 batch alter 边界。

发布文件位于 Project 的 Workflow ObjectStore 路径下；staging、bundle journal 和删除恢复目录属于 runtime 恢复数据，不是公开版本产物。

## 前端行为

- 编辑器显示草稿状态、发布版本、与草稿比较和发布操作。
- App 详情按分页读取版本、Runtime 和 Trigger，不截断在前 100 条。
- Runtime 显示 active → target、generation、revision、fingerprint、worker instance 和失败恢复操作。
- 只有契约 fingerprint 变化时才显示 breaking override。
- `published` 可归档，`archived` 可恢复；archived 不出现在新建/切换候选中。
- failed desired revision 可以 reset 后重新选择同一版本。

## API 入口

当前接口与请求字段见：

- [Workflow App 版本 API](../../api/workflow-app-versions.md)
- [WorkflowAppRuntime API](../../api/workflow-app-runtimes.md)
- [WorkflowRun API](../../api/workflow-runs.md)
- [WorkflowTriggerSource API](../../api/workflow-trigger-sources.md)
- [Workflow SDK](../../api/workflow-sdks.md)

OpenAPI 是公开字段的最终来源。

## 验收要求

- 相同内容并发发布只能有一个普通发布成功；显式重复发布保持可用。
- archive 与 create/select 竞态只能线性化为“先引用后归档”或“先归档后 409”。
- health/start/stop/select/invoke 并发时 generation 单调，输出版本与 Run provenance 一致。
- 旧 heartbeat、旧 response、旧 cancel callback 不得污染新 worker epoch。
- Trigger 恢复不得早于 Runtime ready。
- bundle 任意写入阶段崩溃后可恢复四个权威对象，不留下撕裂草稿。
- 历史数据库升级后数据、索引、外键、nullable worker epoch 和版本去重语义保持正确。
- Runtime/Trigger id 在版本切换和回滚后保持不变。

设计取舍见 [ADR-0005](../../decisions/ADR-0005-workflow-app-versioned-runtime.md)。
