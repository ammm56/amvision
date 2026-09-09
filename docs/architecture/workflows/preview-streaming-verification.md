# Preview 内存会话实现与验证记录

日期：2026-09-10。代码基线：`12c3ba27`，结果对应本次未提交工作区。没有组装或替换生产发行包。

## 实现结果

编辑器使用 `/api/v1/workflows/preview-sessions` 和对应 v1 WebSocket。HTTP 只受理不可变 JSON 快照，常驻独立 Worker 执行节点；节点状态、真实循环进度和值增量发送，图像通过有 ACK 的二进制 Blob 通道读取。恢复订阅读取当前内存快照，不重跑业务、不扫描磁盘事件。

上传、快照、输出和编码使用有界进程内存/OS SHM；Preview 不再建立数据库 Run、JSONL、结果 manifest、临时图片或文件支持的 mmap。明确 Save 节点仍按原配置保存业务文件。模型和已有业务文件仍从原存储读取。任意自定义 Python 主动写盘的副作用不属于平台临时传输，不能声称已拦截所有自定义代码的写入。

职责划分：

| 层 | 实现 | 边界 |
| --- | --- | --- |
| v1 合约 | `backend/contracts/workflows/preview_session.py` | 严格 JSON、身份、分块协议、输入大小和摘要 |
| 会话 | `preview/session.py` | owner/project/app 隔离、去重、快照、终态、断线宽限、文档删除互斥 |
| 资源 | `preview/buffers.py` | 预算、写入/发布、pin、最后借用归还、无磁盘降级 |
| 执行 | `preview/pool.py`、`worker.py`、`execution.py` | spawn 常驻池、取消/超时、死亡确认、隔离进程延后回收 |
| 节点观察 | `preview/events.py`、节点 `report_progress` | 并行/循环 invocation、开始/完成/真实进度；无内部进度时仅显示执行中和耗时 |
| 显示/值 | `preview/display.py`、`values.py` | 异步有界编码、原图与缩略图分离、完整值分页、多输出端口、嵌套显示 |
| 模型 | `preview/models.py` | 复用原 task-native 请求、模型运行时和结果转换，独立有界缓存 |
| Vue 编辑器 | `useWorkflowPreviewSession`、`previewSessionState`、`useWorkflowPreviewDisplays` | WS 增量归并、上一轮结果标记、删除节点释放、Blob URL 生命周期、节点值分页 |
| 数据升级 | Alembic `a8d6c4e2b019` | 删除旧临时表；保留已有策略参数并统一 kind，正式 Runtime 表不改结构 |

`preview/` 路径均相对于 `backend/service/application/workflows/`。正式 Runtime/Trigger 不使用 PreviewSession、显示编码或本次 WS 协议；共享图执行器只在注入编辑器观察者时发送编辑器事件。正式同步/既有异步协议、模型参数和算法保持原职责。前端沿用 Vue 3，资源本地构建，不增加 Redis、外网 CDN 或部署时系统 Node 依赖。

## 自动验证

所有开发命令先执行 `conda activate amvision`。

| 范围 | 命令/测试组 | 结果 |
| --- | --- | --- |
| 会话、内存、WS、显示、值、模型适配、真实 spawn | `python -m pytest tests/test_workflow_preview_{memory,session,session_api,worker,models,values,display,observation}.py`（表中花括号表示文件组，PowerShell 运行时逐项展开） | 73 passed |
| 编辑器服务、状态、Viewer、操作和组件 | `npm run test:unit -- --run src/workflows/workflow-editor` | 64 files / 230 passed |
| 前端类型/生产构建 | `npm run typecheck`、`npm run build` | 通过 |
| 正式 Runtime 进程 | `tests/test_workflow_application_process_executor.py` | 24 passed |
| Parallel / ForEach / Selection / SAHI / 正式 Runtime Preview | 对应六组 pytest 文件 | 44 passed；增加 ForEach 观察者参数化后该文件 3 passed |
| 发行目录 Python | 使用同目录 `python/python.exe` 执行 memory、values、worker 测试 | 当时版本 9 passed；Python 3.12.13，Windows x64 |
| 数据迁移 | 上一版临时表重建、升级、策略参数/正式表结构保留 | 通过；现有迁移回归亦通过 |
| 文档与 API 示例 | 文档链接、Workflow API 示例、Detection / Non-detection Postman、Submit 示例 | 62 passed |
| Python 静态检查 | 新 Preview 模块、协议/API、测试及真实探针的 `ruff check` | 通过 |

关键断言包括：未提交上传不可见、错误摘要不发布、跨 owner 拒绝、释放时仍可持有合法借用、真实子进程退出后计数归零、强制超时和延后回收、重复提交不重复业务、慢订阅者恢复快照、循环 invocation 不串线、节点已完成而 Delay 仍运行、PNG 原图像素一致、临时文件引用无物理文件、文件列表顺序、常驻进程复用、显式图片保存字节及 saved_output 保留。

