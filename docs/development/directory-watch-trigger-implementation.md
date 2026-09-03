# 目录变化 Trigger 实施基线

## 状态与用途

本文定义并记录 `directory-watch` 从“稳定文件批次提交”收敛为“目录变化有界合并通知”的实现基线。后端契约、固定窗口聚合器、Adapter、创建校验、health 和集成页面已经按本文完成；持续 24 小时以上的现场 soak 仍属于发布验收门禁。

目标场景是本地生产结果目录的变化通知、监视 Workflow 唤醒和维护 Workflow 调用。设计优先保证 Trigger 内部没有无界路径集合、文件批次队列和隐式后台恢复，不把每个文件可靠投递、目录导入队列或文件内容传输混入 `directory-watch`。WorkflowRun 的接纳、排队、拒绝和执行容量统一由 Workflow Runtime 负责，目录 Trigger 不另设执行调度规则。

`directory-poll` 保留现有周期扫描、文件批次和 checkpoint 语义。逐文件导入、每个文件必须处理和断点恢复属于 `directory-poll` 或独立持久导入队列的范围，不属于本文。

## 已确认结论

1. 目录变化是 TriggerSource 的一种外部事件源，与 ZeroMQ、本机共享内存和 PLC Trigger 位于同一层，不是常驻 Workflow Node。
2. Workflow Node 只在 WorkflowRun 已经开始后执行，不能通过常驻等待目录变化来触发自身运行。
3. `directory-watch` 只通知目录状态发生变化；Workflow 通过 `Directory Latest File`、`Directory Scan`、`Load Local Image`、`Load Local JSON` 或 `Load Local Text` 读取执行时的真实目录状态。
4. `directory-watch` 始终产生标准化事件；是否把事件映射到 Workflow App Entry，由 TriggerSource `input_binding_mapping` 显式决定。
5. App Entry 的 `request_json` 保持可选。目录 Trigger 可以把完整事件映射到该 binding；不需要事件数据的维护 Workflow 可以不映射。
6. 目录变化默认使用 3 秒最小触发间隔。一个窗口内的所有变化只产生一次提交。
7. 连续变化按相邻 3 秒窗口合并；每个到期且包含变化的窗口都执行一次正常 Trigger 调用，不受上一轮 WorkflowRun 是否完成影响。
8. Adapter 只保留当前窗口的有界聚合状态和提交所需的不可变快照，不保存活动 Run 身份，不实现文件批次队列。
9. 不恢复服务重启前尚未提交的聚合窗口、样本或待触发状态。重启后的下一次真实目录变化重新开启窗口，Workflow 再读取当前目录状态。
10. 不自动重试失败的 WorkflowRun。Trigger 提交失败写入 health；后续真实变化可以重新触发。
11. 事件只携带有界计数和最近变化样本，不携带所有变化文件，不读取图片、JSON、文本或其他文件内容。
12. 默认最多携带 10 个最近变化的不同文件路径。样本限制不是 App Entry binding 数量，也不是待处理文件批次大小。
13. 样本按变化观察顺序倒序返回；同一路径在一个窗口内只保留一条样本，记录该路径最近一个 watcher batch 中观察到的变化类型，不推断无法证明的最终变化类型。
14. 删除样本表示最近观察到的删除变化，不表示被删除文件原始修改时间。没有持久目录快照时不得声称可以按已删除文件的原始时间排序。
15. 一个底层监听批次没有真实逐文件时间顺序时，使用规范化路径作为固定次序补充，保证结果可复现，但不伪装成操作系统的真实删除顺序。
16. `directory-watch` 不提供 `file-batch` 模式，不增加 backlog、批次并发、批次恢复或重启补偿设置。
17. Trigger 到 Runtime 保持单向提交边界。目录 Trigger 不查询 WorkflowRun 状态，不等待上一轮执行完成，也不根据 Runtime 忙闲改变是否触发。
18. 同一个 Workflow Runtime 可以绑定多个 `directory-watch` TriggerSource；每条 TriggerSource 独立监听、独立聚合、独立提交，不做跨 Trigger 去重或合并。
19. 平台不分析 Workflow 中 Save 节点的目录，不判断监控目录与输出目录是否重叠，不警告或阻止可能的自触发循环。目录和过滤规则由配置者负责。

## 层级关系

```text
File system
  -> DirectoryWatchTriggerAdapter
       -> normalized RawTriggerEvent
            -> TriggerSource input binding mapping
                 -> WorkflowAppRuntime submit
                      -> WorkflowRun
                           -> App Entry
                                -> Workflow Nodes
                                     -> App Result
```

各层职责固定如下：

