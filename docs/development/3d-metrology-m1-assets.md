# 3D Metrology M1 资产与保存导出

日期：2026-10-22。承接[运行引用与生命周期](3d-metrology-m1-runtime.md)，规格以[实施基线](3d-metrology.md)为准。

## 当前状态

本页保留本批结束时的实现与证据；后续六节点、资源 API 和源行号确认结果见[节点与资源 API](3d-metrology-m1-nodes.md)，不再将下文历史待确认项视为当前阻塞。

**M1 尚未完成。** 本批完成资源 v2、运行点云保存/恢复、流式资产包及交换文件编码的内部实现。六节点处理器与 Catalog、Trigger/SDK、资源管理 API 和三维界面尚未完成接入。不能在页面中使用内部 helper，不宣称完整 Workflow 已验收。

生产 timeout、数组容量、资产包限额和预览容量仍未填写。没有新增 Broker、执行器、资产系统、等待队列或另一套发布管理。内部目录仍为 `_metrology3d_nodes`，沿现有 loader 的隐藏目录规则保持不可启用；没有用伪造默认值注册空节点。

## 实现边界

| 边界 | 实际实现 |
| --- | --- |
| 资源契约 | 在现有 MeasurementResourceDocument 中增加显式 v2 content，支持 point-cloud；完整引用仍为 project/resource/version/sha256/kind。旧二维 v1 语义不变，不批量改写历史数据 |
| 原件 | 文件逐字节保存，冻结格式、字段映射、原始单位和 PCD 组织信息；内存原件按全部声明字段保存。不会用归一后的坐标或单位冒充原件 |
| 派生 | little-endian 连续属性块、零对齐、完整 dtype/NaN 位模式、validity/sample_origin 和独立 uint32/uint64 源行号块；允许零点派生资源 |
| 追溯 | 冻结处理方法、参数摘要、父内容摘要和真实持久引用。未保存父云只有审计来源，不谎报能够恢复原件。读取资产生成新的 run/observation/cloud 身份 |
| 资源写入 | 沿现有 MeasurementResourceService 的项目锁、版本目录和 ObjectStore；全部 blob 长度/摘要/值域通过后，原子写 version.json 作为提交标记 |
| 重入 | 显式 write_identity；同一身份不能更换名称或内容。重入仍检查本次输入流及既有 blob，不因 manifest 相同而接受坏重传；new-version 使用期望基版本，不自动覆盖 |
| 取消与中断 | 提交前清理未完成 blob；提交后不删除真实副作用。无提交标记的残留在同身份重试时清理。真实子进程强杀覆盖提交两侧及锁释放 |
| 读取与预算 | 从可信版本和 blob 构造位置；完整校验后恢复独立数组。数据/索引联合准入后分为两个真实 owner，关闭分别归还预算，不把历史 mmap 当跨运行资源 |
| 资产包 | ZIP_STORED 流式读写；严格成员列表、长度/CRC/摘要、拒绝链接/加密/压缩/重复/未知成员；独立显式包大小限额。不会读入完整归档 bytes |
| 交换文件 | 使用受控 trimesh/pypcd4 writer 和现有 NumPy。显式字段选择、编码与空间信息缺失确认；错误不换库、不换编码、不窄化 dtype。输出尚未接成节点的下载 file-ref |
| 资源消费者 | 现有引用扫描识别 read/export 的固定资产和 save 的期望基版本；删除保护扫描持久父引用；PreparedMeasurementResources 只准备内容说明，不全量缓存点云数组 |

源码入口：

- [点云资产契约](../../backend/contracts/workflows/point_cloud_assets.py)
- [资源服务](../../backend/service/application/workflows/documents/measurement_resources.py)、[提交](../../backend/service/application/workflows/documents/cloud_resource_writes.py)、[blob 检查](../../backend/service/application/workflows/documents/cloud_resource_blobs.py)、[资产包](../../backend/service/application/workflows/documents/cloud_resource_archives.py)
- [运行保存与恢复](../../custom_nodes/_metrology3d_nodes/shared/cloud_assets.py)、[交换文件 writer 适配](../../custom_nodes/_metrology3d_nodes/shared/io/export_file.py)

原始及派生资产保持全部字段；交换文件只包含显式选择的字段，未选字段列在摘要中。PCD 当前空间与原始 VIEWPOINT 所属空间不一致时明确拒绝，不粘贴错误元数据。PCD 交换输出将逻辑分量展开为标量字段，不宣称逐字节保留原 PCD 的 COUNT 表达；需要原格式原样传递时使用原件资产。

