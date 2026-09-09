# 用户权限专项验收（2026-09-09）

本次覆盖 SQLite、30 分钟真实模型长稳、修改前后性能与资源、CPU/NVIDIA 完整服务发行、正式 .NET SDK、18 个模型任务组合及权限页面。结果分项记录；系统缩放实测与浏览器等效视口分开判定。

## 环境与隔离

- Windows x64、conda amvision 开发环境；基线为 Git `f939dc13`，对照为当前权限实现。
- 修改前后使用独立源码副本、SQLite、端口、文件与共享内存目录。HTTP 默认 amvar Token、图片和灰度工作流相同，按 AB/BA 交替执行。
- CPU/NVIDIA 使用标准 `assemble-release` 组装到本次隔离目录，并使用对应发行版自带 Python。未覆盖用户原有 `release/<profile-id>` 数据；本项验证完整服务 profile，不包含启动器原生窗口验收。
- 原 amvar 默认永久 Token、原业务 App、原 Runtime 和原模型保留。真实模型长稳使用权限验收账号及独立 App 副本。
- 测试期间存在训练/转换等并行负载，性能结果属于该负载条件下的对比，不是空闲机器的吞吐极限。

## 已修复的问题

1. 全新 SQLite 从初始迁移执行至 head 时，初始 `create_all` 已生成页面字段，后续迁移再次添加导致重复列。迁移现在检查已存在列的 JSON 类型和 nullable 属性，正确兼容新建与旧库升级；增加真正从空库执行整个迁移链的测试。
2. 训练设备分配事件缺少当前执行的 `attempt_id`，被既有执行归属校验拒绝。事件现在携带实际 fence 中的 attempt，不降低校验。
3. YOLO 非 detection 训练 runner 仍向已改为 outbox 的应用服务传入失效的 `queue_backend` 参数。移除该失效构造参数，保留 runner 其他队列行为。
4. 全链路测试入口仍使用旧 LocalBufferBroker 路径配置、关闭 Broker，并向 RF-DETR 提交不在公开 schema 中的参数。修正隔离目录与测试输入，不更改生产 schema。
5. 小窗口下 App Mode 结果图被压缩到约 25px。结果区域保留最小可用高度并滚动显示，窄屏输入区至少 160px，结果区至少 320px。
6. 新增权限文案的日语和韩语各 52 个字段已完整翻译，并增加键一致性及非英文回退测试。
7. RF-DETR detection/segmentation 在无目标时没有生成已请求的结果图，导致异步 ObjectStore 回执校验失败。现在无目标也按保存选项生成原图；保留异步结果完整性校验。
8. RF-DETR PyTorch Runtime 忽略已登记的输入尺寸，以 scale 默认尺寸重建位置编码，导致自定义尺寸训练权重严格加载失败。detection/segmentation 构建器和会话现在传递同一输入尺寸；测试验证非默认尺寸 checkpoint 的位置编码严格一致，不插值或丢弃权重。
9. Windows 状态读取者短暂占用 `runtime-state.json` 时，原子替换触发 WinError 5，使 full 监督器退出。状态写入/清理现在对明确的 Windows 文件占用错误限时重试 5 秒；超时仍报告原错误，写入失败保留旧状态。真实 Windows 读句柄及永久失败测试已验证，权限检查与推理数据面不进入此路径。
10. 矩阵脚本误把 classification 的顶层准确率报告当成嵌套 `metrics`，未映射 RF-DETR Lightning 报告中的 bbox/mask 指标名称，且 GBK 控制台无法输出部分错误字符。按真实报告结构修正解析、保留失败前已完成结果，并在控制台采用标准 JSON Unicode 转义；不改变业务报告结构或评估门禁。

## 修改前后性能与资源

输入为 974446 字节、2560×2358 JPEG。HTTP 各预热 20 次、测量 200 次；SDK 每种协议每侧 4 轮，每轮预热 5 次、测量 40 次。所有测量请求均检查实际 Workflow 成功，不能仅以 HTTP 200 判定。

| 路径 | 每侧请求数 | p50 前→后（ms） | p95 前→后（ms） | p99 前→后（ms） |
| --- | ---: | --- | --- | --- |
| HTTP multipart 同步 | 200 | 131.12 → 126.68 | 183.97 → 181.85 | 203.54 → 191.61 |
| .NET ZeroMQ Trigger | 160 | 72.83 → 69.18 | 107.93 → 101.56 | 121.82 → 105.82 |
| .NET 共享内存 Trigger | 160 | 93.87 → 93.76 | 125.65 → 125.70 | 139.54 → 140.01 |

