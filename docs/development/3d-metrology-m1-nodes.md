# 3D Metrology M1 节点与资源 API

日期：2026-10-22。承接[资产与保存导出](3d-metrology-m1-assets.md)，规格以[实施基线](3d-metrology.md)为准。

## 状态

**本记录对应六节点内部接线、独立显示正文、资源管理 API 和固定资产发布批次。** 当时 Trigger/SDK、Preview 大文件上传、三维查看器和资源管理页面尚未接通；后续实现与验证见[传输与界面](3d-metrology-m1-transports.md)。下文的剩余步骤保留为该批历史记录，当前状态以最新记录为准。不能把本批实际执行器测试当作页面或外部调用协议已验收。

生产目录仍为 `metrology3d_nodes`，现有 loader 不发现此隐藏目录。内部 Catalog 使用真实处理器和参数模型，但没有填入猜测的 timeout 或生成生产 manifest。`workflow_runtime.point_cloud` 未配置时为 null，节点运行、点云包传输和固定资产发布校验明确拒绝；没有设置生产容量默认值。

## 实现与审计

| 范围 | 本批实现及验证 |
| --- | --- |
| 六节点 | Read Cloud、Normalize Units、Filter Valid、Cloud Preview、Save Cloud、Export Cloud 接到现有 GraphExecutor。读取、单位换算、过滤、保存和编码调用既有 M1 helper，不复制算法 |
| 来源身份 | source_indices 是最初输入的原始行号；source_point_count 是最初输入总点数。过滤、单位转换、资产保存/恢复、再次过滤和再次保存后不重排编号。声明了源索引却未恢复索引时禁止登记 |
| 保存身份 | 原有 project/run/node/invocation 经规范编码生成写入摘要，不能从用户参数传入任意身份。沿原版本服务提交，不另建资产注册表 |
| 显示 | 全量有限性/validity 扫描，按候选顺序确定性抽样；原始坐标 dtype、uint64 行号和标量保持精度。显示副本为独立有界 base64 SoA，不携带 mmap/lease，Scope 关闭后仍能读取 |
| 显示失败 | 显示超预算、分配失败进入既有显示错误通道；保存/导出分支仍能完成。参数错误和真实取消不伪装成正常显示；空正文也检查正文容量 |
| 资源管理 | 原服务负责列表、版本、完整性和删除保护。新增点云包流式导入；既有 export 路由按明确资源 kind 输出。旧二维 v1 接口语义保持不变 |
| 传输归属 | 原生 TemporaryFile 持有暂存内容；同步读写在既有线程池。请求内监听断连，块校验取消后等待 finally；下载结束/断连关闭文件。没有新增后台常驻进程、等待队列或自动重试 |
| 发布 | 显式策略传入草稿保存、复制和 App Version 服务；固定资源进入原依赖指纹。真实 API 保存与发布通过；被引用资源不能删除，blob 损坏在发布前拒绝 |

本批发现并修复了过滤节点误用摘要对象类型、发布校验未收到资产预算、TaskGroup 包装服务异常导致错误码变化、缺少索引恢复的登记准入、异常 Content-Length 和空显示正文未检查预算的问题。没有修改模型网络、损失、推理数值、模型实例准入、整组停止或恢复规则。

## API

仍使用 `/api/v1/workflows/projects/{project_id}/measurement-resources`：

- `POST /cloud/import?name=...`：请求体为 `application/zip`，必需 `Idempotency-Key`。先检查 workflows:write 和项目范围，再逐块暂存；真实累计大小不能超过独立 `max_archive_bytes`，不能信任 Content-Length 代替计数。
- 导入身份包含操作类型、项目、主体与幂等键。相同键且内容/名称相同返回同一版本；内容或名称改变返回 409。重传仍核验实际字节。
- `GET /{resource_id}/versions/{version}/export`：原路由、workflows:read。point-cloud 使用有界 ZIP_STORED 归档和流式响应；不是整包 bytes。
- 原列表、版本读取和删除入口继续使用；缺预算为既有 `service_configuration_error`，HTTP 500。坏包/超限为 400，无权限为 403，版本/写入冲突为 409。
- 点云包只包含当前资产及父引用，不自动复制持久父资产；跨项目父引用仍拒绝。依赖完整搬运不能描述成已完成。

新增请求路径和 v2 content 是显式扩展，不把旧 v1 multipart import 偷换成另一种请求体。原二维资源无需迁移。本批未删除或迁移现场数据。

## 容量与生命周期

配置键为 `workflow_runtime.point_cloud`，包括 `io`、`preview`、`max_asset_bytes`、`max_archive_bytes`、`max_export_bytes`，全部容量必须显式填写。节点参数不能覆盖服务预算。preview 分别限制点数、二进制、JSON 和临时分配；渲染端 GPU/误差预算仍需随 viewer 接入，当前没有生产 renderer。