| 层 | 职责 | 不承担的职责 |
| --- | --- | --- |
| File system watcher | 接收新增、修改和删除通知 | 创建 WorkflowRun、读取业务文件 |
| Directory Trigger adapter | 过滤路径、合并窗口、维护有界样本、按窗口提交事件 | 文件内容解析、逐文件可靠队列、查询 Runtime 执行状态 |
| TriggerSource mapping | 把事件显式映射到已发布 App Contract | 猜测 App Entry binding |
| Workflow Runtime | 创建和执行 WorkflowRun | 常驻扫描业务目录 |
| Directory/Load Node | 读取执行时目录状态和明确文件 | 监听并触发自身 Workflow |

## 触发窗口

### 参数

```json
{
  "min_trigger_interval_seconds": 3.0
}
```

默认值为 `3.0` 秒。公开范围固定为 `1.0` 至 `3600.0` 秒，避免目录 watcher 因过短间隔形成无意义的高频唤醒；后端 schema 是唯一范围事实源，前端不得单独放宽。

### 窗口语义

首次匹配变化到来时开启窗口，截止时间为：

```text
window_deadline = first_change_monotonic + min_trigger_interval_seconds
```

窗口截止前不提交 WorkflowRun。窗口内新增、修改和删除事件只更新计数、最近样本和 `has_changes` 状态。窗口到期后生成一份不可变事件快照并执行一次 Trigger 调用。

该语义不是 trailing debounce。持续变化不会无限推迟触发，而是按固定窗口持续收敛：

```text
00s--03s -> event 1
03s--06s -> event 2
06s--09s -> event 3
```

### 统一提交规则

目录变化 Trigger 与其他 TriggerSource 使用同一提交边界：

- 每个到期且包含匹配变化的窗口调用一次 `handle_trigger_event()`。
- 上一轮 WorkflowRun 正在 queued、running 或已经终态，都不改变当前窗口的触发行为。
- Adapter 不读取 WorkflowRun，不等待执行完成，也不维护 `active_workflow_run_id`。
- Workflow Runtime 按自身统一规则决定接纳、排队或拒绝；Trigger 只记录本次提交立即返回的结果。
- 连续变化且间隔为 3 秒时，正常情况下每 3 秒产生一次调用；Workflow 执行耗时不会把该频率隐式降低。
- 如果实际处理速度不足，由配置者把 `min_trigger_interval_seconds` 调整为 10 秒或其他合适值，不在 Adapter 中增加目录协议专用的背压逻辑。
- 没有变化的窗口不创建事件，不调用 Runtime。

该设计只限制目录变化合并后的调用频率，不限制 Runtime 中允许存在多少 WorkflowRun。Runtime 容量、队列上限和 admission policy 必须作为所有 Trigger 与 HTTP 调用共用的运行时能力实现，不能由目录 Trigger 反向获取状态后单独处理。

### 提交调用与停用边界

`handle_trigger_event()` 的本地提交调用和后续 WorkflowRun 执行是两件事。目录 Trigger 不等待 WorkflowRun，但当前 Adapter 线程仍需等待本地提交调用返回。为保持实现简单，不为目录 Trigger 增加额外 dispatcher、提交线程池或内部提交队列。

- 正常 async 提交只负责创建 WorkflowRun，应快速返回 accepted 或结构化失败。
- 如果本地提交调用本身阻塞超过触发间隔，后续 watcher 观察和窗口提交可能延迟；不能伪造仍然按时触发。health 必须记录提交耗时和延迟窗口次数。
- 提交调用返回后继续处理 watcher 已收集的变化，不因上一轮 WorkflowRun 仍在执行而停止后续提交。
- stop 标记和 `submit_call_in_progress` 必须在同一状态锁内更新，二者先获得锁的一方确定停止线性化顺序。stop 之前已经登记开始的提交允许完成，已经创建的 WorkflowRun 不取消；stop 先登记后不得开始新的提交。
- disable/delete 必须等待 watcher 线程完全退出后才能移除 Adapter 状态。等待超时应返回明确失败并保留 stopping/failed 状态，不能留下不可管理的后台线程。

### 与现有 debounce 的关系

TriggerSource 顶层 `debounce_window_ms` 当前只抑制窗口内后续事件，被抑制事件不会在窗口结束后重新提交，也不会合并进下一份 payload。目录变化不能复用该语义。

目录协议模板必须清空并隐藏通用 `debounce_window_ms`，改用 `transport_config.min_trigger_interval_seconds`。`watch_debounce_ms`、`watch_step_ms` 和 `watch_timeout_ms` 属于文件系统 watcher 内部调度参数，不作为业务触发间隔展示。

## 有界内存状态

每条 enabled `directory-watch` TriggerSource 只维护：

```text
window_started_monotonic
window_started_at
window_deadline_monotonic
created_count
modified_count
deleted_count
window_observed_sequence
samples[0..event_sample_limit]
samples_truncated
has_changes
submit_call_in_progress
last_submitted_at
```

