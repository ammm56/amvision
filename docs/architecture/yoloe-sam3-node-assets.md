# YOLOE 与 SAM3 节点资产规范

## 文档目的

本文档用于固定 `YOLOE` 和 `SAM3` 第一阶段作为 `custom node` 接入时的磁盘资产规则、`manifest.json` 最低字段，以及 workflow 节点输入输出 contract。

本文档只讨论：

- 预训练模型和附属资产放在哪里
- 目录层级和命名怎么定
- `manifest.json` 至少要写什么
- `custom node` 第一阶段应使用哪些 payload 规则
- preview run、`WorkflowAppRuntime` 和 `DeploymentInstance` 三种运行形态的关系

本文档不展开：

- 节点推理代码实现细节
- workflow app 改造
- 核心模型主链的训练、转换、发布接入

workflow app 侧的接入顺序、目标机器启用/禁用和运维排障，见 [yoloe-sam3-workflow-app-operations.md](yoloe-sam3-workflow-app-operations.md)。

## 当前状态说明

- `YOLOE` 与 `SAM3` 这部分文档当前先固定资产目录、`manifest.json` 规则和节点输入输出 contract。
- `projectsrc/` 只作为参考源码面，不参与运行时。
- `YOLOE` 当前不会回退到已安装官方包或 `projectsrc` 参考代码执行推理；`prompt-free`、`text-prompt`、`visual-prompt` 三条 project-native runtime 已经接通，后续只继续扩能力面。
- `SAM3` 当前已经接通 `interactive-segment`、`semantic-segment`、`video-interactive-segment` 和 `video-semantic-segment` 的 project-native runtime，读取登记的 `sam3.1_multiplex.pt` 执行单图或多帧分割。视频节点使用 checkpoint 内正式 propagation 分支、固定 16 槽 bucket decoder、7 帧 memory 和最多 16 个 object pointer，不再维护 prototype、shared-prompt、stateful-mask 或启发式 memory-attention 跟踪模式。

## 适用范围

- `custom_nodes/yoloe_open_vocab_nodes`
- `custom_nodes/sam3_segment_nodes`
- `data/files/models/pretrained/yoloe`
- `data/files/models/pretrained/sam3`

## 核心结论

- `YOLOE` 和 `SAM3` 第一阶段都应作为 `custom node` 扩展能力接入，不直接并入当前核心模型主链。
- 大权重和附属模型资产继续统一放在 `data/files/models/pretrained/` 下，不放进 `custom_nodes/`。
- `YOLOE` 第一阶段先使用官方 segmentation 权重接 open vocabulary detection 节点，`SAM3` 第一阶段先从 image segmentation 起步，当前已扩到 video segmentation / tracking，但仍保持 custom node 边界。
- `YOLOE text-prompt` 第一阶段默认文本编码器固定为本地 `mobileclip_blt.ts`，并复用本地 `CLIP` tokenizer/BPE 资产。
- `YOLOE text-prompt` 当前支持同一 `prompt_id` 下多条 positive/negative 文本组合，运行时会先按 `prompt_id` 聚合，再生成单个类别原型。
- `YOLOE` 和 `SAM3` 在 workflow 中的第一阶段运行形态应为：`WorkflowAppRuntime` 进程内按需首次加载并缓存，runtime 停止时释放；不是每次调用重新加载，也不是一开始就做成正式 `DeploymentInstance` 常驻服务。当前 `YOLOE / SAM3` 都已经补了 CPU 会话缓存复用回归。
- `YOLOE` 第一阶段节点同时输出 `detections.v1` 和 `regions.v1`；`SAM3` 输出也应使用 `regions.v1`，不要硬塞进 `detections.v1`。

## 参考实现来源

### YOLOE

- `projectsrc/ultralytics/ultralytics/models/yolo/yoloe/predict.py`
- `projectsrc/ultralytics/ultralytics/nn/tasks.py`
- `projectsrc/ultralytics/ultralytics/nn/modules/head.py`
- `projectsrc/ultralytics/ultralytics/nn/modules/block.py`

### SAM3

- `projectsrc/ultralytics/ultralytics/models/sam/build_sam3.py`
- `projectsrc/ultralytics/ultralytics/models/sam/sam3/sam3_image.py`
- `projectsrc/ultralytics/ultralytics/models/sam/predict.py`

## 与现有模型主链的关系

