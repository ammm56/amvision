# M3.2 边界与拟合实施记录

## 1. 当前交付范围

2026-10-23 接线批次已实现 `extract-boundary`、`fit-line`、`fit-circle` 的内部 Catalog、GraphExecutor、保存恢复及 Vue 编辑器，内部节点共十五个。生产 manifest 仍不存在，节点不可发现、不可启用。第 3–4 节保留前一批计算内核的实现和验证记录，本次接线与当前限制见第 5–7 节。

源码基点为 `1b91b05f`。本批在原 CloudRuntime/Scope 内扩展来源视图，同批升级三维运行引用、资产、显示及图输入读取方；不另建资源服务或发布系统，不修改已有业务资产。

## 2. 已确认规则

- 整片共面三角区域返回 `coplanar_region`，不能将区域外缘冒充截线；单条共面边对称保留，反转法向不改变几何。
- 原始点与有序源点视图保留全部字段及原始精度；生成顶点仅保存坐标、源边/面及插值关系，不自动插值颜色、强度或法向。
- 实测点最初输入行号和 `source_point_count` 语义不变；内核返回的父逻辑行号必须由 CloudRuntime 映射，不能直接作为最初输入行号输出。
- 统一升级受影响的三维格式和读取方。旧三维开发资产不删除、不自动迁移，不维护旧算法执行分支；使用新节点前重新保存/导入。二维资源、原始 PLY/PCD 和 Workflow 发布版本系统不变。
- 生产容量、timeout、kill grace 和节拍未确认，继续不启用节点。测试数值不作为生产默认。

## 3. 前批计算内核实现

### 3.1 参数与拓扑

[boundary3d.py](../../backend/contracts/workflows/boundary3d.py) 复用 `Contract`、现有 ROI、`GeometryQualityPolicy` 和 `LimitRule`：

| 对象 | 字段与检查 |
| --- | --- |
| EvaluationPlane3d | frame_id、length_unit、origin、rotation；列向量分别为面内 X/Y 与正法向，严格正交右手 |
| BoundarySurfaceSettings | alpha_radius、max_edge_length、max_normal_step、min_projected_area；全部显式提供 |
| projection | 只定义投影支持拓扑，输出点仍为实测三维坐标 |
| section | origin、normal、numeric_tolerance；有限支持面求交，不改变全局库容差 |
| contour | reference_feature_id、positive_normal、min_orientation_cosine、height、numeric_tolerance；沿定向基准法向偏移 |
| BoundaryTarget | 稳定 segment_id、完整有限 ROI、closed、role；选择完整候选而不裁断段；零个/多个匹配分别无效，同一候选不能重复赋予两个目标 |
| FitLineParameters | 稳定特征与段选择、评价面、正方向、最小方向余弦、显式质量；TLS 是唯一实现方法 |
| FitCircleParameters | 稳定选择、评价面、正半径范围、最大相邻弧步长、完整求解参数、显式质量 |
| CircleSolverSettings | ftol、xtol、gtol、max_nfev、x_scale；固定 TRF、解析 Jacobian、精确子问题、linear loss，不按失败切换算法 |
| BoundaryTopology | 新的内部拓扑契约 `amvision.boundary-topology.v1`；point_count 与完整 segments 分区；不含运行访问权 |
| BoundarySegment | segment_id、start、count、closed、role、orientation；段连续分区、不跨段连线，闭段不重复首点 |

公开 feature、运行引用、资产及显示使用同批严格模型生成 Schema，见第 5 节；没有将自由 `dict` 几何作为公开契约。

### 3.2 边界计算

计算责任分为五个已有包内模块，不新增服务或资源管理器：

1. [boundary_surface.py](../../custom_nodes/_metrology3d_nodes/shared/boundary_surface.py)：SciPy Delaunay；拒绝重复投影、多层同 XY、退化和遗漏顶点；按显式半径、边长、法向跳变和面积条件保留支持面。
2. [boundary_section.py](../../custom_nodes/_metrology3d_nodes/shared/boundary_section.py)：受控 trimesh `mesh_plane` 的局部尺度适配；正反法向分别求交后按源身份合并。保留全部关联源面，而不是只记录去重前的第一个面。
3. [boundary_topology.py](../../custom_nodes/_metrology3d_nodes/shared/boundary_topology.py)：按实际边邻接组织开链/闭环，拒绝分叉、重复边、自环和零长边；不作最近邻补线。大量独立段使用一次排序，避免重复扫描剩余顶点。
4. [extract_boundary.py](../../custom_nodes/_metrology3d_nodes/shared/extract_boundary.py)：组合三种方法，复用 `roi_mask`；执行目标唯一匹配，返回失败的稳定 segment_id；生成点记录源边权重及逐顶点完整源面关联。
5. [boundary_fitting.py](../../custom_nodes/_metrology3d_nodes/shared/boundary_fitting.py)：中心化 TLS、几何圆最小二乘、逐段有限区间/弧段、真实缺口与质量指标。