状态不保存所有变化路径。达到样本上限后只更新计数、截断标记，并按最近变化规则替换最旧样本。Adapter 跨 watcher yield 长期保留的状态复杂度为 `O(event_sample_limit)`。

`watchfiles` 每次 yield 的原始变化集合由依赖库完整构造，其瞬时内存取决于该批次变化数。Adapter 不得再复制或完整排序该集合，只允许单次遍历并使用固定容量结构选择诊断样本。因此不能承诺进程峰值内存与单批文件数无关，只能承诺处理完成后没有按文件数长期保留的 Python 容器。

关闭、删除 TriggerSource 或 backend-service 退出时，未提交状态直接释放。启动时不扫描现有文件，不恢复退出前窗口，不把已有文件伪装成新变化。

watcher 写入和窗口提交必须使用同一窄锁执行原子 snapshot-and-swap：锁内只把当前聚合器替换为新的空聚合器，锁外完成 JSON 构造和 Workflow 提交。边界时刻到来的文件事件必须进入旧快照或新窗口之一，不能丢失，也不能同时进入两份事件。提交前必须再次检查 stop；具体停用语义以上述停止线性化点为准。

## 最近变化样本

### 配置

```json
{
  "event_sample_limit": 10
}
```

默认值为 `10`，建议范围为 `0` 至 `100`。`0` 表示只返回计数，不返回路径样本。

### 选择规则

- 样本表示窗口内最近观察到变化的不同文件路径。
- 输出按 `observed_sequence` 倒序排列，最新变化在前。
- `observed_sequence` 只在当前聚合窗口内从 1 单调增加，新窗口重新从 1 开始；它不是跨窗口或跨重启的持久游标。
- 同一路径后续再次变化时移动到最新位置，并用最新 watcher batch 的 `observed_change_types` 替换旧值；不需要为了记住已淘汰路径的历史而保存无界状态。
- 同一个无序 watcher batch 对同一路径报告多种变化时，把变化类型合并进固定最多三项的 `observed_change_types`。
- `observed_change_types` 使用固定顺序 `created`、`modified`、`deleted`，只表示该路径最近一批观察事实，不表示文件最终状态。
- 文件重命名按 watcher 实际提供的旧路径删除和新路径创建表示，不增加无法跨平台稳定保证的 `renamed` 类型。
- 达到上限后淘汰最早变化样本，并永久设置本窗口 `samples_truncated=true`。
- `change_counts` 统计观察到的原始变化次数；重复修改同一文件会增加计数，但不会占用多个样本。

底层 watcher 可能一次返回无序变化集合。Adapter 不得为了稳定顺序完整排序整个集合；使用容量为 `event_sample_limit` 的有界选择结构，按规范化路径提供同批次内的确定性次序补充，再只对最终入选样本排序和分配 `observed_sequence`。该次序不代表真实的逐文件发生顺序。同一路径在同一无序批次出现多种变化时合并 `observed_change_types`，不选择虚假的最终类型。

### 删除事件

删除后通常只能获得路径，不能重新读取 size、mtime 或 checksum。删除样本按删除变化的观察顺序参与最近样本选择：

- “最新删除样本”表示最近被 Adapter 观察到删除的路径。
- 不表示被删除文件中原始修改时间最新的文件。
- 不为样本排序维护完整目录 metadata 快照。

## 标准事件

目录事件的公开值使用 `amvision.directory-change-event.v1`：

```json
{
  "format_id": "amvision.directory-change-event.v1",
  "event_id": "directory-watch-event-0123456789abcdef",
  "trigger_source_id": "directory-watch-workflow-runtime-0123456789abcdef-a1b2c3d4",
  "workflow_runtime_id": "workflow-runtime-0123456789abcdef",
  "window_started_at": "2026-09-03T02:00:00.000Z",
  "window_finished_at": "2026-09-03T02:00:03.000Z",
  "min_trigger_interval_seconds": 3.0,
  "directory": {
    "path": "T:\\results",
    "recursive": false,
    "glob_pattern": "*.result.json",
    "extensions": [".json"]
  },
  "change_counts": {
    "created": 20,
    "modified": 0,
    "deleted": 0,
    "total": 20
  },
  "samples": [
    {
      "observed_change_types": ["created", "modified"],
      "path": "T:\\results\\result-020.result.json",
      "relative_path": "result-020.result.json",
      "observed_at": "2026-09-03T02:00:02.900Z",
      "observed_sequence": 20
    }
  ],
  "sample_limit": 10,
  "sample_count": 10,
  "samples_truncated": true
}
```

字段语义：

| 字段 | 规则 |
| --- | --- |
| `event_id` | 每次实际提交生成 UUID 风格唯一值，不复用文件路径或非持久观察序号 |
| `window_started_at` | 本次聚合窗口第一次匹配变化时间 |
| `window_finished_at` | 事件快照完成时间，不等于 Workflow 开始时间 |
| `change_counts` | 原始观察次数；三类总和必须等于 `total` |
| `samples` | 有界、不同路径、最近变化优先的诊断样本 |
| `samples_truncated` | 本窗口曾因上限淘汰样本时为 true |

