# B04 特征粗定位

日期：2026-11-05。基点 `6293ec57`，包 `0.1.27`，仍为二十四节点。本批扩展既有 Register Cloud，不新建定位、资源或调度系统；原 111 节点、317 边、50 项工件测量图不改。

## 1. 已确认的语义

`initialization=explicit` 保留显式初值局部 ICP；`initialization=fpfh` 使用 FPFH、严格双向特征对应、多批 RANSAC，再调用同一 ICP。两种模式互斥，无隐式重采样、法向估计、缩放、镜像或质量失败回退。

每批 RANSAC 只产生一个候选，不能将它理解为枚举所有解。每个候选使用原有双向覆盖、全对应残差、六自由度可观测性及收敛条件。任意两个合格候选超出显式姿态等价范围，返回 `ambiguous/ambiguous_candidates`，无可执行矩阵。不按最高分挑选，不用单链聚类吞掉首尾不等价的姿态。全部合格候选两两等价时按批次取第一个；这只表示“本次有限搜索未见多解”，不证明全局唯一。

RANSAC 使用库的随机状态，不重设全局随机种子，不影响 Fit Plane 的种子配置。实际初值、精化矩阵、指标和失败原因均保留；不承诺跨线程、跨平台逐位重演随机采样。重采样、法向方向和邻域尺度须在图中显式声明，不能把显示采样用作算法输入。

## 2. 参数与证据

公共 settings 继续保存 pose ID、源/参考 frame、单位、ICP 方法与停止条件、原质量策略。新增必填 search：

| 字段 | 含义与边界 |
| --- | --- |
| feature_radius / feature_max_neighbors | FPFH hybrid 邻域的物理半径及邻居上限；不自动放大 |
| max_correspondence_distance | 粗定位的对应距离，与 ICP 对应距离分别配置 |
| edge_length_ratio | 原生边长一致性检查下限，(0,1] |
| samples | 每个 RANSAC 假设至少三个对应 |
| iterations_per_trial / trials | 每批显式假设预算及至少两批搜索；confidence 固定为 1，仅用于执行完整预算，不作为唯一性概率 |
| equivalent_translation | 源原点在参考坐标中的位置差上限，使用 length_unit |
| equivalent_rotation_degrees | 两个旋转的测地角差上限，(0,180] |

候选数上限沿现有 8192 项质量表结构容量计算为 `8192 // 11`，不是生产建议值。工作预算另外检查输入规模、FPFH/SPFH、原生复制/索引、RANSAC 预采样和证据成本。

根质量新增 `candidate_consistency=1` 必检；每候选仍使用相同的十一项既有指标和同一比较器。等于 1 的含边界规则不可关闭。方法 scope 为 `feature-se3`，记录严格双向匹配数、连续批号、初始/精化矩阵、失败原因及逐项质量。根指标必须对应实际代表候选；持久 Pose、变换、Preview 读取方共同验证候选与选定矩阵，运行消费者再复核实际质量计算。不另建“粗定位评分”替代原门禁。

特征对应不足返回 `underconstrained/insufficient_feature_matches`；无合格候选返回 `insufficient_quality/no_acceptable_candidate`。坏法向、非有限点、旧 Run、坐标/单位不符和预算不足仍为输入/执行错误。空原生结果的单位矩阵及零 RMS 不能冒充成功。所有失败均不复用上一件 pose。

## 3. 复用、保存与资源

两路 Read/Filter Valid → 可选显式 Resample → Estimate Normals → Register Cloud。原始完整云另接 Transform Cloud，Pose 同时接既有 Preview、B05 求逆/组合或后续查询。粗定位要求两云均有完整有效单位法向；存在 normal_valid/normal_oriented 字段时必须全部有效且已定向。不静默删除坏法向或翻转方向。

