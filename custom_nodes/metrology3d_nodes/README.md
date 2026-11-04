# 3D Metrology

通过项目现有 Node Pack、Workflow、CloudRuntime 和 ResourceScope 提供点云处理与测量。正式包 ID 为 `metrology3d.nodes`，只有本目录一套实现，不依赖 `projectsrc` 或测试注册器。

## 节点

- 数据：Read Cloud、Normalize Units、Filter Valid、Denoise Cloud、Crop ROI、Transform Cloud、Save Cloud、Export Cloud。
- 定位与特征：Fit Plane、Build Frame、Extract Boundary、Fit Line、Fit Circle。
- 测量：Height Query、Measure Step、Measure Extents、Measure Edge Pair、Measure Hole。
- 显示：Cloud Preview。

既有严格截线与轴向跨度保持原定义。Extract Boundary 已接通显式 `visible-envelope` 栅格剖面，Measure Extents 已接通 `robust-profile-spans`；前端、来源与保存读取同步。F4 已接通多片段拟圆、实际距离分区及基准应用范围，当前工件 50 项均几何有效，S2 当前方法已获工程使用确认，不再以旧稳定性诊断阻塞交付。最终十秒节拍尚未验收通过。无效量值保持 null 并保留原因，几何有效不表示产品合格或实体精度认证；正式配方另经 Check Limits 输出 OK/NG/INVALID。

Fit Circle 明确区分等权、`angular-soft-l1` 角区均衡和 `arc-length-soft-l1` 连续实测边长权重。新方法不跨片段缺口，不删除候选，不自动替换原配方；显示使用统一的 `fit_weights`。S2 独立对照未通过 0.03 mm 诊断的历史事实保留，当前工件继续使用角区法，不重新换权重或声称历史诊断通过。契约、局部参数编辑修复与验证见[连续边长拟圆](../../docs/development/3d-metrology-circle-support.md)，当前范围见[剩余清单](../../docs/development/3d-metrology-remaining.md)。

## 依赖与启动

`0.1.21` 新增 Denoise Cloud：显式统计邻域/半径邻域，输出保留和剔除的互补源点子集以及摘要；所有属性和原始行号沿原资源系统保存。统计使用其他 K 点的平均距离及总体标准差，半径包含边界且排除自身。参数不设生产默认，当前工件配方不自动去噪。完整云及双平台验证、实际成本见[本批记录](../../docs/development/3d-metrology-method-resources.md)。体素/规则重采样及法向估计尚未交付。

去噪接线为 Read Cloud → Normalize Units（单位需转换时）→ Filter Valid → Denoise Cloud；`cloud` 接后续计算或 Cloud Preview，`removed` 可单独接另一 Cloud Preview/Save Cloud 查看剔除点，`summary` 提供点数和实际统计阈值。统计法 K 必须小于输入点数；半径法使用输入云已确认的物理单位。该操作会改变支持点，不能无审核地插入已有测量配方；对真实细线/孤立结构是否保留须由方法与配方决定。去噪输出清除父云边界连接，不把删点后的旧线段当新边界。

开发环境先激活项目环境，在仓库根目录安装受控版本：

```powershell
conda activate amvision
python -m pip install --find-links runtimes/third_party/python-io --find-links runtimes/third_party/python-geometry -r custom_nodes/metrology3d_nodes/requirements.txt
python -m pip check
python -m custom_nodes.metrology3d_nodes.workflow.generate_catalog
```

manifest 锁定 NumPy 2.4.4、SciPy 1.18.0、Open3D 0.20.0、trimesh 5.1.1+amvision.2、pypcd4 1.5.1+amvision.2、python-neo-lzf 0.3.5。缺包或版本不符时包仍显示在节点管理中，但不注册可执行节点；安装不会由业务请求或节点自动触发。发行包的 bundled Python 必须安装同一组依赖及其传递依赖，不能只复制节点目录。

