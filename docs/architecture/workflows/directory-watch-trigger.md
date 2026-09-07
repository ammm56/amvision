# 目录变化 Trigger

## 状态与用途

`directory-watch` 提供目录变化有界合并通知。后端契约、固定窗口聚合器、Adapter、创建校验、health 和集成页面已经按本文完成；持续 24 小时以上的现场 soak 仍属于发布验收门禁。

目标场景是本地生产结果目录的变化通知、监视 Workflow 唤醒和维护 Workflow 调用。设计优先保证 Trigger 内部没有无界路径集合、文件批次队列和隐式后台恢复，不把每个文件可靠投递、目录导入队列或文件内容传输混入 `directory-watch`。WorkflowRun 的接纳、排队、拒绝和执行容量统一由 Workflow Runtime 负责，目录 Trigger 不另设执行调度规则。

`directory-poll` 保留现有周期扫描、文件批次和 checkpoint 语义。逐文件导入、每个文件必须处理和断点恢复属于 `directory-poll` 或独立持久导入队列的范围，不属于本文。

## 执行规则

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
| File system watcher | 接收新增、修改和删除通知 | 执行 Workflow、读取业务文件 |
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

- 正常 async 提交只负责登记执行；默认 none 使用内存句柄，minimal/full 才创建 WorkflowRun 数据库记录。提交应快速返回 accepted 或结构化失败。
- 如果本地提交调用本身阻塞超过触发间隔，后续 watcher 观察和窗口提交可能延迟；不能伪造仍然按时触发。health 必须记录提交耗时和延迟窗口次数。
- 提交调用返回后继续处理 watcher 已收集的变化，不因上一轮 WorkflowRun 仍在执行而停止后续提交。
- stop 标记和 `submit_call_in_progress` 必须在同一状态锁内更新，二者先获得锁的一方确定停止线性化顺序。stop 之前已经登记开始的提交允许完成，已经登记的执行不取消；stop 先登记后不得开始新的提交。
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
- WorkflowRun 后续执行失败：默认 none 模式不保留单次执行记录；worker 失效仍由 Workflow Runtime 更新 Runtime 故障状态。需要审计单次业务失败时显式改用 minimal/full；目录 Trigger 不查询该状态，也不自动重跑。
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
- `result_mode` 固定为 `event-only`，不选择输出。目录 Trigger 没有等待结果的调用方；默认使用 none 瞬时异步执行，回执中的 run id 只用于本次事件关联，不能后续查询，也不在 Trigger 内建立额外结果交付计划。需要查询历史时显式改用 minimal/full。
- none 模式统一关闭输入和输出持久化；minimal/full 再按 Trigger 类型与显式 retention 配置决定保留范围。
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


## 验证与实现入口

后端固定窗口聚合、过滤、有界样本、JSON 容量、提交和停用边界由目录 Trigger 测试覆盖；前端使用同一公开配置与 health。真实目录验证应覆盖新增、修改、删除、持续变化、多 Trigger 绑定同一 Runtime、Runtime 忙与停止、停用后不再提交和无重启补偿。24 小时以上目标现场 soak 仍属于发布门禁。

实现位于 `backend/service/application/workflows/trigger_sources/`、`backend/service/infrastructure/integrations/` 和前端 integrations 模块。公开配置和回执见 [TriggerSource API](../../api/workflow-trigger-sources.md)。
