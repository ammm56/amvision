# 文件记录、汇总与字段显示

本能力由五个通用 Core Node 与既有字段提取、对象组装、数值运算组合。记录内容由工作流决定；不建立生产数据库，不绑定类别名称，不计算复检去重，也不改变部署模型调用方式。

## 节点与连接

| 名称 | node_type_id | 主要输入与参数 | 输出 |
| --- | --- | --- | --- |
| Count by Rules | `core.logic.count-by-rules` | `items`；`rules`；可选 `fallback_group` | `counts`、`input_count`、`matched_count`、`fallback_count`、`unmatched_count`，均为 value.v1 |
| Append JSONL | `core.output.jsonl-append-local` | `value` 对象；`save_location` 参数或同名输入 | `receipt` value.v1 |
| Read JSONL | `core.io.jsonl-load-local` | `file` 或 `path` 输入/`local_path` 参数；`cursor`；`snapshot_end`；读取预算 | `records`、`next_cursor`、`snapshot_end`、`has_more`、`status`，均为 value.v1 |
| File Summary | `core.io.file-summary` | 同一文件来源；`state_path` 输入或参数；`reducers`；可选 `condition`；读取预算 | `snapshot` value.v1 |
| Value Display | `core.io.value-display` | `value`；可选 `context`；`fields`、`title` | `body` response-body.v1，`type=value-display` |

Append JSONL 沿用当前统一的 Save Location 机制：绝对路径保存到本机磁盘，相对位置由 ObjectStore 解析。没有新增第二套目录/文件名解析器。Read JSONL 和 File Summary 的 `file` 输入采用既有文件记录格式；Append 回执中的 `file.local_path` 可通过 Value Field Extract 接到 `path`。

检测图推荐顺序：部署模型调用 → 规则计数 → 字段提取/对象组装 → 必需的明确保存节点 → Append JSONL → 返回回执。追加必须依赖业务判定与所需图片保存成功，不放在尚未确定结果的并行分支。追加已经提交后，后续其他节点失败不能回滚该条记录，因此检测记录与显示汇总应按设计分到不同工作流。新调用再次执行仍会新增记录。

显示图推荐顺序：File Summary → 提取 `totals`、`latest`、`source` → 计算 → Value Display；从同一个 `latest` 对象提取明确保存的图片路径 → Image Load Local → Image Preview。不要分别从多个目录猜测“最新图片”。Value Display 的 `body` 明确连接 Image Preview 的可选 `presentation`。文件汇总场景中，File Summary 的 `source` 继续同时连接 Value Display 的 `context` 与 Image Preview 的 `presentation_context`，用于来源核对。

## 可配置规则与字段

Count by Rules 的 `rules` 示例，类别名仅为示例：

```json
[
  {"key":"ok","condition":{"operator":"in","path":"top_item.class_name","right":["acceptable-a","acceptable-b"]}},
  {"key":"ng","condition":{"operator":"in","path":"top_item.class_name","right":["defect-a","defect-b"]}}
]
```

`counts.ok` 与 `counts.ng` 独立计数。同一项命中多个分组明确失败；未匹配项默认只增加 `unmatched_count`。只有显式指定 `fallback_group` 才归入对应组。常量 24/80 通过 Object Build 配置，不能用总数减 OK 推导 NG。缺失槽位需要上游提供明确输入项；计数节点不补造项目。

Object Field / Object Build 可组装任意 JSON，例如：

```json
{"state":"ng","delta":{"total":24,"ok":20,"ng":2,"tray":1},"images":{"result":"D:/inspection/images/cycle-001.jpg"}}
```

File Summary 的 `reducers`：

```json
[
  {"source_path":"delta.total","operation":"sum","output_key":"total","numeric_type":"integer"},
  {"source_path":"delta.ok","operation":"sum","output_key":"ok","numeric_type":"integer"},
  {"source_path":"delta.ng","operation":"sum","output_key":"ng","numeric_type":"integer"}
]
```