源面关联采用 offsets + faces 的变长数组，源面保存三个父逻辑顶点；共面共享边的两侧来源都保留。前批此结构仅为内核工作结果；本批已将其映射到最初输入行号并接通 CloudRuntime 所有权及资产，见第 5 节。

投影是采样边界估计，不承诺恢复不可分辨的实体尖角。独立 L 形网格测试确认：凹角三角形若与内部网格具有相同 alpha 和边长支持，不能凭这些规则排除。测试检查实际支持定义下的凹形，不把凸包当边界，也不以未知实体轮廓作为无依据的期望。

### 3.3 求解、质量和错误

- 直线按完整段作面内正交拟合，记录面外偏差、方向分离、RMS、最大残差、跨度和段间缺口。各段参数区间独立保留。
- 圆的代数解仅作初始化；最终解由 SciPy 几何径向最小二乘产生。明确记录收敛状态、求值次数、代价、最优性和半径边界命中。
- 连续支持弧从真实相邻顶点展开，拒绝大角跳变、回折和重复绕圈；不通过重新按角排序伪造连接。多段覆盖作区间并集，不填补真实缺口。
- `evaluate_fit_quality` 调用同一 `geometry_quality` / `check_limits`，没有第二套限值算法。面外点或短弧可以求得数值候选，但质量不通过时不能成为有效特征。
- 预算、取消、原生异常保持执行错误；无交线、缺目标、歧义、共面区域和几何退化为明确原因。圆迭代恰好经过支持点时返回不可微退化，不切换代数结果。
- 工作预算估计覆盖已知工作数组和对象，不宣称限制整个进程 RSS。完整输入仍通过既有入口读入；只在明确、已准入的局部 ROI 上建立三角面。

## 4. 前批内核验证记录

Windows 使用独立 `.tmp/m32-env`，继承现有 amvision 环境并安装仓库内受控 I/O wheel；未修改开发主环境。WSL Ubuntu 使用 `/home/am/.cache/amvision-m32` 独立环境，运行数据、缓存和 pycache 位于原生文件系统。只读源码和完整输入可来自 `/mnt/w`。

关键数值依赖为 NumPy 2.4.4、SciPy 1.18.0、trimesh 5.1.1+amvision.1、pypcd4 1.5.1+amvision.2。没有扩大第三方 I/O 修复范围；没有安装自建 C/C++ 适配器。

定向测试包括：共面区域/边、过顶点、法向反转、mm/m、源边权重和全部源面；凹形、多孔、断带、乱序、重复投影、缺目标/多目标；TLS 的解析方向、正交残差和大平移；整圆/半圆/短弧、断弧、任意评价面、半径边界、迭代失败；预算、取消、原生异常和质量单位错误。

最终候选结果：Windows **240 passed / 30.85 秒**，WSL Ubuntu **240 passed / 33.58 秒**，各包含一次完整样本测试。组合范围包括本批参数/内核，以及既有点云契约、Runtime、资产、M1 预处理、M2 几何和 M3.1 高度/高差。WSL 初次组合有一项因隔离环境缺少 SQLAlchemy 无法导入；补齐与现有环境一致的 2.0.51 后，该项单独通过，最终组合也全部通过，没有跳过该资源释放回归。

完整样本验证使用原始 479,677,235 字节、14,745,099 点 ASCII PLY，不读取前缀替代全文件：

| 项目 | Windows / WSL Ubuntu |
| --- | --- |
| 原文件 SHA256 | `ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b` |
| 全量 float32 XYZ SHA256 | `956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6` |
| 显式测试 ROI | 两平台均为 311 点 |
| 投影边界 / 截面 | 两平台均为 44 / 20 点；源行、源边、权重核对一致 |
| 人工 ROI 边界拟合半径 | `0.2866204012515831`；不是实体孔径，也不是标定真值 |
| 样本截线 RMS | `0.015525559422087208`；高于测试配方 0.01，质量必须拒绝，不放宽门槛 |
| 资源 | 既有输入/过滤/裁剪 Runtime 关闭后数组预算归零；新顶点 Runtime 所有权尚未接通，不借此宣称已验收 |

完整样本只证明本批读取、局部计算和来源自一致性，不证明新节点发布、前端、可追溯测量准确度或生产容量。

## 5. 运行引用与保存契约