所有公开时间使用带时区的 UTC ISO 8601。样本永远是诊断信息，不是可靠文件清单；`samples_truncated=false` 只表示本次 Adapter 已观察到的不同变化路径都能放入当前样本集合，不表示 watcher 没有丢失或合并底层事件，也不表示文件内容仍存在、完整或稳定。需要当前目录事实时始终由目录节点读取，因此不提供容易被误解成可靠性保证的 `rescan_required` 字段。

Adapter 的 `RawTriggerEvent.payload` 同时提供统一 value 包装：

```json
{
  "directory_event_value": {
    "value": {
      "format_id": "amvision.directory-change-event.v1"
    }
  }
}
```

推荐 App Entry 映射：

```json
{
  "request_json": {
    "source": "payload.directory_event_value",
    "required": false,
    "payload_type_id": "value.v1"
  }
}
```

App Entry 没有 `request_json` 或 Workflow 不需要事件内容时可以不创建 mapping；Trigger 仍可调用没有必填输入的 App。

## 请求容量

数量上限不是唯一保护。后端必须对最终 `RawTriggerEvent` 执行 UTF-8 JSON 序列化容量检查，并使用固定硬上限，目标默认不超过 64 KiB。

目录事件是状态变化通知，样本不承担可靠文件投递。因此达到容量边界时按以下顺序收敛：

1. 保留格式、来源、时间窗口和全部计数。
2. 从最旧样本开始减少样本。
3. 设置 `samples_truncated=true`。
4. 即使样本减少为零仍超过硬上限时拒绝提交并记录明确 health 错误；不得截断 JSON、路径或字段文本。

64 KiB 是目录事件内部 JSON 的目标保护值，不复用或改变 ZeroMQ、LocalMessage mailbox 的传输上限。

## 目录过滤与写入完整性

公开目录配置保留：

```json
{
  "directory_path": "T:\\results",
  "recursive": false,
  "include_hidden": false,
  "glob_pattern": "*.result.json",
  "extensions": [".json"],
  "event_types": ["created", "modified", "deleted"],
  "min_trigger_interval_seconds": 3.0,
  "event_sample_limit": 10,
  "force_polling": null,
  "poll_delay_ms": 300,
  "ignore_permission_denied": false
}
```

- `event_types` 至少选择一项，枚举固定为 `created`、`modified`、`deleted`。
- `glob_pattern` 针对监控根目录下的相对路径，`extensions` 是额外过滤条件，两者使用 AND 关系；空 `extensions` 表示不限制扩展名。
- `directory_path` 去除两端空白后长度为 1 至 4096，禁止 NUL，必须是明确绝对路径；不接受依赖 backend-service 工作目录的相对路径或 `~` 展开。创建时允许目录暂不存在，enable 时必须存在且是可读目录。
- `glob_pattern` 去除两端空白后长度为 1 至 256，禁止绝对路径、NUL 和 `..` 路径分段；`recursive=false` 时拒绝 `**`。
- extensions 最多 32 项，每项规范化后长度为 2 至 32，只允许一个前导点和不含路径分隔符、NUL、`*`、`?` 的扩展名；统一转成小写、去重并稳定排序。
- Glob 大小写规则跟随目标文件系统；Windows 不区分大小写，POSIX 区分大小写。该差异必须进入 contract 测试。
- `event_sample_limit` 必须是 0 至 100 的整数；`min_trigger_interval_seconds` 必须是 1.0 至 3600.0 的有限数值，拒绝 bool、NaN 和 Infinity。
- `poll_delay_ms` 必须是 50 至 60000 的整数，只在 `force_polling=true` 时生效；其他情况下保留配置但页面明确显示“不生效”。
- `include_hidden` 沿用现有目录节点的名称规则，只判断相对路径中是否存在点开头的路径分段，不读取 Windows hidden attribute，避免删除事件与现存文件使用两套结果。
- 样本身份使用规范化绝对路径；Windows 按大小写不敏感规则归一，POSIX 保持大小写敏感。监控根目录在启动时解析一次；仍存在的路径按解析后的实际路径做包含关系校验，已删除路径按 watcher 返回路径做词法包含关系校验。递归监听不得跟随指向根目录外的符号链接，不能通过 `..`、符号链接或路径大小写差异逃逸过滤边界。
- watcher 报告的目录项和已删除路径可能无法可靠判断是文件还是目录。过滤只按规范化路径、Glob、扩展名和事件类型执行；删除样本的路径类型不得伪造成已验证文件。
- 新增和修改事件的文件 metadata 只能作为当时观察值；Trigger 不读取文件内容。
- `min_trigger_interval_seconds` 只限制 Workflow 调用频率，不等于文件写入完成保证，也不实现文件稳定期队列。
- 本项目 Save 节点使用原子发布，生产结果目录应监听最终文件或最终 manifest 的 Glob，避免监听临时文件。
- 非原子第三方写入由 `Directory Latest File`、`Directory Scan` 或 Load 节点使用显式稳定期和读取前后 size/mtime 核对；Trigger 仍只负责通知变化。
- 调用 `watchfiles` 时显式使用 `watch_filter=None`，关闭依赖库对 `.git`、临时文件等名称的隐藏默认过滤。Adapter 只执行页面和公开 schema 中明确配置的 `recursive`、`include_hidden`、Glob、extensions 和 `event_types`；不分析或过滤 Workflow Save 节点写入的业务文件。
- 目录路径在创建时校验字段格式，在 enable 时校验目录存在、可读和 watcher 能力。创建 stopped TriggerSource 时允许目录暂不存在，不能因为暂不存在而跳过其他字段校验。

