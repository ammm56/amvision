# 3570 治具、塑盒计数与结果显示编排

当前配置及验收见文末“治具与塑盒完整接入”。前面的日期段落保留各阶段事实，其中旧路径、Preview Write 和塑盒尚未接入等描述不再代表当前草稿。

## 2026-09-15 保存范围

已更新并读回开发环境 project-1 的两个应用草稿：

- `workflow-app-20260910030059`：摆盘分拣3570治具空盘检测应用，122 个节点、147 条连线。
- `workflow-app-20260910030132`：摆盘分拣3570显示结果，45 个节点、53 条连线。

两份应用及模板均通过 v1 校验。原始文档、修改后文档、保存响应、编排脚本及隔离验证记录保存在本机 `data/files/developer/workflow-backups/20260915-count-display/`。目录包含本地应用备份，不是平台运行时依赖。保存草稿不会更新 Runtime 的固定发布版本；本次尚未发布或切换现有 Runtime。

## 检测应用

Count By Rules 读取既有并行推理结果的 `result.top_item.class_name`，配置如下：

| 分组 | 分类名称 |
| --- | --- |
| OK | `slot_empty` |
| NG | `slot_barcode_surface_full`、`slot_barcode_surface_abnormal`、`slot_pcb_surface_abnormal`、`slot_pcb_surface_full` |
| 未匹配结果 | 显式归入 NG |

OK 与 NG 分别按规则计数，没有使用总数减 OK 计算 NG。每条正常完成记录的 `material_total` 固定为 24；本次状态沿用既有 Classification Summary 的 `state`。规则只分类实际输入条目，不凭空生成缺失槽位结果。9 月 17 日移除每条记录中冗余的 `tray_total: 1`，托盘数量改为统计记录条数。

Create Object 组装总数、OK/NG 数、本次状态、条码、原图/结果图路径及结果 JSON 路径。Append JSONL 依赖原有图片和 JSON 保存结果，追加完成后返回原有响应；公开输出端口和响应内容保持原有契约。当前已移除节点内写入开关，Preview 与正式调用均在实际执行时追加；下文早期 Preview Write 配置仅为修复过程记录。

默认记录文件为 `D:/摆盘机/记录/生产统计/治具.jsonl`。写入目录跟随既有请求 JSON 的 `savepath`，再拼接 `生产统计/治具.jsonl`；上位机修改 `savepath` 时，需要同步修改显示应用 File Summary 的路径。

模型节点继续调用已部署实例，未改变部署模型、ROI、推理参数和既有判定规则。新增的文件节点是显式业务编排，未接入这些节点的 Runtime/Trigger 不增加文件操作。

## 显示应用

File Summary 增量读取上述 JSONL，对 `material_total`、`material_ok`、`material_ng` 求和，以 `count` 输出 `tray_total`；检查点为 `D:/摆盘机/记录/生产统计/治具汇总.json`。良品率通过 Number Operation 计算累计 OK / 累计总数。

两个治具图片栏读取同一汇总快照的 `latest.images.original`、`latest.images.result`，不再分别寻找最新图片。Value Display 配置本次结果、总产量、OK、NG、良品率，通过 App Mode 的 overlay 绑定到两个治具图片栏左上角。图片和统计传递相同的 presentation context，避免不同批次混显。大图使用既有 App Mode 查看器的相同叠加数据。

无记录时走独立空分支：使用空白图片，总数/OK/NG 为 0，本次状态和良品率为空。空分支也传递一致的非空 context，避免被前端误判为关联不可用。部分汇总沿用 File Summary 的完整性标记，不宣称已追平最新日志。

原有塑盒原图和结果图两个栏目及其读取逻辑保留，没有绑定治具计数。塑盒检测应用未在本次范围内，其每次 80 个物料需要在对应检测应用另行配置独立记录及统计绑定。

## 实际验证

