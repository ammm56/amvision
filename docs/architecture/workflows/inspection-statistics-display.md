# 通用文件记录、增量汇总与结果显示方案

状态：通用节点与界面已实现，现场部署并发验收未完成。2026-09-15 更新。

本文件是需求、节点边界与数据语义的统一入口。具体编码顺序、文件范围、验证方法和完成条件见[代码实施清单](file-record-display-implementation.md)。节点使用与实际参数见[文件记录、汇总与字段显示](../../nodes/file-record-display.md)；未完成的验收以实施清单为准。

生产记录写入指定磁盘文件，不写数据库。使用通用的提取、计算、追加记录、读取汇总和字段显示能力，不新增生产数据库表或 Save Inspection / Read Inspection 专用节点。

## 已确认的核心约束

- 总数量由工作流配置常量提供，当前现场为每次 24 或 80；OK 和 NG 各自按可配置规则独立计数，禁止用总数减 OK 推导 NG。
- 每次正常完成且有结果的调用独立记录，不进行条码、同图、重试或复检业务去重。内部文件恢复只解决同一次物理追加中断。
- 节点不绑定模型类别、治具、塑盒或生产字段；缺槽结果由上游明确提供，通用计数器不补造物料。
- 记录、读取、计算和显示职责分开。显示工作流可保存派生检查点，但不追加生产记录。
- 字段配置同时用于图片栏左上角和双击大图的左上角，保持图片与字段同源更新，不烧录到图片中。
- 不改 Runtime/Trigger 高性能数据面，不增加推理队列或业务统计服务。所有新增接口保持 v1。

## 现场口径与已有实现

- 治具每盘 24 个槽位对应 24 个物料数量，塑盒每盘 80 个槽位对应 80 个物料数量；产量按物料累计。盘数可另外记录，本场景不要求显示。
- 整盘判定与物料数量分开。例如 23 个 OK、1 个 NG，整盘可为 NG，但物料 NG 数仍为 1，不能自动计成 24。
- 治具与塑盒分别统计。同批物料经过不同工序，不把两处累计简单相加当作整机产量。
- 检测应用 workflow-app-20260910030059 已有 data.state、data.passed、槽位分类计数并通过 Save JSON 保存。外层 code=200/message=ok 代表调用状态。
- 显示应用 workflow-app-20260910030132 当前四组 Directory Latest File → Image Load Local → Image Preview，没有读取结果 JSON。不同目录独立取最新文件有跨次图片错配风险，本轮未做并发故障复现。
- 实施前 App Mode 只有 node_id/output_port/title/size 绑定；本次新增可选 overlay。2026-09-15 检查时草稿与发布 v1 模板一致，浏览器四栏图片正常显示。

## 业务字段与计算

以下是工作流配置的字段示例，不是文件节点内置的生产概念：

| 字段 | 含义 |
| --- | --- |
| material_total | 本次物料数量，治具完整周期 24、塑盒完整周期 80 |
| material_ok / material_ng | 按当前工艺规则判定的物料 OK/NG 数 |
| tray_total | 本次盘数量，通常为 1 |
| tray_ok / tray_ng | 整盘判定对应的盘数 |
| state | 本次结果；当前业务中表示整盘判定，与累计数量独立 |

每次生产检测正常执行完成并有结果，material_total 固定增加配置常量 N，治具 N=24，塑盒 N=80。material_ok 与 material_ng 分别由显式配置的结果分组计数得到；禁止将 material_ng 固定实现为 N-material_ok，也禁止把未匹配结果暗中归为 NG。一个或多个结果值可以配置到 OK，另一个或多个结果值可以配置到 NG，模型分类名称不固定。

count 是模型实际返回结果数，不能替换固定总量 N。缺槽、unknown、低置信度在当前现场需要计入 NG 时，应由工作流显式产生对应结果或条件并纳入 NG 规则。通用分组节点不凭未匹配项或固定总量补造 NG；缺少结果项不等于已经存在一个名为 missing 的类别。24/80、槽位关系、标签和低分策略都属于工作流配置。

OK/NG 覆盖全部预期物料且互斥时，应校验 OK+NG=N。未覆盖时输出未匹配/缺失的诊断，不能通过差值补齐伪装成配置正确。一个槽位只提交一份归类结果，多模型候选、重复 ROI 应由上游归一化；不能把候选数量当物料数量。

每次调用独立计数；同图片、同条码、跨调用重试或复检，只要本次正常完成并有结果，都再次增加 N 和本次 NG。上位机负责真实产量去重和复检管理，本项目不实现这类业务识别、跨调用去重索引或保留窗口。

