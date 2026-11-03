# R5 C 动态等高与评价面继承

更新：2026-10-26。实施基点为 R5 B 提交 `9040bc0a`。承接 [R5 配方基线](3d-metrology-r5.md)，不替代 D/E 的工件配方审核。

## 状态与范围

内部接线、契约、前端与定向验证已完成，内部包为 `0.1.14`。extract-boundary、fit-line、fit-circle、measure-extents、measure-edge-pair、measure-hole 及 read-cloud/save-cloud/export-cloud/cloud-preview 的实现版本为 `0.1.12`。仍为十八内部节点，隐藏目录没有生产 manifest；生产容量、超时及启用参数不填写。

继续使用全部三维 v1 契约。新增实际评价面与来源字段为必需字段，缺字段的旧开发边界/拟合/尺寸证据明确拒绝，旧文件不删除，重新运行或保存。其他平台协议、发布版本管理、LocalBuffer、CloudRuntime 所有权体系不变，不增加脚本绑定器、缓存或等待队列。

未完成事项：A_top_L/S1 工程 ROI 和质量配置未冻结，十四对象正式量值验收未执行。后续[真实工件审计](3d-metrology-audit-20261026.md)确认 21 个候选区的支持与容量缺口，并在无项目脚本的静态 iframe 复现同一浏览器异常；不能将其归因于项目组件，具体浏览器脚本归属仍未定位。内部接线通过不等于整个 R5 或工业计量验收通过。

## 参数与接线

| 节点/位置 | 当前规格 |
| --- | --- |
| extract-boundary.inputs | cloud 单输入；features 接多组本次平面；可选单 pose、多 evidence；按显式 ID 选择，不取第一个结果 |
| settings.evaluation | 配置评价面，或 `{kind: pose, frame_id, length_unit, pose_id, target_frame_id}`；后者必须且仅对应 pose-contour |
| settings.method | `{kind: pose-contour, reference_feature_id, height, numeric_tolerance}`；reference_feature_id 是本次 pose 的主基准 |
| height 固定来源 | `{kind: fixed, value}`；有符号基准高度，无测量证据输入 |
| height 比例来源 | `{kind: measurement-ratio, item_id, reference_feature_id, target_feature_id, ratio, order}`；0 < ratio < 1；明确 B/T 两面，不自动换端点 |
| order | `target-above` / `target-below`，沿本次基准正 N 的有符号高差分别严格为正/负；零或方向不符无效，不取绝对值 |
| fit-line / fit-circle.evaluation | 原配置面，或 `{kind: feature, frame_id, length_unit}`，继承选中边界的实际截面 |
| fit-line.positive_direction | 原单位 XYZ 向量，或 `{kind: axis, axis: u/-u/v/-v}`，轴来自本次解析面 |
| 尺寸节点.evaluation | 继承选中边界/圆；边对继承 reference 直线，target 仍受原共面距离/角度门禁；普通 cloud 长宽不允许继承不存在的特征 |
| measure-edge-pair.query_position | 原源坐标 XYZ，或 `{kind: plane-uv, uv: [u,v]}`；方向支持面内轴，有限支持与缺口规则不变 |
| measure-hole.display_direction | 原单位向量或面内轴；直接使用 CircleFeature，不重拟合，不改 open-arc / closed-hole 规则 |

钢片 ratio=0.5 和半圆 h=0.25 mm 是 R5 工件配置，不是通用默认值。前端新增来源、比例、方向、ID 和几何字段不猜初值，缺失不能应用。

## 计算与失败

由 pose 解出源坐标基准原点 O 和 U/V/N，源云和 ROI 不变换。固定模式 h=value；比例模式从有效方向测量取真实端点 B/T，计算 P=(1-r)B+rT、h=N·(P-O)。截面原点为 O+hN，U/V/N 继承本次 pose。

