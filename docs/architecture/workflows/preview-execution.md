# 编辑态 Preview 长执行

Preview 属于编辑调试控制面。它复用节点执行器、模型会话、对象存储及 Broker/Gateway 接口，使用独立常驻进程执行；不占用 FastAPI 事件循环，也不占用正式 Workflow Runtime 的执行槽位。

## 执行与资源所有权

1. HTTP 路由校验身份和输入、保存不可变快照；上传和同步校验通过线程执行。请求断开或反复取消，不得提前关闭正在使用的文件或 lease。
2. 进程池在锁内登记应用占用和 Future。默认容量为两个进程，每应用最多一个活动预览，满载返回 409。首次使用延迟启动，后续复用模型和 registry。
3. 异步上传保存为执行拥有的文件引用。返回 run id 后，文件由执行器负责清理；同步旧接口仍持有上传 lease 直到执行结束。
4. 执行进程持久化状态、JSONL 事件与完整展示结果，异步执行的控制通道只回传结果摘要和事件；旧同步接口保留完整返回结果。父进程分发既有 WebSocket 与项目摘要事件，不重复写 JSONL。
5. 取消或 timeout 先发协作信号，宽限后停止不响应的执行进程。确认退出之后回收输入并释放容量；无法确认退出时保留所有权并阻止依赖排空。
6. 停止服务时先停止 Preview 接入并排空，再关闭正式 Runtime、模型依赖和共享缓冲区。父进程异常退出时，Preview 复用已有父进程 watchdog；查询以 PID 和创建时间识别遗留记录，不能按任务耗时误判。

## 配置与兼容性

| 配置 | 默认值 | 范围 |
| --- | --- | --- |
| workflow_runtime.preview_worker_count | 2 | 1–8；每进程独立模型缓存，增加容量会增加内存占用 |
| workflow_runtime.preview_default_timeout_seconds | 1800 | 异步预览默认执行期限，1–86400 秒 |
| workflow_runtime.preview_model_session_scope_limit | 1 | 每个 Preview 进程保留的模型 scope 上限 |

`sync` 默认期限仍为 120 秒，显式 execution policy 按已有规则应用。自定义节点包声明的 timeout 不因 Preview 改为异步而失效。节点包版本或启用状态变化时清理旧模型并刷新 registry；开发环境代码修改仍由服务 reload 管理。

这是 v1 接口的显式可选扩展：默认 sync 和默认 GET 脱敏摘要保持；新增 async、cancelled、cancel 接口及完整结果查询参数。无数据库 schema 迁移、无模型文件或前后处理变更。旧版本无法执行 async，应把前后端和启动器作为同一发行单元发布或回滚。

开发使用 `conda activate amvision`；发行由 `assemble-release` 将源码和前端打包，子进程采用同目录 Python 的 spawn，不依赖系统 Python/Node。运行中的 `release/<profile>/app` 不手工修改。

## 界面与健康状态

Vue 编辑器在提交后保持运行状态，直到查询到真实终态；取消期间显示“正在取消”。同一标签页按账号、项目、应用保存运行 ID，刷新后继续查询，不把浏览器文件对象或输入内容持久化。服务故障不会自动重放任务。

启动器 `Checking` 保留已经显示的工作台；首次启动和确认故障后的恢复不能通过 Checking 绕过就绪判断。Supervisor 明确进入 Recovering/Failed 时仍展示故障界面。外部服务连续三次探测失败才显示 Unavailable，不改变 Python Supervisor 的恢复职责和健康期限。

属性面板对大型运行 JSON 使用有界摘录，完整对象继续交给查看器，避免单个长节点记录引发大量文本布局。此交互沿用 Vue 3 和现有组件，支持本地离线分发。

## 验证边界

长任务延时测试只验证执行时长与 HTTP 可用性解耦。真实 YOLO11 分类结果比较提供回归证据，不能替代标注集准确率、受控 P99 对照或 24 小时长稳验收。常驻 Preview 与 Runtime 仍共享机器的 CPU、GPU、磁盘和内存，不能宣称物理资源竞争完全消失。