良品率为累计 material_ok / 累计 material_total，不平均各盘百分比。零分母显示“—”。模型满载、执行异常且没有正常结果的调用不计数；正常产出含缺槽/未知的 NG 结果则按 N 正常计数，两者不能混淆。盘数可每次加 1，盘 OK/NG 与物料计数分开。

## 通用节点边界

### 通用结果分组计数

新增 Count by Rules（按规则计数），定位为通用列表规则归约，不是模型、治具或生产专用节点。已有 Filter List 会输出过滤后的列表和 count，可复用其受控条件 DSL；简单图也可使用两个 Filter List 分别得到 OK/NG。多规则配置采用一次遍历的 Count by Rules，复用条件解释器，不再实现另一套表达式语言。

- 输入 items 为 value.v1 列表，每个元素代表上游明确的一次计数单位；节点不自行猜测图像中的物料数量。
- rules 为可编辑数组，每条包含唯一输出 key 和条件。条件选择结果字段路径、匹配值集合或既有组合条件。key 可为 ok/ng，也可为合格等级、报警类别等任意通用分组名。
- 普通分类可用字段值属于配置集合；数值、布尔结果和复合规则复用既有 DSL。字符串默认精确匹配，不写死类别名称、大小写替换或中文标签。
- 每个元素对同一规则最多计 1 次，即使命中该规则的多个备选值，也不重复计数。本期分组计数要求互斥：同项命中多个组时明确报配置/匹配冲突，不按规则排列顺序偷偷选择。
- 未匹配默认单独返回 unmatched_count；需要归入 NG 时显式配置 fallback_group=ng。fallback 只覆盖实际输入项，不能凭 N 自动生成缺失槽位。
- 结构缺失沿用既有条件 DSL：普通条件的路径不存在时不匹配，missing 条件可显式匹配缺失或 null。不新增 missing_field_policy；字段缺失不等于字符串 unknown，实际 unknown/missing 状态仍可按普通值配置到任意组。
- 输出 counts 对象、input_count、matched_count、fallback_count、unmatched_count；不输出累计、不写文件、不加载模型、不产生固定 material_* 字段。上游错误不默认为零计数。

示意配置（可视化规则的表达，不冒充现有 DSL JSON 语法）：

| 结果字段 | 分组 key | 匹配值（仅示例，可任意配置） |
| --- | --- | --- |
| result.label | ok | acceptable_a、acceptable_b |
| result.label | ng | defect_a、defect_b、missing、unknown |

组装层将 counts.ok → delta.material_ok，counts.ng → delta.material_ng，常量 N → delta.material_total。如果上游已经提供各类别数量，使用字段提取加数值求和分别组成 OK/NG，不把类别数量当作列表长度再次计数。

当前整次 OK/NG 判定也由工作流配置：可以基于上述计数加完整性条件，也可以复用已一致配置的 summary.passed。修改类别分组后必须核对整次判定是否一致，不能沿用与新映射冲突的旧标签规则。

### 业务语义与基础契约

通用层使用“本次结果”或由配置指定的标签，不内置“整盘判定”。治具应用可标为“治具判定”，塑盒应用可标为“塑盒判定”，其他应用可标为“尺寸判定”“工件状态”。上述 material_*、tray_*、state、delta、images 都只是当前工作流的对象字段示例，不是 Append JSONL 强制要求的 schema；可以使用扁平对象或嵌套对象。

Append JSONL 不识别或自动补齐这些业务字段，保留上游提交的对象内容。每次执行的记录均独立追加，不按业务字段去重，也不要求存在 record_id。文件 generation/sequence 可用于图片与字段关联，执行内操作身份仅用于恢复同一次被中断的物理追加。读取游标、校验和及提交状态属于文件协议元数据，与业务内容分离。

File Summary 只认识配置的字段路径、输出别名及归约操作，不自动生成生产总数/良品率或推断 OK/NG。Value Display 只认识选择的路径、标签、格式及样式映射，不根据字段名猜测工业含义。

现有 Result Record 的实际输入是 value.v1 的 decision 字符串，输出 result-record.v1 使用 ok_ng（OK/NG）和 ok（布尔值），并不是直接写任意 state 字段。布尔比较结果可交给已有 Process Decision 得到标准结果；需要自定义 state、Alarm 或任意对象时使用通用对象/条件节点组装。采用通用文件/显示节点不意味着改掉已有 result-record.v1 契约，也不强制所有日志都经过 Result Record。

参考讨论中的 abnormal_count > 0 只是判定示例，不能替代当前工作流完整规则。空盘目标下还需保留非空槽、未知结果、数量不匹配等条件；直接复用现有 summary.passed 可以避免弱化判定。

