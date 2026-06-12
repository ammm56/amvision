# Postman 本地调试数据包

full-chain Postman collection 默认把 `datasetZipPath` 指到本地目录 `data/files/postman-assets/`。

这个目录用于放最小联调数据包，不放在 `docs/` 下，也不纳入 git。

当前约定文件名：

- `detection-coco-min.zip`
- `segmentation-coco-min.zip`
- `classification-imagenet-min.zip`
- `pose-coco-keypoints-min.zip`
- `obb-dota-min.zip`

这些 zip 只用于接口联调、参数验证和最小回归，不代表真实训练质量。

`detection-coco-min.zip` 同时被 `detection-full-chain.postman_collection.json` 和 `docs/api/postman/workflows/01-detection-end-to-end-qr-crop-remap/` 复用。

这些文件都按本地联调资产处理，需要手动放到 `data/files/postman-assets/`，不纳入 git。
