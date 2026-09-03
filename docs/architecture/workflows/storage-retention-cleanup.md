# 保存结果保留清理节点

## 状态

本文定义规划中的 `core.io.storage-retention-cleanup` 节点。该节点尚未实现；实现、节点参数、输出字段和测试必须以本文为边界，不能在 Save 节点或 Runtime 中增加隐式清理行为。

## 目标

生产现场保存的图片、视频、JSON、文本和其他结果文件通常只保留一个月、三个月或一年，也可能只保留最新 1000 个文件。节点用于在一次明确的 Workflow 调用中，按保存时间、最大文件数量或两者组合清理指定结果目录。

节点遵循以下执行边界：

- 节点被调用时立即执行一次扫描和清理。
- 不创建常驻线程、定时线程、后台扫描器或内部调度器。
- 不提供 `check_interval_hours`，不保存 `last_run_at` 或 `next_due_at`。
- 调用频率完全由 Workflow Runtime 的实际调用频率或外部调度决定。
- 不向同步调用增加队列、排队等待或隐藏重试。

保留期限不加入 Save Image、Save Video、Save JSON 或 Save Text。保存和删除是不同副作用：Save 节点只负责原子写入，清理节点只负责显式删除。该边界避免多个 Save 节点重复扫描同一目录，也避免普通保存操作隐藏触发删除。

## 当前能力边界

当前 Core Node 没有生产结果保留期限清理节点：

- `core.io.directory-scan` 只能列举本地文件、读取修改时间并执行过滤，不负责删除。
- `backend-maintenance cleanup-runtime-storage` 只清理平台 Runtime、Preview 和临时输入等内部数据，不能用于生产结果目录。
- `LocalDatasetStorage.delete_tree()` 是基础设施内部的整树删除操作，不具备逐文件期限判断和并发条件删除语义，不能直接暴露为该节点实现。
- `ObjectStore` 端口尚未定义分页列举、最后修改时间和条件删除能力。

## 节点定义

| 项目 | 规划值 |
| --- | --- |
| Node type id | `core.io.storage-retention-cleanup` |
| Display name | `Storage Retention Cleanup` |
| Category | `core.io.file` |
| Runtime | Python callable Core Node |
| Input | 可选动态 `target_directory: value.v1` |
| Output | `result: value.v1` |

`target_directory` 的连接值优先于固定参数值，与 Save 节点动态参数的优先级规则一致。节点只输出一个完整结果对象，不拆分为互相依赖的多个输出。

### 参数

| 参数 | 类型与默认值 | 规则 |
| --- | --- | --- |
| `target_directory` | string，必填 | 绝对目录表示 Runtime 主机文件系统；相对目录表示 ObjectStore prefix |
| `retention_policy` | `age`、`count`、`age-and-count`，默认 `age` | 明确选择时间、数量或组合策略 |
| `retention_value` | integer，最小 1 | `age`、`age-and-count` 必填；时间保留数量 |
| `retention_unit` | `day`、`month`、`year` | `age`、`age-and-count` 必填；时间保留单位 |
| `max_file_count` | integer，最小 1 | `count`、`age-and-count` 必填；匹配范围最多保留的物理文件数 |
| `recursive` | boolean，默认 `true` | 是否递归处理子目录 |
| `include_patterns` | string array，默认 `["*"]` | 按文件名匹配；空数组不合法 |
| `delete_empty_directories` | boolean，默认 `false` | 删除文件后是否清理空子目录；永远不删除目标根目录 |
| `delete_limit` | integer，默认 `1000`，最小 1 | 单次调用最多删除的文件数量 |
| `dry_run` | boolean，默认 `true` | 只扫描并返回统计，不执行删除 |

不增加以下参数：

- `check_interval_hours`：节点没有内部调度职责。
- `max_scan_files`：没有持久化游标时限制扫描数量可能使目录后部文件永久无法被检查。
- `on_delete_error`：权限、磁盘或未知 I/O 错误不能通过配置静默忽略。

参数校验必须按策略执行：`age` 不接受缺失的时间参数，`count` 不接受缺失的 `max_file_count`，`age-and-count` 要求两组参数同时完整。未被当前策略使用的参数不参与运行时判断。