| 能力 | 节点 | 边界 |
| --- | --- | --- |
| 提取 | 复用 Extract Value Field、Pick Object Fields、List Map | 选择任意对象字段/数组项 |
| 分组计数 | Count by Rules，复用 Filter List 条件 DSL | 配置一个或多个结果到任意分组，分别输出计数，不推导 NG=总数-OK |
| 计算 | 复用 Number Operation、比较/条件、Array Summary | 四则运算、条件选择和数组汇总，保留除零校验 |
| 组装 | 复用 Object Field/Create/Merge；需要标准判定时复用 Result Record | 按连线构造任意记录对象 |
| 文件追加 | 新增 Append JSONL；保留 Append CSV | 一次追加一个对象，不理解生产、盘数或 OK/NG |
| 文件读取 | 新增 Read JSONL；复用 Load JSON、File Read JSON | 有界解析，输出 records、cursor、has_more，不计算业务指标 |
| 文件汇总 | 新增 File Summary | 按字段路径配置 sum/count/min/max/last，输出 totals、latest、source_revision、complete |
| 字段显示 | 新增 Value Display | 选择任意字段、标签、格式和状态样式，无计数、写文件或图片重编码副作用 |
| 页面组合 | 扩展 App Mode v1 可选绑定 | 字段卡片独立显示，或绑定图片栏左上角；不新增页面设计器 |

File Summary 是通用文件增量归约节点，内部复用 JSONL reader、纯归约器和可恢复检查点，分别负责读取、计算和进度保存。有限数组继续用现有 Array Summary。File Summary 不加载模型、不持有浏览器状态，也不硬编码 material_total 等字段。

不在不同生产调用中拼接“读取累计 JSON → 加一 → Save JSON”，这种跨节点读改写会丢失并发更新。写端仅追加单次增量，累计计算移到显示工作流。

## 文件与工作流

推荐 UTF-8 JSONL，一行一条增量记录，保留逐次历史。路径由已有路径参数/模板指定，例如：

- D:/摆盘机/记录/治具/production.jsonl
- D:/摆盘机/记录/塑盒/production.jsonl

Append CSV 可用于已有固定扁平表格；优先 JSONL 便于记录命名图片引用和扩展字段。不同时维护两份权威累计。

下例仅说明格式，并非真实 NG 数据。images 实际使用已有类型化持久引用，此处用字符串占位：

```json
{
  "record_id": "cycle-000123-tray",
  "timestamp": "2026-09-15T11:07:18+08:00",
  "state": "NG",
  "delta": {
    "material_total": 24,
    "material_ok": 23,
    "material_ng": 1,
    "tray_total": 1,
    "tray_ok": 0,
    "tray_ng": 1
  },
  "images": {
    "original": "<本次 Save Image 返回的持久引用>",
    "result": "<本次 Save Image 返回的持久引用>"
  }
}
```

生产图：检测结果 → 字段提取/工艺计算 → 组装单次增量及上下文 → Append JSONL。原图和结果图由显式 Save Image 保存后，将返回的准确引用接入同条记录。图片和 JSON 不靠各自生成的毫秒时间戳配对，不持久化临时 mmap/Preview 句柄。

显示图：File Summary → 读取 totals/latest → Number Operation 等计算良品率 → 对象组装 → Value Display。latest.images → 加载图片 → Image Preview。App Mode 把字段显示绑定到指定图片栏。

需要明细时使用 Read JSONL → 数组/表格处理；不让 File Summary 返回全部历史。需要保存独立统计 JSON 时可显式连接 Save JSON，但该文件是可重建的派生结果，不参与生产追加事务。

## 增量读取与检查点

正常运行只处理 cursor 之后新增的完整记录。File Summary 可在明确 state_path 保存小型检查点，包括日志身份/读取位置、字段规则摘要、累计值、最新处理记录及 revision；不缓存全部历史。

cursor 和累计必须在同一文件中原子替换，不能分别保存。检查点是派生加速文件，日志是权威来源。保存检查点失败时下一次从旧位置重新计算未提交的派生状态，不等于新增生产记录。

- 多个浏览器共享显示 Runtime 输出，不各自计数。多个显示 Runtime 使用不同 state_path；共享检查点必须使用路径锁及 revision 校验，避免旧状态覆盖新状态。
- 文件截断、替换、规则变化使检查点失效。日志身份不能只依赖路径/长度；需明确 generation/identity 与位置验证。
- 首次读取或检查点丢失需要重放。每次设置字节/记录/时间上限，complete=false 时显示“统计加载中”和处理范围，不能把部分累计冒充最终结果。
- 在一次读取开始时固定提交边界，latest 与 totals 来自同一处理位置。新追加留到下次，不能独立查最新图片再配旧累计。
- 切换日期/批次文件属于显式范围切换。只读今日文件代表今日统计；跨文件累计要明确有序文件集合及每个 cursor，不自动扫描所有历史目录。
- 日志删除改变重建能力。派生累计的备份和日志保留必须协调，不能删除源明细后仍保证任意重放恢复。

