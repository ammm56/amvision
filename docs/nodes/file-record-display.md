# 文件记录、汇总与字段显示

本能力由五个通用 Core Node 与既有字段提取、对象组装、数值运算组合。记录内容由工作流决定；不建立生产数据库，不绑定类别名称，不计算复检去重，也不改变部署模型调用方式。

## 节点与连接

| 名称 | node_type_id | 主要输入与参数 | 输出 |
| --- | --- | --- | --- |
| Count by Rules | `core.logic.count-by-rules` | `items`；`rules`；可选 `fallback_group` | `counts`、`input_count`、`matched_count`、`fallback_count`、`unmatched_count`，均为 value.v1 |
| Append JSONL | `core.output.jsonl-append-local` | `value` 对象；`save_location` 参数或同名输入；`enabled`；`preview_write` | `receipt` value.v1 |
| Read JSONL | `core.io.jsonl-load-local` | `file` 或 `path` 输入/`local_path` 参数；`cursor`；`snapshot_end`；读取预算 | `records`、`next_cursor`、`snapshot_end`、`has_more`、`status`，均为 value.v1 |
| File Summary | `core.io.file-summary` | 同一文件来源；`state_path` 输入或参数；`reducers`；可选 `condition`；读取预算 | `snapshot` value.v1 |
| Value Display | `core.io.value-display` | `value`；可选 `context`；`fields`、`title` | `body` response-body.v1，`type=value-display` |

Append JSONL 沿用当前统一的 Save Location 机制：绝对路径保存到本机磁盘，相对位置由 ObjectStore 解析。没有新增第二套目录/文件名解析器。Read JSONL 和 File Summary 的 `file` 输入采用既有文件记录格式；Append 回执中的 `file.local_path` 可通过 Value Field Extract 接到 `path`。

检测图推荐顺序：部署模型调用 → 规则计数 → 字段提取/对象组装 → 必需的明确保存节点 → Append JSONL → 返回回执。追加必须依赖业务判定与所需图片保存成功，不放在尚未确定结果的并行分支。追加已经提交后，后续其他节点失败不能回滚该条记录，因此检测记录与显示汇总应按设计分到不同工作流。新调用再次执行仍会新增记录。

显示图推荐顺序：File Summary → 提取 `totals`、`latest`、`source` → 计算 → Value Display；从同一个 `latest` 对象提取明确保存的图片路径 → Image Load Local → Image Preview。不要分别从多个目录猜测“最新图片”。File Summary 的 `source` 同时连接 Value Display 的 `context` 与 Image Preview 的 `presentation_context`。

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

格式支持 `text/integer/number/percent/status`；状态样式仅支持 `success/danger/warning/neutral`。原始状态值不自动改名或推断业务含义。规则/归约/显示字段使用摘要按钮打开独立编辑对话框，支持行的添加、删除、排序；简单匹配值逐行填写，复杂条件沿用现有条件 JSON。取消不修改节点参数，应用才提交，无效 JSON 阻止应用。

## App Mode 与大图

在应用模式配置中选中 Image Preview，在该行的“结果显示”选择 Value Display。绑定的 Value Display 不必再勾选成独立图片栏。配置仍为 v1，新增可选字段：

```json
{"node_id":"image-preview","output_port":"body","title":"检测结果","size":"large","overlay":{"node_id":"value-display","output_port":"body","position":"top-left"}}
```

图片与字段只在 `generation/sequence/snapshot_revision` 一致且均为当前结果时配对。缺少或冲突时显示“结果关联不可用”，不把新数量叠到旧图。角标在图片解码后显示；小图和双击大图共用同一字段组件，缩放/平移不会改变角标位置。可收起，多字段内容有高度边界；图片字节不被改写。旧工作流未配置 overlay 时行为保持不变。

## 文件边界与恢复

- 单条 JSONL 最大 1 MiB；严格 UTF-8 JSON 对象，每条完整换行，拒绝 NaN/Infinity。
- 默认每批最多 1000 条、4 MiB、100 ms；参数上限分别为 100000 条、64 MiB、5000 ms。时间在完整记录之间检查，File Summary 的归约也计入该预算，不能中断一条正在处理的记录。
- 规则最多 64 组、条件嵌套最多 16 层；归约最多 64 项；显示最多 32 个标量字段，文本最多 1024 字符、精度 0–6、正文最多 128 KiB；派生检查点最多 4 MiB。
- `records.jsonl.commit.json` 与 `records.jsonl.intent.json` 是管理协议元数据，不能单独删除或编辑。协议默认 managed；外部稳定 JSONL 可显式使用 snapshot，不能自动降级。
- 写入使用既有非等待路径锁；冲突报 `jsonl_busy`。读端只读已提交边界，不持写锁。检查点使用独立短锁与比较后提交；冲突报 `jsonl_checkpoint_busy` 或 `jsonl_checkpoint_conflict`。
- 写意图 → 完整行与 fsync → 原子提交边界 → 清理意图。中断恢复只处理核对过的未提交尾部。物理操作身份不作为业务记录去重；检查点丢失或校验失败可有界重建，权威文件损坏不能伪装为空结果。
- Preview 默认 `preview_write=false`，回执为 `write_state=skipped`、`reason=preview_write_disabled`；节点未启用时原因为 `disabled`。开启 Preview Write 后编辑预览也会真实追加记录，调试应配置测试路径。跳过回执没有 `file`，下游不能当作成功追加使用；节点执行成功不等于文件已提交，写入结果以 `write_state=committed` 为准。
- 本期面向本机单文件；不保证网络盘、任意外部并发修改或所有硬件掉电情形。文件与元数据一起备份，检查点可重建。

## 兼容与验证

未增加数据库迁移、外部运行时依赖、API v2 或 .NET 数据面字段要求。新增节点只在工作流显式配置时执行；文件同步持久化有真实磁盘成本。Runtime/Trigger 调度、部署模型、满载拒绝、JPEG 和 WebSocket 压缩设置未改变。

自动化入口：`tests/test_rule_counting.py`、`test_managed_jsonl.py`、`test_file_summary.py`、`test_file_display_nodes.py`、`test_file_display_workflow.py`、`test_file_display_api.py`。完整图构造见 `tests/workflow_file_display_support.py`；其中合并记录与显示仅用于隔离测试，生产按上文职责拆分。

设计约束与实际验收进度见[实施清单](../architecture/workflows/file-record-display-implementation.md)。现有生产 App/Runtime 未被测试替换；接入时需要为实际分类输出配置独立规则、保存路径和图片关联。