扫描必须逐项处理，不能把完整目录列表或完整删除清单一次性加载进内存。`delete_limit` 只限制本次实际删除数量；达到上限后返回 `has_more=true`，下次调用从仍然存在的文件继续清理。

`dry_run=true` 时不应用删除数量上限，必须流式检查完整目标范围，才能给出真实的候选文件和容量统计。

## 目录与时间语义

### 目标目录

目标必须是稳定的结果根目录。清理目录不展开 Save 节点的日期时间模板，避免只扫描当前日期目录。

例如：

```text
Save directory:    D:\results\{YYYY}\{MM}\{DD}
Retention target:  D:\results
```

目标目录不存在时是成功的幂等空操作，返回 `state=target_not_found`，不能导致 Workflow 失败。空目录返回 `state=completed` 且计数均为零。

文件系统路径必须拒绝磁盘根目录、用户主目录、项目根目录和平台数据根目录本身；这些目录的正常结果子目录仍可使用。路径解析后如果目标自身是符号链接、junction 或 reparse point，也必须拒绝。ObjectStore 模式只允许清理当前 `project_id/application_id` 对应的 `projects/<project-id>/results/workflow-applications/<application-id>/` 结果命名空间，必须拒绝空 prefix、父目录引用和其他 Project、模型、数据集、Runtime 等命名空间。节点不得删除目标根目录本身。

### 保留期限

一次节点调用只捕获一个 Runtime 主机本地时间点。截止时间按照以下规则计算：

- `day` 使用本地日历日递减。
- `month` 使用日历月递减，目标月份不存在同一日时收敛到该月最后一天。
- `year` 使用日历年递减，并正确处理闰年二月。
- 只删除 `last_modified_time < cutoff_time` 的文件；等于截止时间的文件继续保留。

文件名中的日期不参与保留期限判断。所有 Save 节点必须保证最终发布文件的 `last_modified_time` 表示本次发布完成时间，不能因复制源文件而保留与本次保存无关的旧时间。

## 数量保留语义

`retention_policy=count` 时，节点在 `include_patterns` 匹配范围内最多保留最新的 `max_file_count` 个物理文件。文件使用以下稳定顺序从旧到新排列：

1. `last_modified_time` 从早到晚。
2. 时间相同时，按规范化相对路径或 ObjectStore key 的字典序排列。

目录枚举顺序、节点位置和文件名中是否包含日期均不参与关系判断。例如目标中有 1200 个匹配文件且 `max_file_count=1000` 时，最旧的 200 个文件属于删除候选，最新的 1000 个继续保留。

`include_patterns` 中的多个模式共享一个数量上限；同一文件同时匹配多个模式时只统计一次。例如 `["*.jpg", "*.json"]` 表示 JPG 和 JSON 合计最多保留 `max_file_count` 个文件。需要分别保留 1000 张 JPG 和 1000 个 JSON 时，应配置两个清理节点，分别使用单独的匹配范围。

### 时间和数量组合

`retention_policy=age-and-count` 时，两种约束必须同时成立：

1. 所有早于时间截止点的文件进入候选。
2. 假设时间过期文件已移除；剩余文件仍超过 `max_file_count` 时，继续把其中最旧的文件加入候选。
3. 所有候选使用同一稳定顺序，从最旧文件开始执行删除。

时间候选和数量候选都是稳定最旧顺序的前缀，因此组合候选数量等于两者候选数量的较大值，不能因先执行时间策略还是数量策略而产生不同结果。

### 有界内存算法

数量策略采用两次流式扫描，不能把全部 metadata 加载后整体排序：

1. 第一次扫描计算匹配文件总数、时间过期数量和策略需要清理的候选数量。
2. 本次实际选择数量为 `min(候选数量, delete_limit)`。
3. 第二次扫描使用有界 heap 选出该数量的最旧文件。
4. 对候选重新校验并执行条件删除。