## 写入可靠性与幂等边界

复用并核对 backend/service/application/runtime/io 的路径协调、atomic_files 和 write_journal。现有 Append CSV 已有锁、journal 和 fsync，但不能未经测试就认为涵盖新的并发读取和所有中断恢复。

1. 锁外序列化有大小上限的一条 JSON；锁内完成追加、flush/fsync 和提交回执。跨进程使用同一规范化路径的锁，不能仅依赖线程锁/GIL。
2. 同文件写入串行化是文件正确性要求，不新增推理队列。锁冲突采用明确、有界失败策略；多写入源优先分文件并在读取侧汇总，不无限等待。
3. reader 只消费 writer 原子发布的提交边界，常规读取不持有生产写锁。换行符或文件长度本身不能证明已持久提交。
4. 中断产生的半条尾记录须恢复或明确拒绝；不能继续追加到半条 JSON 后。中间坏行不能静默跳过后显示偏小累计。
5. 每次新执行独立追加，即使输入或业务标识相同。只保留同一次物理写操作中断恢复需要的内部身份，不增加业务去重参数、业务索引或复检判定。文件恢复不能把同一次半写恢复成两条，但下一次完整调用仍是一条新记录。
6. 写前、半写、fsync 后回执前等故障点须保证完整追加一次或明确报错，禁止盲目重复追加。先恢复未完成追加，再接受同文件下一次写入。
7. 首期按本机受管理磁盘验证；网络共享盘的锁、rename 和持久化语义另行验证。

日志提交是记录成功点。图片保存成功而日志失败可能留下孤立图片，普通文件写入不具备跨文件事务；保持明确失败并复用既有保存/保留规则。日志提交后下游显示失败不能再次累计。

Append JSONL 实际执行就追加，Preview 与 Runtime/Trigger 保持相同语义，不提供节点内额外写入开关。调试使用显式测试路径。显示工作流没有追加节点，刷新、重复执行和断线重连不产生生产记录。

## 通用显示与图片组合

Value Display 的 fields 配置示例：

| Path | Label | Format |
| --- | --- | --- |
| latest.state | 本次 | status |
| totals.material_total | 总产量 | integer |
| totals.material_ok | OK | integer |
| totals.material_ng | NG | integer |
| yield_rate | 良品率 | percent，2 位小数 |

也可以选择温度、尺寸、重量、盘数或报警。字段缺失显示空值标记，不默认为 0/OK；状态映射采用受控值映射，不支持任意脚本/HTML。保留整数精度，百分比只格式化一次。首期累计超过前端安全整数范围时明确报错，不扩展任意精度编码，不静默舍入。

保持当前四栏布局。治具原图/结果图绑定同一个 Value Display，塑盒同理；盘数不选择就不显示。文字使用 Vue 组件叠加在图片容器左上角，不写入图像、不随图片缩放漂移，不遮挡查看器操作，无闪烁/数字滚动动画。

图片与字段以相同文件 generation/sequence 和 snapshot_revision 更新，不依赖业务 record_id 唯一性。迟到回调不能覆盖新结果，缺图不使用别次图替代。零记录、断线、旧数据、统计未完成有明确状态。显示允许跳帧，统计来自完整文件记录，不因跳帧漏计或重复显示多计。

## 数据契约与显示集成

本节为实施约束，节点与字段名均为拟定 v1 契约，不表示现有代码已经实现。主流程已覆盖，但仅有节点名称不足以实施，还需以下约束。

### 提取、指定格式和错误处理

- 提取节点负责源路径，Object Field/Create 负责目标字段名及嵌套结构。重命名不等于 Pick Object Fields，不能假定选择字段会自动改名。
- 记录按实际 JSON 值组装，不能把完整对象先变成字符串，再追加成包含转义 JSON 的字符串行。Append JSONL 接收 value.v1 中的对象，严格拒绝不可序列化对象、NaN/Infinity 和超限单条数据。
- 数据字段缺失、null、空字符串、0、false 分开处理。必需计数字段默认缺失即失败，不自动补零；可选字段由上游显式默认值规则处理。
- 数据格式版本由工作流按需放入 schema_version 等业务字段；文件层使用独立文件协议版本。不同业务 schema 混入同文件时，汇总必须按明确过滤/规则处理，不能默默改变口径。
- 显示端默认统计全部记录。需要过滤时配置显式条件，不用“当前画面字段选择”改变统计范围。

### 文件节点端口