五种任务 detection/classification/segmentation/pose/obb 的模型网关测试核对真实请求构造器的参数和批次顺序，预测执行使用受控测试结果；这些是契约测试，不能作为五种模型的真实精度验收。

## 真实开发环境验证

使用 `workflow-app-20260831130620` 已保存快照，用户已授权保存原草稿。探针另建未持久化应用身份，只在内存副本追加 Delay；没有发布或替换原应用。图片来自 `data/files/developer/图片/3570/治具托盘/空盘/Image_20260721103308382.bmp`，59,885,622 字节（57.1 MiB）。明确 Save 节点的验证输出定向到本次临时目录。

脚本：`python -m tests.integration.workflow_preview_session_live --image <图片> --output <明确保存目标> --report <证据文件>`。默认 Delay 90 秒，整体观测超时 180 秒；不改业务默认 timeout。

通过运行：session `848bdbc09d434cd8b649657384f87406`，run `0cf4cb8d84464626a56821e1224dfe04`。原快照 SHA256：`70d047f1cc0b7a7c7bff5d045ba1e88c9d823182199dcdd91d3aa85778fdde31`。

| 观察项 | 实测 |
| --- | --- |
| 整体验证 | 108.407 秒 |
| 首个显示结果 | 17.485 秒，包含启动及真实图执行开销，不是单节点传输延迟 |
| Delay 开始 | 18.391 秒；当时已有 10 个显示 |
| 原图获取、解码 | 18.860 秒完成，5472×3648，PNG 29,016,749 字节；此时 Delay 未结束 |
| WS | 92 个节点开始/完成、113 个值更新、17 个显示、7 次连接心跳；无 display.unavailable / protocol.error |
| 最终业务结果 | 24 个空槽；full / abnormal / unknown / low_score 均 0；passed=true |
| 重连 | succeeded，保留 17 个显示；探针最后释放会话 |
| HTTP 接入 | 107 次成功；P95 16 ms、最大 109 ms；此指标不是推理延迟或 SHM/ZeroMQ P99 |
| API RSS | 开始 1,034,162,176；峰值 1,094,852,608；结束 1,068,556,288 字节；未宣称回到初值 |

随后在 Codex 内置浏览器直接执行原保存应用，核对图片预览、24 张 Crop 图库、分类汇总、ROI 完整值、Hough 调试图及 5472×3648 原图查看器。Hough 查看器的 Preview Run 单节点调用也已完成：查看器保持打开，新图替换成功，其余节点明确标为上次结果。浏览器日志中的旧 HMR 错误保留其发生时间，不当作最终运行错误；最终验证期间没有新增错误。

失败证据也保留：第一轮探针将 HTTP 接入地址误写成 `/api/v1/liveness`，其 404 不代表监听丢失；同时 `Value Preview 5` 因 ROI JSON 含 execution image id 被拒绝。修复为使用 `/api/v1/system/liveness`，完整 JSON 保留不透明 ID 并标明 `reference_scope: execution`，只有授权 `blob_id` 能取图。修复后才得到上表通过结果。较早的编码/会话容量失败已分别加入编码队列限额、临时借用归还和不可变源编码合并，不能把失败样本抹去。

## 验收边界

- 本次真实模型是既有 YOLO11、OpenVINO CPU FP32 分类部署，不能据此宣布其他模型/任务/格式真实精度通过。没有重训或修改模型阈值。
- Windows conda 与同目录 Python 已验证；POSIX 的共享内存资源跟踪/退出尚未实测。
- API RSS 是进程内所有业务的合计；没有取得本次真实运行的逐 Worker Private Bytes、GPU 显存或全部资源计数时间序列。SHM/预留计数归零证据来自独立跨进程测试，不能冒充真实服务全部内存归零。
- 显示传输 P95 目标没有完成时钟校准下的分位验收。三分钟观察不能证明长期工业稳定性，历史共享内存 P99 比 ZeroMQ 高 17.46% 的失败结论保持。
- Preview 与正式执行共用机器硬件，仍可能产生 CPU/GPU/内存竞争；独立进程和预算不等于完全没有性能影响。标准启动只支持单 API 进程，Preview 执行池数量单独配置。
- 本轮没有自动迁移生产数据库或重新发布。发行更新应同时更新前后端，并使用项目维护入口备份、迁移数据库；不能直接编辑生成的 release/app。

## 临时文件清理受阻

结束时已确认本次 pytest / 探针进程均退出。清理目标限定为仓库 `.tmp` 下明确列出的本轮 `preview-session-*` 与 `preview-route-inspect` 目录，执行前核对了解析后的绝对路径边界。自动审批拒绝了原生 PowerShell 删除操作，仅返回 `blocked by policy`，未提供更具体原因；没有尝试绕过，目录仍保留。证据报告与截图已另存于长期交付目录，不依赖 `.tmp`。
