# 3D Metrology M1 传输与界面

日期：2026-10-22。承接[节点与资源 API](3d-metrology-m1-nodes.md)，约束以[实施基线](3d-metrology.md)为准。

## 状态

本批已接入同机数组 Trigger、.NET SDK、Preview 流式文件上传、Workflow 资源选择管理和共享 Three.js 查看器。没有重复创建 Broker、Workflow、节点执行器或发布版本系统。

**生产包仍未启用；M1 生产验收尚未完成。** `_metrology3d_nodes` 继续隐藏，没有填写生产 timeout、容量或显示预算。本页保留传输与界面批次的证据边界；后续真实已发布 WorkflowAppRuntime、.NET 完整样本及异常退出验收已完成，见[真实发布运行验收](3d-metrology-m1-published.md)。

## 实现边界

| 范围 | 实现及所有权 |
| --- | --- |
| 同机数组 | 新增 `amvision.workflow-trigger-cloud-prepare.v1`，descriptor 复用 `CloudBufferDescriptor`。独立类型，不填入图片 shape/pixel_format，不接受 ZeroMQ 点云或远程 mmap |
| PREPARE | 已发布输入类型及 `payload.<key>` 映射、显式 I/O/live-array 预算在分配前检查；仍使用同一 source permit、executor 与 LocalBuffer arena |
| REQUEST | writer 关闭后提交，禁止 payload 覆盖已准备的点云字段。先取得既有 Runtime 准入，再发布并转移 owner；失败沿原补偿路径归还 |
| worker | 私有 `CloudInputHandoff` 固定 run、binding 与 descriptor；普通 JSON 不能伪造。复用进程安全 metadata、受保护只读 reader 和 ResourceScope；多个 binding 分支共享一次映射 |
| 原始行号 | source_indices 保留最初输入行号，source_point_count 保留原始总点数；输入引用由 worker 创建，不接受调用方伪造执行期 cloud_id |
| .NET | 低层 `InvokePointCloud` 支持 byte[] 与受限 Span writer；高层 `InvokeSharedMemoryPointCloud` 复用配置 client 和结果物化/ACK。文件仍走现有 HTTP `AddFile`/stream factory |
| Preview 文件 | 原会话新增 HTTP raw-body 上传，浏览器直接传 File，不先 arrayBuffer/hash。服务按 256 KiB 块计数/hash，先占磁盘预算；不把完整文件放入 SHM 或进程消息 |
| 临时快照 | Windows delete-on-close、Ubuntu 匿名文件/procfd 由文件系统适配器实现；私有描述符带 device/inode/size。owner 释放后，worker pin 持有到执行结束或确认退出；打开旧 PID/fd 命中新文件时身份校验拒绝 |
| 显示传输 | 大点云显示正文复用既有 PreviewValues Blob 通道；控制事件只放摘要及 descriptor，不增大消息上限。正式节点业务输出不被分页摘要替换 |
| 资源管理 | 现有参数编辑器增加 schema 驱动的来源/保存目标控件；同一资源 API 完成固定版本选择、ZIP 导入/导出、删除保护。取消不提交半个引用，切换为资产时清除文件选项及其旧编辑草稿 |
| 三维显示 | Preview、Runtime/App Mode 的节点显示与结果正文共用查看器。查看器按需加载，没有后台常驻动画；支持透视/正交、轴视图、旋转/平移、点大小、原始行号与坐标拾取 |
| 浏览器准入 | point-cloud-ref 只接受同机握手；浏览器不提供伪造 JSON 编辑框，必需数组输入不生成不可执行的 HTTP 示例。文件复算使用 Read Cloud 的文件入口 |

前端只消费有界显示副本，不下载/解析完整原云。原坐标 float32/float64、uint64 行号和标量保存在显示副本中；渲染使用局部原点和 float32，检查显式允许误差。Decimal.js 只用于避免 uint64 色标经 Number 窄化，不改变计量算法或原字段。

## API 与配置

- `POST /api/v1/workflows/preview-sessions/{session_id}/inputs/file?byte_length=...&file_name=...`：沿原会话 owner/项目授权，流式请求体；实际大小必须与声明一致；输入上限 1,000,000,000 字节。
- 返回既有 input_id/摘要，不能获取服务端临时路径。未配置文件策略为 503，容量/长度错误为 413；中断或失败释放未提交输入。
- 创建 Preview 会话返回 `file_upload_limit_bytes`；未配置为 null。图片仍使用原二进制通道，不按错误尝试另一种 transport。
- `GET /api/v1/workflows/projects/{project_id}/measurement-resources/cloud/capabilities`：沿 workflows:read 和项目权限，只返回实际 `max_archive_bytes`、`renderer`；未配置为 null，不泄露内部路径或填默认值。
- 配置扩展仍在 `workflow_runtime.point_cloud`：可选 `preview_files` 包括必填 `session_bytes`、`total_bytes`；可选 `renderer` 包括必填 `max_points`、`max_data_bytes`、`max_cpu_bytes`、`max_gpu_bytes`、`max_canvas_pixels`、`max_position_error`。任何一个可选对象不存在时，对应能力不开放。
- 浏览器 CPU/GPU 计量覆盖受管显示副本、属性缓冲及画布估算，不等于驱动/浏览器整进程 RSS 或显存硬隔离。打开多个视口共用受管计数；超限明确拒绝，不增加等待队列。

调用方格式和 .NET 示例见 [Workflow 点云输入](../api/workflow-point-cloud-input.md)。Cloud PREPARE JSON Schema 随 SDK 发布，回归校验它与后端 Pydantic 契约一致。