- 使用真实图片 `data/files/developer/图片/3570/治具托盘/空盘/Image_20260817212353_29_5.bmp` 调用既有部署模型。两次检测成功，记录 2 条，总产量 48、OK 48、NG 0。
- 检测 Preview 从会话执行到输出就绪约 2362 ms、1936 ms；包含图片上传，不是单独模型推理耗时。
- 读取测试记录的显示 Preview 约 430–472 ms，空记录显示约 402 ms，均成功。重复读取没有新增生产记录。
- 内置浏览器临时读取隔离日志，实际显示总产量 48、OK 48、NG 0、良品率 100.00%；双击打开 2560×2358 JPEG。页面上报 `client_total_ms` 约 852 ms。验证后已刷新恢复正式草稿路径，未保存测试路径。
- 浏览器确认 App Mode 中两个治具图片栏均绑定 `tray_value_display`；塑盒两栏未绑定。现有 Runtime 尚未切换，因此新版本 Runtime 的 App Mode 小图及大图叠加仍需切换后最终核对。编辑画布直接打开图片不使用 App Mode 的 overlay 绑定。
- 验证数据只写入备份目录下 `verification/`，未迁入正式生产日志。本次没有使用真实 NG 样本，不宣称 NG 精度或长期性能验收通过。

编排验证发现 Preview 在没有显式连线时提前释放 Conditional/Switch Start 的 `selected_branch`。现已把对应 End 登记为隐式使用者，保留到读取结束后释放；仅在 Preview 生命周期管理启用时执行。`tests/test_workflow_preview_lifetime.py` 和 `tests/test_workflow_selection_nodes.py` 共 19 项通过，覆盖条件 true/false、Switch 命中/默认分支及图片释放；改变文件的 Ruff 检查通过。

收尾读回确认两份草稿指纹与保存备份一致，正式生产日志仍不存在，隔离日志仍为两条。自动审批拒绝清理本次 `.tmp/preview-selection-counts` 测试目录，返回 `blocked by policy`；未改用其他方式删除，该目录不作为交付资产。

## 生效步骤

两个运行中的 Runtime 分别为 `workflow-runtime-00ac97b7030b4bb5bda4c3d1e7a76fba`（检测）和 `workflow-runtime-71bf1addb3614f24b7554eec8925b343`（显示）。发布新草稿后需要选择新版本，按原运行状态恢复，再核对空数据应用模式及首条正式记录。切换涉及短暂停止对应 Runtime，当前等待用户选择是否立即执行；测试累计不迁入正式文件。

## 2026-09-17 写入与节点显示修复（阶段记录）

现场的“物料计数 · 保存成功后追加生产记录”组负责计数、字段提取、对象组装及 JSONL 追加。图片仍由原有两个 Save Image 节点保存；组内 Payload to Value / Extract Value Field 只提取保存回执中的路径，没有再次保存图片。

未生成正式日志的直接原因是检测应用的 Append JSONL 关闭了 Preview Write。Preview 的节点成功状态表示处理器正常完成，不能替代 `receipt.write_state=committed`。本次仅把该应用草稿的 `production_append.parameters.preview_write` 改为 `true`，保存并读回核对；节点全局默认仍为 `false`。之后此应用的正常编辑预览也会追加正式记录，调试需要提供隔离的 `savepath`。Runtime 的固定发布版本未更新。

Append JSONL 的跳过回执增加 `reason=disabled` 或 `preview_write_disabled`，便于区分未启用与预览禁写；保存路径参数绑定对应输入端口，连线后明确显示“来自连接”。

Count By Rules 的 Rules 行之前直接在窄参数栏展开复杂编辑器，而节点几何高度仍按普通 JSON 控件计算，造成内容越界。现在改为摘要按钮与独立编辑对话框，使用已有对话框组件，取消不修改节点参数，应用才提交；无效条件 JSON 阻止应用。File Summary 和 Value Display 的同类行编辑器共用此修复。

验证结果：

