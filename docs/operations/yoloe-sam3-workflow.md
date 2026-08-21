# YOLOE / SAM3 Workflow 操作

## 适用范围

本文档说明以下 node pack 在 Workflow Preview 和 Workflow App Runtime 中的启用、验证和上线步骤：

- `custom_nodes/yoloe_open_vocab_nodes`
- `custom_nodes/sam3_segment_nodes`

两个 pack 当前均为 `metadata.phase=implemented`、`enabledByDefault=true`。节点使用项目内 runtime 实现，不从 `projectsrc/` 或外部安装包回退执行。模型权重按需加载，不会因为 pack 默认启用而在 backend-service 启动时加载全部模型。

## 上线前检查

### 1. 模型资产

YOLOE 需要对应模型 manifest 和 checkpoint，以及：

- `data/files/models/pretrained/text-encoders/mobileclip/blt/mobileclip_blt.ts`
- `data/files/models/pretrained/text-encoders/clip/tokenizer/bpe_simple_vocab_16e6.txt.gz`

YOLOE 模型目录位于 `data/files/models/pretrained/yoloe/`。

SAM3 通过资产 manifest 登记 checkpoint，标准 Multiplex 资产为：

- `data/files/models/pretrained/sam3/.../checkpoints/sam3.1_multiplex.pt`

文件存在不代表登记有效；同时核对 manifest 中的路径、SHA-256 和模型身份。

### 2. Node pack 状态

依次检查：

```text
GET  /api/v1/workflows/node-pack-status
POST /api/v1/workflows/node-packs/{node_pack_id}/validate
GET  /api/v1/workflows/node-packs/{node_pack_id}/logs
GET  /api/v1/workflows/node-catalog?node_pack_id={node_pack_id}
```

标准 pack id：

- `yoloe.open-vocab-nodes`
- `sam3.segment-nodes`

需要改变当前机器的启用状态时使用：

```text
POST /api/v1/workflows/node-packs/{node_pack_id}/enable
POST /api/v1/workflows/node-packs/{node_pack_id}/disable
POST /api/v1/workflows/node-packs/reload
```

enable 和 disable 会修改本机 manifest 的 `enabledByDefault` 并刷新 loader。它们是本机管理动作，不是每次 Runtime 启动前的必要步骤。

## 接入顺序

1. 在 Workflow Preview 中验证最小节点和一张代表性图片。
2. 验证文本提示、视觉提示和输出 payload 与应用公开契约匹配。
3. 保存 Workflow App，并发布不可变版本。
4. 为已发布版本创建 Workflow App Runtime。
5. 预热并检查 Runtime health、worker、heartbeat 和 snapshot fingerprint。
6. 执行同步调用 smoke，再接入 Trigger 或长期调用方。
7. 按目标设备执行 soak，确认内存、显存和延迟趋势。

Runtime 观测接口：

```text
GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}
GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health
GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events
```

版本更新时发布新 Workflow App 版本，并让稳定 Runtime id 选择新版本；不需要删除 Runtime 或改变 Trigger 的外部调用 id。详细语义见 [Workflow App 版本管理](../architecture/workflows/app-versioning.md)。

## 验证命令

Workflow App Runtime 显式 smoke：

```powershell
conda activate amvision
python -m pytest --basetemp .tmp/yoloe-sam3-runtime tests/integration/test_yoloe_sam3_workflow_app_runtime_smoke.py -q
```

该测试覆盖 pack 状态切换、应用保存、Runtime 创建/启动/调用/停止，以及 YOLOE 和 SAM3 的代表性节点。测试会临时修改 manifest，测试逻辑负责恢复原状态；不要与正在修改相同 manifest 的开发操作并行运行。

长时验证使用 [YOLOE / SAM3 soak](yoloe-sam3-soak.md) 中的独立命令和记录方式。

## SAM3 视频样例

可直接导入的样例：

- `docs/examples/workflows/sam3_video_multiplex_review.template.json`
- `docs/examples/workflows/sam3_video_multiplex_review.application.json`

主要输入：

- `request_video_path`：`value.v1`，正文形如 `{"value":"D:/cases/line-a/review.mp4"}`。
- `request_prompts`：`prompt-regions.v1`，支持 box、point、polygon 和 mask。

视频请求的可变 memory 只存在于单次节点执行。模型 session 归属单个 Workflow App Runtime，不跨 Runtime 或请求共享视频状态。

## 故障定位

| 现象 | 首要检查 |
| --- | --- |
| catalog 中没有节点 | pack 是否 enabled、manifest/catalog 是否通过 validate、loader logs |
| 模型资产缺失 | 资产 manifest、checkpoint 路径、SHA-256、text encoder/tokenizer |
| 输入不合法 | `text-prompts.v1` 或 `prompt-regions.v1` 的必填字段和 prompt 聚合规则 |
| CPU 慢或 CUDA 未使用 | 节点 summary 的 device/precision、CUDA runtime 与显卡驱动 |
| Runtime failed | Runtime events、health、node pack logs、模型资产，然后停止并重新启动 |
| 内存或显存持续增长 | 使用 soak 测试记录稳态区间，不根据单次峰值判断 |

详细错误顺序见 [YOLOE / SAM3 排障](yoloe-sam3-troubleshooting.md)。

## 相关文档

- [Node system](../architecture/workflows/node-system.md)
- [Node pack manifest](../nodes/node-pack-manifest.md)
- [Workflow Runtime](../architecture/workflows/runtime.md)
- [YOLOE / SAM3 soak](yoloe-sam3-soak.md)
