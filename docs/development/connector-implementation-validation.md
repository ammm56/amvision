# 二维连接器工程实现验证记录

日期：2026-10-07 至 2026-10-08。实现基线见 [连接器规划](connector-inspection-2d.md)。本记录区分代码闭环、准备资源的工程验证和真实产品验收。

后续配方易用性与结果解释改动另见 [U01–U07 实现记录](connector-usability-implementation.md)。下文保留各轮历史结论，不能把前一轮的未完成项与后一轮的实测状态混用。

## 交付范围

- 通用契约：原图身份、刚性姿态、有限几何、带有效性和单位的数值表、平面标定、不可变资源引用。
- Core：Check Limits、Numeric Table To Value、Merge Numeric Tables。
- OpenCV：有界亚像素采样/边缘对/有限截面，Rigid Locate、Planar Calibrate。既有定位、标定、测量节点继续使用原入口。
- Connector Nodes 0.1.8：Pin Array Locate、Connector Measure；固定 PIN 身份、留空、具名端点、指定候选带；Width/Pitch/Total Pitch/Gap/Offset/Length/Angle。
- 资源：项目内保存版本、PNG 模板、内容摘要、导入导出、引用保护、删除恢复、发布冻结与运行准备。
- Vue 3：资源选择器、PIN 布局、参考图扫描带、预览剖面/梯度/逐线拟合、尺寸方向/截面编辑、标定取点；Apply/Cancel 编辑事务。
- 工程模板：单排 10 PIN、双排各 8 PIN；显式规则和显示连线；无隐式图片/生产记录保存。

初期实现默认禁用行业包；2026-10-08 已通过节点管理启用开发包，当前 manifest 的 `enabledByDefault` 为 true，`developmentOnly` 为 true，用于新增连接器工程应用，不改写原有客户应用。无模型加载器、新业务数据库或新调度器；Runtime/Trigger 的调用、容量拒绝和 .NET 公共协议不变。诊断数据仅在 Preview 明确启用时生成，Runtime 不生成剖面。

## 环境与数据

- 开发 Python：conda `amvision`；Windows x64。开发前后端 5600/5601 在联调时未监听，因此完整页面使用独立 5650 服务、SQLite、ObjectStore、本地内存目录和本轮前端构建。
- .NET：仓库 SDK 0.1.8，Visual Studio MSBuild，Release/net472/x64；没有改写业务示例中的现场资源 ID。
- Bundled：现有 CPU/NVIDIA 发布目录内 Python 3.12.13、OpenCV 4.13.0，针对本轮源码运行测试；不是重新组装发行包验收。
- 已准备资源：`data/development/connector-inspection/synthetic-v1` 的连接器 PNG、独立生成的几何真值、参考图及 12 张棋盘图。单排和双排共 44 张连接器图，12 张棋盘图。
- 平面比例示例明确标注 SYNTHETIC。厂商图纸名义值、Blender 渲染和投影真值不能代替真实工件的独立测量值。

## 自动化结果

| 检查 | 本轮结果 | 说明 |
| --- | --- | --- |
| 连接器/计量/资源/独立 Runtime 九个测试模块 | 107 passed，79.94 s | 准备图片、契约反例、位深、取消、几何、资源、真实 GraphExecutor/Preview/Snapshot/API Runtime |
| 示例 App Mode 修复后重跑完整图 | 11 passed，21.12 s | 单/双排、正常/缺针/多针/无工件/旋转；校验完整面板契约 |
| 编辑器及 App Mode | 最终复测 15 passed，4.83 s | 空类型修复、取消、坐标回传、旧诊断失效、引用关联、面板契约 |
| 平台后端回归 | 52 passed，130.76 s | 发布、依赖、资源、既有渲染、WebSocket、Runtime invoke 等选定模块 |
| 前端已有相关组件回归 | 48 passed，7.17 s | 当时版本的编辑器、参数、ImageViewer 和 Runtime 显示；后续诊断/方向编辑另有 35 项相关测试通过 |
| 最后目录契约检查 | 4 passed，1.52 s | Core/行业分类、OpenCV matching/calibration 静态目录与生成器一致 |
| Bundled CPU / NVIDIA | 各 33 passed，22.85 / 22.92 s | 两种解释器执行采样、棋盘、阵列尺寸和示例图，不需要 CUDA 模型 |
| .NET SDK | Release 构建及仓库契约程序通过 | 真实 HTTP/ZeroMQ 调用另见下节 |
| 前端构建 | vue-tsc 与 Vite 构建通过 | 行业编辑器随本地前端构建，不依赖 CDN |
| 代码静态检查 | 60 个 Python 文件 Ruff 检查/格式检查通过；Git 差异空白检查通过 | 临时 UI 验证入口已经移除，不进入正式构建 |