| 契约 | 本批格式与消费者 |
| --- | --- |
| 点云运行引用 | `point-cloud-ref.v2` / `amvision.point-cloud-ref.v2`；Graph、Trigger 入站、App Contract/Mode、节点及 Scope 同批更新 |
| 点云资产内容 | `amvision.point-cloud-asset.v2`；资源外层仍为 `amvision.measurement-resource.v2`，不升级二维内容 |
| 特征 | `features3d.v2` / `amvision.features3d.v2`；严格区分 plane/boundary/line/circle；原平面消费者拒绝其他类型 |
| 显示 | `amvision.point-cloud-preview.v2`、`amvision.geometry-preview.v2`；Preview/Runtime 捕获、共享 viewer、编辑器同批更新 |
| 不变的传输 | `point-cloud-buffer.v1`、Cloud PREPARE、LocalBuffer ABI 和 .NET 数组传输布局不变；它们传原始数组，不传运行 ref |

运行引用新增 `vertex_kind=source/generated` 和可空 `topology`。unavailable 分支二者均为 null。有序源点沿 `register_ordered` 保留全部原始字段和最初行号，普通 subset 仍严格递增且裁剪后清除旧拓扑。生成点沿 `register_generated` 注册位置和独立来源 owner；两者均归已有 Scope，不新增句柄系统。变换只改位置，来源继续指向最初输入；生成点禁止调用 `source_indices()`。

来源块采用固定 little-endian 布局：N×2 uint64 `source_edges`、N×2 float64 `weights`、(N+1)×1 uint64 `face_offsets`、K×3 uint64 `source_faces`。`lineage.bin` 长度严格为 `40*N+8+24*K`，保留原始 source_point_count；CSR 每点必须有支持面，权重有限且和为 1，行号范围、面顶点和源边归属逐项核验。源点资产仍使用 data.bin 和可选 source-indices.bin；生成点使用 data.bin 和 lineage.bin，不伪造原始行号。分块写出、摘要检查与恢复沿已有 ObjectStore/资源服务；全部活数组计入原预算，工作估算不是进程 RSS 硬上限。

已确认并实现扩展原 `save-cloud` 的可选 `features:features3d.v2` 输入：仅派生模式接受一个有效 boundary，且 support 必须等于保存的完整 cloud。资产 `boundary` 保存方法、逐段质量、拓扑和原观测证据，不保存运行权限。`read-cloud` 增加可选 features 输出，恢复时绑定新的 run/observation/support；普通已知物理空间点云输出空特征集，单位未确认的原件不伪造 Features3d。只存普通点云不能凭空恢复边界质量；重存已有资产可原样保留已存证据。

旧三维资产保留原文件、不自动迁移。列表返回明确 `rebuild-required` 元数据，不执行旧内容；使用新节点须从原件重新导入/保存。依赖删除检查仅读取已核验历史父引用，既保护其父资产，也不阻止删除不相关资源。不保留旧格式执行分支。旧三维显示和旧图输入类型明确拒绝，受影响配方审核重发。

## 6. 节点与界面

- extract-boundary 复用 ROI 和三种完整计算路径，输出 cloud 与严格 BoundaryFeature；逐目标失败定位、计数和质量保存，失败输出没有可使用的边界云。
- fit-line/fit-circle 只消费明确 feature_id/segment_ids 的完整边界；不从普通散点猜拓扑。区间分别保存，不连接缺口；有效圆必须真实收敛且未命中半径边界。
- 前端沿可信编辑器注册表接入方法、评价面、有限 ROI、稳定目标、支持段、求解参数及现有限值编辑器。未知阈值留空，缺项不可应用；更换节点或输入后关闭草稿，更换 Preview 后清除旧显示选择。
- 共享 Three.js viewer 显示完整受预算约束的边界与拟合区间；超容量拒绝，不对抽稀点重新连线。生成点显示逻辑顶点号而不是原始行号；原始有序点允许非单调原始行号。选择、缓冲计费和卸载沿既有组件生命周期。

## 7. 接线批次验证与剩余范围

使用隔离 Windows Python 环境和 WSL Ubuntu 原生缓存/运行目录；依赖版本与第 4 节一致，不修改开发主环境。真实 GraphExecutor 测试覆盖提取→保存 features→关闭→新运行读取→拟合直线/圆，并断言 Scope 关闭后数组预算归零。另验错绑支持、缺失质量、旧资产只读拒绝、无关资源删除、来源字段和分块 CSR、三维显示容量及前端任务/输入切换。

完整 479,677,235 字节样本本批重新执行了运行引用、保存恢复及拟合组合，不只运行纯内核。Windows/WSL 均为 311 ROI 点、44 投影点、20 截面点；恢复前后几何/指标一致。截线 RMS 仍为 0.015525559422087208，按原测试门禁保持无效，不增加公差。

