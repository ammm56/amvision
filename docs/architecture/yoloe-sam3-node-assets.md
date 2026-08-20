# YOLOE 与 SAM3 Node Pack

## 定位

YOLOE 开放词汇检测和 SAM3 分割以自定义 Node Pack 提供，不进入核心模型训练、转换和 deployment registry。使用者显式安装、配置资产并在 Workflow 中选用这些节点。

实现目录：

- `custom_nodes/yoloe_open_vocab_nodes/`
- `custom_nodes/sam3_segment_nodes/`

每个包都包含 `manifest.json`、Workflow catalog、Python entry、runtime、payload 与包内 core 实现。运行时不直接依赖 `projectsrc/` 参考仓库。

## 当前节点

### YOLOE

| node type id | 用途 |
|---|---|
| `custom.yoloe.text-prompt-detect` | 文本提示开放词汇检测 |
| `custom.yoloe.visual-prompt-detect` | 视觉提示检测 |
| `custom.yoloe.prompt-free-detect` | Prompt-free 检测 |

输出为稳定的 Detections、Regions 和 Summary payload，可继续连接过滤、绘制、裁剪和规则节点。

### SAM3

| node type id | 用途 |
|---|---|
| `custom.sam3.load-checkpoint` | 加载并复用模型 session |
| `custom.sam3.interactive-segment` | 单图交互式分割 |
| `custom.sam3.semantic-segment` | 单图语义提示分割 |
| `custom.sam3.video-interactive-segment` | 视频交互式目标传播 |
| `custom.sam3.video-semantic-segment` | 视频语义目标传播 |

单图输出 Regions/Summary，视频节点输出 Tracks/Summary。checkpoint/session 是执行期资源引用，不作为普通 JSON 大对象跨节点复制。

## 资产目录

权重、文本编码器和其他大型模型资产按 manifest/config 指定的本地路径加载，不在线自动下载。资产必须满足：

- 版本和文件 hash 可识别；
- 路径由包配置或平台设置解析；
- 发布包装配时显式纳入或列为外部依赖；
- 缺失、损坏或结构不匹配时启动/节点执行明确失败；
- 不把开发机绝对路径写进 Workflow App Version。

Git 只保存源码、manifest、小型配置和必要的 schema；大型 checkpoint 不进入仓库。

## Runtime 与缓存

- Preview 在 backend-service 进程使用受控 session cache；
- 生产 Workflow Runtime 在自身常驻进程加载和复用 session；
- 不为每个节点调用新建 Python 进程；
- 同一个模型资产按规范化 identity 复用，配置或 checkpoint 变化会形成不同 cache key；
- Runtime 停止、切版或进程退出时释放 session；
- 图片通过 memory handle 或 LocalBuffer 传递，视频帧不通过 Base64 JSON 批量复制。

## Prompt 与输出边界

YOLOE 和 SAM3 节点只接受 catalog 声明的 prompt payload。节点负责把输入规范化为包内模型接口，再把模型结果转换为平台稳定 payload；下游节点不依赖第三方模型对象、Tensor 或内部类。

模型加载保持严格结构校验。不得通过关闭 strict、忽略不匹配权重或静默插值来掩盖 checkpoint/config 错误。

## 发布与长期运行

Workflow App 发布会把 NodeDefinition version、Node Pack version 和 manifest identity 纳入依赖指纹。Runtime 启动时按不可变版本校验依赖，不能用当前工作区中不匹配的包静默替换已发布依赖。

健康和性能验证至少覆盖：

- checkpoint 冷启动与热复用；
- 单图连续调用；
- 多 Runtime 独立 session；
- 视频长序列状态释放；
- Runtime stop/restart/version switch；
- 缺失资产和 hash/config 不匹配；
- LocalBuffer owner/generation 回收。

## 相关文档

- [节点系统](node-system.md)
- [Workflow Runtime](workflow-runtime.md)
- [高性能图片数据面](high-performance-image-data-plane.md)
- [YOLOE/SAM3 运行验证基线](yoloe-sam3-soak-baseline.md)
- [YOLOE/SAM3 Workflow 运行](yoloe-sam3-workflow-app-operations.md)
- [YOLOE/SAM3 排障](../operations/yoloe-sam3-troubleshooting.md)