Windows/Ubuntu x64 为当前支持范围。Ubuntu Open3D 需要可加载的 `libusb-1.0.so.0`；开发环境须满足该依赖，当前 CPU 离线包已将受控 libusb 及许可随包装配，不依赖临时 sysroot 或现场 apt 安装。实际发行验收覆盖 Windows x64 / WSL Ubuntu 24.04 x64，见[CPU 离线发行](../../docs/deployment/cpu-offline-release.md)，不外推任意 Linux。Ubuntu 运行数据库、锁、共享内存及输出目录使用原生文件系统，不使用 `/mnt/w` 的 DrvFS。源码与输入样本可以从挂载盘只读访问。

## 显式容量

Cloud Preview 可显式设置 `prepare_details=true`，对 Read Cloud 读取的完整点云资产准备原始细节。默认关闭；当前裁剪/变换云须先沿既有 Save Cloud 保存并重读。查看器勾选“原始点细节”后按视野读取原始叶块，超出显示预算时明确保持概览；不自动保存动态输入、不延长 Run 引用，也不以显示点重算尺寸。每次显式准备会重建索引，建议与数值节拍图分开。完整样本及精确1 GB有界索引已双平台验证，详见[有界索引记录](../../docs/development/3d-metrology-bounded-details.md)；这不是全部原始点同时驻留GPU或所有算法容量认证。

[workstation.example.json](workstation.example.json) 是 2026-10-28 确认的本机工程配置。本机已写入忽略版本控制的 `config/backend-service.local.json`，未改变所有机器的默认值。

| 配置 | 本机上限 |
| --- | --- |
| 每 Run 活跃数组 | 1 GiB |
| 算法工作预算 | 4 GiB |
| 有界显示点数 | 1,000,000 |
| 节点默认/最大超时 | 180 / 180 秒 |
| 强制停止宽限 | 2 秒 |

这些数值是安全准入边界，不是测量节拍承诺，也不是整个进程 RSS 硬上限。预算不足立即拒绝，无等待队列。示例另保留本工件验收的 400,000,000 字节解码容量、600,000,000 字节资产/导出容量、610,000,000 字节资产包容量及 500,000,000 字节 Preview 单会话文件容量。因此不能声称此配置能处理任意接近 1 GB 的文件；输入载荷上限、解码数组、资产包和运行工作集是不同限制。

未配置 `workflow_runtime.point_cloud` 时明确拒绝执行。已有后端、worker 和浏览器静态构建需要按正常更新流程重启/重建后使用新包，不靠修改在运行进程的模块状态启用。

可选 [workstation-1gb.example.json](workstation-1gb.example.json) 提供 1 GB 输入工程配置：解码 2 GB、活跃数组 4 GiB、工作预算 4 GiB、独立文件/资产包限额。Windows/WSL 已验证实写 1 GB 文件、同机数组、HTTP Preview、ROI 派生及保存导出恢复；业务本地配置未自动替换。配置账本、最低内存结论的边界及尚需补验项见[容量实施记录](../../docs/development/3d-metrology-capacity.md)。大文件可能因解码膨胀或算法图密度超过显式预算而拒绝；有界显示仍保持原限额，不等于全分辨率显示。

## 验证入口

2026-11-03 补验：Windows .NET byte[]/writer 精确 1 GB 经真实发布 worker 保存重读，全字段和原始行号一致，写入者异常退出及再次调用通过；三维上游来源切换与等价刷新已修复，八节点生命周期及双平台完整工件组合通过。详见[候选组合记录](../../docs/development/3d-metrology-candidate-validation.md)。本项不是最终离线候选、十秒节拍或近 1 GB 显示索引全部通过。

实施记录见 [R5 F 实施与验收](../../docs/development/3d-metrology-r5-f-implementation.md) 和 [F3 字段、来源与实测](../../docs/development/3d-metrology-r5-f3-implementation.md)。正常发布测试直接读取本目录 manifest/Catalog，不生成临时替代节点包。业务数据、旧三维资产与原始样本不迁移、不删除。