### YOLOE

- 与现有 `YOLOv8/11/26` 有结构血缘关系，但不是当前核心 detection 主链里的同层正式模型分类。
- `text prompt`、`visual prompt`、`prompt-free` 是节点运行模式，不是三套独立平台模型分类。
- 官方当前提供的是 `-seg` 权重，它本质上是 open-vocabulary instance segmentation 模型。
- 第一阶段 custom node 先同时开放 detection 与 region 输出，既保留 bbox 结果，也把 mask/region 结果纳入正式 contract。
- 第一阶段不直接接训练、转换、`DeploymentInstance` 主链。

#### 为什么目录放在 segmentation，而节点先做 detection 输出

- 目录的 `task_type` 表达的是权重本身的真实属性，不是第一阶段节点的输出形式。
- 官方 `YOLOE` 预训练权重文件名就是 `*-seg.pt` / `*-seg-pf.pt`，对应的是 open-vocabulary instance segmentation 权重。
- 这些权重在一次前向里同时包含 bbox、score、label，以及可继续扩展使用的 mask 相关能力。
- 第一阶段 custom node 同时开放 detection 风格输出 `detections.v1` 与 region 风格输出 `regions.v1`，因为当前平台既需要稳定的开放词汇检测链，也需要把 segmentation 权重的原生结果接进节点边界。
- 因此：
  - 磁盘资产目录保持 `yoloe/segmentation/...`
  - 节点输出 contract 第一阶段同时提供 `detections.v1` 和 `regions.v1`
- 不能因为节点要兼容 detection 下游，就把官方 segmentation 权重误记成 detection 目录；那样会在后续扩充分割能力时造成理解混乱。

### SAM3

- 不属于现有 `yolo_primary segmentation` 的同层实现。
- `semantic` 和 `interactive` 是节点运行模式，不是两套独立权重目录。
- 第一阶段不直接接训练、转换、`DeploymentInstance` 主链。

## 磁盘资产放置规则

- 所有大权重、tokenizer、embedding 缓存和配置文件都放在 `data/files/models/pretrained/` 下。
- `custom_nodes/` 目录只放节点包源码、catalog、schema 和文档，不放大权重。
- `data/files/models/pretrained/` 属于本地数据目录，仓库只保留生成规则和维护命令，不把大权重和生成产物纳入源码提交。
- YOLOE 保持现有 Scale 目录规则，SAM3 直接使用资产变体目录：

```text
{root}/yoloe/{task_type}/{scale}/{variant}/manifest.json
{root}/yoloe/{task_type}/{scale}/{variant}/checkpoints/{file}
{root}/sam3/{task_type}/{variant}/manifest.json
{root}/sam3/{task_type}/{variant}/checkpoints/{file}
```

- YOLOE 继续使用统一 Scale 命名：
  - `nano`
  - `tiny`
  - `s`
  - `m`
  - `l`
  - `x`
  - `xx`
- 不再引入旧的 `n`。

### 共享文本编码器资产

`YOLOE text-prompt` 和 `SAM3` 第一阶段都应复用本地 `text-encoders` 资产目录，不再依赖外部 `clip` 或 `mobileclip` Python 包的在线安装和在线下载逻辑。

推荐目录如下：

```text
data/files/models/pretrained/
└─ text-encoders/
   ├─ clip/
   │  ├─ tokenizer/
   │  │  └─ bpe_simple_vocab_16e6.txt.gz
   │  └─ vit-b-32/
   │     └─ ViT-B-32.pt
   └─ mobileclip/
      └─ blt/
         └─ mobileclip_blt.ts
```

说明：

- `bpe_simple_vocab_16e6.txt.gz` 是共享 tokenizer 资产，`YOLOE text-prompt` 和 `SAM3` 都会使用。
- `mobileclip_blt.ts` 是 `YOLOE text-prompt` 第一阶段默认文本编码器。
- `ViT-B-32.pt` 当前不是 `YOLOE text-prompt` 默认链路的硬依赖，但作为后续支持 `clip:ViT-B/32` 的预留资产保留在本地目录中。
- `simple_tokenizer.py` 这类加载与编码逻辑属于项目代码，不属于磁盘模型资产。

## 官方权重名与项目目录的关系

