"""可公开的校验规则白名单；不读取异常文本、输入值或校验上下文。"""

PUBLIC_VALIDATION_MESSAGES: dict[str, tuple[str, tuple[str, ...]]] = {
    "yolox_warmup_epochs_invalid": (
        "YOLOX warmup_epochs 必须小于 max_epochs，请减少 Warmup 轮数或增加总轮数",
        ("body", "parameters", "optimization", "warmup_epochs"),
    ),
    "yolox_epoch_schedule_invalid": (
        "YOLOX warmup_epochs + no_aug_epochs 必须小于 max_epochs，请减少 Warmup/no-aug 轮数或增加总轮数",
        ("body", "parameters", "optimization", "no_aug_epochs"),
    ),
    "training_range_order_invalid": ("范围最小值不能大于最大值", ()),
}
