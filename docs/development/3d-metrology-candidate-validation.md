# 三维候选组合核对

2026-11-04 固定资产操作续验见[资产操作与资源观测](3d-metrology-asset-operations.md)：固定资产保存/导出/冲突与重选恢复、Windows 页面发布、代表语言主题以及双平台逐进程资源已补证。本文下方各批“尚缺”保留历史语境，当前剩余范围以统一清单为准，不把旧缺项重复列回待实现。

最新续验见[停止与完整 Preview 验证](3d-metrology-stop-preview.md)：已修复下文历史记录中的采样异常、正常停止 semaphore 引用残留，以及真实完整文件 Preview 的传输容量问题。双平台最终 CPU 候选各两轮五十项结果和停止重启通过；下文各批未完成说明保留当时语境，当前剩余范围以[统一清单](3d-metrology-remaining.md)为准。

最新续验见本文末尾“双平台隔离发行续验”。前文保留各批源码、测试数和当时限制，不把历史结果算成本轮新通过。

## 范围

2026-11-03，按剩余清单第 7.1 节推进 A08/A09，并执行受影响源码组合。基点为 `01587765`，保留开始时已有的五份进度文档修改。本轮生产代码只改三个三维参数编辑器的 watcher，没有改算法、质量条件、配方数值、运行配置、准入、队列或停止机制。

本项不是 A13 全部完成：没有重新装配本次前端修改后的两个离线包，没有运行十秒门禁、长稳或近 1 GB 显示索引。A12 原离线证据仍按原候选有效，不冒充本次发行验收。S2 工程接受沿既定决定，不重复历史诊断。

## 实际修复

1. GeometrySettingsEditor、MeasurementSettingsEditor 未监听上游接线身份/参数变化。窗口打开期间切换来源，旧草稿及选中的旧显示可能继续保留。沿现有编辑事务在来源变化时关闭并清除显示；高度编辑器同时清除候选位置，不提交旧参数。
2. DimensionSettingsEditor 将多个依赖放在返回新数组的 getter 内，内容相同的 inputSources 对象刷新也触发关闭。改用 Vue 多来源 watch，比较来源的序列化内容；真实来源变化关闭，等价刷新不关闭。不新增第二个编辑状态系统。
3. 新增八节点生命周期回归：fit-plane、build-frame、height-query、measure-step、extract-boundary、fit-circle、measure-extents、measure-hole。覆盖等价刷新、来源替换、旧显示清除、无隐式参数提交、重开、运行失效和卸载。Boundary 原实现通过，未为统一外观重写。

正确性先验：修复前上述定向用例六项失败、两项通过；修复后全部通过。补强后的运行切换断言先选中显示，再失效，避免对本来为空的状态作无效断言。

## 十八节点覆盖账本

以下是当前公开方法及现有验证入口，不是宣称每个入口本轮重新测试。`tests/frontend/workflows/` 下全部 43 个文件本轮执行；三维集成用例只有下节列出的子集本轮执行。真实页面未覆盖的方法仍明确保留，不使用测试数量代替操作矩阵。