- 使用真实 `Image_20260721103258062.bmp`（约 57 MB）调用既有部署模型，一次 Preview 完成约 4694 ms，包含图片上传与结果传输，不是单独推理耗时。
- 在隔离目录提交 1 条 JSONL：物料总数 24、OK 24、NG 0、状态 ok；追加节点约 17.979 ms，回执 `write_state=committed`、`sequence=1`。
- 实际文件为原有两张 JPEG、一份原有结果 JSON 和新增 JSONL 及其协议元数据；记录引用的图片路径存在，没有重复图片保存节点。
- 浏览器确认 Rules 内容不越界、四个 NG 分类可完整查看、无效 JSON 无法应用、Preview Write 已开启。
- 后端相关测试 7 项、前端编辑器及几何相关测试 24 项通过，TypeScript 类型检查与改动 Python 文件 Ruff 检查通过。

本次备份及验证记录位于本机 `data/files/developer/workflow-backups/20260917-count-record-review/`。测试结束时正式生产日志仍未创建，验证记录没有计入正式统计；下次使用正式路径执行此应用预览才会创建或追加该日志。

## 2026-09-17 清理恢复与托盘计数简化

再次读取最新草稿后，检测应用仅移除 `production_record.parameters.fields.tray_total`；显示应用的 `tray_summary` 将该项归约改为 `count`，保留输出键 `tray_total`。两份真实应用均通过 v1 校验、保存和读回核对，没有重新生成或覆盖其他节点布局、分类规则及图片保存逻辑。旧记录无需迁移，汇总规则签名变化会从现存日志重算；Runtime 固定版本仍需另行发布和切换。