支持 `sum/count/min/max/last`。`count` 统计纳入记录的条数；物料数量使用指定字段的 `sum`。`missing_policy` 为 `error` 或 `skip`。整数保持精确并拒绝超出 JavaScript 安全整数范围；不把布尔、字符串或非有限值隐式转换成数量。

File Summary 返回 `totals/latest/source/complete/status`。`complete=false` 表示本批尚未处理完固定边界；下次显式执行继续，不启动后台循环。`source.complete=false` 透传到 Value Display 后显示“汇总中 · 当前为部分结果”。空文件/允许缺失返回 `status=empty`，损坏日志仍报错。

良品率通过既有 Number Operation 计算 `累计 OK / 配置口径的累计总数`，原始比值交给 `format=percent`，不预先乘 100。空数据时使用 Conditional Start / End 分支避免除以零，并输出 null；Value Display 将缺失/null 显示为“—”。

Value Display 的字段配置示例（假设输入对象已经组装）：

```json
[
  {"path":"state","label":"本次结果","format":"status","states":{"ok":"success","ng":"danger"}},
  {"path":"total","label":"总产量","format":"integer"},
  {"path":"ok","label":"OK","format":"integer"},
  {"path":"ng","label":"NG","format":"integer"},
  {"path":"yield","label":"良品率","format":"percent","precision":2}
]
```

格式支持 `text/integer/number/percent/status`；状态颜色支持 `success/danger/warning/neutral` 主题预设或 `#RRGGBB` 自定义颜色。原始状态值不自动改名或推断业务含义。规则/归约/显示字段使用摘要按钮打开独立编辑对话框，支持行的添加、删除、排序；简单匹配值逐行填写，复杂条件沿用现有条件 JSON。取消不修改节点参数，应用才提交，无效 JSON 阻止应用。

Value Display 的 Fields 编辑器提供 Label Color、Value Color；Status 格式提供 State Colors 行编辑器，通过色块选择颜色，无需手写语义名称或 JSON。状态按原值精确匹配，命中的状态颜色优先于 Value Color，标签颜色独立；空颜色使用主题默认。颜色只改变显示，不改变状态或数量。状态键不能重复，每个字段最多 64 项；null 显示“—”，不匹配字符串 `"null"` 的状态规则。

File Summary / Value Display 的 Apply、Cancel、Reset to Default、Collapse、Expand Results 等操作文案，以及配置摘要和校验提示，随界面语言即时切换，支持中文、English、日本語、한국어。节点参数名沿用英文；用户配置的 Label、状态值和字段路径不自动翻译。切换语言不重置已打开的编辑草稿，也不写入工作流参数。

Appearance 配置面板提供即时示例、取消和恢复默认：

| 参数 | 默认 | 范围 |
| --- | --- | --- |
| Panel Width | Auto（内容自适应，最大 280 CSS px） | 100–1600 CSS px |
| Panel Height | Auto（内容自适应，正文有滚动上限） | 80–1200 CSS px |
| Font Size | 13 | 10–72 CSS px |
| Status Font Size | 图片叠加 20，普通节点继承正文 | 10–120 CSS px |
| Background Color | 主题面板色 | `#RRGGBB` |
| Background Opacity | 78% | 0–100 整数 |

宽高留空为 Auto；字号留空使用默认。宽高和背景仅用于图片叠加，字段颜色和显式字号也用于普通节点预览。叠加始终限制在图片容器内，空间不足时正文滚动，收起按钮保持可访问；图片放大不缩放叠加文字。背景透明度不影响文字。参数通过可选 `appearance` 对象保存，缺省节点无需迁移；已有语义颜色保持有效。固定 Runtime 需要发布并选择包含新参数的版本后使用自定义配置。

## App Mode 与大图

Image Preview 的可选 `Display Data` 输入接受 Value Display 的 `Display Data` 输出。其内部端口标识分别为 `presentation` 和 `body`。不接线只显示图片，接线后图片 Body 携带 `presentation` 字段。一个 Value Display 可连接多个图片节点；不按名称、位置或相同 context 自动选择来源。图片节点单独预览会沿真实连线执行字段显示上游。

