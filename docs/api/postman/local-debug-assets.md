# Postman 本地调试数据包

各个 Postman collection 默认都把 `datasetZipPath` 指到本地目录 `data/files/postman-assets/`。

这个目录用于放最小联调数据包，不放在 `docs/` 下，也不纳入 git。

当前约定文件名：

- `detection-coco-min.zip`
- `detection-yolo-min.zip`
- `segmentation-coco-min.zip`
- `segmentation-yolo-min.zip`
- `classification-imagenet-min.zip`
- `pose-coco-keypoints-min.zip`
- `pose-yolo-min.zip`
- `obb-dota-min.zip`
- `obb-yolo-min.zip`

这些 zip 只用于接口联调、参数验证和最小回归，不代表真实训练质量。

这些 zip 只是建议文件名，不是固定规则。真实联调时，直接把 `datasetZipPath` 改成当前要传的本地 zip 路径即可。

这些文件都按本地联调资产处理，需要手动放到 `data/files/postman-assets/`，不纳入 git。