这些计数有重叠，不能相加当作独立用例总数。中间测试失败及修复原因见后文；这里只列对应最终通过记录。

核心复测命令：

```powershell
conda activate amvision
python -m pytest tests/test_connector_metrology_contracts.py tests/test_metrology_sampling.py tests/test_metrology_localization.py tests/test_metrology_calibration_resources.py tests/test_connector_nodes.py tests/test_connector_array_measurements.py tests/test_connector_example_workflows.py tests/test_measurement_resources.py tests/test_connector_runtime_api.py -q
node frontend/web-ui/node_modules/vitest/vitest.mjs run --config frontend/web-ui/vite.config.ts tests/frontend/workflows/test_connector_editors.ts frontend/web-ui/src/workflows/workflow-editor/app-mode/workflow-app-mode.test.ts
npm --prefix frontend/web-ui run build
```

准备资源不存在时，部分图片测试显式 skip；本轮资源存在，不把 skip 当作图片验收通过。

## 浏览器和真实进程链路

隔离项目 `connector-engineering`、应用 `connector-single10_front` 通过正常 HTTP 保存；浏览器上传原始参考 PNG，运行 9 节点完整 Preview，实际 WebSocket 接收图片和结果。WebSocket 压缩关闭。

实际核对：

1. 原图上传、参考资源读取、中文/英文与亮/暗主题、Apply/Cancel、不修改原配置。
2. 所选 PIN 的剖面来自实际扫描，9 条扫描线、覆盖率 100%、最大拟合残差 0.2844 px；这是该样本内部拟合证据，不是量具精度。
3. 参数修改后旧剖面被隐藏；尺寸方向/截面通过显式 Pins/Features 连线找到参考图；大图坐标返回编辑草稿。
4. 保存、发布 v1、创建并启动独立 Runtime。资源引用与传递 OpenCV/Connector 包依赖进入快照。
5. .NET SDK 上传原图，经现有 HTTP 同步执行接口读取结果；正常/缺中针/无工件循环，每轮结果与预期一致。本轮三组各 12 次 HTTP 调用完成。
6. `AMVisionTriggerClient.InvokeImage` 同步 ZeroMQ 调用相同三类原图，全部成功；读取 `ResponsePayload.results.output_result.value.passed`。图片按配置返回；本例为 inline-base64，独立附件数为 0。
7. App Mode 随调用显示 OK 或 NG。双击大图保留同次结果的 Result/Required/Passed；无工件显示本次原图与 NG/51/0，不复用旧 OK。
8. 隔离服务重启后页面恢复新 Runtime generation 的结果；旧图片查看器关闭。没有修改既有治具/塑盒应用或生产计数。

### 时间记录

| 路径 | 样本结果 | 边界 |
| --- | --- | --- |
| 浏览器首次 Preview | client total 4794.9 ms；graph 1564.2 ms | 包含进程初次准备、上传和显示 |
| 浏览器后续 Preview | client total 2967.7 ms；graph 2402.2 ms | 当时同机正在执行测试，不能作为独占性能基线 |
| .NET HTTP，第 1 组 12 次 | P50 1305.7 ms；最大 1546.6 ms | 1280×800、10 PIN、39 尺寸项、51 规则项，上传与返回图片均计入 |
| .NET ZeroMQ | 正常 1431.5 ms、缺针 1270.0 ms、无工件 1181.6 ms | 仅 3 次功能样本，不是 P99 或长期稳定性统计 |