| 节点 | 已有公开边界 | 现有验证入口 / 本轮页面 |
| --- | --- | --- |
| read-cloud | 本次文件 / 固定资产；PLY/PCD/XYZ 配置、字段、单位 | test_cloud_resources.ts；test_file_read.py；本轮完整 PLY 发布运行 |
| normalize-units | 显式单位转换、字段语义 | test_normalization.py；本轮没有新增单位错误页面证据 |
| filter-valid | 指定有限字段、sentinel；原始行号 | test_nodes.py；本轮完整云及 .NET 1 GB 全字段往返 |
| crop-roi | 参数 / 端口；box、cylinder、section-band、union | test_geometry_editors.ts、test_roi_union.ts、test_roi_visibility.ts；本轮完整图复用五窗并集 |
| transform-cloud | 输入 pose、源/目标坐标及字段变换 | test_geometry_nodes.py、test_geometry_assets.py；本轮没有新增变换页面证据 |
| save-cloud | original / derived；新资源 / 指定期望版本 | test_cloud_resources.ts、test_resource_api.py；本轮 .NET 两种入口各保存并逐行重读 |
| export-cloud | 运行云 / 固定资产；PLY/PCD/XYZ 系列显式字段 | test_nodes.py、test_capacity_file.py；格式边界不因 .NET 成功算作全部重验 |
| fit-plane | SVD / RANSAC-SVD、法向、质量策略 | test_geometry_editors.ts；本轮真实 D 参数、零法向阻止提交、取消重开恢复原值 |
| build-frame | 锚点投影 / 三平面交点；显式方向 / 交线 | test_geometry_editors.ts、test_geometry_nodes.py；新增上游身份生命周期回归 |
| extract-boundary | projection / section / contour / visible-envelope；固定/动态等高、grid/distance 分区、调试捕获 | test_boundary_editors.ts、test_dynamic_contour_editors.ts、test_envelope.ts、test_boundary_debug.ts；本轮完整图使用既定方法 |
| fit-line | 显式边界及有限连续段、评价面继承/配置 | test_boundary_editors.ts、test_boundary_runtime.py；其他方法真实页面仍需逐项补证 |
| fit-circle | 等权 / 角区 / 连续边长；单段 / 片段组 | test_circle_groups.ts；本轮 S2 参数与部分弧量值/证据聚焦，未换方法 |
| height-query | 配置测量线 / pose-uv；实测基准 / 有限延伸 | test_measurement_editors.ts；新增上游身份生命周期回归，不拿 measure-step 页面代替 |
| measure-step | 同线两面 / ROI 统计（mean、median、quantile）；两种查询来源 | test_measurement_editors.ts；本轮 A_top_L 固定 U/V、基准/目标 ID 与延伸上限页面 |
| measure-extents | 轴向跨度 / 最小面积矩形 / 稳健剖面跨度 | test_dimension_editors.ts、test_envelope.ts；本轮完整工件 24 项长宽，新增等价刷新与来源隔离 |
| measure-edge-pair | 显式线对及方向、signed / absolute、有限支持 | test_dimension_editors.ts、test_dimension_nodes.py；完整工件未调用，不能由工件成功推定页面全覆盖 |
| measure-hole | 直接消费 CircleFeature；closed-hole / open-arc | test_dimension_editors.ts；本轮 S1/S2 直径与工程判定；新增来源隔离 |
| cloud-preview | 有界概览 / 显式保存资产原始叶块、同次证据 | test_cloud_details.ts、test_cloud_viewer_lifecycle.ts、test_metrology_workspace.ts；本轮完整云 50 万概览、50 项详情、S2 定位 |

尚未补齐的 A08 页面项：各方法的中文/英文与明/暗代表路径、固定资产保存导出冲突/失败、任务与版本切换的完整页面矩阵、浏览器内存和故障采样。本轮 S2 截图还显示数值列直接显示长小数，在窄列中折行；后续按既有数值格式规则改善可读性，原始结果与计算精度不变。已有自动回归和历史页面证据继续使用，不将这些重新定义为十八个节点缺实现。

## 真实 .NET 1 GB

新增 [test_capacity_dotnet.py](../../tests/integration/metrology3d/test_capacity_dotnet.py)，复用已有 .NET probe、cloud_documents、正式 Save Cloud、发布准入与 Broker，不替换 handler。默认 1 MB 用于日常回归；本次显式传入 `--cloud-capacity-bytes=1000000000`。

- Windows net472 x64 的 `byte[]`、writer 两种方式分别提交实际写满的 1,000,000,000 B，62,500,000 点。
- 发布版本、worker 身份与回执一致；保存重读逐行比较 XYZ float32、uint32 序号、source_indices 和 source_point_count，而非只核对预览计数。
- 两次成功调用之间终止持有真实 1 GB 分配的写入客户端；按显式测试截止时间回收后，原 Runtime 的 writer 调用成功；停止后租约为零，Broker 2 GiB 空间全部归还。
- 故障探针采用已有 5 秒请求期限。首次测试误用成功调用的 120 秒期限，却要求 15 秒内回收，因此失败；修正测试配置后通过。未提交 writer 的资源回收受现有请求期限约束，不宣称客户端退出后立即回收，也没有修改生产期限。
- Ubuntu 正式 .NET net472 不在支持范围。本轮 Ubuntu 使用既有正式 Python 同机工具覆盖实写 1 GB、执行中取消、再次调用与停止，不将它冒充 .NET 验证。