内存复杂度固定为 `O(delete_limit)`，不随目录文件总数增长。`dry_run=true` 时只需完成第一次全量流式统计，不构造或保留完整候选路径列表。两个 Runtime 同时执行相同配置时必须选择同一批最旧文件；一个实例已经删除的文件由另一个实例记入 `skipped_missing_count`，不能转而多删下一批文件。

### 物理文件和执行记录

`max_file_count` 只表示物理文件数量。一次 Workflow 执行只保存一个文件时，它可以等价表示执行记录数量；一次执行同时保存图片、JSON 和其他附件时，不能把 1000 个文件描述为 1000 条执行记录。

当前节点 v1 不根据文件名、相邻顺序或时间接近程度推断多个文件属于同一执行。按执行记录数量整体保留需要独立的受管理结果组契约，以明确的 `workflow_run_id` 或 `result_record_id` 作为分组身份，并保证整组发布和整组删除。该能力不混入 `max_file_count`，避免再次形成隐式位置或命名关联。

## 文件选择和删除边界

扫描和删除必须遵循以下规则：

- 只处理普通文件，不跟随符号链接、Windows junction 或其他 reparse point。
- `include_patterns` 只匹配文件名，不把文件名解释为路径。
- 自动跳过 `.amvision-*` 控制目录、原子写入临时文件和 write journal。
- `recursive=false` 时只处理目标目录直属文件。
- `delete_empty_directories=true` 时按最深层优先删除已经为空的子目录；目标根目录和内部控制目录始终保留。
- 单个文件已被其他实例删除时按预期并发跳过处理，不作为错误。
- 文件被重新写入、修改或占用时不删除，计入对应 `skipped_*_count`，等待下一次外部调用重新判断。
- 权限不足、存储损坏或未知 I/O 错误必须使节点失败，并在结构化错误详情中携带有界统计和错误样本。

## 并发与原子性

同一个 Workflow App 可以部署多个 Runtime 实例，因此不能依赖单进程锁或“先检查、后删除”。

文件系统实现需要新增 Save 与 Retention 共用的目标文件协调机制：

1. Save 节点在最终原子发布期间持有目标文件的跨进程锁。
2. Retention 节点对候选文件尝试非等待锁；锁已被占用时立即跳过，不排队等待。
3. 获得锁后重新读取文件标识、大小和最后修改时间。
4. 只有文件仍与扫描记录一致且仍早于截止时间时才执行原子删除。
5. 进程退出后锁由操作系统释放；锁文件位于受控 `.amvision-*` 目录并被清理扫描排除。

ObjectStore 不能依赖本机路径或 `resolve()` 实现相同语义。需要新增独立的可选 capability port，而不是直接扩大现有 `ObjectStore` 基础端口：

- 分页列举指定 prefix 下的对象。
- 返回 object key、大小、最后修改时间和不可变版本标识。
- 按版本标识执行条件删除。
- 对象已经不存在或版本已变化时返回未删除，不得删除新版本。

本地 `LocalDatasetStorage` 实现该 capability；未来云对象存储 adapter 使用 ETag、version id 或供应商条件删除实现。节点在当前 ObjectStore 不支持该 capability 时明确失败，不能退化为无条件 `delete_tree()`。

## 输出契约

`result.value` 使用以下版本化格式：

```json
{
  "format_id": "amvision.storage-retention-cleanup-result.v1",
  "state": "completed",
  "target_directory": "D:\\results",
  "location_kind": "filesystem",
  "retention_policy": "age",
  "retention_value": 3,
  "retention_unit": "month",
  "cutoff_time": "2026-06-03T08:00:00+08:00",
  "dry_run": false,
  "scanned_file_count": 5000,
  "matched_file_count": 5000,
  "eligible_file_count": 327,
  "deleted_file_count": 327,
  "deleted_size_bytes": 198273211,
  "skipped_changed_count": 0,
  "skipped_locked_count": 0,
  "skipped_missing_count": 0,
  "failed_file_count": 0,
  "has_more": false,
  "duration_ms": 186
}
```

数量策略在相同结果格式中使用对应字段：

