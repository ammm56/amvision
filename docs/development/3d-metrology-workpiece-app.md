# 实际锂电工件 Workflow Node App

日期：2026-11-14。源码基点 `4f54fba8d7d22c6793825a35418729db57ec3418`。

## 本轮完成

使用既有 `scripts.metrology_workpiece.app_document()` 和公开应用保存、发布、运行接口，在日常默认项目创建真实业务 App。没有测试专用节点、替换 handler、修改测量算法或降低质量条件。源代码没有运行逻辑变更，本轮只增加实际应用数据、验证记录和文档。

| 项目 | 已落地内容 |
| --- | --- |
| 项目 | `project-1`，默认项目 |
| 应用 | `lithium-workpiece-file-full`，锂电工件测量 · 文件 |
| 发布版本 | v1，`workflow-app-version-8934becb895446c89491c6bee444ee15` |
| 运行实例 | `workflow-runtime-f4fcb66884c248f7840a3e063f978b0e`，锂电工件50项测量 |
| 编排 | 原 111 节点、317 边；十二钢片 H/Z/L/W 和两半圆直径 |
| 本轮 Windows Run | `workflow-run-ff6f3336e61347eb80589d0df8e37241` |
| 结果 | 50 项有效、50 项工程限值合格，汇总 OK |

应用详情：`http://127.0.0.1:5601/workflows/apps/lithium-workpiece-file-full`。

应用模式：`http://127.0.0.1:5601/workflows/runtime/workflow-runtime-f4fcb66884c248f7840a3e063f978b0e/app-mode`。

服务由用户管理，本轮接入已启动的 5600/5601。未启停用户后端、前端、daemon 或原有八个摆盘机运行实例；工件实例作为新业务应用保留。此前启动核对已在数据库备份后执行仓库既有 Alembic 迁移到 `c0f3e7a5b129`，没有新增迁移或绕过版本检查。备份保留于 `data/backups/workpiece-app-20261114/`。

## 输入与操作

1. 进入上述应用模式，在“完整点云文件”选择原 `1-1_0.ply`，点击“运行”。文件仍由调用方提供，配方未写死本机数据路径。
2. 本轮输入为 479,677,235 字节、14,745,099 点的完整 ASCII PLY，SHA-256 为 `ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b`。计算使用完整输入，不用页面采样点替代。
3. “50 项尺寸”卡片默认显示前四行；点击展开可查看完整 50 行及各项上下限、判定和原因。
4. “查看点云”显示工件范围及测量叠加；本配方概览为 500,000 点，明确显示输入总点数。使用现有视图、缩放、平移和旋转控件；测量详情可选择 A_top_L、S1、S2 等对象并聚焦。配方 `prepare_details=false`，本轮没有启用原始细节索引，不将这次概览验收描述成全分辨率加载验收。
5. 测量详情中的“几何有效”不等于公差合格；正式产品判定在尺寸判定表。S1/S2 均为已有 open-arc 圆模型直径，S1 的支持较完整，S2 使用已确认的部分弧方法；均不宣称实测闭合整圆。
6. 每次 Save JSON 显式保存 `inspection.json`。同步运行的历史记录开关与结果保存是不同机制，不要求开启全量 WorkflowRun trace 才能查看保存结果；页面显示也不是永久保存原云。重新进入应用模式需要重新选择输入文件，页面等待下一次执行，不把上次结果自动当作本次结果。

本次结果路径：

`data/files/projects/project-1/results/workflow-applications/lithium-workpiece-file-full/runs/workflow-run-ff6f3336e61347eb80589d0df8e37241/inspection.json`

App 文档、身份、截图和本机验证输出保留在 `data/development/workpiece-app-20261114/`，不作为新的运行依赖。用户原始点云及手工报告未改动。

## 手工报告对照

原报告目录为 `C:/Users/tanga/Documents/Codex/2026-10-21/referenced-chatgpt-conversation-this-is-an/outputs`。读取 `measurements.json` 的 pads 与 `dimensions.json` 的 steel_sheets、semicircular_slots；不是从截图舍入值反推，也没有把报告值写入工作流。

完整 50 项：[逐项 CSV](assets/workpiece-app-20261114/manual-comparison.csv)，摘要与原报告哈希：[JSON](assets/workpiece-app-20261114/comparison-summary.json)。差值统一为工作流减手工报告。