资源采样复用现有 ResourceGate，只有测试 report 的可选开关，不进入业务运行。Windows 本轮进程树 711 次有效采样、一次子进程退出中间态丢弃、无采样错误；RSS 合计峰值 4,013,268,992 B，线程峰值 104，句柄峰值 1936。结束时仅测试主进程，线程 45 → 44，RSS 368,619,520 → 439,455,744 B，句柄 582 → 741。RSS 合计可能重复计入共享映射，不能当独占物理内存或最低整机 RAM；两次调用和末尾增量不能证明无泄漏或长期稳定性。浏览器不在此进程树内，未作浏览器峰值结论。

## 本轮结果

| 验证 | 结果 |
| --- | --- |
| Windows 新增 .NET 容量测试 | 1 MB 定向通过；精确 1 GB 1 项通过 |
| Workflow 前端组合 | 43 文件，282 项通过、2 项既有跳过；加强生命周期断言后 8 项再次通过，不重复累计 |
| Vue 类型检查、Vite 生产构建、变更 Python Ruff | 通过；构建仍有部分 chunk 大于 500 kB 的提示，未修改警告阈值 |
| Windows 正式工件文件/数组、显示与恢复准入组合 | 17 项通过；两次完整工件均 50 项与冻结参考及落盘一致 |
| WSL Ubuntu 完整工件文件/数组 + 精确 1 GB 同机容量 | 原组合 3 项通过；不是分开运行后拼成组合通过 |
| WSL Ubuntu 同一显示/恢复准入补充组合 | 15 项通过 |
| 隔离真实页面 | 创建 Runtime、启动、完整 PLY 上传运行、50 项结果展开、三维/S2 证据、参数防错/取消重开通过；浏览器捕获的 error 日志为空 |

Ubuntu 使用本轮隔离 venv 与原生文件系统；三维受控 wheels 来自既有本地资产，libusb 复用已有发行资产。其余依赖复用 A12 安装清单约束，Pydantic 按当前 I/O 锁 2.13.4。首次环境采集缺 filelock/pycocotools，补齐测试环境后执行同一原组合；没有修改系统 Python 或伪造节点注册。组合等待期间取得两份成功报告但进程尚未结束，最终正常结束为 3 项通过；未捕获异常栈，不据此认定生命周期挂起。

完整工件时间含输入读取/传输、显示/结果核对，且双平台有计算重叠，不是 A01 受控十秒验收。没有用 1 GB Filter Valid/保存图时间替代工件检测时间。

精简报告见 [Windows .NET](assets/metrology-a13/capacity-dotnet-windows.json)、[Ubuntu 1 GB](assets/metrology-a13/capacity-runtime-linux.json)、[Windows 文件](assets/metrology-a13/delivery-file-windows.json)、[Windows 数组](assets/metrology-a13/delivery-array-windows.json)、[Ubuntu 文件](assets/metrology-a13/delivery-file-linux.json)、[Ubuntu 数组](assets/metrology-a13/delivery-array-linux.json)。页面见 [50 项结果](assets/metrology-a13/results-page.png)、[S2 证据](assets/metrology-a13/s2-published-page.png)、[高度参数](assets/metrology-a13/measurement-editor.png)。

[候选记录](assets/metrology-a13/candidate.json) 包含基点、源码范围与指纹、本轮变更文件指纹、双平台关键依赖实际版本。该记录用于追溯本轮源码验证，不是新的发行包清单。

## 剩余与下一出口

1. A08 按上表补明确的页面/浏览器资源缺项，不重做 viewer 或平台列表。
2. A09 精确 1 GB .NET 不再列为未验。大载荷磁盘写失败、截断/断连、worker 强制退出与各进程资源分项仍需补齐；本轮 writer 退出不能替代全部故障矩阵。
3. A13 仍需同源码重新装配两 CPU 包并完成最终组合与资源验收。既有 A10/A11/A12 不重复开发；本轮没有生成新的离线发行完成结论。
4. A01 十秒、近 1 GB 索引有界构建保留独立未完成状态。B01–B23 没有在本轮新增实现；实体精度需要独立参考，不从本云反推认证。

