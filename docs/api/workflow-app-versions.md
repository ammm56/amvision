# Workflow App 版本接口

## 资源边界

FlowApplication 和 WorkflowGraphTemplate 仍是可修改草稿。`WorkflowAppVersion` 是一次不可变发布物，同时固定 Application、实际解析的 Template、公开输入输出契约、节点依赖清单和内容指纹。保存草稿、发布版本、Runtime 选择版本是三个独立操作；任何操作都不会让既有 Runtime 自动追随最新草稿或最新版本。

公开规则：

- 版本前缀：`/api/v1`
- `WorkflowAppVersion.format_id`：`amvision.workflow-app-version.v1`
- 读取需要 `workflows:read`
- 发布需要 `workflows:write`
- published 版本不允许原地覆盖
- 相同内容默认不能重复发布；确需保留重复发布记录时显式使用 `allow_duplicate_content=true`
- 默认去重由数据库唯一占位保证，并发请求不会同时创建两条相同内容版本

## 当前接口

```text
POST /api/v1/workflows/projects/{project_id}/applications/{application_id}/versions
GET  /api/v1/workflows/projects/{project_id}/applications/{application_id}/versions
GET  /api/v1/workflows/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}
GET  /api/v1/workflows/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}/compare
POST /api/v1/workflows/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}/archive
POST /api/v1/workflows/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}/restore
```

版本列表支持统一的 `offset`、`limit` 查询参数和分页响应头。

## 发布版本

发布使用草稿指纹做 compare-and-swap。调用方必须先读取 Application，取得响应中的 `draft_fingerprint`，再把同一个值放入 `expected_draft_fingerprint`。编辑器保存使用 Application PUT 的可选 `template` bundle，而不是先后发出独立 Template PUT 和 Application PUT。发布和使用 `application_id` 引导创建 Runtime 都按 Application claim→Template resource claim 的固定顺序读取草稿；bundle 保存使用相同顺序，独立 Template PUT/COPY/DELETE 也占用 Template claim。因此共享 Template 被修改时，任意引用 App 的发布或引导创建都会立即返回 409，不会持久化新 Template + 旧 Application 的混合快照。普通 GET 是两个独立文件的无锁读取，不承诺跨两个并发 GET 的线性化视图；调用方在并发保存期间读取后，应以新的 `draft_fingerprint` 刷新。

请求示例：

```json
{
  "expected_draft_fingerprint": "sha256:...",
  "release_notes": "调整空槽分类阈值",
  "display_version": "2026.08.19-r1",
  "allow_duplicate_content": false
}
```

响应包含版本 id/序号、显示版本、快照 object key、content/contract fingerprint、状态、时间、发布主体和错误摘要。发布先用短事务占用 Application lifecycle，再以短事务写 `publishing` 记录和内容去重占位，之后才写入并回读 staging 对象与完成 manifest，最后原子移动到最终目录并改为 `published`。数据库记录先于 staging，因此进程中断后不存在“只有 staging、没有可恢复记录”的新发布。服务启动会恢复或标记未完成发布，并清理异常遗留的孤儿 staging，不会把缺少对象或指纹不匹配的版本提供给 Runtime。

默认发布在写入 `publishing` 记录时原子占用 `(project_id, application_id, content_fingerprint)`。同一 Application 的并发发布通常先由 lifecycle 状态门裁决，竞争请求直接返回 409 和当前操作；数据库唯一内容占位继续作为持久化不变量，防止绕过控制面或异常恢复路径产生重复默认版本。两层裁决都不进入排队或轮询。发布收敛为 `failed` 时释放内容占位，后续请求可以明确重试。`allow_duplicate_content=true` 不占用默认去重键，因此仍可保留有意创建的重复发布记录。

同一 `project_id/application_id` 的保存、发布和删除还共享一行持久化 lifecycle CAS 状态门。状态门只在两个短事务中占用和释放，文件 I/O 不持有数据库事务；竞争操作立即返回 409，不排队、不轮询。共享 Template claim 使用集中生成的保留资源 key，真实 `application_id` 禁止使用 `__amvision_workflow_lifecycle__` 前缀；保留资源在异常和启动恢复后保持 `deleted=false`，不会被 Application tombstone 规则误伤。删除成功保留 tombstone，重新保存同一 id 时以新的 generation 明确恢复。服务启动依次恢复 Project 删除、Application+Template bundle journal、`publishing` 版本，最后才按草稿文件实际存在性释放中断的普通 claim，旧 generation 不能覆盖新操作。