| 节点 | 输入/参数 | 输出 |
| --- | --- | --- |
| Append JSONL | value；save_location 参数或输入；固定单条字节上限 | receipt：file、generation、sequence、committed_offset、write_state；不把业务对象改写为固定生产 schema |
| Read JSONL | file 或 local_path（二选一，沿用现有文件来源约定）；cursor；max_records/max_bytes | records、next_cursor、snapshot_end、has_more；保持一条完整记录的边界 |
| File Summary | 同一文件来源；state_path；reducers；读取预算；显式过滤条件 | snapshot：totals、latest、source、complete、status |
| Value Display | value；可选 context；fields 配置 | 结构化 display 正文，不新增文件读写或业务副作用 |

Append JSONL 使用当前统一 save_location 参数及同名输入，复用现有路径解析和主机路径边界，不新增目录/文件名双重解析。路径在一次调用开始时解析并固定，不能写入中途跨日期切换。累计文件路径与检查点路径必须不同；校验碰撞，禁止覆盖原始日志。项目隔离不能代替主机路径权限，同一目标路径必须使用同一个规范化锁键。

### 明细、累计与输出命名

File Summary 与 Read JSONL 共用单批读取预算，界面统一显示以下名称：

| 界面参数 | 默认值 | 上限 | 存储/API 字段 |
| --- | ---: | ---: | --- |
| Batch Records | 1,000 条 | 1,000,000 条 | max_records |
| Batch Size (MB) | 4 MB | 128 MB | max_bytes，仍为整数字节 |
| Batch Time (s) | 1 秒 | 20 秒 | max_seconds，整数秒，最小 1 秒 |

界面容量按 1 MB = 1,048,576 字节换算，JSON Schema 通过 `x-ui-display-divisor` 声明容量显示换算。时间参数从节点、保存配置到读取器统一使用 `max_seconds` 整数秒，不再接受 `max_ms` 或小数秒，不维护旧时间参数兼容分支。开发期已有工作流需要移除 `max_ms` 并显式设置 `max_seconds`（默认 1）；已发布 Runtime 快照通过重新发布和切换版本更新，不直接修改不可变快照。容量默认值和记录数默认值不变。

这些是每批处理的限制，不是整个文件的容量限制。200 万条、500 MB 的合法 JSONL 可以由多次调用分批汇总；达到任一预算即在完整记录边界保存检查点，以 `loading / complete=false` 返回，下次继续。时间预算包含本批读取、解析和归约，在记录之间检查，不是整个节点调用的硬超时；节点/工作流 deadline 仍优先。正常增量只处理新增记录，单条记录仍限制 1 MiB。首次重建的总用时取决于磁盘、规则和批次调用频率，不保证 500 MB 全量一秒完成。

2026-09-21 本地 conda 隔离验证：200 万条合成记录，每条 250 字节，文件 500,000,000 字节，使用 sum/count 两条规则和上述三个预算上限。managed 模式首次缺少提交元数据，自动恢复后分四批累计到 2,000,000；耗时分别 17,779.37 ms（包含提交元数据重建）、4,897.84 ms、4,712.34 ms、3,578.43 ms。无新增重复调用 5.95 ms，追加一条后汇总 8.41 ms，累计 2,000,001，未重复计数。这是本机单次功能与耗时验证，不是最坏延迟或长期性能保证。

File Summary 的 reducers 显式声明 source_path、operation、output_key、numeric_type、missing_policy。初期计数使用 integer 精确累加；bool 不视为 0/1，字符串数字不隐式转换。Array Summary 当前会转 float，因此不能直接用其实现长期整数累计。

例如：source_path=delta.material_total，operation=sum，output_key=material_total。输出为 totals.material_total，而不是再次包在 totals.delta 中；输出别名重复必须拒绝。count 是匹配记录条数，sum 是字段数值之和，两者不能混淆。

latest 保留最新已纳入本快照的完整业务对象，单次值读取 latest.delta.material_total，累计值读取 totals.material_total。latest 的定义是日志提交顺序，不是客户端时钟最大的记录。需要时间窗口时明确时区、窗口和迟到记录规则，不在首期隐式实现班次重算。

complete 表示已处理完本次固定 snapshot_end，不表示之后没有新记录。跨调用重建期间保留该目标边界，完成后再追赶新边界，避免持续生产时不断移动目标而永远无法完成。单条记录超过限制要显式报错，不能无限返回相同 cursor。

### 提交、恢复与不阻塞读取

受管理 JSONL 使用小型文件协议元数据记录 generation、sequence 和 committed_offset，和业务行内容分离。writer 在同路径短锁内执行可恢复追加，完成日志 fsync 后原子发布提交元数据。reader 先读取完整提交快照，再仅消费 committed_offset 以内的日志，读长历史时不持有 writer 锁。