补齐主日志删除、清空、提交文件丢失及检查点删除后的恢复，行为和并发清理边界见[文件节点说明](../../nodes/file-record-display.md#定期或手动清理)。删除主日志后统计从零开始，不继续显示旧检查点累计。

使用真实图片与当前部署模型，通过开发服务 Preview Worker 在隔离目录完成六次调用：检测写入、显示统计、删除提交文件后显示恢复、删除日志后显示空状态、再次检测写入、读取新代次统计。两次检测约 3765 ms / 1653 ms（含图片上传及结果返回）；显示约 228–471 ms。新记录没有 `tray_total`，删除提交文件后累计仍为 1 盘/24 个物料；删除日志后显示 0，再检测后为 1 盘/24 个物料，未重复累计。

备份、候选草稿、保存响应及真实调用记录位于本机 `data/files/developer/workflow-backups/20260917-log-cleanup/`。删除操作只针对隔离测试日志，未清理正式生产记录。

自动化验证：`test_managed_jsonl.py`、`test_file_summary.py`、`test_file_display_nodes.py`、`test_file_display_workflow.py`、`test_file_display_api.py` 共 40 项通过；修改 Python 文件的 Ruff 检查通过。覆盖正常路径不进入重建、不增加读锁，以及删除、清空、重建、取消、损坏拒绝和汇总两次读取间发生清理的情况。

## 2026-09-17 统一追加节点执行语义（当前）

移除 Append JSONL 的 `parameters.enabled` 和 `parameters.preview_write`、预览分支及 skipped 回执。实际执行即追加，成功返回 committed，失败明确报错；节点顶层启用状态与工作流控制仍沿用既有机制。旧参数即使残留也不再控制写入，调试须使用隔离保存路径。

保存浏览器当前草稿后读取最新文档，只清理 `production_append` 的两个旧参数，校验、保存并读回一致。`production_record.fields` 已由当前草稿简化为 `{"material_total":24}`，确认没有冗余 `format_id` 或 `tray_total`，没有覆盖现场已有修改。显示图的 count 规则保留，Runtime 版本未切换。

真实图片 Preview 在无旧参数的情况下成功提交 1 条记录，总数 24、OK 24、NG 0，耗时约 5396 ms（含上传和结果传输）。隔离显示约 535 ms，统计 1 盘、24 个物料。43 项相关测试及 Ruff 检查通过，浏览器确认两个开关不再显示。

现场配置另有差异：检测图 `production_log_suffix` 当前为 `/治具生产统计/治具.jsonl`，显示图仍读取 `/生产统计/治具.jsonl`；显示图依赖的 `D:/摆盘机/记录/塑盒原图` 目录不存在，原配置的显示执行在该节点失败。本次没有修改这些现场路径；隔离验证将显示日志指向实际测试文件，并为塑盒栏使用测试图片目录，因此不能把该结果视为原路径完整显示验收通过。

备份与验证记录位于本机 `data/files/developer/workflow-backups/20260917-jsonl-write-semantics/`。正式生产记录未被测试写入。

## 2026-09-17 治具与塑盒完整接入（当前）

以下三个开发环境草稿已通过 v1 校验、保存及读回核对：

| 应用 | 节点 / 连线 | 本次变化 |
| --- | --- | --- |
| `workflow-app-20260910030059` 治具空盘检测 | 119 / 143 | 核对原有统计链路，修正 Append JSONL 的备用路径 |
| `workflow-app-20260910030110` 塑盒满盘检测 | 95 / 113 | 新增 22 个通用节点，提取、计数、组装并追加生产记录 |
| `workflow-app-20260910030132` 显示结果 | 78 / 98 | 修正治具日志路径，增加塑盒独立统计和图片显示分支 |

治具草稿中此前的 response/receipt 组装及再提取节点已经移除，本次没有重新添加。两个检测应用均保留原有公开结果、部署引用、ROI、模型参数和判定逻辑。塑盒原图与结果图 Save Image 的节点编号和治具相反，按真实连线分别引用，不能按编号直接复制。

### 写入规则与路径

| 项目 | 治具 | 塑盒 |
| --- | --- | --- |
| 每次物料总量 | 24 | 80 |
| OK 标签 | `slot_empty` | `slot_barcode_surface_full` |
| NG 标签 | `slot_barcode_surface_full`、`slot_barcode_surface_abnormal`、`slot_pcb_surface_abnormal`、`slot_pcb_surface_full` | `slot_empty`、`slot_barcode_surface_abnormal`、`slot_pcb_surface_abnormal`、`slot_pcb_surface_full` |
| 未匹配分类 | NG | NG |
| 日志相对路径 | `治具生产统计/治具.jsonl` | `塑盒生产统计/塑盒.jsonl` |

Count By Rules 对实际分类条目分别计算 OK 与 NG，不通过总数减 OK 推算 NG。记录的总量是应用配置常量；该节点不会凭空补出不存在的检测条目。本次实测分别输出 24 和 80 个条目。

路径跟随请求 JSON 的 `savepath`，默认根目录 `D:/摆盘机/记录`。Append JSONL 依赖已有原图、结果图及结果 JSON 的保存输出，仅提取路径，不新增或重复保存图片。记录包含 `barcode`、`state`、`material_total`、`material_ok`、`material_ng`、`images`、`result_json`，不添加业务 `format_id` 或 `tray_total: 1`。正常执行即追加，预览调试必须使用隔离保存目录。

### 读取、计算与显示

两个 File Summary 分别读取上述日志；检查点分别为同目录的 `治具汇总.json`、`塑盒汇总.json`。读取路径必须与检测请求的保存根目录一致，修改上位机 `savepath` 后也需修改对应读取配置。

各自累计物料总量、OK、NG，并按日志条数计算盘数；良品率为累计 OK / 累计物料总量。当前界面显示本次结果、总产量、OK、NG、良品率，盘数保留在汇总输出中。没有日志时走空分支，数量为 0，状态与良品率为空，不依赖图片目录预先存在。

原图与结果图均来自同一汇总快照的最新记录，并与 Value Display 使用相同 context。四个原有图片栏目保留：治具两栏绑定 `tray_value_display`，塑盒两栏绑定 `box_value_display`，均位于左上角。删除塑盒旧的 Directory Latest File / Image Load Local 分支，避免分别寻找最新图片导致结果混配。双击大图沿用同一叠加数据。

### 真实开发环境验证

测试记录及图片写入本机 `data/files/developer/workflow-backups/20260917-tray-box-integration/verification/`，不计入正式生产日志。实际部署模型的结果如下：

| 输入图片 | 总数 | OK | NG | 本次结果 | Preview 总耗时 |
| --- | ---: | ---: | ---: | --- | ---: |
| 治具空盘 `Image_20260721103258062.bmp` | 24 | 24 | 0 | ok | 3350 ms |
| 塑盒条码面满盘 `Image_20260718171401852.bmp` | 80 | 75 | 5 | ng | 4423 ms |
| 塑盒条码面缺料盘 `Image_20260801175117494.bmp` | 80 | 72 | 8 | ng | 4628 ms |
| 塑盒条码面满盘 `Image_20260801175758031.bmp` | 80 | 80 | 0 | ok | 3617 ms |

上述耗时包含 WebSocket 图片上传及输出接收，不是单独模型推理耗时，也不是长期性能统计。较早的满盘图片在修改前原塑盒图中同样得到 75 OK / 5 NG（3 个 empty、2 个 abnormal），新增统计没有改变分类；文件夹名称不能作为准确率验收标签。

验证覆盖双侧无记录、仅治具有记录、两侧均有记录、重复读取不追加、最后一条图片与状态匹配。最终治具累计 24 / 24 / 0、100.00%，塑盒累计 240 / 227 / 13、94.58%，盘数分别 1 和 3。独立读取磁盘文件核对记录数量、累计值、原图/结果图目录及 JSON 路径均一致。

浏览器编辑预览报告 `client_total_ms` 约 1074 ms。另创建仅引用隔离日志的临时显示应用及 Runtime，通过真实 Runtime 调用验证四个图片栏的统计和图片；双击塑盒结果图显示 2560 × 1860 JPEG，并保留 240 / 227 / 13、94.58% 的左上角叠加。截图为备份目录下 `app-mode-grid.png`、`app-mode-large.png`。

临时 Runtime 已停止并删除，临时显示应用已删除。浏览器测试路径未保存，刷新后确认恢复正式路径；三个实际草稿指纹与保存结果一致。此轮修改仅涉及应用编排和文档，没有修改平台执行引擎、模型实现或 Runtime/Trigger 数据面。现有现场 Runtime 的固定发布版本未切换；正式运行新编排仍需发布对应草稿并选择新版本。本轮真实样本验证不代表模型准确率或长期稳定性验收。

## 2026-09-17 参数编辑与结果叠加布局

Reducers 编辑面板按输出字段/来源字段、运算/数值类型/缺失策略分栏，统一输入与下拉控件尺寸、字体和焦点样式。选项使用可读名称，保存的枚举值不变。Count 隐藏不参与计算的 Source Path、Numeric Type、Missing Policy；Last Value 隐藏 Numeric Type；切换运算保留原参数，取消编辑不修改草稿。通用对象行中的 JSON 编辑仍占完整行。

后续修正原生 select 的菜单风格差异：对象行编辑统一使用项目 Select 组件，选中项使用主题高亮和勾选标记。仅此处启用浮动菜单，脱离弹窗滚动裁切，按视口余量向上或向下展开；父页面滚动或窗口缩放时关闭，菜单自身滚动保持打开。Esc 首先关闭菜单而不退出编辑对话框。原有其他 Select 默认布局不变。相关 8 项前端测试及 TypeScript 检查通过，浏览器验证鼠标展开、键盘选择、底部菜单完整显示和 Esc 行为。

应用模式及大图共用的 Value Display 叠加改为左上角纵向布局，状态大写显示，面板采用 78% 不透明度的主题底色，文字保持不透明，不使用模糊滤镜。字段顺序仍由节点配置决定，不在通用组件中识别生产字段。当前显示应用的两组 Value Display 标签已保存为生产总数、良品数量、不良数量、良品率；首项为本次 OK/NG。非叠加的普通节点显示不改为此布局。

7 项相关前端测试和 TypeScript 检查通过；浏览器验证 Reducers 切换到 Count 后隐藏无关项、取消保持原配置，并使用真实隔离记录验证四栏图片及双击大图的纵向半透明叠加。截图与应用备份保存在本机 `data/files/developer/workflow-backups/20260917-display-layout/`。现有 Runtime 的固定版本没有切换：样式由前端直接生效，新字段标签须在发布并选择更新后的显示应用版本后生效。