Project 删除使用同表中的保留 sentinel 与 Project 资源写入建立持久化顺序。Application/Template/版本、Preview、执行策略、Runtime、TriggerSource，以及 Task 创建、Dataset 导入/导出提交、Model 训练输出/构建登记和 DeploymentInstance 创建，在一个短事务内通过 sentinel admission 后执行；Project 删除只有在没有活动 claim 时才能进入 `deleting`。先进入的一方生效，另一方返回 409。一次性 Project 资源 claim 在提交后删除，长期运行不会累计记录。删除成功保留 `deleted=true` 的 Project sentinel，防止迟到写复活已经删除的目录。该机制不用于 invoke、Task 事件、Run、取消、heartbeat 或 worker callback，不增加生产推理和 worker 热路径的数据库访问。

草稿物理删除会在同一 lifecycle claim 内检查 `publishing`、`published` 和 `archived` 记录；存在任一可恢复版本时返回 409。已经清理发布文件且只保留诊断信息的 `failed` 记录不阻止草稿删除，但该诊断记录继续保留；若以后重新保存同一 Application id，版本序号仍沿用原审计历史，不从 v1 重新开始。

## 读取和比较

详情响应返回 `application`、`template`、`contract`、`dependencies` 和 `manifest`，用于审计和控制面展示，不进入每次 WorkflowRun 的热路径。

`content_fingerprint` 同时覆盖完整 Application（包括 bindings）、Template、公开 contract、节点定义、node pack manifest 和稳定资源引用。dependency manifest 会把 Template 节点参数和 Application binding 配置中的稳定资源 id 展开列出，便于直接审计。节点实现身份只使用项目已有的稳定来源：core node 使用 `NodeDefinition.version`，custom node 使用 node definition version、node pack version 和 manifest SHA-256；不会扫描工作区或把实时文件状态写进发布身份。core 实现或 custom node pack 代码变化时必须同步推进相应版本/manifest。worker 启动后会按实际加载的节点目录重新计算同一指纹；依赖漂移或版本资产损坏都会阻止 revision 激活。

`compare` 固定表示“指定已发布版本 -> 当前草稿”的公开契约差异，返回 `compatible`、`changes`、`breaking_changes` 和 source/target contract fingerprint。非破坏性修改仍需要显式发布和 Runtime 停机选择版本，不会自动生效。

## 归档和恢复

归档只把版本从 `published` 改为 `archived`，不会删除 snapshot、修改 fingerprint 或影响已经引用该版本的 Runtime、Trigger 和 Run。归档版本不再用于新建 Runtime 或切换版本；恢复为 `published` 后才会重新成为候选。

两个操作都使用调用方读取到的状态做 compare-and-swap：

```json
{
  "expected_state": "published"
}
```

归档请求只接受 `published`；恢复请求使用同一结构并把值改为 `archived`。状态已经变化时返回 409，不排队、不自动重试。

## Runtime 使用规则

新建 Runtime 优先传准确的 `workflow_app_version_id`。也可以传 `application_id`，由服务基于当前一致草稿创建不可变初始版本；两个字段必须且只能提供一个。Runtime 升级与回滚统一使用 `select-version`，详见 [WorkflowAppRuntime 接口文档](workflow-app-runtimes.md)。

create 和 `select-version` 会在最终数据库事务内用目标版本行的条件 UPDATE 再确认版本仍为 `published`，随后才写 Runtime/revision。archive 使用同一版本行完成状态 CAS，所以 archive 成功提交后不会再出现指向该 archived 版本的新 Runtime/revision；已经先提交的历史引用继续有效。竞争失败立即返回 409，不排队、不自动重试。restore 只把版本从 `archived` CAS 回 `published`，之后的新引用仍必须经过相同 fence。

## 数据库和迁移

升级已有环境前执行：

```powershell
conda activate amvision
python -m backend.maintenance.main migrate-database --output text
```

迁移增加 `workflow_app_versions`、`workflow_runtime_revisions`、`workflow_application_lifecycles` 及 Runtime/Run 来源字段，并增加仅用于数据库并发裁决的 nullable `content_deduplication_key`。lifecycle 表使用 `(project_id, application_id)` 复合主键，`generation + operation_id` 负责过期操作隔离，`deleted` 保存物理删除 tombstone；实现只使用 SQLAlchemy 通用类型和条件更新，可迁移到 SQLite、MySQL 和 PostgreSQL。历史相同内容版本不会被删除：每组非 failed 版本只选择一条规范记录持有默认占位，其余记录保持可读且占位为空。服务启动后以每个旧 Runtime 自己的快照为事实来源做幂等导入，保留原 `workflow_runtime_id`、TriggerSource id、协议地址和 SDK 配置。

## 相关文档

- [Workflow App 版本管理与 Runtime 稳定切换设计](../architecture/workflows/app-versioning.md)
- [WorkflowAppRuntime 接口文档](workflow-app-runtimes.md)
- [WorkflowRun 接口文档](workflow-runs.md)
- [SDK 配置包](sdk-config-packages.md)
