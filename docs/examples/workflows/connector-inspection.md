# 二维连接器工程 Workflow

示例通过参考原图构建配方，待检缺陷图片不参与配方或阈值生成。输出仅用于工程验证；理想正交投影比例不能作为真实相机标定。

## 生成

先按 [开发资源说明](../../development/connector-development-assets.md) 准备资源。以下命令使用独立资源目录，不修改现有客户应用或生产计数：

```powershell
conda activate amvision
python -m scripts.connector_assets.workflow --assets data/development/connector-inspection/synthetic-v1 --storage-root data/development/connector-inspection/workflow-examples/store --output-dir data/development/connector-inspection/workflow-examples/single10_front --project-id connector-engineering --family single10_front
python -m scripts.connector_assets.workflow --assets data/development/connector-inspection/synthetic-v1 --storage-root data/development/connector-inspection/workflow-examples/store --output-dir data/development/connector-inspection/workflow-examples/dual08_top --project-id connector-engineering --family dual08_top
```

每组输出 Template JSON、Application JSON、定位模板 ZIP 和平面标定 ZIP。资源库与工作流 JSON 引用一一对应。资源导入另一 Project 后会获得新的资源 ID；必须在 Rigid Locate 和 Connector Measure 参数中重新选择导入的版本。参考图内容 hash 保持不变，PIN Layout 使用相同 reference_id/hash。不能直接复制引用路径冒充导入成功。

## 编排

```text
Image → Rigid Locate → Pin Array Locate → Connector Measure
                          checks ─┐              measurements
                                 └→ Merge Numeric Tables → Check Limits → Value Display
Image ─────────────────────────────────→ Draw Measurements → Image Preview
                                                annotations ↑    ↑ presentation
                                                   Connector     Value Display
                                                   Measure
```

实际图中 Check Limits.summary 同时作为公开结果，Draw Measurements.image 连接 Image Preview.image，Value Display.body 连接 Image Preview.presentation。只有显式连接才在图片上显示结果。

- 单排 10 PIN、双排各 8 PIN；节距 2.54 mm、宽度 0.64 mm 为合成工程模型名义值。
- 检查项包含存在性、配置带内额外候选、宽度、偏移、相邻节距、间隙及每排总节距。
- 候选带检查明确范围内符合所选采样类型的边缘对，不是任意外观异常检测。
- Length、Angle 算法有独立图像/几何测试；示例模板不默认打开不可见端点尺寸。
- 无工件时输出 NG 和本次原图；缺失项的 value 为 null，不使用旧值或名义值补齐。
- 示例不包含 Image Save、Append JSONL 等保存节点。需要保存时由实际 Workflow 显式添加。

## 使用

在隔离工程 Project 中启用 `opencv.nodes` 和开发包 `connector.nodes`，先导入两种资源，再通过既有 Workflow 文档导入入口载入示例，重新选择资源引用后保存。正常、旋转、缺针、多针和无工件图片分别位于开发资源 `images` 目录。预览调试通过后使用原有发布、Runtime 和 Trigger 入口。

`connector.nodes` 已为开发环境的工程应用启用。Layout 中选择诊断 PIN、启用 Debug Preview 后重新预览，可查看剖面和逐线边缘证据；修改配置后旧诊断失效。Items 可使用显式连接的 PIN 布局，在参考图上设置方向/截面。App Mode 默认只启用图片面板，结果通过 Value Display 连线叠加，不重复生成独立结果卡。

工程验证及现场计量门禁见 [验证记录](../../development/connector-implementation-validation.md) 和 [实施基线](../../development/connector-inspection-2d.md)。

## 自动验证

```powershell
conda activate amvision
python -m pytest tests/test_connector_example_workflows.py tests/test_connector_runtime_api.py -q
```

测试使用隔离 ObjectStore 和独立 Runtime 进程；不会修改治具或塑盒应用。Preview/Snapshot 的同图同结果测试位于 `tests/test_connector_nodes.py`。

## 已创建的开发应用（2026-10-08）

当前开发服务的默认项目 `project-1` 已保存、校验并发布以下应用。通过应用列表按名称打开，不需要重新导入。原有客户应用、Runtime、Trigger 和生产计数未修改。

