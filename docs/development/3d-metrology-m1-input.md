# 3D Metrology M1 输入适配实施记录

日期：2026-10-22。源码起点：`bfc99213`。前一阶段见[受控 I/O 实施记录](3d-metrology-m1-io.md)，规格仍以[实施基线](3d-metrology.md)为准。

## 当前状态

本页保留输入适配阶段的验收记录；后续运行引用、资源收尾及预处理进度见[运行引用与资源生命周期](3d-metrology-m1-runtime.md)。下列尚未完成项描述当时边界，不覆盖后续实施记录。

**M1 尚未完成。本轮实现内部文件读取和同机数组受保护读取基础，不发布六节点，也不宣称页面、Trigger 或 SDK 已支持点云。**

已确认允许使用显式测试配置完成内部实现和验证。生产节点启用仍等待既有 manifest 的 `defaultSeconds`、`maxSeconds`、`killGraceSeconds` 及运行/预览容量确认，不复制其他节点的数值。

Ubuntu 后续验收与生产运行数据使用 Ubuntu 原生文件系统。源码和只读输入样本可以位于 Windows 挂载盘；不迁移现有数据。该部署边界不表示 Ubuntu bundled profile 已通过发行验收。

## 已实现

| 边界 | 实现与复用 |
| --- | --- |
| 严格内部契约 | `backend/contracts/workflows/point_cloud.py`：字段、单位、轴声明、PCD 组织信息、文件 profile/完整字段映射、同机块布局；拒绝未知字段、bool 数量、重叠、额外尾部和外部伪造派生来源 |
| 文件来源校验 | `WorkflowInputValidator.validate_file_reference` 复用既有项目权限、file-ref、长度及不可变身份校验，不另建文件输入服务，不改变已有图片/文件默认限额 |
| 文件解析 | `custom_nodes/_metrology3d_nodes/shared/io/` 复用 ObjectStore snapshot 和受控 PLY/PCD 公开接口；NumPy 处理四种明确的 XYZ 文本 profile；检查真实字节摘要、字段全覆盖、精度和分块取消 |
| 数组预算 | `PointCloudIoPolicy` 全部参数必填；`CloudArrayBudget` 在分配前立即准入，文件重排同时计入源结构数组和目标属性；没有队列、自动溢出或全云 float64 提升 |
| 文件数组生命周期 | `OwnedCloudArrays` 只读借用、活跃借用时拒绝关闭、正常关闭幂等；复用 ResourceScope，解析失败、分配失败及登记时 scope 已关闭都收回本次数组和预留 |
| 同机内部读取 | `borrow_cloud_buffer` 接受现有 acquire-view guard，核对固定描述摘要、实际长度、零填充与 validity，分块计算内容摘要和非有限坐标数；`np.frombuffer` 保留 readonly memoryview，未复制成完整 bytes |
| 同机生命周期 | 调用者须先完成已有准入及所有权交接，并让一个 guard 覆盖整个运行消费区间；退出先清除 ndarray 别名再关 guard；关闭失败不退回预算，不冒充恢复成功 |
| 生产启用隔离 | 使用加载器已有的下划线内部目录约定；不改 loader，不创建空 manifest/catalog，不注册点云 payload，不在节点状态页制造缺少 manifest 的错误 |

内部目录不是第二份实现或兼容包。满足节点实现及生产策略条件后，原目录一次性进入正式节点包路径，不能保留双份逻辑或转发别名。包名和公开节点 ID 仍按实施基线。

两种读取入口现在还没有统一到公开 `point-cloud-ref.v1` 的运行 registry。`ReadCloudResult`、`BorrowedCloudBuffer` 都是内部对象，不能写入 API、数据库、跨进程消息或历史结果。文件原名、映射参数及 PCD 元数据保留；不推断样本单位、姿态或精度目标。

## 修复与审计

1. **不可变目录重复发布的跨平台错误**：既有 `LocalDatasetStorage.write_immutable_stream` 只捕获 `FileExistsError`。同内容目标已存在时，Ubuntu 原生文件系统可返回 `ENOTEMPTY`，导致重复导入失败。现在只将 `EEXIST`/`ENOTEMPTY` 交给已有内容身份核对；权限、磁盘满和 I/O 错误原样失败。并发同内容发布、暂存清理和三种错误注入均有回归。
2. **大数组异常持有**：格式错误产生的 traceback 可被任务错误记录保留。新文件入口在失败时清除已退栈 decoder 的数组局部变量，解除本层引用后归还预算；测试持有异常对象并通过 weakref 核对数组不残留。
3. **NumPy 只读约束**：实现过程中实测 `np.ndarray(buffer=readonly_view)` 可以重新启用写标志；改用 `np.frombuffer` 保留 readonly memoryview，并在真实 arena 上验证不能重新启用写入。
4. **未注册目录污染状态页**：普通 custom_nodes 一级源码目录会进入 manifest 校验，故内部阶段使用 loader 现有的 `_` 目录约定。公共目录刷新回归确认没有新增可用节点或坏包状态。
5. **WSL 文件系统差异**：同一既有 `test_cross_process_readers_do_not_block_commit_and_summary` 在 DrvFS/9p `/mnt/w` 出现子进程 `OSError(61, ENODATA)`、父进程 EOFError；原生目录通过。标准库简化替换例在两边均通过，因此不将问题泛化为“所有 DrvFS 原子替换都失败”，也没有修改既有原子文件算法或添加降级重试。