解析成功交给原 SectionBoundary 内核。有限表面、截面、目标连续段、TLS 直线、圆拟合、尺寸及质量比较复用原实现；不另写算法、不缩窗或放宽质量规则。

- 跨运行/观测、错空间、重复 ID、缺接线、统计差冒充方向测距、支持摘要/方法不一致是输入错误，不能包装成正常缺测。
- 合法失败来源分别为 `contour_pose_unavailable`、`contour_datum_unavailable`、`contour_measurement_unavailable`；顺序不符为 `contour_height_order`。h、解析面及输出几何为空，不保留旧值。
- pose 主基准与 datum 的完整支持摘要、方法、几何和质量相符；比例 B/T 与 live 平面及支持逐项核对。只给历史证据不能授权新云。
- 截面/选段/质量失败沿原原因传递。错误底面仍触发原面外质量门禁，不用自动投影绕过。
- 取消和异常沿 Scope、借用和异常清理路径，无新增全量点云持有对象。

## 保存与前端

BoundaryMethod.resolution 保存原观测 ID、实际面、h、有限 pose/datum 快照和所选方向测量项。不含 run_id/cloud_id/lease 或整云，只含单个方向测量项，不反向引用尺寸集合，避免证据递归。

拟线/拟圆方法保存原参数、实际 evaluation、边界快照和支持摘要；尺寸方法也保存实际 evaluation。读取方重验来源选择、解析关系和身份，不能只检查字段存在。

沿既有 save-cloud/read-cloud 保存生成点、源边/面、插值及拓扑。恢复分配新运行支持，原 resolution 观测 ID 保留追溯；边界质量绑定新观测。恢复后的拟合/尺寸继承保存的实际截面，不使用旧租约。普通 cloud 不凭空生成边界质量。

复用原编辑器、ConfirmDialog、CloudViewer：固定/比例互斥，切换清除旧字段；本次 pose 模式不允许编辑截面矩阵；继承面模式没有隐藏 origin/rotation。边对 U/V 候选只用当前匹配观测及所选 reference 直线的实际面，来源/节点/运行变更清除候选，精确测量仍需 Preview。详情显示 O/U/V/N、h、pose/datum、比例/顺序和来源观测；圆弧按实际评价面绘制。应用/取消、晚返回和卸载沿既有生命周期，无新增常驻查询服务。

## 验证记录

| 验证 | 观察结果 |
| --- | --- |
| Windows 组合 | 372 项通过；最后补两项重合面后，10 项动态截面定向用例全过。前后按用例去重 374 项，不累加重复执行 |
| Windows 真实发布 | 1 项通过；真实发布准入 → 独立 WorkflowAppRuntime → Trigger，连续两次调用，独立观测身份及 Broker 回收通过 |
| WSL Ubuntu | 原生文件系统中新增几何/资产/真实发布 10 项通过，相关既有回归 188 项通过；最后含两项重合面的动态截面 10 项全过，重复执行不累加 |
| Catalog | 既有真实 UI schema fixture 与当前 Catalog 一致，1 项通过，没有修改不受影响的 fixture |
| 前端 | 相关 7 文件 37 项通过；补圆弧回归后受影响 3 文件 13 项通过，去重 38 项。Vue 类型检查、生产构建通过 |
| 完整 ASCII PLY | 两平台各一次，479,677,235 字节、14,745,099 点；float32、原始行号及摘要保持，显示 1,000,000 有界点。关闭 Scope 后数组计费为零 |
| 桌面/窄屏 | 真实云、来源/比例/顺序、继承面、取消、释放已检查；390×720 iframe 内编辑器和画布无文字重叠。画布有色像素为 55,472 / 18,148，非空白；关闭后 cpuBytes/gpuBytes 均为零 |

独立真值为解析倾斜面/斜坡：h=2.525、U/V 跨度 10/4、边距 10，端点按独立刚体矩阵校验；解析环半径 4、直径 8。覆盖 float32/float64、正/负/重合顺序、错误底面、无效来源、篡改摘要、跨运行、取消、保存恢复及圆边界角色。真值不调用生产求解 helper。