- `YOLOE` 官方文档直接提供权重文件，例如：
  - `yoloe-v8s-seg.pt`
  - `yoloe-11s-seg.pt`
  - `yoloe-26n-seg.pt`
  - prompt-free 变体使用 `*-seg-pf.pt`
- `SAM3` 默认登记资产使用官方 `sam3.1_multiplex.pt`。

这里要分清两层：

- 权重文件名：尽量保持官方文件名不变，方便直接下载后放入目录
- 节点运行模式：`text prompt`、`visual prompt`、`semantic`、`interactive` 这些属于节点使用方式，不应全部编码进磁盘目录层级

因此第一阶段目录只对“真正需要不同权重的变体”做区分：

- `YOLOE default`
- `YOLOE prompt-free`
- `SAM3 default`
- 当前 `YOLOE prompt-free`、`YOLOE text-prompt`、`YOLOE visual-prompt` 都已经接通 project-native runtime；`YOLOE visual-prompt` 当前已开放 `box / point / polygon / mask` 四类提示。同一 `prompt_id` 只能表示同一种提示，其中 Point 可包含多个正负点；Box、Polygon、Mask 的 id 不允许重复。

## 第一阶段目录规则

### YOLOE

SAM3 不存在本项目可用的模型 Scale，资产目录直接按稳定变体名组织：

```text
data/files/models/pretrained/
└─ yoloe/
   └─ segmentation/
      ├─ s/
      │  ├─ v8-default/
      │  │  ├─ manifest.json
      │  │  └─ checkpoints/
      │  │     └─ yoloe-v8s-seg.pt
      │  ├─ v8-prompt-free/
      │  │  ├─ manifest.json
      │  │  └─ checkpoints/
      │  │     └─ yoloe-v8s-seg-pf.pt
      │  ├─ 11-default/
      │  │  ├─ manifest.json
      │  │  └─ checkpoints/
      │  │     └─ yoloe-11s-seg.pt
      │  └─ 11-prompt-free/
      │     ├─ manifest.json
      │     └─ checkpoints/
      │        └─ yoloe-11s-seg-pf.pt
      └─ nano/
         ├─ 26-default/
         │  ├─ manifest.json
         │  └─ checkpoints/
         │     └─ yoloe-26n-seg.pt
         └─ 26-prompt-free/
            ├─ manifest.json
            └─ checkpoints/
               └─ yoloe-26n-seg-pf.pt
```

说明：

- `v8-default` 和 `11-default` 供文本提示、视觉提示节点共用。
- `v8-prompt-free`、`11-prompt-free`、`26-prompt-free` 对应真正不同的 prompt-free 权重。
- `YOLOE` 的官方权重是 segmentation 权重。
- 第一阶段节点同时输出 `detections.v1` 和 `regions.v1`，这样既能直接接现有 detection 下游，也不会丢掉 segmentation 权重的原生 region 能力。
- 后续如果开放 `YOLOE` 的 mask 输出，同一批权重目录可以继续复用，不需要再换一套资产规范。
- 后续如果补 `m / l / x` 等其他官方权重，继续沿同一规则扩展，不另起新目录规范。

### SAM3

第一阶段先创建已确认的最小目录骨架：

```text
data/files/models/pretrained/
└─ sam3/
   └─ segmentation/
      └─ default/
         ├─ manifest.json
         └─ checkpoints/
            └─ sam3.1_multiplex.pt
```

说明：

- `semantic` 和 `interactive` 共用同一份 `sam3.1_multiplex.pt`，但运行时只实例化当前能力需要的分支：semantic 使用 `convs`，interactive 使用 `interactive_convs`。
- 单图节点不加载 `propagation_convs` 和 multiplex 的 bucketized 通用 decoder，避免无用权重增加显存，也避免把不同 decoder 协议混载。
- 当前 project-native 视频节点继续使用已声明的项目内逐帧或 memory 模式；不能把它描述成最新参考仓库的完整 multiplex video predictor。
- 如果后续出现新的正式上游权重，再按同一规则追加 variant。

### ComfyUI 兼容推理资产目录

`data/files/models/checkpoints/` 用于保存不参与训练、微调和平台 `ModelVersion` 登记的直接推理权重。例如：

```text
data/files/models/checkpoints/
└─ sam3.1_multiplex_fp16.safetensors
```

这个目录可以与 ComfyUI 的 checkpoint 放置习惯保持一致，但它与
`data/files/models/pretrained/` 的职责不同：