## 与目录节点的关系

Trigger 事件回答“为什么执行”，目录节点回答“执行时目录的真实状态”。两者没有隐式共享状态：

```text
directory-watch
  -> request_json directory event
       -> Directory Latest File / Directory Scan
            -> Load Local Image / JSON / Text
```

推荐使用：

- 结果监视：目录事件唤醒 Workflow，`Directory Latest File` 读取当前最新且稳定的结果。
- 目录维护：目录事件唤醒 Workflow，`Storage Retention Cleanup` 扫描并清理当前目录。
- 诊断与显示：可以展示样本路径和变化类型，但不能把样本当成必须逐一处理的可靠文件清单。
- 当前状态处理：无论 `samples_truncated` 取值如何，都由 `Directory Latest File`、`Directory Scan` 或业务专用目录节点读取当前状态。
- 手动执行：App Entry 不提供事件时，目录节点按固定参数读取，不依赖 Trigger。

目录节点不读取 TriggerSource 内存，不自动选择样本，不自动回退到最新文件。事件值和目录读取结果需要通过图中的显式条件、字段提取或 Coalesce 节点组合。

## 失败与恢复

- 文件系统 watcher 错误：TriggerSource health 进入 degraded/failed，记录最近错误；不伪造 WorkflowRun。
- 事件提交被 Runtime 拒绝或提交调用抛出异常：当前不可变快照结束并记录失败，不在没有新变化时隐藏重试；异常必须被提交边界吸收，不能直接终止仍然健康的 watcher 主循环。
- WorkflowRun 后续执行失败：由 Workflow Runtime 按统一机制记录；目录 Trigger 不查询该状态，也不自动重跑。
- backend-service 重启：enabled TriggerSource 按现有 Supervisor 生命周期重新启动 watcher，但不恢复退出前的窗口或未提交快照，也不扫描既有文件。
- 下一次真实目录变化：重新开启窗口；监视/维护 Workflow 通过目录节点读取当前状态，因此可以自然收敛到最新事实。

本文只取消聚合事件的重启恢复，不取消 TriggerSource 配置、enabled 状态和 Runtime revision/generation 校验的持久化。

## 集成页面

集成页面的协议模板增加“目录变化”，`trigger_kind` 固定为 `directory-watch`，`submit_mode` 固定为 `async`，`ack_policy` 固定为 `ack-after-run-created`。

同一 Runtime 允许创建多条目录 Trigger。默认 id 使用 `directory-watch-<workflow-runtime-id>-<8位十六进制UUID>`；后缀在新建表单初始化时生成，避免顺序号分配、并发抢号和删除后复用导致历史 WorkflowRun 来源混淆。`trigger_source_id` 仍以数据库唯一约束为准，极小概率冲突时返回现有明确冲突错误，不在后端隐藏重试。

多条目录 Trigger 即使目录和过滤条件完全相同也保持独立，平台不进行配置去重、事件合并或重复调用警告。页面也不读取 Workflow 图来分析 Save 节点路径。

基本设置：

- 监控目录（backend-service 所在机器的绝对路径，不是浏览器上传目录）
- 包含子目录
- 包含隐藏文件
- Glob 模式
- 扩展名
- 监听新增、修改、删除

高级设置：

- 目录变化最小触发间隔，默认 3 秒
- 最近变化样本数，默认 10
- 强制轮询
- 轮询延迟
- 忽略无权限文件
- WorkflowRun 记录模式和结果模式
- 手动输入 mapping

页面约束：

