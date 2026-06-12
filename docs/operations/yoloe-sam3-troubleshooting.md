# YOLOE / SAM3 排障手册

## 文档目的

本文档用于给现场、本地验证和 workflow app 受控接入场景提供 `YOLOE / SAM3` 常见问题排查顺序。

本文档是操作手册，不重复解释长期架构边界；受控接入策略见 [docs/architecture/yoloe-sam3-workflow-app-operations.md](../architecture/yoloe-sam3-workflow-app-operations.md)。

## 推荐排查顺序

1. 先看 node pack 是否启用
2. 再看本地资产目录是否完整
3. 再看 preview 或 app runtime 的 summary / last_error / events
4. 再决定是节点输入问题、模型资产问题，还是目标机器运行时问题

## 快速入口

- node pack 状态：`GET /api/v1/workflows/node-pack-status`
- 单 pack 校验：`POST /api/v1/workflows/node-packs/{node_pack_id}/validate`
- 单 pack 日志：`GET /api/v1/workflows/node-packs/{node_pack_id}/logs`
- runtime 健康：`GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health`
- runtime 事件：`GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events`
- 长时 soak：`tests/integration/test_yoloe_sam3_soak_benchmark.py`
- 扩展 soak：`tests/integration/test_yoloe_sam3_extended_soak_benchmark.py`

## 常见问题

### 看不到节点

- 检查 `enabledByDefault`
- 执行 `enable`
- 执行 `reload`
- 再看 `node-catalog`

### 资产缺失

- `YOLOE` 检查 `yoloe` 权重、`mobileclip_blt.ts`、`bpe_simple_vocab_16e6.txt.gz`
- `SAM3` 检查 `sam3.pt`

### 提示输入不合法

- `text-prompts.v1` 不能空
- 同一 `prompt_id` 不能只有 negative
- `prompt-regions.v1` 的 `point / box / polygon / mask` 结构必须完整

### 长时运行不稳定

- 先跑基础 soak
- 再跑扩展 soak
- 对照 [docs/architecture/yoloe-sam3-soak-baseline.md](../architecture/yoloe-sam3-soak-baseline.md)

### 是否应该默认启用

- 不看单次 smoke
- 先看受控接入过程是否稳定
- 再看 soak/benchmark
- 最后再决定是否改默认启用策略