完整样本只沿 B 局部诊断窗口验证，不是 A_top_L/S1 正式配方。固定 h=0 及比例 h≈0.00002047462933 mm 均命中多段，返回 `target_ambiguous`，线/圆和尺寸无效/null；没有选最长段、拼洞或改阈值。两平台实际面及原因一致，差异为浮点舍入级。与相同显式 SectionBoundary 的对照只证明接线一致，不是独立精度验证。

报告：[Windows](assets/r5-c/windows-report.json)、[Ubuntu](assets/r5-c/ubuntu-report.json)。`live_array_bytes` 为关闭前计费，归零由 finally 断言；耗时不是节拍承诺。截图：[完整工件](assets/r5-c/real-cloud.png)、[比例编辑](assets/r5-c/contour-editor.png)、[窄屏编辑](assets/r5-c/mobile-editor.png)、[窄屏显示](assets/r5-c/mobile-cloud.png)。截图资源数值是检查时快照，不是实时仪表。

页面使用既有组件测试入口读取真实节点输出，不冒充空白 Workflow → 发布运行。桌面控制台无新增 error；窄屏 iframe 初次打开记录 `MutationObserver.observe: parameter 1 is not of type Node`，刷新无新增记录，编辑/显示/释放正常。增加页面错误堆栈采集后，初次打开仍只有浏览器无源位置记录，没有可归属项目脚本的堆栈；**来源未定，不声称已修复，也不据此改业务代码**。D/E 完整业务页验收仍须复核。

生产构建保留 WorkflowEditorPage、CloudViewer 两个超过 500 kB 的既有提示，不调整阈值。Windows 真实进程/浏览器验收使用本机回环及子进程权限；受限启动失败不计通过，也不归为几何错误。Ubuntu 缺测试依赖的收集失败不计通过，补齐隔离环境后才得到上述结果。本轮不验证 Open3D 新算法、GPU/P99、长稳或工业精度。

真实发布测试显式配置 4 MiB 预览正文、16 MiB 预览工作预算以容纳有限来源快照；旧测试 128 KiB 不足时由原门禁拒绝。完整样本沿 B 百万点测试容量。以上不是生产默认，不改运行准入或质量门禁。

## 审计与后续

变更限于三维契约、来源解析/接线、相关前端和测试。方向证据拆出独立模块，避免 boundary → 全部 measurement → dimension → boundary 循环依赖；不复制旧算法。二维、模型内核、进程管理和部署配置未改。

下一步 D → E：审核 A_top_L/B.A_top/S1 的有限 ROI、U/V、质量及显式预算，再运行正式 H/Z/L/W/D，失败逐层定位；之后扩展十四对象、文件/数组、双平台和空白业务页发布。M3.4 公开三态、生产启用和工业准确度保持独立验收边界。

复验入口：`test_metrology3d_dynamic_contour.py`、`test_dynamic_contour_assets.py`、`test_dynamic_contour_published.py`，以及 `test_measurement_full_sample.py --cloud-sample <完整文件> --cloud-report-dir <隔离目录>`。浏览器沿 `full_cloud_viewer.mjs <目录>/r5-c-preview.json <隔离端口>` 的 `/verify`、`/mobile`。隔离环境与临时目录不作为交付物；仅保留本节小报告和截图，原始文件、手工报告及业务数据不动。

收尾：变更 Python 的 Ruff 检查与格式检查、git diff --check 通过，四份入口/实施文档的 178 个本地链接有效。验收页已关闭，本轮 Vite/真实发布测试进程结束，5631 不再监听。仓库 `.tmp/` 已清空，本轮 Ubuntu 原生隔离目录删除并验证不存在；没有操作用户 5600/5601 服务、原始样本、手工报告或旧三维资产。本轮未提交 Git。
