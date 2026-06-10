# 10 Industrial Single Frame Glue ROI Delivery Bundle 调试说明

## 文档目的

本目录用于说明 `10-industrial-single-frame-glue-roi-delivery-bundle.postman_collection.json` 的实际导入、改值和联调顺序。

这组请求对应一条更贴近现场交付面的工业单帧闭环：

- 保存 workflow template
- 保存 workflow application
- 先用 preview/runtime 做规则链联调
- 再观察 PLC 信号写入、JSON/CSV 归档、MES 请求准备和 local-db upsert 是否都按预期收口

## 导入后先改的变量

- `baseUrl`：FastAPI 服务地址，默认是 `http://127.0.0.1:8000`
- `projectId`：目标项目 ID
- `accessToken`：本地用户 token

## 导入后先改的请求体字段

以下字段通常需要按现场机器改成真实值：

- `preview-run.request.json`、`app-runtime.invoke.request.json`、`app-runtime.run.create.request.json` 里的 `request_image_path`
- 上述三个请求里的 `request_regions`
- 上述三个请求里的 `request_roi`
- 上述三个请求里的 `request_delivery_context`
- 上述三个请求里的 `request_signal_write.host`
- 上述三个请求里的 `request_signal_write.unit_id`
- 上述三个请求里的 `request_signal_write.signal_values.*`

如果需要联调 local-db upsert，先执行 [docs/examples/workflows/industrial_single_frame_glue_roi_delivery_bundle.sqlite.sql](../../../examples/workflows/industrial_single_frame_glue_roi_delivery_bundle.sqlite.sql) 准备本地 SQLite 表结构。

默认模板中的 MES 地址、JSON/CSV 保存路径和 local-db 连接参数都只是现场占位值。第一次联调建议先确认“准备出的结果对象和请求摘要”是否正确，再接入真实外部系统。

## 推荐联调顺序

### 1. 先保存图和应用

按下面顺序执行：

- `Save Template`
- `Save Application`

这一步只验证 template/application 合同和图绑定关系。

### 2. 先做图级 dry run

按下面顺序执行：

- `Create Preview Run`
- `Get Preview Run`

这一步最适合先确认：

- `request_regions` 输入形状是不是正确
- `request_roi` 和面积/覆盖率/偏移规则是不是对
- `request_delivery_context` 是否完整进入结果对象
- `request_signal_write` 是否成功生成现场写入摘要

### 3. 启动正式 runtime

按下面顺序执行：

- `Create App Runtime`
- `Start App Runtime`
- `Get App Runtime Health`

只有这一步通过，后面的同步 invoke 和异步 run 才有共同宿主。

### 4. 先跑同步 invoke

执行：

- `Invoke App Runtime`

这一步最适合检查完整交付输出是否成型，重点关注：

- `inspection_result`
- `signal_write_summary`
- `json_summary`
- `csv_summary`
- `mes_prepared_request`
- `local_db_prepared_row`

### 5. 再跑 async workflow run

按下面顺序执行：

- `Create Workflow Run`
- `Get Workflow Run`

这一步用于确认正式异步执行入口下，输出结构和同步 invoke 保持一致。

### 6. 调试完成后收尾

执行：

- `Stop App Runtime`

## 现场联调建议

- 第一次联调建议先把 PLC/MES/local-db 都当作“结果准备对象”来看，不要一上来就接真实写入。
- 如果规则链本身还在调整，优先盯 `inspection_result.metrics`、`inspection_result.conditions` 和 `inspection_result.reasons`。
- 如果规则已经稳定，再逐步核对 `signal_write_summary`、`json_summary`、`csv_summary`、`mes_prepared_request`、`local_db_prepared_row` 这几类结果出口。
