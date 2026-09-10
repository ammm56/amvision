# Preview 实时执行代码实施清单

日期：2026-09-10。当前代码实现与 [设计](preview-streaming-design.md)、[v1 协议](../../api/workflow-preview-sessions.md) 对齐。功能测试通过不等于全部性能及工业验收通过。

| 步骤 | 实现 | 核对方式 | 状态 |
| --- | --- | --- | --- |
| S0 固定边界 | 同一真实应用、BMP、部署实例；区分冷启动、图执行、全量显示 | 保存输入/快照摘要和分段计时 | 已完成 |
| S1 恢复部署调用 | 删除 preview/models.py，注入 PublishedInferenceGatewayClient 和 Broker 通道 | 五任务协议测试、真实 YOLO11 分类 | 已完成 |
| S2 解耦执行与显示 | run.finished、run.outputs 分离，异常交付明确 unavailable | Worker/会话/前端归并测试 | 已完成 |
| S3 JPEG 与有界编码 | 缩略图先交付、全尺寸 JPEG、原 JPEG 复用；小值预算减少逐项 RPC | 格式、尺寸、原业务输入不变、真实全部资源解码 | 已完成 |
| S4 浏览器接管 | 完整 Blob、receipt、分块 ACK、多订阅者、pin、断线和容量边界 | 协议单测、缓存/分页测试、真实 40 个资源回收证明 | 已完成 |
| S5 最后消费释放 | PreviewOutputScope、嵌套别名、父子交接、输入容器和解码缓存释放 | 生命周期、循环/并行/选择、真实图 | 已完成；第三方私有持有仍依赖节点自身释放 |
| S6 性能与发布 | 禁用 WS DEFLATE、单节点渲染、连续上传窗口、分段计时 | 无压缩客户端对照、真实浏览器、启动器测试 | 代码与短测完成；浏览器 5.25 / 5.92 秒，历史基线与长期验收未通过 |

## 实现位置

- preview/worker.py、pool.py：常驻进程、正式部署网关、取消/退出与通道补偿关闭。
- preview/lifetime.py、graph_executor.py、snapshot_execution.py：Preview 专用消费计划；正式调用不创建管理器。
- preview/display.py、values.py、bridge.py：JPEG 与 JSON 编码、显示结果、受管预算。
- preview/session.py、api/ws/v1/preview_sessions.py：状态归并、完整接管、共享内存资源回收。
- workflow-preview-session.service.ts：上传窗口、完整资源缓存、接管确认、本地 JSON 分页。
- useWorkflowPreviewSession.ts：业务完成/显示就绪分离、前端分段耗时。
- WorkflowGraphNode.vue、WorkflowGraphNodeLayer.vue：单节点更新边界，保留拖拽、参数及预览交互。
- runtimes/launchers/service/start_backend_service.py：固定不协商 WebSocket DEFLATE，拒绝开启压缩；VS Code 调试入口同样关闭压缩。

## 验证约束

先运行最小行为测试，通过后验证循环、并行、选择、正式 Runtime Preview 回归及 Vue 类型检查。真实脚本 tests/integration/workflow_preview_session_live.py 使用隔离快照与显式保存目录；默认使用页面一致的 Base64 入口，计时包含原始文件上传。追加 Delay 只验证长业务与显示独立，不作为正常延迟基线。

已按实际开发启动参数完成浏览器重启后首次运行与复用运行，并保留优化中间的慢样本。最终两轮均复用已启动 Worker，不冒充最终代码冷启动基准。不能拿 Python 客户端结果冒充浏览器结果，不能把图执行结束当作全量结果已显示，也不能用当前版本替代历史同步版本的同条件基线。

真实模型证据仅覆盖已有 YOLO11 分类实例及 3570 图片。其他模型只报告协议/适配测试覆盖；历史共享内存 P99 +17.46% 的失败和长期稳定性验收保持独立。