- `pretrained/` 是项目登记资产，必须有 manifest、稳定资产 id、SHA-256、能力和运行时架构声明。
- `checkpoints/` 是 ComfyUI 兼容的推理资产池，供后续通用 `Load Checkpoint` 类节点受控扫描，不作为训练产物或平台模型版本。
- 当前 SAM3 节点 manifest 不跨目录引用 `checkpoints/`；现有 project-native runtime 继续读取登记的 `.pt` 资产。
- `.safetensors` 文件应由专用 loader 使用 `safe_open` 或等价安全接口读取，并通过 sidecar 或本地索引声明模型家族、精度、能力和 SHA-256；不能仅凭文件名猜测架构。
- 节点只能使用资产 provider 返回的稳定 id，不接受任意磁盘绝对路径。
- `projectsrc/sam3` 只用于核对最新参考实现，不得成为运行时 import 或响应字段来源。

当前 `sam3.1_multiplex_fp16.safetensors` 与登记的 `.pt` 属于同一模型家族：
它保留 multiplex 参数，但省略可重建的 RoPE `freqs_cis` 等 buffer。未来
ComfyUI 兼容 loader 必须在模型构造后恢复这些 buffer，再按 capability
选择分支；不能直接复用现有 `.pt` loader。

## manifest.json 最低字段

`YOLOE` 与 `SAM3` 都使用项目现有的预训练目录 `manifest.json` 约定，不引入新的 `variant.json`。两者的模型标识字段不同：YOLOE 使用真实的 `model_scale`，SAM3 使用 `model_asset_id` 和 `architecture_id`。

最低字段如下：

- `model_name`
- YOLOE：`model_scale`
- SAM3：`model_asset_id`、`architecture_id`、`checkpoint_sha256`
- `task_type`
- `model_version_id`
- `checkpoint_file_id`
- `checkpoint_path`
- `metadata`

### 字段说明

| 字段 | 说明 |
| --- | --- |
| `model_name` | 预训练模型系列名，例如 `yoloe-v8`、`yoloe-11`、`yoloe-26`、`sam3.1` |
| `model_scale` | 仅用于确实存在 Scale 的 YOLOE，例如 `nano`、`s`、`l` |
| `model_asset_id` | SAM3 稳定资产 id，例如 `sam3/default` |
| `architecture_id` | SAM3 运行时架构 id，例如 `sam3.1-multiplex.vision-1008.v1` |
| `checkpoint_sha256` | SAM3 checkpoint 完整性校验值 |
| `task_type` | `YOLOE` 与 `SAM3` 第一阶段都固定写 `segmentation` |
| `model_version_id` | 预训练目录的稳定 `ModelVersion` id |
| `checkpoint_file_id` | 预训练 checkpoint 的稳定文件 id |
| `checkpoint_path` | 相对 `manifest.json` 的 checkpoint 路径 |
| `metadata.catalog_name` | 当前目录使用的变体名 |
| `metadata.entry_name` | 当前条目显示名 |
| `metadata.source` | 当前来源，建议固定写 `local-pretrained` |
| `metadata.upstream_weight_name` | 官方权重文件名 |
| `metadata.upstream_mode` | 官方或项目约定的权重模式，例如 `default`、`prompt-free` |

### YOLOE manifest.json 示例

```json
{
  "model_name": "yoloe-v8",
  "model_scale": "s",
  "task_type": "segmentation",
  "model_version_id": "mv-pretrained-yoloe-v8-segmentation-s",
  "checkpoint_file_id": "mf-pretrained-yoloe-v8-segmentation-s-checkpoint",
  "checkpoint_path": "checkpoints/yoloe-v8s-seg.pt",
  "metadata": {
    "catalog_name": "v8-default",
    "entry_name": "v8-default",
    "source": "local-pretrained",
    "upstream_weight_name": "yoloe-v8s-seg.pt",
    "upstream_mode": "default"
  }
}
```

### SAM3 manifest.json 示例