```json
{
  "format_id": "amvision.storage-retention-cleanup-result.v1",
  "state": "partial",
  "target_directory": "D:\\results",
  "location_kind": "filesystem",
  "retention_policy": "count",
  "max_file_count": 1000,
  "dry_run": false,
  "scanned_file_count": 1200,
  "matched_file_count": 1200,
  "eligible_file_count": 200,
  "deleted_file_count": 100,
  "deleted_size_bytes": 52718321,
  "skipped_changed_count": 0,
  "skipped_locked_count": 0,
  "skipped_missing_count": 0,
  "failed_file_count": 0,
  "has_more": true,
  "duration_ms": 92
}
```

时间字段只在 `age` 和 `age-and-count` 中出现，`max_file_count` 只在 `count` 和 `age-and-count` 中出现。不能使用 `null` 代替未启用策略的字段。

`state` 只使用以下值：

- `dry_run`：完成扫描但没有删除。
- `target_not_found`：目标目录尚未创建。
- `completed`：本次清理完成且未达到删除上限。
- `partial`：达到 `delete_limit`，仍可能存在符合条件的文件。

默认不返回完整删除路径列表，避免结果体和 Workflow 内存随文件数量增长。失败详情只保留有界错误样本。

## Workflow 编排

推荐使用独立维护 Workflow App，由现场已有调度系统、Windows Task Scheduler 或其他外部调用方按需要调用 HTTP Runtime：

```text
外部定时调用
  -> String Value（稳定结果根目录）
  -> Storage Retention Cleanup
  -> Workflow Result
```

该方式没有平台常驻定时线程，也不会增加检测 Workflow 的正常调用耗时。

该节点不改变 App Entry、HTTP Runtime、ZeroMQ、Local Shared Memory Trigger 或 .NET SDK 协议。调用方只负责正常触发 Workflow；除非 Workflow 把清理参数公开为 App Entry 输入，否则调用请求不需要增加保留期限字段。

节点也可以直接加入检测 Workflow。此时每次检测调用都会执行一次完整清理检查，不存在内部间隔判断；到期文件较多时会增加该次 Workflow 耗时，必须根据现场目录规模决定是否采用。

## 实现顺序

1. 新增与节点无关的时间、数量和组合保留策略计算服务。
2. 新增 ObjectStore retention capability 及分页对象 metadata 契约。
3. 实现本机文件系统和 `LocalDatasetStorage` adapter。
4. 增加 Save 与 Retention 共用的跨进程、非等待目标文件锁。
5. 保证所有 Save 文件的最后修改时间代表发布完成时间。
6. 实现两次流式扫描和 `O(delete_limit)` 的确定性最旧文件选择。
7. 实现 `core.io.storage-retention-cleanup` 的 NodeDefinition、handler 和参数输入绑定。
8. 更新节点目录、前端参数显示、Workflow 示例和架构说明。
9. 使用真实保存结果和多 Runtime 并发完成验收。

## 验收要求

- Save Image、Save Video、Save JSON、Save Text 和 CSV 等结果文件均可由同一节点清理。
- `dry_run=true` 时磁盘和 ObjectStore 内容完全不变。
- 日、月、年和月末、闰年截止时间测试通过。
- `count` 可以从 1200 个文件中稳定删除最旧的 200 个并保留最新 1000 个。
- `age-and-count` 的结果不受时间策略和数量策略计算顺序影响。
- 相同修改时间的文件始终按规范化路径稳定选择。
- 多个 `include_patterns` 共享数量上限，不产生隐式的分类型配额。
- 目标不存在、目录为空和没有到期文件时幂等成功。
- 日期分层目录可以从稳定父目录递归清理，并按配置删除空子目录。
- 两个 Runtime 实例同时清理同一目录时，不重复删除、不误删刚发布或刚覆盖的文件。
- 文件被占用、文件已变化和文件已经不存在时按预期跳过；权限和 I/O 错误明确失败。
- 文件系统与 LocalDatasetStorage 的行为和输出字段一致。
- 大目录数量策略采用两次流式扫描，额外内存保持 `O(delete_limit)`，结果体有界，执行前后 process handle 和 Private Memory 不持续增长。
- 连续多轮清理、Runtime 重启和异常中断后不遗留无限增长的线程、句柄、锁或临时文件。