写意图保留起始位置、长度、内容摘要和操作身份；下一次写入先解决未完成意图。只有核对为未提交的尾部，才能按恢复协议完成追加或恢复到原边界；已经提交的数据不得截断。文件元数据更新失败时回执不得声称成功，后续恢复结果必须可确定。仅调用 rename 不能宣称任何硬件掉电情形下绝对不丢失，必须区分进程中断验证与设备持久化能力。

普通外部 JSONL 没有提交元数据时，Read JSONL 只支持已关闭或显式稳定快照文件，不能宣称对任意外部 writer 具有一致并发读取保证。不能缺少元数据就悄悄切换为“长度等于已提交”。

不提供跨调用业务去重。内部 operation identity 仅处理当前追加的崩溃恢复，不接受条码或调用方 record_id 覆盖它以合并多个执行。任意新调用成功产出结果，都作为独立增量；统计检查点避免的是重复读取旧行，不能据此过滤内容相同的新行。

### Value Display 配置与 App Mode 绑定

字段配置示意：

```json
{
  "fields": [
    {"path": "latest.state", "label": "治具判定", "format": "status", "states": {"OK": "success", "NG": "danger"}},
    {"path": "totals.material_total", "label": "总产量", "format": "integer"},
    {"path": "yield_rate", "label": "良品率", "format": "percent", "precision": 2}
  ]
}
```

字段顺序就是显示顺序，允许选择单次或累计字段。百分比输入规定为 0..1，0.9583 格式化为 95.83%；普通数值按原值显示，不再乘第二次。状态键精确匹配，大小写需要上游显式规范化或配置多个映射；未知状态采用中性样式，不猜测 OK。

现有 App Mode 显示项增加可选 overlay 引用，位置固定 top-left；示意：

```json
{
  "node_id": "image_preview_result",
  "output_port": "body",
  "title": "治具结果图",
  "size": "medium",
  "overlay": {"node_id": "value_display_result", "output_port": "body", "position": "top-left"}
}
```

fields 只在 Value Display 配置，不在 App Mode 重复维护。配置对话框为图片项提供“结果显示”选择器，只列出有效的 Value Display 输出；作为 overlay 使用不强迫再生成一个独立卡片，同一显示输出可复用到原图和结果图。旧项没有 overlay 时保持原样。

保存、读取、发布和 Runtime 快照链路都必须保留并校验 overlay，不能只在 Vue 对话框中新增字段。删除/禁用源节点、错误端口、错误类型或缺失引用应在配置/发布阶段明确报错，不按数组位置补绑。

后端节点注册、Preview 显示事件、Runtime 完成后显示捕获、前端显示解析和共享组件必须一并接入 Value Display 类型。当前前端只分派 image-preview/table-preview/gallery-preview/value-preview；只加组件会得到“节点执行成功但显示为空”。不为新类型额外建立 WebSocket 连接，不将节点名字符串作为业务规则。

### 结果关联与视图生命周期

Value Display 的可选 context 传递通用来源身份，例如文件 generation、sequence、record_key 和 snapshot_revision，不要求业务对象特定字段名。要与图片组合时必须有同源上下文；图片预览可增加可选 presentation context 输入，仅作为显示信息透传，不改变图片像素或存储引用语义。此前只写“按 record_id 对齐”不足以保证身份真的经过所有端口。

同一组更新使用显示 run 身份及来源 context 校验。新图加载中保留旧图与旧角标并标注更新中，或同组显示占位；不把新状态先叠在旧图上。缺少匹配来源时显示关联不可用，不回退到最新文件。不同组可以分别更新，不要求治具/塑盒共享生产 cycle。

角标锚定图片内容容器左上角，不替换上方标题。宽度受容器约束、长文本换行，超长字段不无限遮挡图像；提供收起入口，普通信息层不截获图片拖动事件。双击打开专用大图查看器后，必须继续显示同一份配置的结果字段；查看原图仍使用未烧录文字的图像。

### 专用大图查看器必需接入

已通过实际双击核对：App Mode 调用 WorkflowPreviewViewers，内部使用共享 ImageViewer；目前大图只有图片工具栏和图像信息，没有业务字段层。不能只在 WorkflowAppModeDisplayGrid 添加角标。

