# YOLOE / SAM3 WorkflowApp 接入与排障

## 文档目的

本文档用于说明 `YOLOE / SAM3` custom node 在 `WorkflowAppRuntime` 中的接入方式、启用/禁用步骤、观测入口和常见排障路径。

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
- 当前 `YOLOE / SAM3` 还额外补了显式 `WorkflowAppRuntime` 接入 smoke；测试会临时把 pack 置为 `enabledByDefault = false`，再覆盖 `disable -> enable -> save application -> create/start runtime -> invoke -> stop` 最小闭环。
- 当前 `YOLOE / SAM3` 的 pack manifest 与节点定义 `metadata.phase` 都已收口到 `implemented`。
- 当前仓库默认把 `YOLOE / SAM3` 作为已启用节点能力提供；接入重点不再是“仓库默认关闭”，而是“目标机器仍要先校验本地模型资产和 workflow 接入路径”。

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

当前状态：

- `YOLOE / SAM3` 当前都已经改成 `true`
- 如果某台目标机器不希望暴露这批能力，仍可通过 `/api/v1/workflows/node-packs/{node_pack_id}/disable` 显式禁用

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

## 为什么当前选择“implemented + 默认启用”

对 `YOLOE / SAM3` 这类重资产扩展型 node pack，当前已经满足：

- 第一阶段目标能力已经做完整
- pack 与节点定义都已收口到 `implemented`
- pack 默认自动启用，但模型会话仍保持按需首次加载

这样做的好处：

- workflow editor、preview 和 app-runtime 默认就能看到这批节点
- 不需要再为每台标准目标机器重复执行 enable
- 即使默认启用，模型权重也不会在服务启动时全量加载，仍是节点首次执行时按需载入
- 如果个别环境不需要这批节点，仍可通过 disable API 快速关闭

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

### 3. 必要时启用或禁用 pack

接口：

- `POST /api/v1/workflows/node-packs/yoloe.open-vocab-nodes/enable`
- `POST /api/v1/workflows/node-packs/sam3.segment-nodes/enable`
- `POST /api/v1/workflows/node-packs/yoloe.open-vocab-nodes/disable`
- `POST /api/v1/workflows/node-packs/sam3.segment-nodes/disable`

说明：

- 当前接口本质上是修改 JSON manifest 里的 `enabledByDefault`，然后刷新 loader。
- 当前仓库默认已经启用；这些接口主要用于目标机器上的覆写、恢复和排障，而不是首次开通。

### 4. 刷新 loader 并确认节点目录

接口：

- `POST /api/v1/workflows/node-packs/reload`
- `GET /api/v1/workflows/node-catalog?node_pack_id=yoloe.open-vocab-nodes`
- `GET /api/v1/workflows/node-catalog?node_pack_id=sam3.segment-nodes`

建议确认：

- 节点定义已经进入 node catalog
- payload 规则 已经可见
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

### 7. 显式执行 WorkflowAppRuntime 受控接入 smoke

当前已经提供一条不参与默认 pytest 收集的显式 integration 测试：

- `tests/integration/test_yoloe_sam3_workflow_app_runtime_smoke.py`

建议只在目标机器上手动执行：

```powershell
conda activate amvision
python -m pytest tests/integration/test_yoloe_sam3_workflow_app_runtime_smoke.py -q
```

当前 smoke 重点覆盖：

- `YOLOE text-prompt` 的受控启用与 `WorkflowAppRuntime` invoke
- `SAM3 semantic-segment` 的受控启用与 `WorkflowAppRuntime` invoke
- `SAM3 video-semantic-segment` 的受控启用与 `WorkflowAppRuntime` invoke
- pack 默认关闭、node-catalog 过滤、显式 enable、runtime start/stop 这条正式控制链

### 8. `SAM3 memory-attention` 现场样例 workflow

当前已经提供一套可直接保存为 template/application 的源 JSON：

- `docs/examples/workflows/sam3_video_memory_attention_review.template.json`
- `docs/examples/workflows/sam3_video_memory_attention_review.application.json`

推荐输入：

- `request_video_path`
  - `value.v1`
  - 示例：`{"value":"D:/cases/line-a/review.mp4"}`
- `request_prompts`
  - `prompt-regions.v1`
  - 可直接输入 `box / point / polygon / mask`

推荐先用这套样例做现场验证，再根据视频复杂度调整：

- 简单任务：改成 `memory-prototype-state`
- 更轻任务：改成 `stateful-mask-propagation`
- 最轻短窗口：改成 `shared-prompts-across-window`

## 当前建议的上线策略

### 建议策略

- 仓库 manifest 默认保持 `enabledByDefault = true`
- 目标机器先校验本地模型资产，再做 preview 和单 runtime 验证
- 如果某台机器暂时不需要这批节点，再通过 node-pack API 显式禁用
- 先通过 preview 与单 runtime 验证，再扩大范围

### 当前不建议的策略

- 在没有本地资产校验和 runtime 观察的情况下直接接入现场生产图
- 在未确认目标机器资源边界前，直接让所有 workflow 依赖这批节点

## 常见问题与排障

### 1. node catalog 里看不到 `YOLOE / SAM3` 节点

优先检查：

- pack manifest 的 `enabledByDefault` 是否被本机改成了 `false`
- 是否已经执行 `enable` / `disable` / `reload`
- `GET /api/v1/workflows/node-pack-status` 里该 pack 的 `enabled` 是否符合预期
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

- 先对照 payload 规则
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

## 当前阶段是否已经把 pack `metadata.phase` 收口到 `implemented`

### 当前状态

- `YOLOE / SAM3` 都已经接通 project-native runtime
- 本地 smoke、稳定性回归、CPU/GPU soak 和扩展 soak 已补齐
- `WorkflowAppRuntime` 显式接入 smoke 已补齐
- pack manifest 与节点定义的 `metadata.phase` 当前都已经收口到 `implemented`

## 当前建议

- 仓库默认保持 `enabledByDefault = true`
- 目标机器继续以“先校验资产、再 preview、再 app-runtime”的方式接入
- 如果某些环境不适合默认暴露这批能力，可用 disable API 做本机覆写