| 类型 | 项数 | 最大绝对差 mm | 定义差异 |
| --- | ---: | ---: | --- |
| H | 12 | 0.013854566 | 当前固定 U/V 同线沿台面法向求交；报告使用各顶面中心及源 XY 计算 |
| Z | 12 | 0.018460372 | 同上，当前有显式有限基准延伸及工程支持 ROI |
| L | 12 | 0.006597720 | 当前实际距离分区及稳健剖面跨度；报告为栅格和分位边界 |
| W | 12 | 0.026947014 | 同上，格距、边界与支持定义不完全相同 |
| D | 2 | 0.014776599 | 当前完整实测支持的圆模型；报告使用栅格等高线及角区拟合 |

例如 A_top_L：H=1.128335846、Z=1.577699540、L=7.916129643、W=6.996303211 mm；S1.D=20.147824 mm、S2.D=20.184324 mm（完整精度以 CSV/结果 JSON 为准）。

这份对照说明同一工件的量值对应和方法差异，**不是把差值视为实体精度已认证，也未新增一个宽松差值门禁**。全部 50 项与原冻结 F4 软件结果按绝对容差 `1e-7 mm`、相对容差 0 逐项一致。工程带仍为原 H/Z/L/W/D 配置，没有为本次结果调参。

原手工报告的整体外包络、各级台面尺寸及局部凸起摘要不在当前约定的 50 项内；本轮不把它们隐含为已交付测量，也不擅自增加新节点或配方指标。

## 本轮验证范围

| 平台 | 验证与结果 |
| --- | --- |
| Windows 日常环境 | 真实浏览器选择完整文件、公开运行、点云与50行显示；A_top_L 基准延伸、S1/S2 方法和支持证据可读；页面 50 行与保存 JSON 的数值及判定一致；浏览器无记录到的 error/warn |
| Windows 回归 | `tests/test_metrology_workpiece_delivery.py` 9 项通过，覆盖四种输入/显示组合参数不变、必检50项、NG/INVALID、防本机路径/测试依赖、绝对比较容差 |
| WSL Ubuntu | 同一配方回归及 `tests/integration/metrology3d/test_workpiece_delivery.py`，共 11 项通过；真实发布版本、独立 worker、完整输入、50项与保存/返回一致、停止及资源回收 |
| WSL 显示范围 | 数组入口 full：500,000 显示点、50 项测量证据、两圆、两个显示输出；文件入口 numeric：完整上传/读取/测量/表格/保存。未冒称 Ubuntu GUI 或文件 full 浏览器验收 |

WSL 运行数据库、临时结果、Broker/mmap 使用 Ubuntu 原生目录，源码及输入只读 Windows 挂载盘。隔离 Python 3.12、Open3D `0.20.0+amvision.1`，未修改系统 Python。测试环境初次收集因缺 filelock 失败，补齐隔离依赖后正式 11 项通过；该失败不算产品算法缺陷。

WSL 报告：[数组 full](assets/workpiece-app-20261114/delivery-array-linux.json)、[文件 numeric](assets/workpiece-app-20261114/delivery-file-linux.json)。其中 22.487/26.771 秒包括各自传输、读取及显示等范围，不作为纯检测节拍或十秒门禁结论；本轮没有追加性能与长稳测试。

图编辑器保存重开显示“已保存”，所有对象分组与参数仍在。测试进程已退出，仓库 `.tmp/` 本轮文件及 Ubuntu `/home/am/.cache/amvision-workpiece-app` 隔离环境已清理；仅保留上述业务 App、结果、备份及正式验证证据。

## 当前进度与剩余范围

| 范围 | 当前位置与后续 |
| --- | --- |
| 本工件主流程 | 已从示例文档落地为日常项目中的真实 App，完整输入、50项计算、判定、结果保存、显示和发布运行完成 |
| 现有通用节点 | 本轮直接复用，未新增工件专属算法；B17 已公开但不强塞进这份50项配方 |
| 工程使用范围 | 当前固定装夹/既定 ROI；换工件或来料位姿变化需另审配方，不等于任意来料自动定位 |
| 性能/容量 | 正式完整图稳定十秒、新证据布局的极限容量和最低机器资源仍单列，不阻塞当前 App 使用 |
| 发行 | 既有 CPU 离线包有历史验证；包含最新源码能力的新发行仍需统一装配与验收 |
| 实体与现场 | 独立实物参考、重复扫描、实采标定、客户 PLC/HTTP 设备联调不由本轮同云软件验证替代 |
| 通用后续 | B04 台面内自动粗搜索及尚未公开的高级拟合/形位/缺陷/面积体积等保留原清单；CAD、正式报告与 SPC 暂不开发，不作为本工件前置条件 |

下一步优先在现有 App 上完成现场人员试用与必要参数审核，不另建一套工件流程。需要外部系统调用时，复用当前已公开 HTTP 或同机工具入口；不默认新增 Trigger、设备连接或输出副作用。完整未完成范围继续以[统一剩余清单](3d-metrology-remaining.md)为准。