文件输入仍受既定 1 GB 载荷上限；资产 ZIP 限额独立。临时盘需要同时容纳上传包/下载包或编码临时文件与正在提交的不可变对象，不能把单包限额称为总磁盘占用上限。运行数组由同一 Scope/CloudArrayBudget 管理；导出是配方明确要求的持久文件，保存于 Project 管理的 ObjectStore 前缀，不自动保存未要求保留的原云。

没有将现有 Runtime 64 MiB / Preview 4 MiB 消息限制放宽。显示节点仍会执行全量扫描；没有观察者仅关闭显示捕获，不能声称生成显示的计算成本消失。当前验证不是容量、节拍或长期资源验收。

## 验证证据

Windows 和 WSL Ubuntu 原生数据目录的相同组合回归各 **384 项通过**，覆盖点云契约/运行/资产、六节点、资源 API/发布、受控 I/O，以及已有 ResourceScope、显示捕获和发布并发回归。最后两处防御性修正另执行节点/API/发布针对性回归，两平台各 **16 项通过**，不重复大样本或性能测试。测试使用隔离环境，环境依赖未齐导致的收集或启动失败不计作通过。

完整原始 ASCII PLY：479,677,235 字节、14,745,099 点，全部以 float32 参与读取、过滤、保存和导出重读。证据见 [Windows](evidence/metrology3d-m1-nodes/windows-full-sample.json) 和 [Ubuntu](evidence/metrology3d-m1-nodes/ubuntu-full-sample.json)。

- 两平台完整规范坐标摘要均为 `956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6`，节点产生的资产及 PLY 导出独立重读后摘要相同。
- 五个正常节点在实际 GraphExecutor 连线执行；真实样本单位未知，Normalize Units 验证明确拒绝。六节点全部正常执行另由已知单位夹具覆盖，不伪称真实样本已确认单位。
- 真实样本显示抽样 1,000 点，二进制 20,000 字节，源行号逐项按公式核验，显示摘要两平台一致。原 Scope 释放后显示仍可读；数组预算归零，真实 mmap reader 释放。
- 本批大样本走实际节点与存储服务，不是 480 MB HTTP 上传或 SDK 端到端验收；API 使用隔离小包验证鉴权、重传、超限、坏包、取消和断连。PCD/XYZ 本批覆盖受控格式回归，完整样本的多格式交换历史证据见上一批记录。

完整样本显式测试配置，仅用于复现，不是生产默认：

| 项目 | 测试值 |
| --- | --- |
| I/O | header 65536；decoded 400000000；working 134217728；chunk_rows 65536；chunk_bytes 4194304；live arrays 800000000 |
| 资产/包/导出 | 600000000 / 610000000 / 600000000 字节 |
| Preview | max_points 1000；max_data_bytes 32000；max_body_bytes 131072；max_working_bytes 8388608 |
| mmap | min block 1048576；reader slots 8；lease 300 秒；revocation grace 2 秒 |

复现入口是 `python -m scripts.verify_metrology3d_file_input`，增加 `--verify-nodes-policy <显式测试JSON>` 与 `--node-preview-points 1000`；仍需提供该脚本的完整样本摘要、预算和新建工作目录参数。Ubuntu 工作目录必须在原生文件系统，源码及只读样本可位于 Windows 盘。

## 下一步

1. App Entry/公开输入能力表与本机 Trigger 接线：固定点云布局、receipt/descriptor 摘要、owner 转移、REQUEST/ACK 及超时/进程退出。复用既有 Broker 和 Runtime，不新建点云服务，不冒充图片契约。
2. Python/.NET SDK：文件引用和同机数组两入口，精确 dtype/offset/长度，writer 关闭后交接；与文件路径同一真值核验。
3. Preview 文件上传：在现有入口消除大文件整块 bytes/进程消息复制，保持取消、身份和释放约束。
4. 资源管理页面及共享 Three.js viewer：沿现有 Vue Workflow/Preview/App Mode，配置表单和固定版本选择；晚返回、节点/运行切换、卸载和 WebGL 释放；真实浏览器验证后才描述页面可用。
5. 实际 worker、Trigger/SDK 和页面双平台整链验证；确认生产 timeout、显示/容量参数后再启用正式 manifest。完整发行、1 GB 全链容量、现场计量准确度均不能由本批样本通过代替。

本批没有启动常驻 backend/worker/Vite、没有运行 P99 或长稳、没有提交 Git。最终确认测试及样本脚本均已退出，已清理 `.tmp/m1-nodes/`、`.tmp/pytest-cache/` 与 WSL `/home/am/.cache/amvision-m1-nodes/`；`.tmp/` 为空。原始点云、现有受控 wheel 与上述验收 JSON 保留。涉及代码的 Ruff、148 个本地文档链接和 `git diff --check` 通过。