本轮未自动 Git 提交。页面 Runtime 已正常停止，隔离后端/前端进程已退出，5620/5621 没有监听；原有 5600/5601 业务进程未停止。归档精简证据后，仓库 `.tmp/` 本轮测试数据与缓存已清空，Ubuntu 原生文件系统的本轮隔离 venv/数据已删除，并恢复该发行版原先的停止状态。业务目录、原始 PLY 和已有发行包保持不变。

## 结果显示与大载荷故障续验

2026-11-03 继续执行剩余清单 7.4。本批生产修改只在 `MeasurementSummary.vue`：默认使用已有四位显示选项、保留原值切换及 title、数值与单位不折行，复用现有横向滚动；小数选择栏在明细内保持可见。非零极小值不会被显示成零。没有修改共享格式化器、测量值、保存/导出、三态、算法、质量限值、准入或运行时策略。

回归先失败后修复，覆盖零、负数、极小/极大值、无效结果、原值切换和源对象不变。Workflow 前端最终组合为 **43 文件、287 项通过、2 项既有跳过**；Vue 类型检查和正式 Vite build 通过。构建仍提示部分 chunk 大于 500 kB，未调整警告阈值。

### 真实页面

- 隔离 5620/5621，通过真实草稿指纹发布、创建 Runtime、上传完整 `1-1_0.ply` 并运行。不是测试 handler；14,745,099 点、50 项量值及 500,000 点概览正常显示。
- S2 原值 `20.184324164862264 mm` 与四位显示 `20.1843 mm` 可切换，733 个支持点和部分弧方法不变；没有借显示修正宣称实体准确度。
- 中文亮色桌面、英文暗色 768×900 浏览器视口均核对；50 个数值单元格没有内部溢出，页面宽度未超视口。恢复语言、主题和浏览器尺寸，没有改变操作系统缩放。
- 正常停止页面 Runtime 后再关闭隔离服务。截图：[S2 明细](assets/metrology-final/01-s2-readable.png)、[英文暗色窄屏](assets/metrology-final/02-english-dark-narrow.png)、[停止状态](assets/metrology-final/03-stopped.png)。
- 首次 Vite 仍被 runtime-config 指向业务 5600，识别后立即停止；仅登录及读取列表，没有启动、修改或删除业务对象。随后在临时 Vite 配置明确返回 5620 的 API/WS 地址，重新登录空库，以上运行证据均来自隔离环境。临时配置不进入生产源码。

### 大载荷故障

复用既有容量测试、正式发布支持、ObjectStore 和 Python 客户端，不增加测试客户端或生产降级。Windows 16 MB 预检 **4 项通过**；精确 1 GB 组合 **3 项通过**，HTTP 短传补强后仅重验该用例，**1 项通过**。覆盖范围如下：

| 故障与恢复 | 验证内容 |
| --- | --- |
| 不完整正文 | 声明 1,000,000,000 B，实际流式发送 999,999,999 B；明确拒绝，文件暂存和 pins 归零 |
| 连接断开 | 在真实 TCP 连接实际发送 16 MiB 正文且已分配暂存后断开；回收后同 session 完整上传和 Preview 成功 |
| 保存写失败 | 真实写完整块后，在隔离 ObjectStore 边界注入 ENOSPC；没有提交版本或残留 content.bin，原运行数组仍可用，随后保存、ZIP 往返、导出和派生恢复成功。这不是填满实际磁盘 |
| 执行 worker 退出 | 在真实 Filter Valid 的 node-started 后强杀本测试 worker；调用和 Run 均为 failed，不伪装成功；原进程退出，租约/准入归零 |
| 版本切换 | 停止、禁用 Trigger 后按 expected_generation 切版；旧 generation 请求明确拒绝，新版本真实调用成功，回执版本及 worker 身份一致 |

文件链逐行比较 62,499,984 点全部 XYZ、uint32 字段和原始行号；派生 31,250,064 点保存恢复一致。ZIP 为 1,000,001,463 B，数组预算和临时文件最终归零。worker 故障使用 62,500,000 点紧密数组，Broker 2 GiB 全部归还。

