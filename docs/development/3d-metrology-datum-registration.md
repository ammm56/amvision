# B04 台面约束局部配准

日期：2026-11-05。实施基点 `6293ec57`，包含前批尚未提交的 FPFH 粗定位；当前包 `0.1.28`、二十四节点。三维契约仍为 v1。不新增注册节点、资源系统、调度器或依赖。原工件 111 节点、317 条边、50 项测量配方和生产预算均不变。

## 1. 本批定义

用户确认：两路当前有效 Build Frame 分别作为移动与参考基准，Z=0 平面和正法向显式对齐，只求 U/V 平移及绕基准 +Z 旋转。首批使用显式面内初值，局部有效不代表全局唯一；台面内自动粗搜索后续独立实现。不把六自由度 FPFH/ICP 结果投影成三自由度，不回退其他方法。

输入链：每路 Read/Filter Valid 分别接 Crop ROI → Fit Plane → Build Frame；点云接既有 Register Cloud 的 `source/reference`，基准接 `source_datum/reference_datum`。点到面方法的参考云法向由既有 Estimate Normals 显式提供。需要降采样时只在配准支路显式连接 Resample；完整原云仍由同一 Pose 接 Transform Cloud。基准可来自同观测的完整支持，不要求与采样支路为同一个 cloud_id，但必须保持当前 Run、观测、坐标、单位和真实支持身份。

## 2. 参数与失败规则

| 参数 | 定义与检查 |
| --- | --- |
| initialization | `datum`，与 `explicit/fpfh` 互斥 |
| algorithm | `point-to-point` 或 `point-to-plane` |
| initial_uv | 两个有限数，参考基准坐标内平移，单位为 length_unit |
| initial_angle_degrees | 绕参考基准正 Z 的有限转角，度 |
| max_solver_evaluations | 每轮固定对应最小二乘求解次数，正整数，显式给定 |
| solver_tolerance | 数值停止容差，大于 float64 epsilon 且小于 1；不是产品公差 |
| max_correspondence_distance | 三维最近邻距离，不能投影为面内距离而隐藏高度差 |
| max_iterations / fitness_change / rmse_change | 复用显式外层停止参数 |
| quality_policy | 复用逐项限值；对应数、双向覆盖、三自由度秩、可辨识性、收敛、RMS、最大残差和 `datum_valid=1` 均必须参与 |

没有生产初值、邻域、求解次数或工程质量默认值。方法切换清除互斥参数与对应专属指标；秩下限按所选方法的实际自由度从 6/3 切换，其余工程门槛保留。非台面模式残留基准接线明确拒绝。

错误接线、过期引用、缺字段、非有限输入、预算不足属于输入/准入错误。真实基准失效输出 `upstream_unavailable`；无对应 `no_overlap`；退化 `degenerate_support`；求解次数用尽 `solver_limit`；外层用尽 `iteration_limit`；质量不达标 `quality_failed`。失败不携可复用矩阵，不沿用上一件 pose，不把缺测写成零残差。纯台面的点到面残差没有面内运动约束，必须拒绝，而不是假定配准成功。

## 3. 算法与证据

设两套 Build Frame 变换 `T_s/T_r` 均从原坐标映射到各自基准，面内修正为 `C`，最终变换为 `inverse(T_r) @ C @ T_s`。`C` 的 Z 行严格为 `[0,0,1,0]`，不包含倾斜或高度自由度。

已有 Open3D 0.20.0 刚性估计器没有该三变量约束入口；本批复用现有 SciPy `cKDTree` 与 `least_squares` 成熟内核，提供必要的三变量 ICP 控制。对应在基准坐标内按完整三维距离选择；每轮所有对应进入线性损失，解析 Jacobian 只含 yaw/U/V。保留完整欧氏距离 RMS、最大残差和双向覆盖，不删不利点。观测法方程沿现有中心化/尺度归一逻辑，只抽取允许的三个自由度，原六自由度逻辑不变。

新增测试发现纯平面经坐标旋转后的法向舍入噪声会被相对特征值阈值归一成非零秩。本批仅对归一化三维约束法方程加入单位尺度的浮点精度下限，防止噪声冒充约束；不更改工程可辨识性门槛。