- 图片栏与 ImageViewer 共用一个轻量字段展示组件和同一份字段格式配置。大图中的信息固定在顶部工具栏下方、图片视口左上角，缩放/平移/适配/100% 不改变信息层的位置和文字大小。
- 打开动作传递图片及其关联显示上下文，不在查看器重新读取文件、计算累计或触发工作流。不把通用 ImageViewer 绑定到生产业务字段或 Workflow 数据库/API。
- PreviewViewerImage 或独立的 viewer presentation context 承载通用字段展示模型；不能复用现有几何 overlays 数组来保存产量文字，也不能为了附带数据随意克隆图片对象，破坏既有对象身份更新及 Object URL 释放逻辑。
- 接入点包括 WorkflowAppModeDisplayGrid 的打开事件、useWorkflowPreviewDisplays 的打开/刷新/关闭生命周期、WorkflowPreviewViewers 透传和共享 ImageViewer 的可选展示插槽/属性。无绑定的图片查看器保持原行为，ROI、Mask、测量与调参工具不受影响。
- 当前查看器已有新执行后更新活动图片的路径。保持此行为时，图片与角标必须按同一 generation/sequence/revision 成组替换；若旧图仍显示，旧角标一并保留并标记更新状态，不能只更新累计数字。
- 从缩略图升级为源图时保留原关联上下文，不重复发送/编码图片。切换图片替换对应信息，关闭后释放上下文和监听，避免上张图的结果残留。
- 验证双击打开、缩放、拖动、100%、适配、关闭重开、图片自动更新、断线、切换治具/塑盒，图片栏与大图的字段值、颜色和来源应一致。普通文字层不拦截拖动/双击，收起按钮单独处理事件。

### 正常完成与计数节点位置

生产图应先完成必需的检测、结果计算及显式图片保存，再将所有依赖汇合到一次 Append JSONL，追加回执作为完成路径的依赖。不要在槽位循环内追加整盘固定数量，也不要让多分支各追加一次 N。

文件提交后才报告记录成功，不能后台丢弃写入失败却向调用方返回已记录。提交后连接断开不撤销已写记录，下一次新调用成功会再次计数，这是已确认的独立执行语义。通用 Append JSONL 不暗中更改为“整张图结束后才写”的执行器钩子；正确节点位置与终端依赖由业务图明确保证。

浏览器关闭/重连不触发生产追加。File Summary 可以写自身派生检查点，所谓“显示端只读”指不修改权威生产日志，不应误解成完全不写任何磁盘文件。

自动显示刷新复用现有显示工作流调用/Trigger，不由 Value Display 偷偷创建轮询或后台任务。只打开页面不等于检测完成后会自动重新读取另一应用的文件。首次有界重建未完成时，下次明确调用从检查点继续；不无限自调度。

## 性能边界与实施入口

记录不写数据库，不新增生产专用服务，不改模型执行、实例满载拒绝、Runtime/Trigger 同步链路与共享内存生命周期。生产新增成本是一条小记录的序列化及持久追加；fsync 有磁盘成本，不能保证文件必然比数据库快，也不能静默关闭持久化换取速度。

汇总/良品率在显示工作流执行，不在生产图扫描历史，也不放在 HTTP 事件循环或浏览器主线程全量处理。WebSocket 保持关闭 permessage-deflate，图片继续 JPEG。

实施顺序、文件范围和逐步验收统一见[代码实施清单](file-record-display-implementation.md)，本文件不重复维护另一份步骤列表。

## 开始实现前的固定约定

核对结论：业务需求与分层已经足够开始代码实现。以下固定首期范围与默认语义，替代前文的可选技术分支；实现时先落实到 schema 和契约测试，再逐层接入，不再引入生产数据库、业务去重或独立统计服务。

### 规则计数

规则对象固定为 key + condition，condition 复用现有 DSL。例如：

```json
{
  "rules": [
    {"key": "ok", "condition": {"operator": "in", "path": "result.label", "right": ["acceptable_a", "acceptable_b"]}},
    {"key": "ng", "condition": {"operator": "in", "path": "result.label", "right": ["defect_a", "defect_b"]}}
  ],
  "fallback_group": null
}
```

key 必须唯一且非空；fallback_group 非空时只能指向已有 key。每条规则在进入循环前完成递归校验，不能因为 items 为空就绕过错误配置。重叠命中明确失败，不引入 first-match 隐式顺序。

matched_count 为命中显式规则的项数，fallback_count 为进入配置兜底分组的项数，unmatched_count 为最终未分组项数：三者之和等于 input_count；counts 各分组之和等于 matched_count+fallback_count。无输入时所有计数为 0。总产量 N 仍由上游常量提供，Count by Rules 不校验分组数必须等于 N；现场可增加独立完整性校验，但不暗中把差值记入 NG。

### 文件范围与状态

