# 3D Metrology M3.1 高度与高差实施记录

更新：2026-10-23。承接 [M3 节点设计](3d-metrology-m3.md)。height-query、measure-step 已实现并接内部 Catalog、GraphExecutor 与 Vue 编辑器；双平台验证结果见下文。生产包仍隐藏，不具备生产启用条件。

## 已确认

- 有序源点视图和生成顶点在现有 CloudRuntime 内扩展，保持实测点原始行号语义，不建新资源系统；实际扩展随 M3.2 边界节点交付，不为 M3.1 提前加入未使用接口。
- M3.1 查询位置/两面交点落在实际支持域外一律无效，不允许外推。
- 显示拾取只填写候选位置，显式 Preview 从完整输入重新计算；历史未保存原云不能重测。
- 测量值复用 NumericTable；产品三态留 M3.4，当前只输出测量有效性与几何质量。

## 参数收口

每个节点配置一个稳定 item_id，多个位置沿现有节点复制/Workflow 组合，不引入新的批任务调度。单位/坐标显式给出，所有生产质量阈值留空，测试配置单独给出。

| 方法 | 输入与参数 | 必检质量 |
| --- | --- | --- |
| height-query | 完整目标云、参考平面特征；查询位置、单位方向、径向搜索半径、轴向区间、局部平面配置、交点支持半径 | 双方支持数量、域内覆盖、方向余弦、最近支持距离、覆盖三角边长、局部最大法向残差 |
| measure-step / directional-planes | 两个稳定平面 ID、同一查询位置/方向和交点支持半径 | 与高度使用同一交点和支持检查 |
| measure-step / roi-statistic | 两个已由 crop-roi 明确选出的云；公共原点/方向；mean、median 或明确 method/probability 的 quantile | 双方点数及总体标准差，不套用方向距离质量 |

交点支持实现：在交点的平面切向邻域内读取原精度点；局部中心化后用 SciPy Delaunay 验证覆盖，并保留实际覆盖三角形和原始行号。最近距离/三角边长限制缺口，局部全部候选的法向残差限制混合表面，不只看 RANSAC 选中的一层。几何退化/无覆盖输出无效；资源不足、坏输入和原生异常按执行错误传播。不使用凸包内部判定代替缺口检查，不在失败后改用最近点。

统计使用全支持精确投影；mean/标准差分块稳定计算，median/quantile 的完整临时数组计入预算。统计差没有唯一物理点对，端点为 null，保存双方统计及支持摘要。

## 运行与接线

| 节点 | 输入端口 | 输出端口 | 复用边界 |
| --- | --- | --- | --- |
| height-query | cloud；features 可多连，显式选参考 ID | measurements、evidence、features（目标局部平面） | crop-roi 有限圆柱、fit-plane、CloudRuntime 子集和 Scope |
| measure-step / directional-planes | features 可多连，显式选参考/目标 ID；不得连统计端口 | measurements、evidence | 同一方向交点与支持函数 |
| measure-step / roi-statistic | reference、target 点云；不得连 features | measurements、evidence | CloudView 分块、NumPy 精确统计 |
| cloud-preview | 在既有 cloud/features/pose/roi 上增加可多连 evidence | 原 point-cloud-preview.v1 | 现有显示策略和传输，不下发完整云 |

配置字段统一为 `settings`。跨运行、跨观测、frame/unit 不一致、ID 缺失/重复、模式端口冲突属于配置错误。合法缺测保留配置 item_id，`value=null, valid=false, reason!=null`；无效结果没有旧端点或旧数值。几何有效性不是产品 OK/NG，公开三态仍留 M3.4。

方向距离为 `dot(target-reference, direction)`，允许负值，交换角色或反转方向必须改变符号。高度搜索区间沿显式方向定义，有限圆柱中心为查询点加区间中点乘方向；不自动扩大搜索域。近平行先按明确方向余弦条件拒绝，不先除法放大误差。

局部实际支持采用三个不同原始点的三角形。域内、最邻近距离、最大三角边长、法向残差均须通过配方质量规则；不存在统一默认“可跨空洞大小”。所有阈值由配方显式给出。RANSAC 支持另查原候选区域残差，不能将另一层剔除后假称局部无层歧义。数值秩退化为缺测；非退化输入的 Qhull 执行异常不被吞掉或改用另一算法。

## 逐字段证据