- 选择目录模板时隐藏并清空顶层 `debounce_window_ms`。
- 不显示 `batch_size`、sort、dedupe、批次并发、待处理队列和 checkpoint 恢复字段。
- 有 `request_json` 且 payload type 为 `value.v1` 时，新建表单默认映射 `payload.directory_event_value`；该 mapping 保持 `required=false`，重新选择模板或 Runtime 时不得覆盖已经存在的手动 mapping。
- 没有 `request_json` 时不猜测其他 binding，不把路径塞入 `request_text`。
- `result_mode` 固定为 `event-only`，不选择输出。目录 Trigger 没有等待结果的调用方；WorkflowRun 的状态与结果由现有 Runtime 查询接口负责，不在 Trigger 内建立额外结果交付计划。
- 只有 ZeroMQ 和本机共享内存高速模板默认关闭 outputs retention；不能因为目录模板不是 Webhook 就错误关闭结果保留。
- 创建前校验数字范围、事件类型、Glob、扩展名和 App Contract mapping；enable 时显示目录可用性错误。

## Health

目录变化 health 至少包含：

```text
configured_min_trigger_interval_seconds
configured_event_sample_limit
watch_running
submit_call_in_progress
window_open
window_started_at
window_change_count
window_sample_count
window_samples_truncated
window_has_changes
last_change_at
last_submitted_at
last_workflow_run_id
last_submission_state
last_submit_duration_ms
max_submit_duration_ms
late_window_count
submitted_count
coalesced_change_count
truncated_window_count
submit_error_count
watch_error_count
last_error
```

health 不返回完整样本路径，避免状态接口泄漏生产文件名和无限增长。路径样本只进入受权限保护的 Workflow input/output 和必要审计记录。

`last_workflow_run_id` 和 `last_submission_state` 只能来自本次提交的立即回执，用于诊断“Trigger 是否完成提交”；Adapter 不再根据该 id 查询 WorkflowRun 后续状态。

## 不实现的内容

- 不把目录 watcher 实现成 Workflow Node。
- 不把所有变化文件写进一个 `request_json`。
- 不按被删除文件的原始 mtime 排序样本。
- 不保证 exactly-once 文件投递。
- 不为每个文件创建一个 WorkflowRun。
- 不实现文件批次 backlog、持久队列、重启恢复和隐藏重试。
- 不查询 WorkflowRun 状态，不等待上一轮执行完成，不实现目录 Trigger 专用单在途或背压。
- 不分析 Workflow Save 节点，不检查、警告或阻止监控目录与保存目录重叠。
- 不对多条目录 Trigger 的目录、Glob、扩展名或事件类型做重复和重叠检查。
- 不在 Trigger 中加载或解析图片、JSON、文本和普通文件。
- 不让目录 Trigger 暗中执行 `Directory Latest File` 或 `Directory Scan`。
- 不改变 ZeroMQ 和本机共享内存的同步高性能调用行为。

## 详细实施步骤

主要落点固定如下，避免实施时把目录协议逻辑散入 Runtime 或 Workflow Node：

| 范围 | 主要文件 |
| --- | --- |
| 公开事件契约 | `backend/contracts/workflows/trigger_sources.py`，必要时拆分同目录 contract 文件并从现有入口导出 |
| 配置解析与路径过滤 | `backend/service/infrastructure/integrations/directory/_directory_trigger_support.py` |
| 目录聚合与 watcher 生命周期 | `backend/service/infrastructure/integrations/directory/directory_watch_trigger_adapter.py` |
| 协议中立提交 | 复用 `backend/service/application/workflows/trigger_sources/protocol_adapter.py`、`trigger_source_supervisor.py`、`workflow_submitter.py` 的现有单向提交链路，不新增 Run 状态接口 |
| Create/Enable/Health API | `backend/service/api/rest/v1/routes/workflow_trigger_sources/`、`backend/service/application/workflows/trigger_sources/trigger_source_service.py` |
| 集成页面 | `frontend/web-ui/src/modules/integrations/pages/TriggerSourcePage.vue` 及其测试与本地化资源 |
| 后端行为测试 | `tests/test_workflow_trigger_source_components.py`、`tests/test_workflow_trigger_sources_api.py` |
| 示例与文档测试 | `docs/api/examples/workflows/09-industrial-local-directory-watch-detection-position-gate/`、对应 Postman collection、`tests/test_workflow_api_document_examples.py` |

### 阶段 1：冻结契约与当前行为测试（已完成）

1. 为当前 `directory-watch` 文件批次行为补充特征测试，锁定迁移前事实，包括批次切分、删除忽略、checkpoint 和通用 debounce 抑制行为。
2. 在 `backend/contracts/workflows` 增加 `amvision.directory-change-event.v1` Pydantic contract，固定字段、计数一致性、样本上限、时间和变化类型。
3. 冻结目标 `DirectoryWatchTriggerConfig` 字段，删除从 `DirectoryPollTriggerConfig` 继承的不相关 batch、sort、dedupe、scan interval 和 checkpoint 恢复语义。
4. 明确开发期迁移策略：删除旧 `directory-watch` TriggerSource 后按新 schema 重新创建；不增加 update API、自动迁移、静默双读或旧字段兼容。