上述检查没有修改模型网络、损失、输出解码、推理运行时、调度准入、线程配置或前端页面。既有执行路径的行为变更仅为同内容不可变目录的 POSIX 错误处理；点云内部能力尚未接入生产调用。

## 验证范围

最终组合包含以下测试文件/目录：

```text
tests/test_point_cloud_contracts.py
tests/test_point_cloud_local_array.py
tests/test_object_store_immutable_directory_collision.py
tests/test_metrology3d_activation_boundary.py
tests/integration/metrology3d/
tests/test_workflow_file_reference_nodes.py
tests/test_workflow_atomic_files.py
tests/test_local_buffer_mmap_arena.py
tests/integration/controlled_io/
```

Windows 使用隔离 venv 继承已确认的开发环境；WSL Ubuntu 使用独立 venv。未修改原 conda 环境，未安装 Open3D。受控 wheel 身份仍与上一阶段锁文件一致。

Windows 最终组合：243 项通过，17.58 s。Ubuntu 最终组合：237 项通过、6 项平台专用测试跳过，32.71 s；运行数据使用自动清理的原生临时目录，不将 `/mnt/w` 的旧结果当作原生文件系统验收。

完整 ASCII PLY 样本通过真正的 `write_immutable_stream -> file-ref 校验 -> snapshot 摘要 -> 严格解码 -> 规范属性 -> ResourceScope.close` 路径，不截取样本，不只检查文件存在。原始 479,677,235 字节、14,745,099 点，规范数组 `<f4`、176,941,188 字节；源及整个数组 SHA 与前阶段独立核验记录相同。

样本记录：[Windows](evidence/metrology3d-m1-input/sample-windows.json)、[Ubuntu 原生 ObjectStore](evidence/metrology3d-m1-input/sample-ubuntu-native.json)。两平台 Scope 正常关闭、活跃数组预算归零；读取与校验观测分别为 22.14 s、12.74 s，不作为跨平台性能比较或生产节拍承诺。WSL 原样本仍从 Windows 盘只读，写入的测试 ObjectStore 位于原生临时目录并在结束后删除。

复现脚本为 `python -m scripts.verify_metrology3d_file_input`，所有预算必须显式传入。样本验证使用 header 65,536、decoded 400,000,000、working 134,217,728、chunk_rows 65,536、chunk_bytes 4,194,304、live_array 800,000,000。这些是本次测试配置，不写入生产默认。预算是声明数组/工作块检查，不是进程 RSS 硬限额或主机级多 worker 容量仲裁。

## 尚未完成

按原 M1 顺序继续，不重新设计 Workflow 或发布管理：

1. 在已有 ResourceScope/执行清理边界完成运行引用、同一 owner 借用、派生依赖和关闭失败后的 worker 恢复阻断；当前内部 guard 测试不代替完整 worker 交接和强杀验收。
2. 完成 Read Cloud、Normalize Units、Filter Valid、Cloud Preview、Save Cloud、Export Cloud 的实际节点入口及算法；本轮只覆盖 Read Cloud 的文件读取基础，不把辅助函数当作六节点完成。
3. 同批接入现有 local-shared-memory Trigger 的显式点云请求、App 契约、SDK、图输入；不得将点云伪装成 image-ref。当前 helper 不提供 PREPARE/REQUEST 端到端能力。
4. 完成现有上传阶段的有界接收、临时磁盘准入，资源 v2 与平台无损保存/交换导出、持久引用及受影响发布的升级保护。
5. 扩展现有 Vue Workflow/Preview 查看器和结果交付，执行真实页面和双平台链路验收；不发送完整原云到浏览器，不新增显示连接。
6. 生产 timeout、预算及预览容量确认后才注册启用；1 GB 是输入载荷约束，不是已验证的所有算法容量或工业准确率承诺。

本轮未运行 P99 或长稳测试，未启动 backend、worker、Vite 或浏览器。更大容量、现场节拍、测量真值和完整生产发行仍未验收。

## 收口检查

- 修改及新增 Python 文件 Ruff 检查通过，新增文件格式检查完成，148 个本地文档链接存在性检查通过。
- Windows 进程清单未发现本轮测试残留；Ubuntu 没有 Python/pytest 测试进程。未终止 Ubuntu 中已有的登录 shell 或其他发行版。
- 原生临时 ObjectStore 和测试目录由验收驱动清理；本轮 `.tmp/m1-nodes/` 中的 venv、缓存、中间报告及完整样本副本已删除。正式源码、受控 wheel 与归档 JSON 保留，预先存在的 `.tmp/pytest-cache/` 未改动。
- 未修改现有运行数据、依赖锁、发布目录、节点加载器、生产 timeout 或服务配置。未创建 git 提交。