上述 1040 次测量调用全部成功。未观察到明显权限开销；共享内存尾延迟小幅波动，不能据此宣称加速或零开销。该工作流包含图片解码/灰度处理，真实训练模型另由下述长稳和全链路验证。

HTTP/ZeroMQ/共享内存平均延迟分别为 132.89→130.73、77.01→72.51、91.91→94.09ms；以累计调用时间计算的串行调用率约为 7.53→7.65、12.98→13.79、10.88→10.63 次/秒。共享内存平均延迟增加约 2.37%，与中位数变化不同，应保留这一差异。测试未做并发饱和扫描，这些调用率不是系统最大吞吐，也不是全部模型/输入分辨率的性能覆盖。

采样范围为两套隔离服务及各自全部子进程，包含对应 Broker/Runtime；两侧执行相同调用量。

| 资源 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 服务树 RSS 峰值 | 672.30 MiB | 670.97 MiB |
| 服务树 Private 峰值 | 1582.90 MiB | 1581.14 MiB |
| 服务树线程峰值 | 76 | 76 |
| 服务树句柄峰值 | 1306 | 1306 |
| 采样区间累计 CPU 时间增量 | 92.80 s | 88.16 s |
| .NET ZeroMQ 进程 RSS 峰值 | 43.48 MiB | 43.52 MiB |
| .NET 共享内存进程 RSS 峰值 | 34.09 MiB | 34.13 MiB |

资源含首次图片执行的分配和缓存增长；峰值相近，不把初始化增长视作泄漏，也不以短测排除长周期泄漏。

本次尚未完成无页面/多订阅组合、数据库等待时间及全部模型的修改前后性能矩阵，因此这是已执行路径的对比结果，不能标记为原设计所有性能场景全部通过。

## 页面与语言

创建账号、编辑权限、启动设置及实际 App Mode 检查了以下 9 组浏览器视口：1024×768、819×614、683×512、1366×768、1093×614、911×512、1920×1080、1536×864、1280×720。它们对应设计中三组分辨率及 100%/125%/150% 的有效空间。

- 创建/编辑表单在最小视口仍保持 18px 外边距，取消/提交按钮可见，内容区域独立滚动；页面无横向溢出。
- 修正后的真实 App Mode 图片高度为约 183～422px，低高度视口通过滚动访问内容，不压缩成细条。
- 权限编辑表单补齐中文/日语/韩语 × 亮/暗主题 × 九组视口共 54 组布局检查，全部保持对话框和底部按钮在视口内、无横向溢出。新增权限字段无英文回退，控制台没有 error/warn。
- **实际 Windows 系统缩放仍待手动协助验证**：当前电脑工具未开放原生 Windows 控制。等效视口仅证明布局适配，不证明操作系统 DPI、字体栅格化或跨屏缩放正确。

## 30 分钟真实模型长稳

2026-09-09 08:58:54～09:28:54（Asia/Shanghai），实际 1800.563 秒。受限账号仅有 App Mode/启动页面、workflows:read、workflows:invoke、projects:files:read，限定 project-1。使用 3570 治具分类模型、OpenVINO CPU、两路分类及 24 个 ROI 的独立验收 Workflow，逐次发送真实图片。

- 1394 次请求全部成功，0 次调用错误、0 次健康监测错误，61 次健康采样。单并发、两次请求间隔 500ms，实测业务吞吐约 0.774 次/秒，包含主动间隔。
- 延迟 min/mean/p50/p95/p99/max：469/783.70/711/1094/1740.46/9891ms。期间存在转换、训练和发行测试，尾延迟不能作为独占机器的模型性能结论。
- 118 次进程资源采样，开发 API 及其子进程集合和创建时间保持一致。RSS 起始/结束/峰值约 1570.21/855.08/1628.66 MiB；Private 起始/结束/峰值约 3412.33/3409.05/3477.33 MiB。线程 217→191，句柄 5623→5620（峰值 5649）。采样树 CPU 时间累计增加 1468.63 秒。
- 资源范围为开发 API 及其后代，包含 Broker/Workflow Runtime；独立手动启动、并非 API 后代的服务不计入该树，不能把这些数值称为整机或所有视觉服务资源。
- Broker 已分配容量峰值 24 MiB，结束时为 0；活跃 lease 峰值 24，结束为 0；quarantined/revoking 容量始终为 0，最终转发错误及丢弃响应均为 0。没有观察到该采样范围内的持续资源增长。