源码前端固定新增 `three 0.186.1`、`@types/three 0.186.0`、`decimal.js 10.6.0`，随 Vite 产物本地分发；无 CDN、无额外生产 Node 依赖。Three.js 查看器动态分包约 598 kB，构建保留大于 500 kB 的提示，没有放宽警告阈值。

## 验证与审计

组合回归覆盖原图像 Trigger/Preview、点云所有权、资源 API/发布、资产交换及六节点。Windows 初次 230 项通过，12 项因隔离环境缺少已锁定 LZF 依赖失败，1 项为新测试漏传 database_name；补齐隔离依赖和测试夹具后相关 33 项通过。Ubuntu 初次 235 项通过、7 项平台跳过、1 项同一测试夹具失败；该单项补验通过。去重后对应 **Windows 243 项、Ubuntu 236 项通过**。不是把失败记录忽略为通过，也没有为修正夹具重复跑完整样本。

完整样本另在两个平台各执行 2 项测试（三点预检与完整链路），证据：[Windows](evidence/metrology3d-m1-transports/windows.json)、[Ubuntu](evidence/metrology3d-m1-transports/linux.json)。

- 原 ASCII PLY 479,677,235 字节、14,745,099 点；文件经真实 HTTP 流式上传、Preview 子进程、实际节点执行。
- 在真实读取节点之后全量核验坐标摘要和原始行号，再将完整 176,941,188 字节点数组经真实 mailbox/arena 交给 spawn 子进程，运行 SnapshotExecution/GraphExecutor。两条输入的显示正文一致。
- Trigger 控制面准入使用已有测试夹具；不能把它称为实际已发布 Runtime 控制面验收。.NET byte[]/writer 回调另以小数据真实进程验证，当前 SDK 为 Windows net472，Ubuntu 的 .NET 项明确跳过。
- 两平台坐标摘要均为 `956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6`。1,000 显示点摘要一致，文件字节占用、pin、lease 与 source permit 在结束后归零。
- 前端组合回归 77 项通过；最后新增的浏览器禁止伪造点云 JSON 用例补齐完整类型夹具后通过，去重共 78 项。最终四个新增测试文件对应 23 项通过，覆盖晚返回、卸载、WebGL context loss、资源上传中断、项目切换、删除引用错误、源参数草稿和 Blob 补全。Vue 类型检查与 Vite 构建通过。沙箱临时缓存 rename 的 EPERM 发生在用例加载前；允许后在沙箱外完成回归，不调整用例断言。
- SDK 重新构建、既有 .NET 契约程序和新增的高层 byte[]/writer 显式 binding 检查通过。补验发布 JSON Schema 与后端契约一致，1 项通过。修改的应用/测试 Python 文件 Ruff 及 git diff --check 通过；本轮未重整受控上游 fork 的既有风格。
- 实际浏览器使用完整样本生成的显示数据和明确的测试能力配置；API 列表是组件测试夹具，不宣称生产页面已启用。1280×720 与 390×844 截图中点云像素分别为 3549 / 3705，视口非空、窄屏无页面横向溢出；视图/投影/平移可操作，关闭后受管 CPU/GPU 计数均为零。
- [桌面截图](evidence/metrology3d-m1-transports/viewer-desktop.png)、[窄屏截图](evidence/metrology3d-m1-transports/viewer-mobile.png)是正式组件的测试装配，不是替换生产 Workflow 的独立应用。

本轮审计修正了大显示正文误入控制事件、取消资产选择仍显示未提交模式、资产来源切换后旧文件草稿可重新提交、投影切换丢失平移状态、浏览器数组输入误导、资源删除错误被确认层遮挡，以及 SDK 高层点云方法可能先填入图片默认 binding 等问题。点云 binding 现在在读取配置或建立 client 前强制检查。没有修改模型网络/损失/推理解码，也没有改变部署实例准入、整组停止或恢复边界。没有执行 P99 或长稳，不据此宣称新增工业计量准确度或容量达标。

## 剩余验收

1. 实际发布版本、WorkflowAppRuntime、Trigger 和 .NET 完整样本组合验收已在[后续批次](3d-metrology-m1-published.md)完成；本页原执行器夹具证据仍不冒充真实准入。后续批次修复 WRITING 超时遗漏清理通知。
2. 明确生产节点 timeout/kill grace、运行数组/磁盘、显示及渲染容量、目标并发和时限后，注册正式节点包并组装 Windows/Ubuntu 发行 profile；当前不得自动启用。
3. 1 GB 上限端到端容量、目标现场节拍和溯源计量验证仍未完成。当前样本单位未知，界面明确显示“单位未确认”，不能据此输出毫米尺寸。
4. 原始点云不自动持久保存；资产包父引用不自动跨项目搬运。Python 独立 SDK 未交付，不能把 backend 内部测试客户端当作外部 SDK。

测试用例及证据保留在版本目录。本轮组件测试页已关闭，Vite 5602 已停止；Windows 本轮测试进程和 5602 监听均为零，WSL 未发现本轮测试进程。仓库 `.tmp/` 的 12 个临时目录已清空，Ubuntu 原生文件系统上的 `/home/am/.cache/amvision-m1-transports` 已删除并复查不存在，包括临时 venv、上传快照、数组和测试数据库。保留原始样本及正式源码/构建产物。现有 5600/5601、worker 和 inference daemon 不是本轮启动，未擅自停止；不能将本轮清理表述为整机所有开发服务已关闭。