原始 float32/float64 和全部属性不改；原生工作数组使用 float64。配准只借用两个当前 Scope 支持，不创建点云 owner。Transform/Save/Read 沿用现有双观测来源和原始行号语义；资产保存搜索证据而非瞬时访问权限。3D 契约仍为 v1，旧开发配置需显式补初始化字段并重存/重发，没有旧解析分支；现有数据不删除。

取消检查覆盖分块读取、原生调用前后、每批搜索及 ICP 迭代。FPFH/特征索引/原生 RANSAC 内部无 Python 取消回调，强制停止继续由既有 worker timeout 和进程组边界负责，不宣称毫秒内合作取消。预算为准入预留，不是 OS RSS 硬限。客户生产容量和超时不变。

## 4. 实际验证

解析椭球独立真值：float32/float64 × 点到点/点到面，旋转 `[37,-22,81] deg`、平移 `[5,-8,11] mm`，变换未传给搜索。覆盖旧引用、原始行号、大整数属性、正逆变换、资产重读、预算拒绝、原生异常释放、全候选质量失败和遮挡拒绝。对称回归受控提供两个真实对称初值，后续 ICP/质量仍使用实际原生算法；它验证歧义处理，不冒称随机搜索必然发现全部对称解。

原生专项验证确认 Open3D 默认双向过滤在匹配不足时会退回单向。本实现使用 `correspondences_from_features(..., True, 0.0)` 禁止该回退，并以实际原生用例验证。额外覆盖 FPFH 刚体不变性、RANSAC 真值及空候选。

完整样本为 14,745,099 点、479,677,235 字节 ASCII PLY，SHA-256 `ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b`。参考由独立 SciPy Rotation 按上述大角度和平移生成。两路显式 stride=512 得到各 28,800 点，B03 kNN=16 估计法向并按各自明确方向定向；FPFH 半径 5 mm、邻居上限 40，粗对应 0.2 mm、边长比 0.9、每假设 3 点、每批 128 次、3 批。等价位置 0.0001 mm、旋转 0.01 deg；ICP 和质量沿解析对照的原设置，无放宽。全部配置只用于本测试，不写入生产默认或原工件测量配方。

| 正式发布运行 | Windows | WSL Ubuntu |
| --- | --- | --- |
| 完整输出点数 | 14,745,099 | 14,745,099 |
| 矩阵最大误差 | 2.66e-14 | 1.78e-14 |
| 双向特征匹配 | 24,047 | 24,047 |
| 合格且等价的候选 | 3/3 | 3/3 |
| 单次发布调用诊断 | 3.993 s | 3.635 s |

完整质量和搜索摘要保存在 [Windows 记录](assets/b04-coarse-registration/windows-report.json)与 [Ubuntu 记录](assets/b04-coarse-registration/ubuntu-report.json)，无需保留临时数据库或完整派生云。

这是同云刚性变换、显式预处理及完整原云变换的功能验证，不是重复实测扫描、遮挡下工程定位成功率或实体精度认证；计时含保存资产读取和显示响应，环境非独占，不作为原 50 项图的十秒结论。测试工作预算 4 GiB、双云活跃数组 2 GiB，未改生产 1 GiB 活跃数组。Ubuntu 的数据库、锁、mmap、缓存和临时环境均在原生文件系统；Windows 挂载盘仅供源码与只读样本。

首次完整样本测试因测试图法向 frame 写成 sensor 而实际为 fixture 被正确拒绝，修正测试接线后通过；未修改产品坐标校验。一次目录一致性检查发现更新契约说明后未重生成 Catalog，重新生成后 Windows 与 WSL Ubuntu 受影响组合各 **114 项通过**。前端参数/位姿/动态等高/查看器组合 **35 通过、1 项既有条件跳过**（I2 外部夹具未提供）；Vue 类型检查与 Vite 构建通过，保留既有大 chunk 警告。

## 5. 页面与复验