证据：[HTTP](assets/metrology-final/capacity-http-windows.json)、[文件](assets/metrology-final/capacity-file-windows.json)、[worker/版本](assets/metrology-final/capacity-worker-fault-windows.json)。worker 故障进程树 441 次有效采样、2 次退出中间态丢弃、无采样错误；合计 RSS 峰值 2,020,360,192 B，线程峰值 90。末尾仅测试主进程，线程 43→41、句柄 766→735；不据此推导最低整机 RAM 或长期无泄漏。HTTP/文件报告 RSS 是主进程，不冒称浏览器/全部角色峰值。

### 该批结束时未通过的出口

1. 上述新增故障本轮只验证 Windows。Ubuntu 上轮临时 venv 已清理，本地未找到完整离线依赖；联网准备命令被安全审核阻止，未绕过限制。已请求仅在隔离构建目录准备已核定依赖的授权，尚未执行安装。
2. 当前既有 Windows CPU 包的 Python 缺 Open3D；A12 当时的隔离完整包已清理。没有修改既有发行目录，没有把该旧目录冒充本轮候选，也没有据此否定已归档的 A12 代码和验收记录。
3. 六条页面路径中，可读性组合已补证；来源生命周期等自动测试继续有效，但固定资产冲突/导出、其余方法和草稿/版本切换的完整真实页面矩阵仍未全部补齐。
4. 最终双平台 CPU 发行重装配、同候选组合及分角色/浏览器资源矩阵尚未完成。十秒与近 1 GB 显示索引仍独立保留，不重复旧 S2 稳定性或模型 P99；B 项未在本批新增。

本批源码和测试身份见[续验候选](assets/metrology-final/candidate.json)，与前文候选区分。未自动 Git 提交。

续验收尾：本轮页面 Runtime 已正常停止，5620/5621 无监听；进程清单未发现本轮隔离服务/worker/测试进程，原有 5600/5601 仍在监听。仓库 `.tmp/` 已清空，Ubuntu 没有创建成功的临时环境并已恢复原先停止状态，其他发行版未停止。Ruff、前端构建及 `git diff --check` 通过。

## 双平台隔离发行续验

2026-11-03 获准准备隔离构建依赖后，补齐上节第一、二项环境条件，并执行原第三、四步中的容量故障及离线主流程。没有修改算法、生产配置、既有 `release/`，也没有重复实现装配器、进程管理或节点。前三个参数编辑器和结果表的源码与上批冻结候选相同；本次只增加验收证据和进度说明。

### 构建身份

- Windows 使用隔离复制的 Python 3.12.15，Ubuntu 使用已核定的 CPython 3.12.16 便携包，SHA256 沿 [CPU 发行说明](../deployment/cpu-offline-release.md)。所有下载/安装在隔离构建目录执行，系统 Python 和原有 CPU 包不变。
- 两平台实际 `pip check`、`validate-layout` 均通过。CPU-only torch `2.12.1+cpu`；三维六项精确依赖为 NumPy 2.4.4、SciPy 1.18.0、Open3D 0.20.0、trimesh 5.1.1+amvision.2、pypcd4 1.5.1+amvision.2、python-neo-lzf 0.3.5。Pydantic 按当前 I/O 约束为 2.13.4 / core 2.46.4；其余实际分发版本完整保留在 source.json。
- 两平台同用本次 Vite 静态产物和 `assemble-release`。逐文件核对 backend、custom_nodes、launchers、A11 客户端/配方/示例：Windows 3,275 个、Ubuntu 3,273 个文件符合源码；各 116 个前端文件完全一致。Ubuntu 两个 `.sh` 按装配器现有规则转 LF，其余比较不做归一化。
- A11 随包 `invoke --help` 与数组配方生成实际执行成功，不要求目标包存在 tests 或源码仓库。
- 发行工件使用已有 `workstation.example.json`，容量故障使用已有 `workstation-1gb.example.json`，不混称同一个容量配置。Ubuntu 运行数据均位于原生文件系统。

### 实际结果

| 验证 | 本次结果 |
| --- | --- |
| Ubuntu 精确 1 GB 原故障组合 | 3 项通过，163.07 秒；完整短传/真实断连、保存写失败回滚、worker 强杀/切版/再次调用全部覆盖 |
| Windows CPU 正式发行 | 两次运行各 50 项与冻结数值、三态及落盘记录一致；空环境导入、真实发布、停止全栈、同目录重启成功 |
| Ubuntu CPU 正式发行 | 同一资源包，两次运行各 50 项一致；同样覆盖空环境与持久版本重启 |
| 正式静态前端与停止 | 各轮 HTML 和 6 个入口资产响应正常；两平台各轮记录的受管子进程身份全部退出 |