当前数据不支持“所有连接器流程均小于 1 秒”或“高并发无性能影响”的结论。需按工位节拍调整定位搜索范围并在目标机器上验收；不能为了降低耗时而改测量定义或降低采样验证门槛。

## 审计发现及处理

| 问题 | 修复/核对 |
| --- | --- |
| 资源删除扫描引用时复用 path 变量，可能指向无关模板 | 分离版本目录变量；回归保证无关模板字节完全不变 |
| 资源文件被占用或替换失败 | 明确持久化错误/系统错误号；保留删除凭据，允许后续继续清理，版本号不复用 |
| 候选与 PIN 在不同截面直接比较造成误判 | 使用同一有限截面比较实际边缘，不外推 |
| 弹窗遮住大图取点、PIN 表格过窄 | 显式编辑层级及表格滚动区域；普通 ImageViewer 默认层级不变 |
| 当前 Schema 省略默认值或类型列表为空 | 补齐当前默认值；空列表可修复，禁止在没有类型时生成扫描；不增加旧版本兼容分支 |
| 旧剖面误用于新参数 | 参数快照一致性及 stale 标记检查，修改后必须重新执行 |
| 示例 App Mode 省略格式和尺寸 | 通过既有 Pydantic App Mode 契约完整序列化，默认一个图片面板；附完整配置断言 |
| 总目录与分类目录使用不同参数 Schema 来源 | 统一从同一类型化 Schema 生成，删除两份手写重复参数定义；静态目录一致性检查通过 |
| 临时 ZeroMQ 验证失败 | 初始隔离环境关闭 Broker，输入映射也误用 `payload.buffer_ref`；开启隔离 Broker，使用 `payload.image`，并按既有 `results` 包装读取。无需修改 SDK/Trigger 实现 |
| 隔离服务首次重启缺节点 | 临时脚本重复制默认禁用 manifest；重新启用测试包后恢复。正式启用状态不通过覆盖 manifest 修改 |

既有图不含计量资源引用时不读取资源文件、不建立资源缓存。资源缓存上限 64 项/256 MiB，借用图像只读，淘汰缓存引用不会销毁正在使用的矩阵；这不是整个进程内存上限。单次执行的图像、扫描点、候选、特征、规则和诊断数组有明确预算；非法值拒绝，缺测为 null，禁止名义值补测。

## 尚不能得出的结论

首轮二维定位、测量、规则、资源、编辑与显示闭环已有代码和准备资源验证。S08 外观扩展按规划后置。

真实型号原图、图纸公差、独立参考量值与重复拍摄/上料数据仍未齐备，不能宣布现场物理准确度验收通过。尚未重新组装 CPU/NVIDIA 完整发行包，也没有完成连接器/旧模型/Preview/Runtime/共享内存 Trigger 混合负载一小时测试；本轮结果不能替代这些生产门禁。

隔离 Trigger 和 Runtime 已通过正常 API 停止，HTTP/Vite 与 SDK 测试进程均已结束；四个临时 UI 验证入口已经删除。对 `.tmp/connector-*` 及本轮 `pytest-cache` 的清理命令在执行前被自动审批拒绝（仅返回 blocked by policy），临时测试数据库和中间产物仍在，不能当作长期交付物。长期开发资源位于 `data/development/connector-inspection/`，生成步骤见 [工程示例](../examples/workflows/connector-inspection.md)。

## 开发服务实际应用配置与验证（2026-10-08）