“应用模式配置”只选择独立面板、标题、大小和顺序。图片行显示“图片内数据”及来源定位；Value Display 行显示当前“随图显示”的目标图片，其“另加独立面板”选项只增加独立数据面板。未勾选时仍保留图片关联；图片面板未选中时显示“已连接，图片面板未显示”。配置界面及节点关联摘要只显示名称，不显示内部节点 ID、类型或端口信息。所有用途均从连线与当前布局推导，不新增启用状态或隐藏绑定。

图片接收 Data Context（内部端口 `presentation_context`）时，校验字段正文的 generation、sequence、snapshot_revision；没有来源约束的通用图不需要伪造文件标识。已连接来源禁用、未产出、空正文、错误显示类型或来源不一致均明确失败，不能变为纯图或沿用旧值。节点组启用沿用成员节点的统一 enabled 状态。

字段面板随同一次图片输出交接，小图和双击大图共用字段组件，图片解码后显示。缩放和平移不改变面板位置，图片字节不重绘。颜色、字体、尺寸和半透明背景仍由 Value Display 控制。图片与统计的业务对应关系须由工作流从同一记录提取，连线本身不能判断外部图片路径是否选对。

旧 `app_mode.displays[].overlay` 已移除，读取旧配置会提示迁移，不能直接恢复旧绑定版 Runtime。导出的 application/template bundle 可生成迁移候选：

```powershell
conda activate amvision
python -m backend.maintenance.workflow_presentation_migration --input old-bundle.json --output connected-bundle.json
```

命令不覆盖已有文件，不修改运行服务。转换后需校验、保存并发布新版本，Runtime 显式选择新版本；原发布快照保留用于追溯。转换规则与本次现场验证见 [显式关联实现](../architecture/workflows/image-value-display-association.md)。

## 文件边界与恢复

- 单条 JSONL 最大 1 MiB；严格 UTF-8 JSON 对象，每条完整换行，拒绝 NaN/Infinity。
- 默认每批最多 1000 条、4 MiB、100 ms；参数上限分别为 100000 条、64 MiB、5000 ms。时间在完整记录之间检查，File Summary 的归约也计入该预算，不能中断一条正在处理的记录。
- 规则最多 64 组、条件嵌套最多 16 层；归约最多 64 项；显示最多 32 个标量字段，文本最多 1024 字符、精度 0–6、正文最多 128 KiB；派生检查点最多 4 MiB。
- `records.jsonl.commit.json` 与 `records.jsonl.intent.json` 是管理协议元数据，正常运行时由节点维护，不手工编辑。协议默认 managed；外部稳定 JSONL 可显式使用 snapshot，不能自动降级。
- 写入使用既有非等待路径锁；冲突报 `jsonl_busy`。读端只读已提交边界，不持写锁。检查点使用独立短锁与比较后提交；冲突报 `jsonl_checkpoint_busy` 或 `jsonl_checkpoint_conflict`。
- 写意图 → 完整行与 fsync → 原子提交边界 → 清理意图。中断恢复只处理核对过的未提交尾部。物理操作身份不作为业务记录去重；检查点丢失或校验失败可有界重建，权威文件损坏不能伪装为空结果。
- Append JSONL 实际执行就追加文件，Preview 与 Runtime/Trigger 使用相同写入语义；成功返回 `write_state=committed`，失败直接报错，不返回成功跳过。节点不再提供额外 `enabled`、`preview_write` 参数，是否执行由工作流统一控制；调试使用独立保存路径。
- 本期面向本机单文件；不保证网络盘、任意外部并发修改或所有硬件掉电情形。文件与元数据一起备份，检查点可重建。

### 定期或手动清理

| 清理操作 | 后续行为 |
| --- | --- |
| 删除主 JSONL 或整个记录目录 | 允许缺失的读取返回空结果；下次追加重建目录和日志，使用新 generation，残留提交文件和旧汇总不带入新累计 |
| 把 JSONL 清空为零字节 | 下一次节点读取或追加重建空日志提交状态，累计归零 |
| 只删除 commit.json，完整 JSONL 仍在 | Append JSONL、Read JSONL、File Summary 在非等待写锁内逐行校验后重建提交文件，保留现有记录；汇总重新计算，避免重复累计 |
| 只删除汇总检查点 | File Summary 根据现存日志分批重建，不丢失日志中的数量 |

