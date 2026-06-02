# YOLOE / SAM3 WorkflowApp 受控接入与排障

## 文档目的

本文档用于说明 `YOLOE / SAM3` custom node 在 `WorkflowAppRuntime` 中的受控接入方式、启用步骤、观测入口和常见排障路径。

本文档不讨论：

- `YOLOE / SAM3` 的训练、转换或 `DeploymentInstance` 主链
- workflow editor 的前端实现细节
- 多帧或视频能力扩展

## 适用范围

- `custom_nodes/yoloe_open_vocab_nodes`
- `custom_nodes/sam3_segment_nodes`
- `WorkflowPreviewRun`
- `WorkflowAppRuntime`
- 本地 `node pack` loader 管理接口

## 当前结论

- `YOLOE / SAM3` 当前都已经接通 project-native runtime，并且本地 smoke、稳定性回归、CPU/GPU soak 基线都已补齐。
- 当前最稳的上线策略不是“默认启用”，而是“受控启用”：
  - pack manifest 继续保持 `enabledByDefault = false`
  - 通过 workflow node-pack 管理接口在目标机器上显式启用
  - 先进入 preview / app-runtime 的受控接入，再决定是否扩大启用范围
- 当前 `YOLOE` 的节点定义 metadata 已经是 `implemented`，但 pack manifest 仍保持 `partial-implementation`。
- 当前 `SAM3` 的节点定义 metadata 和 pack manifest 都仍保持 `partial-implementation`。

## 三个容易混淆的字段

### pack manifest 的 `enabledByDefault`

来源：

- [docs/nodes/node-pack-manifest.md](../nodes/node-pack-manifest.md)
- [docs/api/workflows.md](../api/workflows.md)

含义：

- 这是 node pack 的默认启用开关。
- `LocalNodePackLoader` 扫描到 manifest 后，如果这个字段是 `false`，就不会把 pack 的 `catalog` 和 handler 注册进当前服务的可用节点集。

作用：

- 决定目标环境里是否默认把该 pack 当作已启用能力。
- 这是实际生效的加载开关，不只是说明文字。

当前建议：

- `YOLOE / SAM3` 继续保持 `false`
- 在目标机器上通过 `/api/v1/workflows/node-packs/{node_pack_id}/enable` 显式启用

### pack manifest 的 `metadata.phase`

来源：

- `custom_nodes/yoloe_open_vocab_nodes/manifest.json`
- `custom_nodes/sam3_segment_nodes/manifest.json`

含义：

- 这是 pack 级成熟度标签。
- 它描述的是“整个 pack 的交付状态”，不只是单个节点是否已经能跑。

作用：

- 主要用于文档、状态说明、管理面显示和阶段判断。
- 它不是 loader 的硬开关，不会直接改变是否加载。

### node definition 的 `metadata.phase`

来源：

- `custom_nodes/yoloe_open_vocab_nodes/workflow/catalog.json`
- `custom_nodes/sam3_segment_nodes/workflow/catalog.json`

含义：

- 这是单个节点定义的成熟度标签。
- 它描述的是某一个节点本身是否已经接通和达到当前阶段目标。

作用：

- 便于区分“pack 里有些节点已经做完，但整个 pack 还未完全收口”的情况。

## 为什么当前建议“implemented + 默认不启用”

对 `YOLOE / SAM3` 这类重资产、受控扩展型 node pack，更稳的策略是：

- 可以先把能力做完整
- 可以先把节点定义做到 `implemented`
- 但 pack 默认不自动启用

这样做的好处：

- 不会在所有环境自动加载大模型资产
- 不会要求所有现场机器默认具备这套扩展能力
- 可以先在指定项目、指定机器、指定 workflow app 上做受控上线
- 出问题时只影响已经显式启用的目标环境

## WorkflowApp 受控接入步骤

### 1. 先检查本地预训练资产

`YOLOE` 至少需要：

- `data/files/models/pretrained/yoloe/...`
- `data/files/models/pretrained/text-encoders/mobileclip/blt/mobileclip_blt.ts`
- `data/files/models/pretrained/text-encoders/clip/tokenizer/bpe_simple_vocab_16e6.txt.gz`

`SAM3` 至少需要：

- `data/files/models/pretrained/sam3/.../checkpoints/sam3.pt`

如果目标机器缺少这些目录，后续节点启用后仍会在运行时失败。

### 2. 读取 node pack 当前状态

接口：

- `GET /api/v1/workflows/node-pack-status`
- `POST /api/v1/workflows/node-packs/{node_pack_id}/validate`

建议先确认：

- pack 是否被发现
- manifest 是否有效
- custom node catalog 是否可读
- 是否存在最近 loader 错误

### 3. 在目标机器上显式启用 pack

接口：

- `POST /api/v1/workflows/node-packs/yoloe.open-vocab-nodes/enable`
- `POST /api/v1/workflows/node-packs/sam3.segment-nodes/enable`

说明：

- 当前接口本质上是修改 JSON manifest 里的 `enabledByDefault`，然后刷新 loader。
- 这是目标机器上的运维动作，不要求把仓库里的 manifest 默认改成 `true`。

### 4. 刷新 loader 并确认节点目录

接口：