- 首期 Append JSONL 和 File Summary 面向单个明确文件。已有 CSV 节点保持原行为；新增 CSV 增量汇总、多文件自动归档/扫描、时间窗口和网络盘不纳入首期验收。
- Read JSONL 的 source_mode 显式区分 managed 与 snapshot。managed 读取本项目提交元数据，snapshot 读取显式固定的外部文件快照，不自动降级。
- 文件协议元数据采用固定后缀 sidecar，至少包含 format_id、generation、sequence、committed_offset；待恢复写意图单独保存 operation identity、offset、length、digest。业务 JSON 行不嵌入这些控制字段。所有路径先做碰撞与规范化校验。
- 文件缺失：读取节点返回明确 missing 状态或按 allow_missing 配置处理；File Summary 默认返回 totals 初始值、latest=null、status=empty。日志存在但元数据缺失/损坏不是空数据，必须报错。
- 受管理日志、提交元数据和待恢复意图构成一组文件，复制/备份必须成组；禁止不经校验接管已有非空普通 JSONL。首期不实现自动修复未知来源文件。
- 检查点不复用生产追加锁；短临界区只保护派生状态提交，常规日志读取不阻塞 writer。首期同检查点冲突明确失败，推荐不同显示 Runtime 配置独立 state_path，不实现后台争用重试。
- File Summary 状态固定为 empty/loading/ready，文件损坏/读取失败走显式错误；空文件的 sum/count 初始值为 0，min/max/last 为 null，latest 为 null。过滤后无匹配记录也返回空聚合。
- 各次处理使用明确的字节、记录数和执行时间预算；配置默认值在首个 schema 提交中统一定义并测试，不能在节点、reader 与前端重复硬编码。单条超过上限直接报错，不截断对象。
- 整数计数使用整数累加并校验前端安全整数范围，超出明确报错；首期不扩展跨语言任意精度数值协议。浮点字段只接受有限数，业务自行选择合适单位。

### 显示契约与配置体验

Value Display 的 body 使用 type=value-display，携带有序 fields 及可选 context。每个 field 具有 label、原始 value、format、precision 和受控 states；格式化在共享前端组件完成一次。缺失字段/null 固定显示“—”，不泄露整个输入对象，也不把 null 格式化为 0。

节点属性编辑器提供可添加/删除的规则行、匹配值列表以及显示字段行。字段路径可手动输入，已有样本可辅助选择，但不依赖模型在线或预览结果存在才能保存配置。输出 key 重复、精度越界、空路径等错误在保存/发布前提示。

本期图片关联上下文选择可选 presentation_context 输入透传到 Image Preview，与 Value Display.context 使用同一来源。App Mode.overlay 只负责组件引用。未连接上下文的旧 Image Preview 继续工作；配置了关联角标却缺少匹配上下文时提示关联不可用，不能凭节点顺序猜测。

共享 ImageViewer 以可选通用信息插槽承载同一个字段组件，WorkflowPreviewViewers 负责注入；不让 shared/ui 反向读取文件或了解生产业务。活动查看器保留当前刷新机制，图片与字段成组更新，关闭后清理对应状态。

### 实现门禁与完成界限

| 阶段 | 必须通过后再继续 |
| --- | --- |
| 规则与对象链路 | 任意标签/字段、多值匹配、冲突、兜底、不匹配、空数组，OK/NG 独立计数 |
| 文件追加与读取 | 并发完整记录、各中断点恢复、提交边界、重复新调用正常追加、失败不假报成功 |
| 文件汇总 | 重复读取不多计、增量与全量参考计算一致、重启/检查点失败、文件损坏及固定边界追赶 |
| 字段与大图 | 配置往返/发布保留、Preview/Runtime 均显示、图片栏与大图同源、缩放及切换无错配 |
| 现场接入 | 24/80 来自配置、指定路径文件可核对、同图两次累加、实际图片显示、约 3 分钟性能对照 |

标准节点能力可先实现，不需要再询问产量或复检口径。现场不同模型的具体 OK/NG 值集合通过参数配置，接入时从实际输出核对，不预设类别名称。缺失槽位通过上游明确的槽位结果构造纳入规则；不在计数器中补造对象。

通用节点代码已落地，真实保存结果与图片的隔离 Worker/REST/WebSocket 验证通过；现有部署模型、Trigger 并发性能及真实 NG 精度仍须分别验收，短测不构成长期稳定性保证。逐步实施与进度记录统一维护在[代码实施清单](file-record-display-implementation.md)。

## 复用入口

- backend/nodes/core_nodes/logic/value/value_field_extract.py
- backend/nodes/core_nodes/logic/objects/：对象选择与组装。
- backend/nodes/core_nodes/logic/numeric/number_operation.py
- backend/nodes/core_nodes/logic/collections/array_summary.py
- backend/nodes/core_nodes/io/output/storage/csv_append_local.py
- backend/nodes/core_nodes/io/local/json_load_local.py
- backend/service/application/runtime/io/：路径协调、原子写与 journal。
- frontend/web-ui/src/workflows/workflow-editor/app-mode/workflow-app-mode.ts
- frontend/web-ui/src/workflows/workflow-editor/components/WorkflowAppModeDisplayGrid.vue

关联：[Runtime 显示与 App Mode](runtime-display.md)、[节点系统](node-system.md)。