源码以 `backend/contracts/workflows/measurement3d_parameters.py` 和 `measurement3d_evidence.py` 为准。M3.1 首次实现使用测量证据 v1；2026-10-24 在 M3.3 同批升级为 v2，并为高度/高差增加明确 kind，原几何数学不变。以下契约按当前 v2 记录；历史验收仍对应当时版本。不更改既有 NumericTable 或资源 v2 语义，不新增数据库表或数据迁移。

| 对象 | 字段与含义 |
| --- | --- |
| 顶层 | `format_id=amvision.measurement-evidence3d.v2`、observation_id、frame_id、length_unit、items；各项显式 kind 区分高度、高差及后续尺寸；不包含 run_id/CloudReference |
| item | item_id、value、valid、reason、method、geometry、support、quality、sample_origin；ID 与方法配置一致 |
| method | method_id、method_version=1、完整强类型 parameters、parameters_sha256；高度保留完整局部拟合配置 |
| geometry / directional-distance | query_position、direction、两个实际平面交点；检查端点在指定测量线及对应平面上，并与量值一致 |
| geometry / statistic-difference | origin、direction、endpoints=null；不能用质心连线冒充物理测距 |
| support | 固定 reference/target 顺序；content_sha256、point_count、source_point_count、sample_origin、bounds、plane、coverage、statistic；缺测身份全空，空云保留真实身份 |
| plane | valid、reason、geometry、完整 PlaneFitMethod、GeometryQuality；数值质量通过不代表法向约束一定通过 |
| coverage | count、covered、nearest_distance、triangle_edge、max_residual、direction_cosine、triangle、source_indices；三个行号对应最初输入，范围小于 source_point_count |
| statistic | count、value、mean、std、min、max；std 为总体离散程度，不是测量不确定度；计数与完整支持一致 |
| quality | 复用 GeometryQuality 和既有逐项 Check Limits；检查指标集合/单位、质量策略及观测身份，Preview 再执行真实性核对 |

方向交点标为 interpolated；统计保留输入来源，双方来源不同为 mixed，不把全部实测统计误标为 mixed。双方 support 另存输入来源摘要；该字段不赋予历史数组访问权。M3.1 不生成外推点、不开放允许外推参数；未来输入的来源记录不能被覆盖为“实测”。

NumericTable 从同一个证据对象生成，不再算一次量值。有界证据可独立 JSON 序列化，运行关闭后不持有数组/索引/mmap。原始/派生云保存继续使用 M1 的显式保存节点，不自动保存完整输入。

## 生命周期与成本

- 原始数组按既有 dtype 传递；局部计算才转 float64。不建整云 KDTree、持久测量会话或新的 owner 系统。
- 全云扫描采用已有 chunk 预算、取消检查和只读 borrow。局部三角支持按候选数量预检 NumPy、唯一化和 Qhull 工作开销；原生 RSS/线程栈不是公式可以保证的硬上限，仍需目标发行容量验收。
- mean/std 分块累加；median/quantile 为全部 ROI 投影分配临时 float64 数组，预检工作预算。只对自有数组做原地分位选择，不修改父云；不换近似分位数。
- Open3D RANSAC 复用 M2 原生调用。原生调用不能逐点中断，取消/超时仍由既有执行器和进程归属回收；M3.1 不新建线程池或停止系统。
- 失败、预算拒绝和取消释放借用及异常帧；临时 ROI/内点索引由原 Scope 统一关闭。测试要求关闭后 live-array 计费归零。

## 前端操作

- 沿现有受信任参数编辑器注册两个节点。所有空间、方法和质量参数均可编辑；生产数值留空，不填测试阈值。
- 两种高差模式显式切换并清除旧模式参数；不保留隐藏端口或上一模式阈值。参考/目标平面使用稳定 ID，连线关系由既有配方校验核对。
- 工程师选择当前成功 Preview 的有界点云，开启拾取后只填写查询草稿。应用原子提交，取消不改配方；实际量值必须再次显式 Preview。运行切换、结果失效、节点/参数变化和卸载拒绝旧事件。
- 量值表选择与测量线、双方实际支持三角形联动；统计差仅显示双方范围，不画假端点。历史缺测显示原因和空值。
- 平面支持显示使用相同源身份、原始行号和精确坐标匹配。0=无关、1=支持、2=RANSAC 候选剔除；ROI 外的其他点不能染成剔除点。残差色标带实际范围和长度单位，仅描述有界显示点。
- 显示色彩使用自有已计费副本，不改原始颜色；更换结果、关闭或 WebGL 错误释放 CPU/GPU/监听器。显示预算失败只关闭显示，不修改已完成数值。