- `POST /api/v1/workflows/node-packs/reload`
- `GET /api/v1/workflows/node-catalog?node_pack_id=yoloe.open-vocab-nodes`
- `GET /api/v1/workflows/node-catalog?node_pack_id=sam3.segment-nodes`

建议确认：

- 节点定义已经进入 node catalog
- payload contract 已经可见
- 节点数量和预期一致

### 5. 先走 preview，再进 app runtime

建议顺序：

1. 先在 `WorkflowPreviewRun` 验证单个节点或单条图
2. 再把它接入已保存 application
3. 再创建 `WorkflowAppRuntime`
4. 最后再考虑持续运行

不建议一上来直接把新 pack 节点放进长期运行 app runtime。

### 6. 观察 app runtime

接口：

- `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health`
- `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events`

重点看：

- `observed_state`
- `last_error`
- `worker_process_id`
- `heartbeat_at`
- `loaded_snapshot_fingerprint`

## 当前建议的上线策略

### 建议策略

- 仓库 manifest 默认保持 `enabledByDefault = false`
- 在目标机器通过 node-pack API 显式启用
- 先限制在少量 workflow app 或指定 Project 内使用
- 先通过 preview 与单 runtime 验证，再扩大范围

### 当前不建议的策略

- 直接把 pack manifest 改成默认启用后全环境分发
- 一上来就把 `YOLOE / SAM3` 作为所有 workflow 的默认节点能力
- 在没有本地资产校验和 runtime 观察的情况下直接接入现场生产图

## 常见问题与排障

### 1. node catalog 里看不到 `YOLOE / SAM3` 节点

优先检查：

- pack manifest 的 `enabledByDefault` 是否还是 `false`
- 是否已经执行 `enable` 或 `reload`
- `GET /api/v1/workflows/node-pack-status` 里该 pack 的 `enabled` 是否为 `true`
- `issues` 或 `logs` 中是否存在 manifest/catalog 错误

### 2. `enable` 接口失败

常见原因：

- manifest 不是 JSON
- manifest 校验失败
- pack 依赖未满足

入口：

- `POST /api/v1/workflows/node-packs/{node_pack_id}/validate`
- `GET /api/v1/workflows/node-packs/{node_pack_id}/logs`

### 3. pack 已启用，但节点运行时报模型资产缺失

常见原因：

- `YOLOE` 预训练权重目录不完整
- `mobileclip_blt.ts` 缺失
- `bpe_simple_vocab_16e6.txt.gz` 缺失
- `SAM3` 的 `sam3.pt` 缺失

处理方式：

- 先检查 `data/files/models/pretrained/...`
- 再检查当前节点 summary 里的 `checkpoint_path`
- 目标机器上重新执行对应 smoke 或 integration soak

### 4. 提示输入不合法

常见表现：

- `text-prompts.v1` 为空
- 同一 `prompt_id` 只有 negative 没有 positive
- `prompt-regions.v1` 缺少 `prompt_kind`
- `point / box / polygon / mask` 结构不完整

处理方式：

- 先对照 payload contract
- 再看节点返回的 `summary`
- 当前 `YOLOE / SAM3` 已经有空提示、非法提示和异常目录回归，可以按这些边界排查

### 5. CPU 很慢或 GPU 没生效

先看节点 summary：

- `device`
- `precision`
- `text_encoder`
- `project_native`

再看当前机器：

- CUDA 是否可用
- 目标机器是否真的具备对应 GPU runtime
- 是否误退回 CPU

基线参考：

- [yoloe-sam3-soak-baseline.md](yoloe-sam3-soak-baseline.md)

### 6. 长时运行后怀疑内存或显存泄漏

优先不要猜，直接执行：

- `tests/integration/test_yoloe_sam3_soak_benchmark.py`
- `tests/integration/test_yoloe_sam3_extended_soak_benchmark.py`

这两份测试默认不会进入常规收集，只会在显式指定时执行。

### 7. runtime 失败后如何恢复

建议顺序：

1. 看 `app-runtimes/{id}/events`
2. 看 `app-runtimes/{id}/health`
3. 看 `node-pack-status` 和 `node-pack logs`
4. 确认本地资产目录
5. 必要时先停 runtime，再重启

## 当前阶段是否应该把 pack `metadata.phase` 改成 `implemented`

### 已满足

- `YOLOE / SAM3` 都已经接通 project-native runtime
- 本地 smoke 已补齐
- CPU/GPU soak 基线已补齐
- 更长时长/更大图尺寸扩展 soak 已补齐
- workflow app 受控接入说明和排障手册已经落地

### 仍建议再补 1 步

- 最好再补一条明确针对 `WorkflowAppRuntime` 的端到端受控接入 smoke

原因：

- 当前 `YOLOE / SAM3` 的节点级 runtime 已稳定
- 但 pack 级 `phase` 更像“整个受控上线面是否封账”
- 如果能再补 1 条 app-runtime 级 smoke，再把 pack manifest 的 `metadata.phase` 改成 `implemented` 会更稳

## 当前建议

- 现在先不改 `enabledByDefault`
- 继续保持受控启用
- `metadata.phase` 可以进入“准备收口”状态
- 如果下一步补完 app-runtime 级受控接入 smoke，就可以正式把 `YOLOE / SAM3` 的 pack manifest `metadata.phase` 从 `partial-implementation` 收到 `implemented`