| 应用 | 应用 ID | 使用阶段 |
| --- | --- | --- |
| 连接器 · 相机标定准备 | `workflow-app-connector-camera-setup` | 读取 12 张棋盘，求相机内参与逐视图误差 |
| 连接器 · 平面标定准备 | `workflow-app-connector-plane-setup` | 50 个拟合点、4 个独立验证点，检查毫米映射误差 |
| 连接器 · 单排10针检测 | `workflow-app-connector-single10` | 每次输入单排原图，39 个尺寸项、51 个规则项 |
| 连接器 · 双排16针检测 | `workflow-app-connector-dual16` | 每次输入双排原图，62 个尺寸项、81 个规则项 |
| 连接器 · 单排10针检测 · 设计空位 | `workflow-app-connector-single10-empty` | R1P05 必须为空；误插为 NG |
| 连接器 · 双排16针检测 · 设计空位 | `workflow-app-connector-dual16-empty` | R1P05 必须为空；误插为 NG |

两个满针检测 Runtime 保持运行，便于应用模式直接测试。标定和设计空位 Runtime 测试后已停止，可随时从应用详情启动；编辑器预览不要求 Runtime 启动。

### 操作步骤

1. 标定准备应用直接点击预览，读取 `synthetic-v1/calibration` 中已配置的 12 张图片。棋盘为 9×6 内角点、2 mm 格长、1280×800；平面标定误差上限 0.02 mm。
2. 检测应用使用已导入项目资源库的定位模板及平面标定固定版本。打开 Rigid Locate 的 Template、Pin Array Locate 的 PIN Layout、Connector Measure 的 Items / Calibration、Check Limits 的 Rules，可查看与修改配方。
3. 选中原图输入节点，从 `synthetic-v1/images` 上传相应产品族图片，再点击预览。公开 `image` 输入为必需，不提供参考图回退。节点组按“原图输入 → 工件定位 → PIN 检查 → 尺寸测量 → 公差判定 → 结果显示”排列。
4. Image Preview 左上角显示本次 OK/NG、检查项数和合格项数。两项数量是规则检查数量，不是物料产量。双击图片后大图保留同次叠加。逐项尺寸及有效性、逐项判定另有 Value Preview，用于编辑调试。
5. Runtime 应用模式可直接上传原图执行；外部系统通过既有同步调用接口传入 `image`，读取 `output_result.value.passed`、`output_measurements.value` 和 `output_image`。不增加队列、自动重试或硬件驱动。

图像只绘制测量图形，避免数十个尺寸文字挤在同一截面上；完整数值保留在结果中。示例没有隐式保存图片或生产计数节点。

### 配方边界

- 棋盘使用针孔成像，连接器图片使用理想正交成像。两者不是同一相机工况，不能直接交叉套用标定。检测应用当前使用已导入的合成正交映射；真实工位需要换成该工位的标定资源。
- 满针与设计空位是不同物料配方。`designed_empty` 和 `empty_occupied` 必须使用设计空位应用；保留原编号及空位检查，排除不存在的针所关联的尺寸检查。不根据待检结果自动推断产品类型。
- 透视图片超出当前刚性定位配方工况，本次均拒绝为 NG；不能据此宣称已支持透视测量。
- 3 张临界宽度图片的像素测量值越过 0.69 mm 上限，与合成名义标注不一致。保留 NG 和测量值，不改变公差以迎合标签；详见验证记录。这些应用可用于工程开发测试，不能据此通过实物计量验收。

后续已修复已知 sRGB 合成输入的光度边缘问题，新生成配方显式设置 `Image Encoding=srgb` 和按采样类型配置的相对梯度门限，上述 3 张样本在原公差下通过，0.70 mm 外侧样本仍为 NG。历史已安装应用不被自动覆盖；更新后的开发验证应用为 `workflow-app-connector-single10-usability` 与 `workflow-app-connector-dual16-usability`。具体数值、残余误差及发行验证见[后续修复](../../development/connector-usability-implementation.md#临界误差与后台回收的后续修复)。

### 导出与复现

项目资源版本引用、应用/版本/Runtime ID 保存在 `data/development/connector-inspection/installed-workflows/installation.json`。同目录包含六个完整前端可导入文档及实际测试记录。开发数据目录不进入 Git；构建逻辑在 `scripts/connector_assets/applications.py`。

```powershell
conda activate amvision
python -m scripts.connector_assets.applications --assets data/development/connector-inspection/synthetic-v1 --examples data/development/connector-inspection/workflow-examples --installation data/development/connector-inspection/installed-workflows/installation.json --output data/development/connector-inspection/installed-workflows
```

该命令只导出当前文档，不修改服务。另一项目必须先导入资源并提供相应的安装清单，不能沿用旧项目资源 ID。相机标定输入是明确的本地文件路径，迁移目录后需更新 Image List Local / Load Local Image 参数。