```json
{
  "model_name": "sam3.1",
  "model_version": "sam3.1_multiplex",
  "model_asset_id": "sam3/default",
  "architecture_id": "sam3.1-multiplex.vision-1008.v1",
  "task_type": "segmentation",
  "model_version_id": "mv-pretrained-sam3-1-multiplex-segmentation-default",
  "checkpoint_file_id": "mf-pretrained-sam3-1-multiplex-segmentation-default-checkpoint",
  "checkpoint_path": "checkpoints/sam3.1_multiplex.pt",
  "checkpoint_sha256": "<sha256>",
  "metadata": {
    "catalog_name": "default",
    "entry_name": "default",
    "source": "local-pretrained",
    "upstream_weight_name": "sam3.1_multiplex.pt",
    "upstream_mode": "multiplex",
    "runtime_scope": "workflow-app-isolated-multiplex"
  }
}
```

## 与当前预训练自动登记链的关系

- 当前核心平台自动扫描并登记的预训练目录仍然是 `yolox / yolov8 / yolo11 / yolo26 / rfdetr`。
- `YOLOE` 和 `SAM3` 第一阶段只是 custom node 使用的中心化磁盘资产，不进入当前核心模型自动登记链。
- 也就是说，本文件定义的是“节点运行时如何找权重”，不是“当前平台把它们当正式核心模型分类管理”。
- 如果需要批量校验和重生这两类目录的 `manifest.json`，统一通过 `python -m backend.maintenance.main sync-extension-pretrained-manifests` 执行。

## 第一阶段 payload 规则

第一阶段先固定三种扩展 payload 规则：

- `text-prompts.v1`
- `prompt-regions.v1`
- `regions.v1`

### text-prompts.v1

用途：

- `YOLOE` 文本提示检测
- `SAM3` 语义分割

最小字段建议：

- `items`
- 每项包含：
  - `prompt_id`
  - `text`
  - `display_name`
- 可选：
  - `language`
  - `negative`

运行时约定：

- 同一 `prompt_id` 可出现多条记录。
- `negative=false` 的文本会作为 positive 文本集合。
- `negative=true` 的文本会作为 negative 文本集合。
- `YOLOE text-prompt` 会先按 `prompt_id` 聚合，再把 positive 文本均值作为主方向，并把 negative 文本作为抑制项并入同一个类别原型。
- `SAM3 semantic-segment` 当前也采用同样的 grouped positive/negative 语义：同一 `prompt_id` 至少要有一条 positive 文本，negative 文本会作为抑制项并入同一个语义原型。

### prompt-regions.v1

用途：

- `YOLOE` 视觉提示检测
- `SAM3` 交互分割

最小字段建议：

- `source_image`
- `items`
- 每项包含：
  - `prompt_id`
  - `prompt_kind`
  - `point_xy`
  - `point_label`
  - `bbox_xyxy`
  - `polygon_xy`
  - `mask_image`

说明：

- `prompt_kind` 允许：
  - `point`
  - `box`
  - `polygon`
  - `mask`
- `mask_image` 建议继续复用 `image-ref.v1`，不要把整张 mask 内联到 JSON。
- 同一 `prompt_id` 表示同一个对象，不能混合不同 `prompt_kind`。
- Point 可以使用多条相同 `prompt_id` 记录表达多个 Positive/Negative 点，并且至少包含一个 Positive 点。
- YOLOE 将同一对象的 Positive Point 合并为前景提示，并用 Negative Point 从提示区域中排除背景；SAM3 将这些点作为同一个对象的一组稀疏提示送入 Prompt Encoder。
- Box、Polygon、Mask 的 `prompt_id` 必须唯一。
- `source_image` 记录提示创建时的参考图；参考图内容或尺寸变化后，YOLOE 和 SAM3 都必须拒绝旧提示。

### regions.v1

用途：

- `SAM3` 输出
- 后续也可给其他 region/mask 类扩展节点复用

最小字段建议：

- `source_image`
- `count`
- `items`
- 每项包含：
  - `region_id`
  - `score`
  - `class_name`
  - `bbox_xyxy`
  - `polygon_xy`
  - `mask_image`
  - `area`

说明：

- `mask_image` 建议继续使用 `image-ref.v1`
- `polygon_xy` 供独立预览节点、结果导出节点和规则节点复用

## 节点输入输出 contract

### YOLOE

- `custom.yoloe.text-prompt-detect`
  - 输入：`image-ref.v1`、`text-prompts.v1`
  - 输出：`detections.v1`、`regions.v1`、`value.v1`
- `custom.yoloe.visual-prompt-detect`
  - 输入：`image-ref.v1`、`image-ref.v1(prompt_image)`、`prompt-regions.v1`
  - 输出：`detections.v1`、`regions.v1`、`value.v1`