沿已有参数工作区增加初始化选择、特征搜索成本和姿态等价范围。模式切换清除互斥字段；取消不改配方；来源/节点变更关闭旧编辑态。显示同次完整工件范围、输入/显示点数、有限搜索说明及各候选质量，不把局部有效写成全局唯一。

Windows 隔离环境 5620/5621 完成真实完整样本 Preview、参数防错、取消、保存重开、发布版本 1→2、停止后切换、启动和同步调用，最终停止。Workflow 发布版本号是既有发布管理，不改变三维 v1 契约。源点云为完整样本；配准支持点 28,800，变换输出 14,745,099，页面显示明确标注 100,000 点有界采样。1440×960 与 390×844 页面验证了当前同次点云、参数/三维/证据切换和候选详情；浏览器未观察到警告或错误。发现候选表复用了旧固定列宽，已改为紧凑候选行、按行展开全部指标，并补默认折叠回归。不改测量值或证据字段，不操作系统显示缩放。

- [工作站页面](assets/b04-coarse-registration/desktop.jpg)
- [窄屏候选证据](assets/b04-coarse-registration/narrow-evidence.jpg)

Ubuntu 覆盖原生算法、Scope/资产存读、正式发布运行及停止/重启，不冒称覆盖 Ubuntu 浏览器。取消验证包括原生调用边界、异常释放和既有进程停止路径；本批未新增长时间原生 RANSAC 内核中途强杀用例，不能将空闲停止/重启写成该项已通过。

结束时隔离 API/worker/Broker 与静态前端已退出，5620/5621 无监听；本轮 Windows `.tmp` 与 Ubuntu 原生临时环境、缓存、派生点云均已清理。仅保留文档、回归代码和小型验收记录。业务 5600/5601、原始样本及现有发行包未修改，未自动提交 Git。

```powershell
conda activate amvision
python -m pytest tests/test_metrology3d_coarse_registration.py tests/integration/metrology3d/test_coarse_registration_native.py tests/integration/metrology3d/test_coarse_registration_published.py
python -m tests.integration.metrology3d.registration_acceptance --root .tmp/b04-coarse-full --sample <完整样本路径> --coarse --registration-stride 512
```

## 6. 当前剩余与固定下一步

| 范围 | 已完成 | 剩余 |
| --- | --- | --- |
| B01–B03、B05 | 去噪、重采样、法向、位姿运算 | 新离线包随 A13 装配，不重复实现 |
| B04 | 显式初值局部 ICP、FPFH 多批候选与歧义处理、同源存读和参数显示 | 台面约束的独立方法；更多重复实测、遮挡/对称工件的配方适用性验证 |
| B06–B10 | 已有文件输入、截线/拟圆基础 | 标定深度/轮廓转云、高度图、实体边/缺测区分、完整圆弧量值 |
| B11–B14 | 已有平面/线/圆及部分测距 | 圆柱/球/圆锥、名义匹配、通用关系、圆角/曲率 |
| B15–B23 | 已有质量残差、结果记录和输出 | 正式形位公差、偏差/缺陷、面积/体积、参考云/网格/CAD、报告/SPC |
| A01/A04/A09/A13 | 原有工程链路及分批证据保持 | 正式十秒、独立实物参考、分角色容量认证、最新源码离线装配；不阻塞上述功能 |

下一步先收口台面约束的运动自由度、输入基准、来源有效性和质量定义，再复用当前注册/位姿边界实现；不能把六自由度结果事后截掉三个分量冒充约束求解。随后按原 B06–B23 顺序推进，不重复本批粗定位。

## 7. 上游依据

- [Open3D 0.20.0 Feature.cpp](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/open3d/pipelines/registration/Feature.cpp)：FPFH 法向输入及双向对应的默认回退。
- [Open3D 0.20.0 Registration.cpp](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/open3d/pipelines/registration/Registration.cpp)：单次候选、预生成采样、confidence 和空结果语义。
- [既有局部配准](3d-metrology-registration.md)：Tensor ICP、全对应质量、Scope 与发布消费者基础。