## 验证记录

冻结候选的实际结果在本节记录。Windows 开发测试使用 conda amvision 的隔离子环境；WSL Ubuntu 使用原生目录虚拟环境和临时数据。受控 I/O wheel 与 Open3D 0.20.0 不变；Ubuntu 临时解压官方 libusb-1.0-0，未修改系统安装。主开发环境与生产配置不变。

| 验证 | 结果与边界 |
| --- | --- |
| Windows 组合 | 420 passed、4 skipped；覆盖 test_metrology3d_*、test_point_cloud_*、controlled_io 和 metrology3d 集成目录；不重跑原生进程压力、geometry_published、published_runtime 三组既有 M2 专项 |
| Windows 完整样本 | 1 passed；真实 GraphExecutor，479,677,235 字节、14,745,099 点，读取/过滤/基准/height-query/measure-step/显示/关闭；26.14s 为单次观察，不是性能门禁 |
| WSL Ubuntu 组合 | 418 passed、6 skipped；与 Windows 相同选择，额外跳过现有 net472 Windows .NET 的 bytes/fill 两项，不将 Linux SDK 记为通过 |
| WSL Ubuntu 完整样本 | 1 passed；相同文件/点数、查询位置、高度 0 与行号核对，16.27s 单次观察；ObjectStore/临时目录均在 Ubuntu 原生文件系统 |
| 前端 | workflows 19 文件、115 项通过；vue-tsc、Vite 生产构建通过。Three.js 按需 chunk 约 645 kB，保留既有 >500 kB 构建提醒，不放宽门禁 |
| 浏览器组件 | 正式 Vue/Three 组件、真实完整样本图输出、显式测试 capabilities；1280 与 390px 视口截图中画布非空，无横向页面溢出；拾取、取消/应用、平面着色、关闭后 canvas=0、重开及控制台检查通过 |

测试页只读采样实际 WebGL 绘制缓冲：桌面 1248×272 画布有 10,654 个有色像素，窄屏 358×180 有 5,205 个。关闭显示后 `rendererUsage` 的 CPU/GPU 计费均为 0，canvas 数量为 0；这是客户端缓冲生命周期证据，不是浏览器进程 RSS 测量。浏览器工具整页截图路径曾出现空白，而普通视口截图及实际像素读取正常，未因此改动渲染器或放宽门禁。

解析真值包含 float32/float64、水平/倾斜/垂直面、1e8 整体平移、反向距离、空支持/孔洞、近乎平行、双层拒绝、完整均值/中位数/分位数、稳定行号、证据篡改、预算和取消。真实图覆盖成功→缺测→成功；Open3D 测试证明另一层被 RANSAC 剔除后仍因原候选残差拒绝测量。

完整样本 SHA-256 为 `ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b`，float32 positions 摘要为 `956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6`。同一局部面作为双方得到高度/高差 0，两个方法各自检查 311 点支持及原始行号。这是数据/链路自一致性，不能替代工件标定真值。显示最多 10,000 点是显式测试配置，计算仍使用完整输入中的实际 ROI。

收尾：变更 Python 的 Ruff 和 `git diff --check` 通过。仅启动临时组件 Vite 服务，未启动生产后端/worker；测试服务已停止，5617 监听和本轮 Windows 测试进程数均为 0。仓库 `.tmp/` 本轮 14 个目录已清空；WSL 专用原生测试环境一并移除。用户既有服务、工作流草稿、完整原始样本、受控 wheel 资产保持不变。没有安装到主 Python、没有修改生产参数，没有执行 P99/长稳。

## 剩余边界

1. 有序源点和生成顶点已批准，随实际消费它们的 M3.2 边界/直线/圆节点实现，不提前添加未使用接口。
2. M3.4 的公开三态与消费者、M3.5 的尺寸配方正式发布/Runtime/Trigger/.NET/App Mode 全流程尚未交付。本轮真实 GraphExecutor 和组件验收不冒充这些验收。
3. 生产 timeout/kill grace、内存/显存、节拍未批准，包无 manifest，仍不可发现和启用。
4. 双平台 bundled profile、完整传递依赖/NOTICE、原生峰值和可追溯标准件准确度尚未验收；没有重跑 P99 或长稳。