资源包 SHA256 为 `1d70898f9ddeb4d743719e196cb6cd88a2f02a29af17ec52b3345ec479ae2fb5`。包内原云资产摘要保持 `c9566ae231f30a4b55226673d8644346eb6a58d8bafb66130784596c2da345ed`，同完整 14,745,099 点样本；每轮使用正式 111 节点图。运行不下载依赖、不使用 Vite；外部 HTTP 代理不可用和模型离线变量沿原驱动设置，不冒称操作系统断网审计。

发行 invoke 至结果/落盘核对时间：Windows 12.984 / 12.968 秒，Ubuntu 18.692 / 16.881 秒。包含资产读取，期间还有其他验收负载，**不是 A01 纯检测十秒验收**。本次不改十秒状态、不重跑历史 S2/P99，也未新跑长稳或页面矩阵。

Ubuntu 1 GB 文件链逐行验证 62,499,984 点、全部字段、原始行号及 31,250,064 点派生恢复；最终活跃数组、文件暂存归零。worker 故障后旧请求被拒，新版本调用成功，租约为零、Broker 2 GiB 全部归还。进程树合计 RSS 观测峰值 2,231,021,568 B，线程峰值 97；末尾为测试主进程和 multiprocessing tracker，线程 59→59、句柄/FD 21→19。进程树 1,252 个样本，另有两次 `(pid=544)` 采样错误；报告保留原值，不能称为无采样错误或通过正式资源门禁，也不能用短时观测证明长期无泄漏。

退出日志还有一项需如实保留：Ubuntu 后端两次停止均完成 application shutdown，但 `resource_tracker` 报告 10 个 semaphore 待清理。正式停止驱动已确认受管进程退出；尚未完成该警告的独立根因及退出前后 IPC 对照，不将它掩盖为“资源完全无警告”，也不据此推断测量失败。它属于既有 A13 资源核对，不新增功能阶段。

环境准备中的两类失败不属于产品回归：首次 Ubuntu pytest 缺少原生临时父目录，三个用例未执行，补目录后原组合通过；临时文件审计最初未考虑 assembler 已有的 Shell LF 转换，按该规则核对后通过。Windows 工具审计第一次受沙箱 Temp 写权限限制，改用已获准的隔离目录和正常执行权限后通过，没有修改生产回退逻辑或系统权限。

证据：[Windows 发行](assets/metrology-final/offline-windows/report.json)、[Ubuntu 发行](assets/metrology-final/offline-ubuntu/report.json)、[Ubuntu HTTP](assets/metrology-final/capacity-http-linux.json)、[Ubuntu 文件](assets/metrology-final/capacity-file-linux.json)、[Ubuntu worker/切版](assets/metrology-final/capacity-worker-fault-linux.json)。两个发行子目录含源码逐文件清单/摘要、实际依赖、逐轮结果、布局检查和启动/停止/后端日志。依赖、原云副本及临时数据库不作为 Git 资产保留。

### 剩余范围

本批完成双平台新增容量故障对照及同源码 CPU 离线主流程，不再保留“等待依赖授权、尚未重新装配”的当前阻塞。A08 剩余真实页面操作、A13 分角色/浏览器资源和上述退出警告仍未收口；A01 十秒和近 1 GB 索引有界构建独立保留。A03 工程接受、A04 外部计量证据及 B01–B23 原范围不变，不能用本次运行将它们一并标为完成。

收尾审计：3,909 个冻结源码文件摘要、5 个本批变更摘要、352 个本地文档链接及两个发行报告核对通过。原清单使用 PowerShell zh-CN 排序；已明确该排序规则并补充跨平台 ordinal 摘要，未以排序差异误报源码变化。`git diff --check` 通过。5630/5632 及 5620/5621 无测试监听，Windows 无本轮测试进程，Ubuntu 原生隔离目录已删除并恢复停止状态；仓库 `.tmp/` 为空。业务 5600/5601、原始 PLY、已有 `release/` 和系统 Python 未修改；其他 WSL 发行版未停止。本批没有自动 Git 提交。