## 本批修复与审计

1. 空派生云的 data.bin 合法为零字节。原不可变对象身份检查要求长度大于零，导致已经完整写入的空对象不能打开。现改为严格整数且非负；外部非空调用和文件输入约束没有放宽。
2. Ubuntu 旧 `lockf` 为进程级记录锁，同进程其他句柄重入可成功，关闭同 inode 的无关句柄又可能解除外层锁。复用现有 PathWriteCoordinator，Linux 底层改为 open-file-description 锁；Windows LockFileEx 不变。测试覆盖嵌套/不同 coordinator/不同线程、无关句柄关闭后真实子进程争用和强杀释放。没有修改业务锁接口、增加等待队列或保留 lockf 降级。
3. PCD LZF 对不可压缩的短数据，默认压缩缓冲区不足时返回 None，不能据此判定数据不可编码。本项目受控 writer 使用 LZF literal 上界分配并计入工作预算；真实失败仍拒绝，仍输出 binary_compressed。版本升为 `pypcd4==1.5.1+amvision.2`。
4. 新资产代码审计发现幂等分支仅检查既有资产、没有读取本次重传。三个反例先复现，再补齐重传流的长度、摘要、值域检查；坏重传不损坏已有版本。

Linux OFD 语义依据 [Python fcntl 文档](https://docs.python.org/3.12/library/fcntl.html)和 [Linux OFD 锁手册](https://man7.org/linux/man-pages/man2/F_OFD_SETLK.2const.html)。底层检查 64-bit struct flock 布局；当前验收范围为 Windows x64 和 Ubuntu x64，其他 POSIX 平台不提供不安全降级，也未宣称已通过 macOS 验收。公共业务接口不绑定 Windows。

本批没有修改模型网络、权重、输出解码、数值容差、公差判定、实际部署实例数准入或整组停止机制。正常图片链路不会经过点云读写；共享路径锁和零字节对象的行为变化纳入既有文件/保留清理回归。本批未运行模型 P99 或长稳测试，也不据此宣称工业计量准确度或长期稳定性认证。

## 验证

### 完整样本

使用既有完整 ASCII PLY：479,677,235 字节、14,745,099 点、float32，不截取前缀。原文件 SHA 为 `ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b`。单位未确认，报告保留 null，不根据工件或数值猜 mm。

两平台链路：不可变文件读取 → 运行引用/有效点过滤 → 原件与派生资源保存 → 流式资产包导出/另一项目导入 → 新运行重读 → PLY binary LE / PCD binary / XYZ 导出后严格重读 → 真实 LocalBuffer 数组入口 → 关闭和回收。

全部阶段点数、float32 数据一致，数组 SHA 为 `956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6`。原件资产包 479,678,704 字节，派生资产包 235,923,720 字节；派生源行号全量一致。三个交换输出的文件摘要在两平台相同。Scope 关闭后数组记账归零，真实 mmap reader 最终 released。

证据：[Windows](evidence/metrology3d-m1-assets/sample-windows.json)、[Ubuntu 原生目录](evidence/metrology3d-m1-assets/sample-ubuntu-native.json)。使用现有[样本验证脚本](../../scripts/verify_metrology3d_file_input.py)，增加显式资产预算与 `--verify-exchange`。

本次测试配置：header 65,536、decoded 400,000,000、working 134,217,728、chunk_rows 65,536、chunk_bytes 4,194,304、live_array 800,000,000、asset 600,000,000、archive 610,000,000 字节；lease 300 秒、arena 最小块 4096 字节、reader slots 4、revocation grace 10 秒。arena 按测试数组长度分配为 268,435,456 字节。这些不是生产默认值；数组记账不是 RSS，本样本不等于 1 GB 全算法容量验收。

### 回归范围

覆盖全部已声明格式、float32/64、文本/二进制、颜色/法线/混合属性、uint64/NaN 位模式、字段选择、空派生云、坏包/短流/坏摘要/多余字节、索引/对齐、跨 run 身份、版本冲突、提交前后取消、模拟磁盘满、真实进程中断、被引用资源删除保护和旧二维资源 API。

最终同一组合：Windows 393 项通过、1 项跳过，21.02 秒；Ubuntu 364 项通过、30 项跳过，61.95 秒。Windows 跳过项为环境不允许创建目录符号链接；Ubuntu 跳过的 30 项为 Windows 专用文件/目录语义回归。这些跳过项没有作为通过项统计。

```text
tests/test_point_cloud_assets.py
tests/integration/metrology3d/
tests/integration/controlled_io/
tests/test_point_cloud_contracts.py
tests/test_point_cloud_local_array.py
tests/test_point_cloud_runtime.py
tests/test_metrology3d_preprocess.py
tests/test_metrology3d_activation_boundary.py
tests/test_measurement_resources.py
tests/test_object_store_immutable_directory_collision.py
tests/test_path_write_lock_ownership.py
tests/test_workflow_atomic_files.py
tests/test_managed_jsonl.py
tests/test_file_summary.py
tests/test_retention_directory_safety.py
tests/test_workflow_storage_retention_cleanup.py
```

早期 Ubuntu API 用例因隔离环境缺少项目依赖失败，补齐后定向 12 项通过，再进入相同组合；失败不计入通过。强杀测试最初的共享 Event 故障注入会阻塞测试自身收尾，已终止该次测试并改为只读就绪文件，不将其描述成产品停止故障。磁盘满按已有 PersistenceOperationError 传播，测试断言核对原 errno，不修改应用错误契约。

受控 PCD wheel SHA 为 `7464babfbb6eda2be687c48f092159dd7f166ae8817e096fa00209350944909a`。两平台安装同一 wheel；构建记录见[构建身份](evidence/metrology3d-m1-assets/pypcd4-1.5.1+amvision.2-py3-none-any.build.json)，发行锁仍由 `runtimes/python_patches/wheels.lock.json` 管理。原 `+amvision.1` 的历史证据不覆盖。项目 Python 路径 Ruff 检查通过；受控第三方完整源文件沿独立格式测试和内容 SHA 审核，不为消除原有格式/注解告警扩大补丁。

## 本批结束时的未完成项

1. 六节点尚未接入实际处理器、payload Catalog 和既有执行准备。下一步一次接通 Read/Normalize/Filter/Save/Export 与 Cloud Preview，使用已实现算法和同一运行 Scope，不复制 helper 或创建另一套服务。平台形成 run/node/invocation 保存身份，节点不得自行接收任意写入身份。
2. 当时 Cloud Preview 的源行号描述尚待确认。后续已明确：`source_indices` 保留最初输入原始行号，`source_point_count` 对应原始总点数；过滤后 `[0,2]`、当前点数 2、原始总点数 3 合法，不夹紧或重新编号。实施与回归见后续记录。
3. 资源 v2 内部读写并非管理页面已接通。需在原 API 增加有界上传/受控下载、权限及取消，补齐资源管理 UI。带持久父引用的资产包当前不自动复制父资产，跨项目父引用明确拒绝；本批跨项目样本为没有持久父依赖的原件/派生内容。完整依赖导入/显式引用绑定未完成，不可声称所有资源可独立迁移。
4. 本批没有改变旧二维资源内容或已有发布语义，不需迁移旧数据。正式 v2 消费者开放前仍须核对资源引用准备、发布快照依赖和升级准入；不新建发布版本系统。M3 三态语义升级仍按基线审核重发，不提前伪造兼容分支。
5. 接通现有 App Entry/Trigger 的点云类型、Python/.NET SDK 文件与同机数组输入，验证 PREPARE/REQUEST/ACK 及进程退出。当前 mmap helper 测试不是协议端到端证据。
6. 接入现有 Vue Workflow、Preview 与 App Mode 的共享三维 viewer；验证真实浏览器交互、任务切换、晚返回、卸载与 WebGL 释放。未实现页面，因此本批没有前端视觉验收。
7. 使用显式测试策略完成双平台六节点端到端后，再等待生产 timeout/容量数值确认并注册正式包。不能用本批样本通过替代生产容量、完整发行或真实计量验收。

## 环境

本轮没有启动常驻 backend、worker 或 Vite，未更改生产数据库、运行数据、原 conda 环境或发行目录。Windows/Ubuntu 使用隔离依赖环境；Ubuntu 的存储、mmap、pytest 数据在原生文件系统，源码及原样本可只读来自 Windows 盘。

最终进程核对确认本轮测试及样本脚本均已退出，没有停止其他工作进程。已删除 `.tmp/m1-assets/`、Ubuntu `/home/am/.cache/amvision-m1-assets/` 及确认无人使用的 `.tmp/pytest-cache/`；`.tmp/` 为空。参数转义失败生成的仓库根目录零字节临时文件也已清理。保留原始点云、受控 wheel 和本文 evidence，不保留测试样本副本或隔离环境。155 个本地文档链接核对通过，`git diff --check` 通过。本轮未创建 Git 提交。