首次长稳因开发服务热重载出现 2 次 Broker 调用失败，未计为通过。上述最终轮次冻结后端源码后重新完整运行。最终负载工具写出 succeeded；外层临时脚本在读取整数返回码为字典的打印阶段发生 AttributeError，整体包装进程退出码为 1。已核对持久结果的时长、请求数、健康采样及错误列表；不将打印故障隐瞒为正常进程退出，也不把它误计为业务请求失败。

## 发行包与 SDK

CPU、NVIDIA 均通过真实 full 服务启动、SQLite、基础 API、失效状态文件恢复、dataset-export worker 独立恢复及 stop 后进程回收。带权限/SDK 负载的完整验收分别耗时 345.12、353.96 秒，各含 240 秒驻留。

状态文件竞争修正后重新组装的最终启停复测分别通过，CPU 160.89 秒、NVIDIA 179.92 秒，各含 60 秒驻留；不将修正前 CPU 的 WinError 5 失败计为通过。

之后 RF-DETR segmentation 空结果图修正也已通过标准命令重新组装到两个隔离 profile；核对源文件与发行副本 SHA-256 一致。该最后一次复制未重复整套启停测试，使用针对该预测器的回归与全链路复测验证行为。

- 每种发行版分别用默认管理员与受限账号执行正式 .NET SDK multipart 同步及异步调用，均得到 succeeded；受限账号停止 Runtime 返回 403。
- 创建普通账号后禁止默认自动登录；默认 amvar Token 仍返回 scopes=["*"]。
- 每种发行版正式 .NET SDK ZeroMQ 和共享内存各测量 20 次，全部成功，原传输 benchmark 门禁也通过。
- 开发环境正式 .NET SDK 另以原默认 Token 完成真实 3570 模型 Workflow 的同步与异步检测。
- CPU/NVIDIA 的真实 3570 模型包导入、OpenVINO 同步/异步推理、Workflow 执行、stop/reset 均通过，完整服务用例分别耗时 269.21、269.74 秒。该模型是 OpenVINO CPU 产物；不将 NVIDIA profile 上的此项结果写成 TensorRT 模型实测。

初次发行验证暴露了全新 SQLite 重复列问题，修正后重新组装。一次 CPU 冷启动在并行重负载下超过现有训练 worker 就绪时限；未改变生产时限，串行复测通过。临时 SDK 负载脚本还修正了输入绑定和重复创建测试账号的处理错误，这些失败不计入通过轮次。

## 自动化与模型矩阵

- 前端完整 Vitest：127 个文件、507 项通过；vue-tsc 与 Vite 构建通过。
- 权限相关 8 个后端套件：38 项通过；SQLite/训练/全链路入口补充回归及 Ruff、git diff --check 通过。
- 正式 .NET net472 构建及现有合同测试通过。
- RF-DETR 空检测/分割图片、自定义尺寸严格加载和生命周期回归：25 项通过。launcher 状态/停止回归 12 项通过，模型矩阵入口测试 22 项通过。
- 18 个模型/任务组合的 DatasetImport → Export → 单 epoch 训练 → 评估 → ONNX/OpenVINO/TensorRT → sync/async → Workflow → stop/reset 首轮完整矩阵于 08:48:24～09:53:07 执行，7 项通过、11 项失败。失败项修正或排除并行 GPU 争用后分别串行复测，不能将未完成复测的项目计为通过。
- 已发现 YOLO26 detection 的弱训练权重在 TopK 极接近分数下发生输出顺序差异，OpenVINO 逐项一致性校验拒绝；显式 fp32 编译仍可复现。追加预训练权重场景也未通过 OpenVINO 门禁，未放宽容差。

补充串行结果：