`RegistrationMethod.datum` 保存两套完整 Build Frame 证据及可选 C。原始输入支持和各基准平面支持按固定顺序保留，逐项验证 Run/观测/坐标/单位/质量/内容摘要。既有 Frame 证据和矩阵工具移到公共契约文件，配准与 B05 共用，不复制第二套。Pose、B05 正逆组合、Transform、Save/Read、显示读取方同步校验最终矩阵与两基准/C 一致；源字段及 source_indices 不改变。保存的证据不授予历史 Scope 访问权限。

## 4. 预算与生命周期

沿用 CloudRuntime 借用、工作预算和异常释放，配准本身不创建点云 owner。输入读取、坐标变换、对应查询、外层迭代和 SciPy residual/Jacobian 都检查取消。cKDTree 原生建立期间没有 Python 回调，由既有独立 worker 超时与整组停止边界负责。工作预算为保守准入，不是操作系统 RSS 硬限；本批未把空闲停止冒称原生建树中途强杀验收。

## 5. 验证记录

- 倾斜双扫描坐标的独立 SciPy Rotation 真值，float32/float64 × 两种残差方法；局部求解从零初值恢复实际 3° 和面内平移。
- 原始行号、大于 2^53 的整数属性、字段精度、B05 正逆、派生资产保存重读、错误/过期基准、证据篡改、纯平面退化、高度残差、少点、预算拒绝、求解上限、取消及失败支持传播。
- 两路真实 PLY → ROI/Plane/Frame → Register → Transform → Preview 的正式发布版本，独立 Runtime 两轮启动/调用/停止，每轮新观测，Broker/租约回收。没有测试 handler 替换。
- Windows 与 WSL Ubuntu 配准组合各 **90 通过**；正式包目录与既有基准/变换补充组合各 **29 通过**。分组结果不与前批 114 项叠加成“新总量”。
- 前端参数/位姿/几何/查看器组合 **49 通过，1 项既有夹具条件跳过**；Vue 类型检查与 Vite 静态构建通过，保留既有大 chunk 提示。
- Windows 一次受限进程环境中的补充测试在初始化阶段未结束，终止该测试后在允许原生通信的环境复验 29 项通过。未独立证明挂起原因，不将其归因为已确认的权限问题或产品算法错误。Ubuntu 隔离环境出现 Starlette TestClient 的 httpx 弃用提示，测试通过，未改生产依赖锁。

完整样本：14,745,099 点、479,677,235 字节 ASCII PLY，SHA-256 `ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b`。沿用 R5 五窗 D 联合基准的 ROI、SVD 和质量。独立参考按 `[2,-1,3] deg`、`[0.1,-0.12,0.08] mm` 变换，ROI、方向和锚点同样按真值变换。两云各显式 stride=512，配准各 28,800 点；基准从完整原云裁剪，最终变换完整原云。该测试主要证明真实样本的坐标/来源/发布链，初值偏差恢复另由解析真值覆盖。

| 完整工件发布验收 | Windows | WSL Ubuntu |
| --- | --- | --- |
| 变换输出点数 | 14,745,099 | 14,745,099 |
| 矩阵最大误差 | 1.071e-8 | 1.071e-8 |
| 对应/双向覆盖 | 28,800 / 1 / 1 | 28,800 / 1 / 1 |
| RMS | 5.244e-8 mm | 5.244e-8 mm |
| 三自由度秩/迭代 | 3 / 2 | 3 / 2 |
| 单次发布调用诊断 | 6.701 s | 4.694 s |

报告：[Windows](assets/b04-datum-registration/windows-report.json)、[Ubuntu](assets/b04-datum-registration/ubuntu-report.json)。时间含资产读取及有界显示响应，环境非独占；**不是原 50 项测量图的十秒验收**，也不是重复扫描精度。测试双云活跃数组 2 GiB、工作 4 GiB，未修改生产 1/4 GiB。Ubuntu 运行数据、数据库、锁、缓存和 mmap 均在原生文件系统，挂载 Windows 盘仅用于源码及只读输入。

## 6. 页面范围