门禁：contract 单元测试覆盖合法事件、计数不一致、重复路径、非法或重复 `observed_change_types`、超量样本和 JSON 容量收敛。

### 阶段 2：有界聚合器（已完成）

1. 新建与 watcher 无关的纯 Python 聚合器，例如 `DirectoryChangeWindowAccumulator`。
2. 使用 monotonic time 判断窗口，使用 wall-clock ISO 时间写公开事件。
3. 计数使用现有安全计数器规则，长期运行允许受控 rollover，不允许 Python 容器无界增长。
4. 样本使用容量固定的最近不同路径结构；重复路径移动到最新位置并使用最近 watcher batch 的固定三种 `observed_change_types` 覆盖旧值。
5. 单次遍历 watcher batch，以容量固定的选择结构完成同批次确定性样本选择；禁止把完整变化集合复制为 list 或再次完整排序，只对最终入选样本排序并分配观察序号。
6. 使用窄锁实现原子 snapshot-and-swap，JSON 构造和 Runtime 提交不得持有 watcher 状态锁。
7. 实现 `snapshot_and_reset()`，快照完成后不能被后续文件事件修改。
8. 实现从最旧样本开始缩减的 64 KiB JSON 容量保护。

门禁：模拟 1、10、20、10,000 和同一路径 100 次变化，验证聚合器长期保留内存与样本数量恒定；覆盖创建后修改、创建后删除、混合事件和无序输入。

### 阶段 3：Directory Watch Adapter（已完成）

1. `DirectoryWatchTriggerAdapter` 只把匹配的 watcher 事件写入聚合器，不再扫描全目录并构建 `ready_records`。
2. 调用 `watchfiles.watch(..., watch_filter=None)`，所有过滤统一进入 Adapter 的公开配置逻辑。
3. 增加 3 秒默认窗口调度；持续变化不得推迟已确定的窗口截止时间。
4. 每个到期且非空的窗口直接调用一次现有 `WorkflowTriggerEventHandler.handle_trigger_event()`；不得读取上一轮 WorkflowRun 状态或增加 completion callback。
5. 快照提交前原子换入新的空窗口，使提交期间观察到的变化进入下一窗口；不为 Runtime 忙闲维护 pending dirty 分支。
6. 构造 `payload.directory_event_value` 和 TriggerEvent metadata，idempotency key 使用实际提交 event id，不使用文件路径列表。
7. 删除 directory-watch checkpoint、known identity 和 restart replay 路径；保留 TriggerSource enabled/revision/generation 的现有恢复流程。
8. submit 失败只记录 health，不增加自动业务重试；单次提交异常不得让 watcher 线程退出，后续新的目录变化仍能开启正常窗口。
9. 保持协议中立提交链不变，不在 Supervisor、WorkflowSubmitter、RuntimeService 或 Repository 增加目录 Trigger 专用状态读取和调度分支。
10. 记录提交调用耗时和延迟窗口；提交调用阻塞不得派生额外线程、内部队列或并发提交策略。
11. stop 和 `submit_call_in_progress` 在同一锁内确定先后；stop 前已登记开始的提交允许完成，stop 后不再开始提交。只有 watcher 线程完全退出后才从 Adapter 状态表移除，join 超时必须作为停用失败返回。

门禁：用可控时钟验证 3 秒内 100 次只提交一次、连续 9 秒产生三次提交；即使测试桩返回的上一轮 Run 一直未完成，后续到期窗口仍照常调用，且 Adapter 从未读取 Run 状态。

### 阶段 4：应用层校验与 API（已完成）

1. 在 TriggerSource create 规范化阶段增加 `directory-watch` transport_config 专用校验，不能只等 Adapter enable 时失败；本阶段不新增 TriggerSource update API。
2. 固定 `submit_mode=async`、`ack_policy=ack-after-run-created` 和 `result_mode=event-only`。
3. 校验 `min_trigger_interval_seconds`、`event_sample_limit`、`event_types`、Glob、extensions 和 poll 参数范围，并固定 Glob/extension AND 关系、长度上限、去重和大小写规则；数值字段拒绝 bool、NaN 和 Infinity。
4. enable 时校验目录存在、类型为目录、访问权限和 watcher 初始化结果。
5. 明确顶层 `debounce_window_ms` 对目录模板必须为空或零；同时传入非零值时直接拒绝，避免两套时间语义。
6. 更新 TriggerSource response/health contract 和 OpenAPI 描述。

门禁：REST 测试覆盖创建、非法范围、相对目录、错误同步模式、错误结果模式、enable 时目录不存在或无权限、没有 `request_json` 时不生成 mapping，以及存在 `request_json` 时生成可选 mapping。

### 阶段 5：集成页面（已完成）