元数据重建只发生在上述异常路径，使用有界单行内存，可取消，并设 180 秒（3 分钟）上限；不属于正常读取的 `max_ms` 批次预算。若节点或 Workflow 配置了更短的 deadline，仍以更早的 deadline 为准。重建失败不截断或删除原日志。正常追加不全量扫描，正常读取不新增写锁或等待队列。

managed 日志的已提交历史记录必须保持不变。为保持增量性能，正常调用不会对全部历史内容重新计算摘要；同一文件内等长改写旧记录不保证被发现，也不会自动更新旧累计。非空截断、替换文件或本次读取到的损坏记录会明确报错，不能将任意手工编辑视为自动恢复操作。删除或清空整个日志表示开始新统计；仅删除汇总检查点会从日志重新归约，仅删除提交元数据会校验重建提交边界并使旧汇总代次失效。

半条记录、坏 JSON、非对象记录、非空日志与残留提交身份冲突，以及提交文件丢失但仍存在未完成写意图时，均明确报错，不猜测应保留或删除哪些数据。外部清理程序不受路径锁约束；正在读写时同时清理可能使该次调用失败，应在清理完成后重新调用。没有承诺活动写入期间任意删除都能无损成功。

累计口径是当前日志中的有效记录，删除记录意味着对应累计也被清除。每条成功记录对应一个物件或托盘时，使用 `{"operation":"count","output_key":"tray_total"}`，无需每行保存固定的 `tray_total: 1`；旧记录的额外字段仍可保留。

### Windows 文件并发与系统错误

提交元数据、汇总检查点和输出 journal 使用允许替换的共享读取；Windows 通过 FileRenameInfoEx / POSIX 语义单步发布完整新文件。已有读者读取完整旧版本，不阻塞发布，不新增重试或等待。只读属性、权限和外部不共享句柄仍受操作系统限制。

三个 JSONL 文件节点的 IO 失败提供 `path`、`operation`、`stage`、`errno` 和 `winerror`，区分文件占用、拒绝访问、磁盘满、只读文件系统等情况。追加失败可能发生在日志已写入、提交文件尚未发布之后，因此标记 `write_state=unconfirmed`；不能据此自动重跑整个生产调用。临时文件清理及提交读回的二次错误不会掩盖原始错误。验证与处理边界见 [Windows 文件替换故障修复](../operations/windows-file-replace-audit-20260918.md)。

## 兼容与验证

开发阶段仍使用 v1：已有草稿中 Append JSONL 的 `parameters.enabled`、`parameters.preview_write` 应移除，节点顶层 `enabled` 保留。旧参数不再参与处理器逻辑，不能用旧的 false 值阻止写入；使用旧草稿或已发布版本执行 Preview 时，也遵守“执行即写入”。需要隔离调试数据时调整保存路径，不能依赖旧开关。生产记录字段由工作流自定义，不要求 `format_id`。

未增加数据库迁移、外部运行时依赖、API v2 或 .NET 数据面字段要求。新增节点只在工作流显式配置时执行；文件同步持久化有真实磁盘成本。Runtime/Trigger 调度、部署模型、满载拒绝、JPEG 和 WebSocket 压缩设置未改变。

自动化入口：`tests/test_rule_counting.py`、`test_managed_jsonl.py`、`test_file_summary.py`、`test_file_display_nodes.py`、`test_file_display_workflow.py`、`test_file_display_api.py`。完整图构造见 `tests/workflow_file_display_support.py`；其中合并记录与显示仅用于隔离测试，生产按上文职责拆分。

设计约束与实际验收进度见[实施清单](../architecture/workflows/file-record-display-implementation.md)。现有生产 App/Runtime 未被测试替换；接入时需要为实际分类输出配置独立规则、保存路径和图片关联。
