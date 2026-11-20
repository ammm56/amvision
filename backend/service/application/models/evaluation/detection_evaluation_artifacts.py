"""Detection 评估内部存储键。"""


def failed_sample_images_key(detections_key: str) -> str:
    """返回与公开检测快照同目录的内部失败样本图片索引键。"""
    return f"{detections_key}.failed-images.json"