1. 在 `TriggerSourcePage.vue` 增加 Directory Watch 协议模板和本地化文本。
2. 将模板默认值设置为 async、ack-after-run-created、3 秒间隔、10 个样本。
3. 增加目录基本设置和条件化高级设置；不展示文件批次字段。
4. 选择目录模板时隐藏通用 debounce、reply timeout 和同步回执设置中的无效组合。
5. 自动识别可选 `request_json:value.v1` 并在新建表单初始化时生成 `payload.directory_event_value` mapping；没有匹配 binding 时保持未映射，已有手动 mapping 不被模板默认值覆盖。
6. 修复执行 metadata 默认逻辑，只对 ZeroMQ 和本机共享内存关闭输入、输出和 trace 保留；目录 Trigger 保持普通异步 WorkflowRun 记录，但固定丢弃 Trigger 结果交付。
7. 创建前显示配置摘要：目录、过滤规则、事件类型、最小触发间隔和样本上限。
8. 每条目录 Trigger 生成 `directory-watch-<workflow-runtime-id>-<8位十六进制UUID>`；只处理 id 唯一冲突，不分析多 Trigger 配置重叠和 Save 节点路径。

门禁：Vue 单元测试覆盖模板切换、默认值、短 UUID id、多 Trigger 创建、条件字段、手动 mapping 保留、固定 event-only 和提交 payload。

### 阶段 6：文档示例迁移（已完成）

1. 更新 `docs/api/workflow-trigger-sources.md`，把本文已经实现的部分从“规划”改为当前能力。
2. 更新目录 watch Postman 创建请求、Preview 输入、Application、Template 和断言测试，删除旧文件批次字段。
3. 示例 Workflow 使用可选 `request_json`；监视类示例显式接 `Directory Latest File` 或 `Directory Scan`，不把样本当完整文件列表。
4. 更新 health、错误码和 UI 截图说明。

门禁：文档 JSON、Postman collection、Application/Template contract 和示例测试全部通过。

### 阶段 7：真实目录验证

1. 使用临时本地目录分别创建、修改、删除 1、10、20、1,000 和 10,000 个小文件。
2. 验证 3 秒窗口内只产生一次 Run；10,000 次变化的 request JSON 固定有界，Adapter 不再复制完整 watcher batch，处理完成后的 RSS 回落且长期保留状态不随文件数增长。瞬时 watcher batch 内存单独记录，不宣称与变化数无关。
3. 验证样本为最近观察到的 10 个不同路径且倒序，删除样本按观察顺序，不读取已删除文件 metadata；同一路径同批多事件必须合并 `observed_change_types`，不能推断最终状态；同时覆盖 Windows 路径大小写和超长路径容量收敛。
4. 连续写入 30 分钟，验证 Adapter 内部只有当前有界窗口，没有文件批次队列；每个到期非空窗口都有且只有一次提交尝试。
5. 模拟 Workflow 执行时间 1 秒、3 秒和 10 秒，验证 Trigger 调用频率只由目录变化和配置间隔决定，不读取或等待 WorkflowRun 状态；Runtime 的 accepted、queued 或 rejected 结果按现有统一策略记录。
6. 重启 backend-service，确认未提交窗口不恢复、现有文件不自动触发，下一次真实变化可以正常调用。
7. 验证 force polling、权限错误、目录被移除、Runtime 停止和版本切换时 health 收敛。
8. 至少执行 24 小时 soak，记录 backend/runtime RSS、handle/thread、提交次数、合并次数、截断次数和错误数。
9. 同一 Runtime 启用两条及以上目录 Trigger，验证窗口、事件、health 和停用生命周期彼此独立；允许完全相同配置产生独立调用。
10. 在提交调用延迟和 disable 并发条件下验证 `submit_call_in_progress`/stop 的锁内线性化点、join 超时错误和无孤儿 watcher 线程。
11. 验证 `watch_filter=None` 后只应用公开配置的过滤条件，不继承 `watchfiles` 对临时文件、`.git` 等名称的隐藏忽略规则。

通过条件：无无界 pending 路径、无 Adapter 批次队列、每个到期非空窗口恰好一次提交尝试、无 Runtime 状态反向依赖、无超限 request JSON、无隐式重试，停止和重启后线程与 watcher 句柄全部释放。

## 完成条件

以下条件全部满足后，本文状态才能从“待实现”改为“已实现”：

- 后端契约、Adapter、应用层校验、health 和前端配置全部完成。
- 旧 directory-watch 文件批次实现、checkpoint 和相关双读已经删除。
- `directory-poll` 的独立批次语义没有被破坏。
- 自动化测试、真实目录压力测试和长期 soak 通过。
- API 文档、架构索引、Postman 和示例 Workflow 已同步。
- 生产 ZeroMQ、本机共享内存 Trigger 的同步调用与性能无回归。