- YOLOv8 / YOLO11 / YOLO26 classification 于 10:08:49～10:20:40 完整复测，3 项全部通过，测试进程正常退出 0。
- RF-DETR detection 修正后已完成训练、独立评估、三种转换、sync/async、Workflow；原复测进程最后因测试脚本未映射 `test/mAP_50` 等字段而失败。修正解析器后重读该次真实训练报告并比对 SQLite 中独立评估，AP50/AP50:95 均为 0，符合现有差异门禁。这是对已完成业务结果的补充核验，不把原失败进程改写为正常退出。
- RF-DETR segmentation 于 10:20:40～10:25:46 完整重跑至 OpenVINO 阶段：自定义尺寸训练、评估、ONNX 转换和 sync/async/Workflow 通过，空分割异步图片问题已修复；OpenVINO 转换及前序同步调用成功，但异步实例启动返回 500，底层报 `Cannot find tensor for port ... pred_masks/sink_port_0[0]:f32[1,100,96,96]`。此轮失败，尚未执行 TensorRT。后续专项诊断确认失败部署使用 AUTO，并在纯 OpenVINO 程序中复现 CPU 启动辅助转入 GPU 时的同类错误，见[修复方案](model-matrix-repair-plan.md#5-rf-detr-segmentation修复-auto-启动阶段)。

按组合汇总，10 个组合有完整矩阵成功结果（首轮 7 个及 classification 3 个）；另 1 个 RF-DETR detection 完成业务链路并通过修正解析后的真实指标补验；剩余 7 个组合失败。不能汇报为 18/18 通过。

以下问题仍阻止完整模型矩阵通过，不能把权限专项通过等同于所有业务门禁通过：

| 组合 | 仍未通过的门禁 |
| --- | --- |
| YOLO26 detection | OpenVINO 数值一致性；专项诊断中 TopK 前候选通过原容差，临界候选集合及行顺序不同；完整语义门禁尚待实现，旧 ONNX 特例还漏检框坐标 |
| YOLO26 segmentation / pose / obb | PyTorch→ONNX 数值一致性；专项诊断已确认 TopK 前候选及共同候选完整字段一致，TopK 选择差异与 detection 同类；尚未完成生产修复和完整复测 |
| YOLOv8 pose | 串行复测已完成三种转换、sync/async 和 Workflow，但训练 test OKS AP50=0.1，独立评估=1.0，差异 0.9 超过既有 0.05 门禁 |
| YOLO11 pose | 训练 test OKS AP50≈0.142857，独立评估=1.0，差异≈0.857143 超过门禁 |
| RF-DETR segmentation | OpenVINO AUTO 启动设备切换后无法找到 pred_masks 输出张量；关闭启动辅助的独立短测通过，生产适配及完整复测尚未完成；TensorRT 链路尚未覆盖 |

Pose 的串行复测已排除前一轮 GPU 租约争用。后续专项诊断逐项对齐 scaleup、NMS 和关键点裁剪后，YOLOv8/YOLO11 独立评估与同设备训练评估在报告精度内吻合；生产评估策略尚未修复，不归因于权限修改，也不降低原评估门禁。

参考源码、受控实验、兼容边界和实施步骤见[模型转换与 Pose 评估修复方案](model-matrix-repair-plan.md)。专项诊断不改变本节历史轮次的失败状态，7 个组合仍需修复后逐项完整验收。

## 复验入口

开发终端先执行 `conda activate amvision`。完整模型矩阵的本轮参数如下；测试自行管理隔离进程，端口必须未被占用。小数据、单 epoch 用于验证工程链路，不用于评判模型精度。

```powershell
python -m tests.integration.model_task_e2e_matrix --start-processes --run-workflow --run-id access-regression --batch-mode fixed --max-images-per-split 4 --training-precision fp32 --port 18361
```

针对单类问题，在同一命令中增加 `--models rfdetr --tasks segmentation` 或 `--models yolov8 --tasks pose`。GPU 用例按顺序执行，避免不同隔离库争用同一块 GPU 的独占租约。

发行包通过 `python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-cpu --release-root <隔离发行根目录> --force --output text` 组装，NVIDIA 对应 `full-windows-x64-nvidia`；使用各自的 bundled Python，不以开发 conda 代替发行解释器。正式 SDK 的 HTTP 验收入口见[集成测试说明](../../tests/integration/README.md)。

## 收尾与未完成项

全部本轮模型测试进程已结束；按隔离数据库及共享内存路径检查，没有仍使用本轮资源的 Python/SDK 服务进程。原开发服务及用于复查的账号、应用副本、Runtime 保留。

根据本轮隔离 SQLite 的 324 个任务及数据集记录，核对了 281 个实际存在的测试产物目录（63 个数据集目录、53 个推理输入目录、165 个任务产物目录）。原生 PowerShell 清理命令被执行策略拒绝，返回 `blocked by policy`，未提供更具体原因；未改用其他工具绕过。上述数据以及对应的 `.tmp/user-access-acceptance-20260909`、`.tmp/model-task-e2e-matrix/user-access-20260909*` 中间文件仍待清理，临时文件不是长期交付物。旧轮次已被拒绝的清理命令未重试。

最终状态为部分通过：30 分钟真实负载、已测性能路径、发行服务/SDK、页面等效视口及翻译通过；7 个模型组合、未覆盖的性能组合、实际 Windows 系统缩放及临时数据清理仍未完成验收。数据库验证仅覆盖 SQLite。