本次面向现有 5600/5601 开发环境，通过正式资源、应用、发布版本、Runtime 接口创建六个工程应用；不修改原有八个客户应用、Trigger 或计数文件。应用清单、使用步骤及复现命令见 [工程示例](../examples/workflows/connector-inspection.md#已创建的开发应用2026-10-08)。Connector 包通过管理接口启用，未修改算法、执行器或原有高性能数据面。

### 实际验证结果

- 六份文档均通过服务端图校验及当前前端文档解析器校验，显式绑定项目资源版本。标定准备与逐件检测分开；四种检测配方各 12 节点、16 条连线，按工位步骤分组。
- 满针两种配方对 44 张图片实际同步调用，全部执行完成，无执行器异常。正常、平移、正负旋转、首/中/末缺针、偏移、明显过窄/过宽、多针、明暗变化、裁切、无工件、多工件均产生可解释结果；无有效测量时按规则 NG，并保留本次原图。
- 满针配方用于设计空位产品时有四次产品规则不匹配，已另建两种设计空位配方。空位/误插四次复测全部符合预期。没有根据图片内容自动切换配方，也没有通过删除空位检查让误插通过。
- 单排、双排最终版本分别验证“无输入、损坏图片、正常 → 缺针 → 无工件 → 正常”。无输入返回失败回执、错误码 `workflow_input_required_binding_missing`，无结果；损坏图片拒绝，不返回旧 OK。随后的正常调用成功，原 Runtime 可继续使用。
- 浏览器完成原图上传、12 节点 Preview、PIN 调试图、尺寸及逐项判定预览；App Mode 的同次 OK/NG 和检查项数量与接口一致，双击大图保留叠加。预览图为 JPEG；最终配方关闭拥挤的尺寸文本，只保留测量图形和独立数值预览。
- 12 张棋盘相机标定 RMS 重投影误差 0.0963165 px；平面拟合 RMS 0.00295646 mm，4 个未参与拟合的点最大误差 0.00349404 mm，低于配置上限 0.02 mm。这只验证合成标定图的算法链路。
- 结束时服务 `ready=true`，部署 4/4、Runtime 10/10、Trigger 8/8。10 个运行实例包括原 8 个及新建的两种满针检测；标定及设计空位实例测试后停止。

### 保留的边界及不通过项

| 图片 | 名义标注 | 实测宽度 | 当前结果 |
| --- | --- | --- | --- |
| `single10_front__width_on_limit` | 0.69 mm，OK | 0.69243515 mm | NG，超过 0.69 mm |
| `dual08_top__width_on_limit` | 0.69 mm，OK | 0.69878767 mm | NG，超过 0.69 mm |
| `dual08_top__width_inside_limit` | 0.68 mm，OK | 0.69006337 mm | NG，超过 0.69 mm |

上述三项是名义几何与渲染后边缘测量之间的临界判定差异；当前测量误差预算不足以保证此边界判别，不能记为验证通过。未放宽公差、四舍五入后判定或使用真值替换实测值。需在后续计量专项中明确渲染边缘、成像分辨率、亚像素估计及判定不确定度，实物还必须使用独立参考量值验证。

另有两张透视样本，其物料标签为 OK，但不属于本次正交图像与刚性定位配方工况，均定位失败并输出 NG；没有宣称此配方支持透视补偿。扣除产品配方不匹配并使用相应配方复测后，39 张符合当前工况且非上述临界失败项的样本结果符合预期；其余 3 张临界样本和 2 张透视样本仍单独保留。

44 次 HTTP 上传与返回结果图的完整耗时：最小 1248.33 ms、中位数 1445.435 ms、最大 2402.16 ms。同机存在原有工作流运行，不作为独占 P99 基线。浏览器首次 Preview 总时间 5061.6 ms，其中图执行 1458.84 ms、worker 总时间 1572.29 ms，首次 worker 准备等额外时间单独保留；不能将图执行时间冒充页面总时间。

本次交付是可继续开发、调试和验证的实际应用，不是物理精度或长期工业运行验收。完整逐样本结果、最终输入错误验证、相机/平面结果、六份可导入文档及截图位于 `data/development/connector-inspection/installed-workflows/`；本次未创建 `.tmp` 测试产物。
