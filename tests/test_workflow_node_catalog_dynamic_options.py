"""workflow node catalog 动态枚举选项测试。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.service.api.rest.v1.routes.workflows import node_catalog_helpers


class _FakeCudaRuntime:
    """提供测试所需的最小 CUDA runtime 接口。"""

    def __init__(self, *, available: bool, names: tuple[str, ...], bf16: bool) -> None:
        self._available = available
        self._names = names
        self._bf16 = bf16

    def is_available(self) -> bool:
        """返回 CUDA 是否可用。"""

        return self._available

    def device_count(self) -> int:
        """返回 CUDA 设备数。"""

        return len(self._names)

    def get_device_name(self, device_index: int) -> str:
        """返回指定 CUDA 设备名称。"""

        return self._names[device_index]

    def is_bf16_supported(self) -> bool:
        """返回 BF16 是否可用。"""

        return self._bf16


def test_dynamic_torch_options_only_expose_cpu_without_cuda(monkeypatch) -> None:
    """验证无 CUDA 环境不会显示不可执行的设备和精度。"""

    fake_torch = SimpleNamespace(
        cuda=_FakeCudaRuntime(available=False, names=(), bf16=False)
    )
    monkeypatch.setattr(node_catalog_helpers, "_try_import_torch", lambda: fake_torch)

    device_options = node_catalog_helpers._build_torch_device_options()
    precision_options = node_catalog_helpers._build_torch_precision_options()

    assert [item.value for item in device_options] == ["auto", "cpu"]
    assert [item.value for item in precision_options] == ["auto", "fp32"]


def test_dynamic_torch_options_expose_real_cuda_capabilities(monkeypatch) -> None:
    """验证 CUDA 设备名称和支持的精度会进入下拉选项。"""

    fake_torch = SimpleNamespace(
        cuda=_FakeCudaRuntime(
            available=True,
            names=("NVIDIA RTX A", "NVIDIA RTX B"),
            bf16=True,
        )
    )
    monkeypatch.setattr(node_catalog_helpers, "_try_import_torch", lambda: fake_torch)

    device_options = node_catalog_helpers._build_torch_device_options()
    precision_options = node_catalog_helpers._build_torch_precision_options()

    assert [item.value for item in device_options] == [
        "auto",
        "cpu",
        "cuda:0",
        "cuda:1",
    ]
    assert device_options[2].label == "CUDA 0 · NVIDIA RTX A"
    assert [item.value for item in precision_options] == [
        "auto",
        "fp32",
        "fp16",
        "bf16",
    ]


def test_dynamic_sam3_options_only_expose_installed_assets(monkeypatch) -> None:
    """验证 SAM3 模型选项来自已安装资产扫描结果。"""

    fake_module = SimpleNamespace(
        list_sam3_pretrained_variants=lambda: (
            SimpleNamespace(
                model_asset_id="sam3/default",
                model_name="sam3",
            ),
            SimpleNamespace(
                model_asset_id="sam3/industrial-a",
                model_name="sam3-industrial",
            ),
        )
    )
    monkeypatch.setattr(
        node_catalog_helpers.importlib,
        "import_module",
        lambda _module_name: fake_module,
    )

    options = node_catalog_helpers._build_sam3_model_asset_options()

    assert [item.value for item in options] == [
        "sam3/default",
        "sam3/industrial-a",
    ]
    assert options[1].label == "sam3-industrial · sam3/industrial-a"
