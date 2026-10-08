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

目前 `connector.nodes` 默认禁用。Layout 中选择诊断 PIN、启用 Debug Preview 后重新预览，可查看剖面和逐线边缘证据；修改配置后旧诊断失效。Items 可使用显式连接的 PIN 布局，在参考图上设置方向/截面。App Mode 默认只启用图片面板，结果通过 Value Display 连线叠加，不重复生成独立结果卡。

工程验证及现场计量门禁见 [验证记录](../../development/connector-implementation-validation.md) 和 [实施基线](../../development/connector-inspection-2d.md)。

## 自动验证

```powershell
conda activate amvision
python -m pytest tests/test_connector_example_workflows.py tests/test_connector_runtime_api.py -q
```

测试使用隔离 ObjectStore 和独立 Runtime 进程；不会修改治具或塑盒应用。Preview/Snapshot 的同图同结果测试位于 `tests/test_connector_nodes.py`。