- `custom.yoloe.prompt-free-detect`
  - 输入：`image-ref.v1`
  - 输出：`detections.v1`、`regions.v1`、`value.v1`

### SAM3

- `custom.sam3.semantic-segment`
  - 输入：`image-ref.v1`、`text-prompts.v1`
  - 输出：`regions.v1`、`value.v1`
- `custom.sam3.interactive-segment`
  - 输入：`image-ref.v1`、`prompt-regions.v1`
  - 输出：`regions.v1`、`value.v1`
- `custom.sam3.video-interactive-segment`
  - 输入：`frame-window.v1`、`prompt-regions.v1`
  - 输出：`tracks.v1`、`value.v1`
- `custom.sam3.video-semantic-segment`
  - 输入：`frame-window.v1`、`text-prompts.v1`
  - 输出：`tracks.v1`、`value.v1`

说明：

- `interactive-segment` 当前已经接通 project-native runtime。
- 当前阶段支持 `box`、`point`、`polygon`、`mask` prompt。
- `semantic-segment` 当前也已接通 project-native runtime。
- `semantic-segment` 当前支持按 `prompt_id` 聚合的 `text-prompts.v1`，同组内可混合 positive/negative 文本。
- `video-interactive-segment` 使用 Interactive 首帧提示生成 mask 与 object pointer，后续帧由 Multiplex propagation 传播。
- `video-semantic-segment` 使用 Semantic 首帧生成候选 mask，再经 Interactive 分支生成训练一致的 object pointer，后续帧进入同一 Multiplex propagation。
- `track_id` 稳定映射为 `prompt_id`；传播链路固定，不提供启发式模式选择参数。

### 旧视频模式说明（已删除，不得作为当前实现依据）

以下 prototype、shared-prompt、stateful-mask 和启发式 memory-attention 内容仅记录早期原型取舍。当前 Catalog、节点参数、运行时代码和测试均不再包含这些模式；当前实现依据统一以 [SAM3 自定义节点规划](sam3-custom-node-plan.md) 为准。

`SAM3` 当前的单帧与多帧能力是分层存在的，实际编排时应按任务复杂度选择，而不是默认一律走最重模式。

#### 1. 单帧任务优先使用 `interactive-segment`

适用情况：

- 只需要处理单张图
- 只需要对一张大图中的某个目标做交互分割
- workflow 中只是偶尔从视频窗口里抽一帧做人机交互修正

优点：

- 最简单
- 推理链最短
- 调试最直接

#### 2. 短窗口或变化很小的视频，可直接使用 `video-interactive-segment + shared-prompts-across-window`

适用情况：

- 每帧变化很小
- 相机基本固定
- 只是想把同一组 prompt 在窗口内逐帧重复执行

优点：

- 行为最接近“把单帧节点批量套到多帧上”
- 易理解、易排障

限制：

- 不利用历史状态
- 遮挡和形变下更容易丢目标

#### 3. 中等复杂度视频，可使用 `stateful-mask-propagation`

适用情况：

- 目标有连续位移
- 需要把上一帧 mask 当作下一帧提示
- 但还不需要更复杂的对象记忆

优点：

- 比 shared prompt 更稳
- 成本比更完整记忆跟踪低

限制：

- 更依赖上一帧轮廓
- 遮挡、形变和大位移下仍然容易漂移

#### 4. 当前默认推荐模式是 `memory-prototype-state`

适用情况：

- 目标存在中大位移
- 外观有一定变化
- 需要在多帧里更稳地延续同一个对象

当前实现：

- 保存对象原型特征
- 保存最近若干帧 low-res mask 历史
- 在当前帧特征上生成 memory prompt，再驱动分割

优点：

- 明显强于 shared prompt 和单纯 mask 回灌
- 仍然保持 project-native、可控和可调试

#### 5. 更复杂的视频跟踪，可切到 `memory-attention-tracker`

适用情况：

- 长时跟踪
- 遮挡后重现
- 多目标并行且变化复杂
- 需要更接近 upstream 视频版 `SAM3` 的底层时序能力

说明：

- 当前实现会为对象保存跨帧 token memory、mask history 和 prototype，再在当前帧低分辨率特征上做 attention 风格的对象检索
- 相比 `memory-prototype-state`，这一层更适合更长窗口、更大位移和更复杂遮挡
- 代价是推理更重、调参与回归成本更高，只有在默认模式不足时再选用