复用现有配准工作区，仅添加台面方法、两基准接线、面内初值、求解参数和基准证据；不改应用列表或平台管理。Windows 隔离环境使用完整样本验证 Preview、显示选择、桌面/390×844 窄屏的参数/三维/证据切换、非法零次数禁用应用、取消不保存、显式应用与保存重开。显示明确标注 100,000 / 14,745,099，不把概览冒称全点驻留。

真实页面将显式测试求解次数从 40 改为 41，保存重开后仍为 41；发布第二个 WorkflowAppVersion，停止后切版、启动、同步调用，完整样本返回 `succeeded`、输出 `ready` 和 14,745,099 点。随后停止，页面确认 `stopped / stopped`。此处发布序号 v2 是既有应用版本，不是三维契约升级。应用详情的通用回执以 JSON 展示该测试图直接输出的点云预览，三维及基准证据在图编辑 Preview 工作区验收，不将通用回执页冒称新增三维结果面板。收尾页面控制台无 warning/error。

页面初次静态配置落到默认业务端口，仅访问登录/列表/设置，未修改业务应用；随即为隔离构建补独立 runtime-config.json 并验证只连接测试服务。此项是测试环境配置修正，不修改业务端口或系统显示缩放。Ubuntu 覆盖后端/算法/存读/正式发布，不冒称 Ubuntu 浏览器已验。

- [桌面真实工件](assets/b04-datum-registration/desktop.jpg)
- [窄屏点云](assets/b04-datum-registration/narrow-cloud.jpg)
- [窄屏基准证据](assets/b04-datum-registration/narrow-evidence.jpg)
- [发布调用成功及停止](assets/b04-datum-registration/published-stopped.jpg)

收尾已确认测试 API、Vite、运行时及子进程退出，5620/5621 无监听；本轮 `.tmp/b04-datum-*`、pytest 临时缓存和 Ubuntu 原生目录 `/home/am/amvision-b04-datum-*` 均已清理。原始样本、业务 5600/5601 服务与现有业务数据未删除或停止。必要报告和页面证据保留在本文相邻 assets 目录，不依赖临时环境重开。

## 7. 当前位置与下一步

| 范围 | 状态 / 下一步 |
| --- | --- |
| B01–B03、B05 | 已交付明确方法，不重复实现 |
| B04 | 局部 SE(3)、FPFH 多批候选、显式初值台面 SE(2) 已接通；台面内自动粗搜索仍为独立后续方法，更多重复实测/遮挡/对称配方验证保留 |
| B06–B08 | 下一批：收口标定深度/高度图、扫描轮廓输入元数据；复用点云所有权/来源/文件入口，再公开转换和高度图节点 |
| B09–B14 | 实体边/缺测、完整圆弧、圆柱/球/圆锥、布局匹配、通用关系、圆角/曲率仍未完整公开交付 |
| B15–B23 | 正式形位、表面/缺陷、面积/体积、参考云/网格/CAD、报告/SPC 仍按原顺序推进 |
| A01/A04/A09/A13 | 十秒正式图、实物参考、各角色容量/长稳认证、最新源码离线装配分别保留；不阻塞后续功能，不重跑 S2 历史诊断 |

下批先确定 B06 透视标定深度与已标定正交高度网格的显式方法、单位/轴/无效像素及原像素来源；已有 PLY 不冒充标定图样本。再依次完成独立坐标真值、来源与保存、节点/参数 UI、双平台和公开发布。B07 需单列扫描行时间/位姿、行缺失和重叠规则，B08 需单列多层点冲突与有界网格预算，不猜客户相机标定或隐式填洞。

## 8. 复验与依据

```powershell
conda activate amvision
python -m pytest tests/test_metrology3d_datum_registration.py tests/integration/metrology3d/test_datum_registration_published.py
python -m tests.integration.metrology3d.registration_acceptance --root .tmp/b04-datum-full --sample <完整样本路径> --datum --registration-stride 512
```

[SciPy least_squares](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html) 是本批数值求解内核；[Open3D 0.20.0 TransformationEstimation](https://github.com/isl-org/Open3D/blob/v0.20.0/cpp/open3d/t/pipelines/registration/TransformationEstimation.h) 用于核查既有估计器边界。本批不安装新生产依赖或引入自建原生库。
