# Postman 本地调试数据包

non-detection full-chain Postman collection 默认把 `datasetZipPath` 指到本地目录 `data/files/postman-assets/`。

这个目录用于放最小联调数据包，不放在 `docs/` 下，也不纳入 git。

当前约定文件名：

- `segmentation-coco-min.zip`
- `classification-imagenet-min.zip`
- `pose-coco-keypoints-min.zip`
- `obb-dota-min.zip`

这些 zip 只用于接口联调、参数验证和最小回归，不代表真实训练质量。