推荐参数面：

- `history_limit`
  - 控制跨帧保留多少条历史记忆
  - 默认留空时当前模式使用 `6`
- `prototype_momentum`
  - 控制对象 prototype 的平滑程度
  - 现场常用范围：`0.65 ~ 0.8`
- `attention_temperature`
  - 控制 attention 响应的尖锐程度
  - 现场常用范围：`0.08 ~ 0.18`
- `prototype_blend_weight`
  - 控制 prototype 相似图和 token memory 的融合强度
  - 现场常用范围：`0.25 ~ 0.45`
- `max_memory_tokens_per_entry`
  - 控制每帧最多保留多少对象 token
  - 现场常用范围：`128 ~ 384`

现场样例 workflow：

- [docs/examples/workflows/sam3_video_multiplex_review.template.json](../examples/workflows/sam3_video_multiplex_review.template.json)
- [docs/examples/workflows/sam3_video_multiplex_review.application.json](../examples/workflows/sam3_video_multiplex_review.application.json)

这套样例固定使用：

- `video-load-local -> video-decode-frames -> custom.sam3.video-interactive-segment(memory-attention-tracker) -> tracks-filter -> video-overlay-render -> video-save -> video-body`

适用情况：

- 本地磁盘视频复盘
- 遮挡后重现
- 更长窗口和更大位移
- 多目标跟踪调试

### `video-semantic-segment` 旧边界记录（已由 Multiplex propagation 替代）

当前 `video-semantic-segment` 只提供：

- `shared-text-prompts-across-window`

这表示：

- 同一组 `text-prompts.v1` 会直接作用到整个 `frame-window.v1`
- 当前不会自动把上一帧 region 或 mask 作为下一帧语义状态继续传播
- 当前更偏向“逐帧共享同一组语义提示”的稳定实现，而不是完整时序语义 tracker

这条边界是有意保留的。当前现场以单帧判定和视频复盘为主时，`shared-text-prompts-across-window` 通常已经够用，也更容易解释和排障。

后续如果现场明确需要“语义区域跨帧稳定性”，再考虑按下面顺序增强：

1. `stateful-semantic-propagation`
- 基于上一帧 region 或 mask，把语义区域延续到下一帧
- 适合中等复杂度的视频语义稳定任务

2. `memory-prototype` 风格 semantic 视频模式
- 再进一步为语义目标维护跨帧 prototype / state
- 只在 `stateful-semantic-propagation` 仍不足时才考虑

典型工业场景：

- 点胶区域连续覆盖监控
- 涂层、涂胶、焊缝、密封条等连续工艺区域分割
- 液面、料面、泡沫区域等需要跨帧稳定面积统计的场景

如果现场主要还是单帧抓拍、单张复盘或只是用视频做结果回放，则当前不必优先实现 `stateful-semantic-propagation`。

## 运行形态约定

### preview run

- 单次执行
- 使用稳定的应用级 preview scope；Load Checkpoint 配置未变化时复用同一模型 owner

### WorkflowAppRuntime

- runtime 进程长期运行
- 模型会话应在当前 runtime 进程内按需首次加载并缓存
- runtime 停止时统一释放
- 不做跨 runtime 共享

### DeploymentInstance

- 第一阶段不作为 `YOLOE` 和 `SAM3` 的默认接入方式
- 只有当输入输出语义、现场调用模式和资源占用都稳定后，才考虑把某个固定变体提升为正式长期运行推理服务

## 第一阶段不做的事

- 不把 `YOLOE` 和 `SAM3` 并入当前核心模型训练、转换、`DeploymentInstance` 主链
- 不做 workflow app 文档或旧模板修补
- 不在节点中内置预览、overlay 或 debug 叠图逻辑
- 不实现直播流和跨 AppRuntime 共享；视频传播只在当前 AppRuntime 和单次节点执行的请求状态内运行
- 不在第一阶段接 `YOLOE segmentation`

## 后续实现顺序

1. 固定本文件中的磁盘资产规则、`manifest.json` 字段和 payload 规则
2. 先做 `YOLOE custom node`
3. 再做 `SAM3 custom node`
4. 运行边界稳定后，再评估是否把某些固定变体提升为正式长期运行服务