最终候选验证结果如下。Windows 的组合包含点云入口/传输及共享资源回归；WSL 的本轮范围为契约、运行所有权、资产、节点与算法，不将不同测试范围的数量解释为完全相同的覆盖。

| 验证 | 结果 |
| --- | --- |
| Windows 点云/M1–M3.2 定向组合 | 378 passed / 11.84 秒 |
| Windows 共享二维计量资源、Trigger 输入契约 | 22 passed / 6.59 秒 |
| WSL Ubuntu 契约、来源、资产、M1–M3.2 节点/算法组合 | 219 passed / 19.79 秒；运行目录在原生文件系统 |
| 完整样本运行、保存恢复、拟合、释放 | Windows 1 passed / 28.25 秒；WSL 1 passed / 19.03 秒；原文件及全量 XYZ 摘要一致，Scope 关闭后数组预算归零 |
| 前端 Workflow 回归 | 21 文件、126 passed / 3.82 秒；包括编辑生命周期、显示拓扑/容量、资源只读与既有页面逻辑 |
| 静态与构建 | 58 个变更 Python 文件 Ruff check/format 通过；Vue 类型检查、Vite 生产构建及 diff 空白检查通过 |

浏览器使用真实组件和后端生成的显示正文，能力接口采用显式测试配置。1280×720 桌面与 390px 宽 iframe 内检查拟合参数、Preview 选择、支持段高亮、滚动和取消；画布截图像素非空，无框架错误遮罩。修正测试入口的 API base 后没有新增相关控制台错误；早期错误配置留下的 404/i18n 日志不计为应用通过证据。该验证不等于已登录生产页面或真实发布准入。生产构建仍报告大于 500 kB 的 WorkflowEditor/CloudViewer 分块警告，未调整警告门槛，查看器继续按需加载。

本轮最终审计补齐并验证了生成坐标有限性、源边归属支持面、质量支持计数及旧资产父引用保护。旧资产只读不能运行，但仍保护所引用父资产；无关资源删除不受阻。源码消费者中不再保留受影响的 v1 三维格式路径，v1 只作为明确拒绝的测试输入。生产 manifest 仍不存在，未写入生产预算。

临时 5619 Vite 和浏览器测试页已关闭，测试子进程均结束。仓库 `.tmp/` 测试目录、构建产物及 Windows 隔离环境已清理，WSL 六个本轮 `amvision-m32-runtime-*` 临时目录已清理；原有 pip 缓存、用户 5600/5601 服务、原始样本和业务资产未改动。截图仅保留在工作区外的可视化目录，不把临时样本作为交付资产。

仍未验收：新三节点配方的真实发布→独立 WorkflowAppRuntime→Trigger/.NET 全组合；目标发行包中的依赖装配；标准件标定、重复扫描、公差与节拍；未批准的 timeout、kill grace、内存/显存及容量。生产包继续隐藏，不以本轮测试宣称工业测量资格。未运行 P99 或长稳，未更改模型训练/推理数值路径。

## 8. M3.3 开工前复核

2026-10-23 对照提交 `90c94d6c` 核对：本文件所述十五节点、运行来源、资产 v2、保存边界恢复及前端接线已在源码中；measure-extents、measure-edge-pair、measure-hole 尚未实现。第 7 节仍是既有验证结果，本次只核对源码与记录，没有重新执行测试，也没有将旧阶段发布记录视为新三节点通过。

下一阶段见 [M3.3 长宽、边间距与孔径设计](3d-metrology-m3-dimensions.md)。先补本阶段新配方的真实准入和完整页面验收，再逐节点实现尺寸计算；不重复实现边界、拟合、CloudRuntime 或发布系统。测量证据将按实际新量扩展同一契约，点云引用/资产 v2 不因尺寸节点再次升级；生产仍隐藏。

2026-10-24 补验：M3.2 合成线/圆和完整样本已走正式发布→独立 Runtime→Trigger，
Windows 使用 .NET，Ubuntu 使用真实协议客户端；停止、切版、异常退出及资源回收通过。
圆配方完整页面已完成编辑、Preview、发布、App Mode 与停止，修复了无 MIME 文件被误拒绝。
最终受控 trimesh `.2` 下两平台定向组合各 140 项通过，精确范围、未覆盖项和证据见
[M3.3 前置验收记录](3d-metrology-m33-acceptance.md)。第 7 节原验收缺口是当时状态，不覆盖本次补验；
发行、工业计量、生产预算以及未来三个尺寸节点仍未完成。
