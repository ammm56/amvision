"""RF-DETR core 导出处理模块：`export._onnx.exporter`。"""

import json
import os
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from os import PathLike

import numpy as np
import torch

try:
    import onnx
    from onnx import shape_inference
except ImportError:
    onnx = None  # type: ignore[assignment]
    shape_inference = None  # type: ignore[assignment]

try:
    import onnx_graphsurgeon as gs
    from onnx_graphsurgeon.logger.logger import G_LOGGER
except ImportError:
    gs = None  # type: ignore[assignment]
    G_LOGGER = None  # type: ignore[assignment]

try:
    from polygraphy.backend.onnx.loader import fold_constants
except ImportError:
    fold_constants = None  # type: ignore[assignment]

from backend.service.application.models.rfdetr_core.export._onnx.symbolic import (
    CustomOpSymbolicRegistry,
)
from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def export_onnx(
    output_dir: str | PathLike[str],
    model: torch.nn.Module,
    input_names: Sequence[str],
    input_tensors: torch.Tensor | Sequence[torch.Tensor],
    output_names: Sequence[str],
    dynamic_axes: Mapping[str, Mapping[int, str]] | None,
    backbone_only: bool = False,
    verbose: bool = True,
    opset_version: int = 17,
    variant_name: str | None = None,
    *,
    notes: object = None,
) -> str:
    """执行 `export_onnx`。
    
    参数：
    - `output_dir`：传入的 `output_dir` 参数。
    - `model`：传入的 `model` 参数。
    - `input_names`：传入的 `input_names` 参数。
    - `input_tensors`：传入的 `input_tensors` 参数。
    - `output_names`：传入的 `output_names` 参数。
    - `dynamic_axes`：传入的 `dynamic_axes` 参数。
    - `backbone_only`：传入的 `backbone_only` 参数。
    - `verbose`：传入的 `verbose` 参数。
    - `opset_version`：传入的 `opset_version` 参数。
    - `variant_name`：传入的 `variant_name` 参数。
    - `notes`：传入的 `notes` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if variant_name:
        variant_name = os.path.splitext(os.path.basename(variant_name))[0]
        export_name = f"{variant_name}-backbone" if backbone_only else variant_name
    else:
        export_name = "backbone_model" if backbone_only else "inference_model"
    output_file = os.path.join(output_dir, f"{export_name}.onnx")

    if hasattr(model, "export"):
        model.export()

    exporter_mode = "torch-onnx-dynamo"
    try:
        _export_onnx_with_torch(
            model=model,
            input_tensors=input_tensors,
            output_file=output_file,
            input_names=input_names,
            output_names=output_names,
            dynamic_axes=dynamic_axes,
            verbose=verbose,
            opset_version=opset_version,
            dynamo=True,
        )
    except Exception as exc:
        exporter_mode = "torchscript-fallback"
        logger.warning(
            "RF-DETR 新 ONNX exporter 导出失败，改用 TorchScript exporter。"
            "这表示当前 PyTorch 2.8 exporter 对该 RF-DETR forward 仍有未覆盖算子：%s",
            exc,
        )
        if os.path.exists(output_file):
            os.remove(output_file)
        _export_onnx_with_torch(
            model=model,
            input_tensors=input_tensors,
            output_file=output_file,
            input_names=input_names,
            output_names=output_names,
            dynamic_axes=dynamic_axes,
            verbose=verbose,
            opset_version=opset_version,
            dynamo=False,
        )

    if onnx is not None:
        _write_rfdetr_onnx_metadata(
            output_file=output_file,
            exporter_mode=exporter_mode,
            notes=notes,
        )

    logger.info(f"\nSuccessfully exported ONNX model: {output_file}")
    return output_file


def _export_onnx_with_torch(
    *,
    model: torch.nn.Module,
    input_tensors: torch.Tensor | Sequence[torch.Tensor],
    output_file: str,
    input_names: Sequence[str],
    output_names: Sequence[str],
    dynamic_axes: Mapping[str, Mapping[int, str]] | None,
    verbose: bool,
    opset_version: int,
    dynamo: bool,
) -> None:
    """执行 `_export_onnx_with_torch`。
    
    参数：
    - `model`：传入的 `model` 参数。
    - `input_tensors`：传入的 `input_tensors` 参数。
    - `output_file`：传入的 `output_file` 参数。
    - `input_names`：传入的 `input_names` 参数。
    - `output_names`：传入的 `output_names` 参数。
    - `dynamic_axes`：传入的 `dynamic_axes` 参数。
    - `verbose`：传入的 `verbose` 参数。
    - `opset_version`：传入的 `opset_version` 参数。
    - `dynamo`：传入的 `dynamo` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    torch.onnx.export(
        model,
        input_tensors,
        output_file,
        input_names=input_names,
        output_names=output_names,
        export_params=True,
        keep_initializers_as_inputs=False,
        do_constant_folding=True,
        verbose=verbose,
        opset_version=opset_version,
        dynamic_axes=dynamic_axes,
        dynamo=dynamo,
        report=False,
        optimize=True,
        verify=False,
        external_data=False,
    )


def _write_rfdetr_onnx_metadata(
    *,
    output_file: str,
    exporter_mode: str,
    notes: object,
) -> None:
    """执行 `_write_rfdetr_onnx_metadata`。
    
    参数：
    - `output_file`：传入的 `output_file` 参数。
    - `exporter_mode`：传入的 `exporter_mode` 参数。
    - `notes`：传入的 `notes` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    assert onnx is not None
    onnx_model = onnx.load(output_file)
    _set_onnx_metadata_value(
        onnx_model=onnx_model,
        key="rfdetr_exporter_mode",
        value=exporter_mode,
    )
    if notes is not None:
        notes_value = notes if isinstance(notes, str) else json.dumps(notes, allow_nan=False)
        _set_onnx_metadata_value(
            onnx_model=onnx_model,
            key="rfdetr_notes",
            value=notes_value,
        )
    onnx.save(onnx_model, output_file)


def _set_onnx_metadata_value(*, onnx_model, key: str, value: str) -> None:
    """执行 `_set_onnx_metadata_value`。
    
    参数：
    - `onnx_model`：传入的 `onnx_model` 参数。
    - `key`：传入的 `key` 参数。
    - `value`：传入的 `value` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    existing = next((prop for prop in onnx_model.metadata_props if prop.key == key), None)
    if existing is not None:
        existing.value = value
        return
    meta = onnx_model.metadata_props.add()
    meta.key = key
    meta.value = value


def onnx_simplify(
    onnx_dir: str,
    input_names: Sequence[str],
    input_tensors: torch.Tensor | Sequence[torch.Tensor],
    force: bool = False,
) -> str:
    """执行 `onnx_simplify`。
    
    参数：
    - `onnx_dir`：传入的 `onnx_dir` 参数。
    - `input_names`：传入的 `input_names` 参数。
    - `input_tensors`：传入的 `input_tensors` 参数。
    - `force`：传入的 `force` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    import onnx
    import onnxsim

    sim_onnx_dir = onnx_dir.replace(".onnx", ".sim.onnx")
    if os.path.isfile(sim_onnx_dir) and not force:
        return sim_onnx_dir

    if isinstance(input_tensors, torch.Tensor):
        input_tensors = [input_tensors]

    logger.info(f"start simplify ONNX model: {onnx_dir}")
    opt = OnnxOptimizer(onnx_dir)
    opt.info("Model: original")
    opt.common_opt()
    opt.info("Model: optimized")
    opt.save_onnx(sim_onnx_dir)
    input_dict = {name: tensor.detach().cpu().numpy() for name, tensor in zip(input_names, input_tensors)}
    model_opt, check_ok = onnxsim.simplify(sim_onnx_dir, check_n=3, input_data=input_dict, dynamic_input_shape=False)
    if check_ok:
        onnx.save(model_opt, sim_onnx_dir)
    else:
        raise RuntimeError("Failed to simplify ONNX model.")
    logger.info(f"Successfully simplified ONNX model: {sim_onnx_dir}")
    return sim_onnx_dir


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class OnnxOptimizer:
    """RF-DETR core 类：`OnnxOptimizer`。"""

    def __init__(self, input, severity=None):
        missing_deps = []
        if onnx is None:
            missing_deps.append("onnx")
        if shape_inference is None:
            missing_deps.append("onnx.shape_inference")
        if gs is None or G_LOGGER is None:
            missing_deps.append("onnx_graphsurgeon")
        if fold_constants is None:
            missing_deps.append("polygraphy.backend.onnx.loader.fold_constants")
        if missing_deps:
            missing_str = ", ".join(missing_deps)
            raise ImportError(
                f"RF-DETR ONNX 图优化依赖缺失：{missing_str}。请先安装 requirements.txt 中的 ONNX 相关依赖。"
            )
        if severity is None:
            severity = G_LOGGER.INFO
        if isinstance(input, str):
            onnx_graph = self.load_onnx(input)
        else:
            onnx_graph = input
        self.graph = gs.import_onnx(onnx_graph)
        self.severity = severity
        self.set_severity(severity)

    def set_severity(self, severity):
        G_LOGGER.severity = severity

    def load_onnx(self, onnx_path: str):
        """执行 `load_onnx`。
        
        参数：
        - `onnx_path`：传入的 `onnx_path` 参数。
        """
        assert os.path.isfile(onnx_path), f"not found onnx file: {onnx_path}"
        onnx_graph = onnx.load(onnx_path)
        G_LOGGER.info(f"load onnx file: {onnx_path}")
        return onnx_graph

    def save_onnx(self, onnx_path: str):
        onnx_graph = gs.export_onnx(self.graph)
        G_LOGGER.info(f"save onnx file: {onnx_path}")
        onnx.save(onnx_graph, onnx_path)

    def info(self, prefix=""):
        G_LOGGER.verbose(
            f"{prefix} .. {len(self.graph.nodes)} nodes, "
            f"{len(self.graph.tensors().keys())} tensors, "
            f"{len(self.graph.inputs)} inputs, {len(self.graph.outputs)} outputs"
        )

    def cleanup(self, return_onnx=False):
        self.graph.cleanup().toposort()
        if return_onnx:
            return gs.export_onnx(self.graph)

    def select_outputs(self, keep, names=None):
        self.graph.outputs = [self.graph.outputs[o] for o in keep]
        if names:
            for i, name in enumerate(names):
                self.graph.outputs[i].name = name

    def find_node_input(self, node, name: str = None, value=None) -> int:
        for i, inp in enumerate(node.inputs):
            if isinstance(name, str) and inp.name == name:
                index = i
            elif inp == value:
                index = i
        assert index >= 0, f"not found {name}({value}) in node.inputs"
        return index

    def find_node_output(self, node, name: str = None, value=None) -> int:
        for i, inp in enumerate(node.outputs):
            if isinstance(name, str) and inp.name == name:
                index = i
            elif inp == value:
                index = i
        assert index >= 0, f"not found {name}({value}) in node.outputs"
        return index

    def common_opt(self, return_onnx=False):
        for fn in CustomOpSymbolicRegistry._OPTIMIZER:
            fn(self)
            self.cleanup()
        onnx_graph = fold_constants(gs.export_onnx(self.graph), allow_onnxruntime_shape_inference=False)
        if onnx_graph.ByteSize() > 2147483648:
            raise TypeError("ERROR: model size exceeds supported 2GB limit")
        else:
            onnx_graph = shape_inference.infer_shapes(onnx_graph)
        self.graph = gs.import_onnx(onnx_graph)
        self.cleanup()
        if return_onnx:
            return onnx_graph

    def resize_fix(self):
        """执行 `resize_fix`。
        """
        resized_node_count = 0
        for node in self.graph.nodes:
            if node.op == "Resize" and len(node.inputs) == 3:
                name = node.name + "/"

                add_node = node.o().o().i(1)
                div_node = node.i()

                shape_hw_out = gs.Variable(name=name + "shape_hw_out", dtype=np.int64, shape=[4])
                shape_hw = gs.Node(
                    op="Shape", name=name + "shape_hw", inputs=[add_node.outputs[0]], outputs=[shape_hw_out]
                )

                const_zero = gs.Constant(name=name + "const_zero", values=np.array([0], dtype=np.int64))
                const_two = gs.Constant(name=name + "const_two", values=np.array([2], dtype=np.int64))
                const_four = gs.Constant(name=name + "const_four", values=np.array([4], dtype=np.int64))

                slice_hw_out = gs.Variable(name=name + "slice_hw_out", dtype=np.int64, shape=[2])
                slice_hw = gs.Node(
                    op="Slice",
                    name=name + "slice_hw",
                    inputs=[shape_hw_out, const_two, const_four, const_zero],
                    outputs=[slice_hw_out],
                )

                shape_bc_out = gs.Variable(name=name + "shape_bc_out", dtype=np.int64, shape=[2])
                shape_bc = gs.Node(
                    op="Shape", name=name + "shape_bc", inputs=[div_node.outputs[0]], outputs=[shape_bc_out]
                )

                slice_bc_out = gs.Variable(name=name + "slice_bc_out", dtype=np.int64, shape=[2])
                slice_bc = gs.Node(
                    op="Slice",
                    name=name + "slice_bc",
                    inputs=[shape_bc_out, const_zero, const_two, const_zero],
                    outputs=[slice_bc_out],
                )

                concat_bchw_out = gs.Variable(name=name + "concat_bchw_out", dtype=np.int64, shape=[4])
                concat_bchw = gs.Node(
                    op="Concat",
                    name=name + "concat_bchw",
                    attrs={"axis": 0},
                    inputs=[slice_bc_out, slice_hw_out],
                    outputs=[concat_bchw_out],
                )

                none_var = gs.Variable.empty()

                resize_bchw = gs.Node(
                    op="Resize",
                    name=name + "resize_bchw",
                    attrs=node.attrs,
                    inputs=[node.inputs[0], none_var, none_var, concat_bchw_out],
                    outputs=[node.outputs[0]],
                )

                self.graph.nodes.extend([shape_hw, slice_hw, shape_bc, slice_bc, concat_bchw, resize_bchw])

                node.inputs = []
                node.outputs = []

                resized_node_count += 1

        self.cleanup()
        return resized_node_count

    def adjustAddNode(self):  # noqa: N802
        adjusted_add_node_count = 0
        for node in self.graph.nodes:
            if node.op in ["Add"] and isinstance(node.inputs[0], gs.ir.tensor.Constant):
                tensor = node.inputs[1]
                bias = node.inputs[0]
                node.inputs = [tensor, bias]
                adjusted_add_node_count += 1

        self.cleanup()
        return adjusted_add_node_count

    def decompose_instancenorms(self):
        removed_instance_norm_count = 0
        for node in self.graph.nodes:
            if node.op == "InstanceNormalization":
                name = node.name + "/"
                input_tensor = node.inputs[0]
                output_tensor = node.outputs[0]
                mean_out = gs.Variable(name=name + "mean_out")
                mean_node = gs.Node(
                    op="ReduceMean",
                    name=name + "mean_node",
                    attrs={"axes": [-1]},
                    inputs=[input_tensor],
                    outputs=[mean_out],
                )
                sub_out = gs.Variable(name=name + "sub_out")
                sub_node = gs.Node(
                    op="Sub", name=name + "sub_node", attrs={}, inputs=[input_tensor, mean_out], outputs=[sub_out]
                )
                pow_out = gs.Variable(name=name + "pow_out")
                pow_const = gs.Constant(name=name + "pow_const", values=np.array([2.0], dtype=np.float32))
                pow_node = gs.Node(
                    op="Pow", name=name + "pow_node", attrs={}, inputs=[sub_out, pow_const], outputs=[pow_out]
                )
                mean2_out = gs.Variable(name=name + "mean2_out")
                mean2_node = gs.Node(
                    op="ReduceMean",
                    name=name + "mean2_node",
                    attrs={"axes": [-1]},
                    inputs=[pow_out],
                    outputs=[mean2_out],
                )
                epsilon_out = gs.Variable(name=name + "epsilon_out")
                epsilon_const = gs.Constant(
                    name=name + "epsilon_const", values=np.array([node.attrs["epsilon"]], dtype=np.float32)
                )
                epsilon_node = gs.Node(
                    op="Add",
                    name=name + "epsilon_node",
                    attrs={},
                    inputs=[mean2_out, epsilon_const],
                    outputs=[epsilon_out],
                )
                sqrt_out = gs.Variable(name=name + "sqrt_out")
                sqrt_node = gs.Node(
                    op="Sqrt", name=name + "sqrt_node", attrs={}, inputs=[epsilon_out], outputs=[sqrt_out]
                )
                div_out = gs.Variable(name=name + "div_out")
                div_node = gs.Node(
                    op="Div", name=name + "div_node", attrs={}, inputs=[sub_out, sqrt_out], outputs=[div_out]
                )
                constant_scale = gs.Constant(
                    "InstanceNormScaleV-" + str(removed_instance_norm_count),
                    np.ascontiguousarray(node.inputs[1].inputs[0].attrs["value"].values.reshape(1, 32, 1)),
                )
                constant_bias = gs.Constant(
                    "InstanceBiasV-" + str(removed_instance_norm_count),
                    np.ascontiguousarray(node.inputs[2].inputs[0].attrs["value"].values.reshape(1, 32, 1)),
                )
                mul_out = gs.Variable(name=name + "mul_out")
                mul_node = gs.Node(
                    op="Mul", name=name + "mul_node", attrs={}, inputs=[div_out, constant_scale], outputs=[mul_out]
                )
                add_node = gs.Node(
                    op="Add", name=name + "add_node", attrs={}, inputs=[mul_out, constant_bias], outputs=[output_tensor]
                )
                self.graph.nodes.extend(
                    [mean_node, sub_node, pow_node, mean2_node, epsilon_node, sqrt_node, div_node, mul_node, add_node]
                )
                node.inputs = []
                node.outputs = []
                removed_instance_norm_count += 1

        self.cleanup()
        return removed_instance_norm_count

    def insert_groupnorm_plugin(self):
        group_norm_plugin_count = 0
        for node in self.graph.nodes:
            if (
                node.op == "Reshape"
                and node.outputs != []
                and node.o().op == "ReduceMean"
                and node.o(1).op == "Sub"
                and node.o().o() == node.o(1)
                and node.o().o().o().o().o().o().o().o().o().o().o().op == "Mul"
                and node.o().o().o().o().o().o().o().o().o().o().o().o().op == "Add"
                and len(node.o().o().o().o().o().o().o().o().inputs[1].values.shape) == 3
            ):

                input_tensor = node.inputs[0]

                gamma_node = node.o().o().o().o().o().o().o().o().o().o().o()
                index = [isinstance(inp, gs.ir.tensor.Constant) for inp in gamma_node.inputs].index(True)
                gamma = np.array(deepcopy(gamma_node.inputs[index].values.tolist()), dtype=np.float32)
                constant_gamma = gs.Constant(
                    "groupNormGamma-" + str(group_norm_plugin_count), np.ascontiguousarray(gamma.reshape(-1))
                )

                beta_node = gamma_node.o()
                index = [isinstance(inp, gs.ir.tensor.Constant) for inp in beta_node.inputs].index(True)
                beta = np.array(deepcopy(beta_node.inputs[index].values.tolist()), dtype=np.float32)
                constant_beta = gs.Constant(
                    "groupNormBeta-" + str(group_norm_plugin_count), np.ascontiguousarray(beta.reshape(-1))
                )

                epsilon = node.o().o().o().o().o().inputs[1].values.tolist()[0]

                if beta_node.o().op == "Sigmoid":
                    use_swish = True
                    last_node = beta_node.o().o()
                else:
                    use_swish = False
                    last_node = beta_node

                if last_node.o().op == "Cast":
                    last_node = last_node.o()
                input_list = [input_tensor, constant_gamma, constant_beta]
                group_norm_v = gs.Variable(
                    "GroupNormV-" + str(group_norm_plugin_count), np.dtype(np.float16), input_tensor.shape
                )
                group_norm_n = gs.Node(
                    "GroupNorm",
                    "GroupNormN-" + str(group_norm_plugin_count),
                    inputs=input_list,
                    outputs=[group_norm_v],
                    attrs=OrderedDict([("epsilon", epsilon), ("bSwish", int(use_swish))]),
                )
                self.graph.nodes.append(group_norm_n)

                for sub_node in self.graph.nodes:
                    if last_node.outputs[0] in sub_node.inputs:
                        index = sub_node.inputs.index(last_node.outputs[0])
                        sub_node.inputs[index] = group_norm_v
                node.inputs = []
                last_node.outputs = []
                group_norm_plugin_count += 1

        self.cleanup()
        return group_norm_plugin_count

    def insert_layernorm_plugin(self):
        layer_norm_plugin_count = 0
        for node in self.graph.nodes:
            if (
                node.op == "ReduceMean"
                and node.o().op == "Sub"
                and node.o().inputs[0] == node.inputs[0]
                and node.o().o(0).op == "Pow"
                and node.o().o(1).op == "Div"
                and node.o().o(0).o().op == "ReduceMean"
                and node.o().o(0).o().o().op == "Add"
                and node.o().o(0).o().o().o().op == "Sqrt"
                and node.o().o(0).o().o().o().o().op == "Div"
                and node.o().o(0).o().o().o().o() == node.o().o(1)
                and node.o().o(0).o().o().o().o().o().op == "Mul"
                and node.o().o(0).o().o().o().o().o().o().op == "Add"
                and len(node.o().o(0).o().o().o().o().o().inputs[1].values.shape) == 1
            ):
                if node.i().op == "Add":
                    input_tensor = node.inputs[0]
                else:
                    input_tensor = node.i().inputs[0]

                gamma_node = node.o().o().o().o().o().o().o()
                index = [isinstance(inp, gs.ir.tensor.Constant) for inp in gamma_node.inputs].index(True)
                gamma = np.array(deepcopy(gamma_node.inputs[index].values.tolist()), dtype=np.float32)
                constant_gamma = gs.Constant(
                    "LayerNormGamma-" + str(layer_norm_plugin_count), np.ascontiguousarray(gamma.reshape(-1))
                )

                beta_node = gamma_node.o()
                index = [isinstance(inp, gs.ir.tensor.Constant) for inp in beta_node.inputs].index(True)
                beta = np.array(deepcopy(beta_node.inputs[index].values.tolist()), dtype=np.float32)
                constant_beta = gs.Constant(
                    "LayerNormBeta-" + str(layer_norm_plugin_count), np.ascontiguousarray(beta.reshape(-1))
                )

                input_list = [input_tensor, constant_gamma, constant_beta]
                layer_norm_v = gs.Variable(
                    "LayerNormV-" + str(layer_norm_plugin_count), np.dtype(np.float32), input_tensor.shape
                )
                layer_norm_n = gs.Node(
                    "LayerNorm",
                    "LayerNormN-" + str(layer_norm_plugin_count),
                    inputs=input_list,
                    attrs=OrderedDict([("epsilon", 1.0e-5)]),
                    outputs=[layer_norm_v],
                )
                self.graph.nodes.append(layer_norm_n)
                layer_norm_plugin_count += 1

                if beta_node.outputs[0] in self.graph.outputs:
                    index = self.graph.outputs.index(beta_node.outputs[0])
                    self.graph.outputs[index] = layer_norm_v
                else:
                    if beta_node.o().op == "Cast":
                        last_node = beta_node.o()
                    else:
                        last_node = beta_node
                    for sub_node in self.graph.nodes:
                        if last_node.outputs[0] in sub_node.inputs:
                            index = sub_node.inputs.index(last_node.outputs[0])
                            sub_node.inputs[index] = layer_norm_v
                    last_node.outputs = []

        self.cleanup()
        return layer_norm_plugin_count

    def fuse_kv(self, node_k, node_v, fused_kv_idx, heads, num_dynamic=0):
        weights_k = node_k.inputs[1].values
        weights_v = node_v.inputs[1].values
        channel_count = weights_k.shape[0]
        num_heads = heads
        head_dim = weights_k.shape[1] // num_heads

        weights_kv = np.dstack(
            [
                weights_k.reshape(channel_count, num_heads, head_dim),
                weights_v.reshape(channel_count, num_heads, head_dim),
            ]
        ).reshape(channel_count, 2 * num_heads * head_dim)

        input_tensor = node_k.inputs[0]
        output_tensor_k = node_k.outputs[0]
        # 创建融合后的权重张量。
        constant_weights_kv = gs.Constant("Weights_KV_{}".format(fused_kv_idx), np.ascontiguousarray(weights_kv))

        fused_kv_node = gs.Node(
            op="MatMul",
            name="MatMul_KV_{}".format(fused_kv_idx),
            inputs=[input_tensor, constant_weights_kv],
            outputs=[output_tensor_k],
        )
        self.graph.nodes.append(fused_kv_node)

        node_v.o(num_dynamic).inputs[0] = output_tensor_k
        node_k.o(num_dynamic).inputs[0] = output_tensor_k
        for i in range(0, num_dynamic):
            node_v.o().inputs.clear()
            node_k.o().inputs.clear()

        node_k.outputs.clear()
        node_v.outputs.clear()
        node_k.inputs.clear()
        node_v.inputs.clear()

        self.cleanup()
        return fused_kv_node

    def insert_fmhca(self, node_q, node_kv, final_tranpose, mhca_idx, heads, num_dynamic=0):
        output_q = node_q.o(num_dynamic).o().inputs[0]
        output_kv = node_kv.o().inputs[0]
        output_final_tranpose = final_tranpose.outputs[0]

        node_kv.outputs[0].outputs[0].inputs.clear()
        node_kv.outputs[0].outputs[0].inputs.clear()
        node_q.o(num_dynamic).o().inputs.clear()
        for i in range(0, num_dynamic):
            node_q.o(i).o().o(1).inputs.clear()

        weights_kv = node_kv.inputs[1].values
        dims_per_head = weights_kv.shape[1] // (heads * 2)

        shape = gs.Constant(
            "Shape_KV_{}".format(mhca_idx),
            np.ascontiguousarray(np.array([0, 0, heads, 2, dims_per_head], dtype=np.int64)),
        )

        output_reshape = gs.Variable("ReshapeKV_{}".format(mhca_idx), np.dtype(np.float16), None)
        reshape = gs.Node(
            op="Reshape", name="Reshape_{}".format(mhca_idx), inputs=[output_kv, shape], outputs=[output_reshape]
        )
        self.graph.nodes.append(reshape)

        fmhca = gs.Node(
            op="fMHCA",
            name="fMHCA_{}".format(mhca_idx),
            inputs=[output_q, output_reshape],
            outputs=[output_final_tranpose],
        )
        self.graph.nodes.append(fmhca)

        node_q.o(num_dynamic).outputs[0] = output_q

        if num_dynamic > 0:
            reshape2_input1_out = gs.Variable("Reshape2_fmhca{}_out".format(mhca_idx), np.dtype(np.int64), None)
            reshape2_input1_shape = gs.Node(
                "Shape",
                "Reshape2_fmhca{}_shape".format(mhca_idx),
                inputs=[node_q.inputs[0]],
                outputs=[reshape2_input1_out],
            )
            self.graph.nodes.append(reshape2_input1_shape)
            final_tranpose.o().inputs[1] = reshape2_input1_out

        final_tranpose.outputs.clear()

        self.cleanup()

    def fuse_qkv(self, node_q, node_k, node_v, fused_qkv_idx, heads, num_dynamic=0):
        weights_q = node_q.inputs[1].values
        weights_k = node_k.inputs[1].values
        weights_v = node_v.inputs[1].values

        channel_count = weights_k.shape[0]
        num_heads = heads
        head_dim = weights_k.shape[1] // num_heads

        weights_qkv = np.dstack(
            [
                weights_q.reshape(channel_count, num_heads, head_dim),
                weights_k.reshape(channel_count, num_heads, head_dim),
                weights_v.reshape(channel_count, num_heads, head_dim),
            ]
        ).reshape(channel_count, 3 * num_heads * head_dim)

        input_tensor = node_k.inputs[0]
        output_tensor_k = node_k.outputs[0]
        constant_weights_qkv = gs.Constant("Weights_QKV_{}".format(fused_qkv_idx), np.ascontiguousarray(weights_qkv))

        fused_qkv_node = gs.Node(
            op="MatMul",
            name="MatMul_QKV_{}".format(fused_qkv_idx),
            inputs=[input_tensor, constant_weights_qkv],
            outputs=[output_tensor_k],
        )
        self.graph.nodes.append(fused_qkv_node)

        node_q.o(num_dynamic).inputs[0] = output_tensor_k
        node_k.o(num_dynamic).inputs[0] = output_tensor_k
        node_v.o(num_dynamic).inputs[0] = output_tensor_k
        for i in range(0, num_dynamic):
            node_q.o().inputs.clear()
            node_k.o().inputs.clear()
            node_v.o().inputs.clear()

        node_q.outputs.clear()
        node_k.outputs.clear()
        node_v.outputs.clear()

        node_q.inputs.clear()
        node_k.inputs.clear()
        node_v.inputs.clear()

        self.cleanup()
        return fused_qkv_node

    def insert_fmha(self, node_qkv, final_tranpose, mha_idx, heads, num_dynamic=0):
        output_qkv = node_qkv.o().inputs[0]
        output_final_tranpose = final_tranpose.outputs[0]

        node_qkv.outputs[0].outputs[2].inputs.clear()
        node_qkv.outputs[0].outputs[1].inputs.clear()
        node_qkv.outputs[0].outputs[0].inputs.clear()

        weights_qkv = node_qkv.inputs[1].values
        dims_per_head = weights_qkv.shape[1] // (heads * 3)

        shape = gs.Constant(
            "Shape_QKV_{}".format(mha_idx),
            np.ascontiguousarray(np.array([0, 0, heads, 3, dims_per_head], dtype=np.int64)),
        )

        output_shape = gs.Variable("ReshapeQKV_{}".format(mha_idx), np.dtype(np.float16), None)
        reshape = gs.Node(
            op="Reshape", name="Reshape_{}".format(mha_idx), inputs=[output_qkv, shape], outputs=[output_shape]
        )
        self.graph.nodes.append(reshape)

        fmha = gs.Node(
            op="fMHA_V2", name="fMHA_{}".format(mha_idx), inputs=[output_shape], outputs=[output_final_tranpose]
        )
        self.graph.nodes.append(fmha)

        if num_dynamic > 0:
            reshape2_input1_out = gs.Variable("Reshape2_{}_out".format(mha_idx), np.dtype(np.int64), None)
            reshape2_input1_shape = gs.Node(
                "Shape", "Reshape2_{}_shape".format(mha_idx), inputs=[node_qkv.inputs[0]], outputs=[reshape2_input1_out]
            )
            self.graph.nodes.append(reshape2_input1_shape)
            final_tranpose.o().inputs[1] = reshape2_input1_out

        final_tranpose.outputs.clear()

        self.cleanup()

    def mha_mhca_detected(self, node, mha):
        if (
            node.op == "MatMul"
            and len(node.outputs) == 1
            and (
                (mha and len(node.inputs[0].inputs) > 0 and node.i().op == "Add")
                or (not mha and len(node.inputs[0].inputs) == 0)
            )
        ):
            if node.o().op == "Shape":
                if node.o(1).op == "Shape":
                    num_dynamic_kv = 3 if node.o(2).op == "Shape" else 2
                else:
                    num_dynamic_kv = 1
                num_dynamic_q = num_dynamic_kv if mha else num_dynamic_kv + 1
            else:
                num_dynamic_kv = 0
                num_dynamic_q = 0

            o = node.o(num_dynamic_kv)
            if (
                o.op == "Reshape"
                and o.o().op == "Transpose"
                and o.o().o().op == "Reshape"
                and o.o().o().o().op == "MatMul"
                and o.o().o().o().i(0).op == "Softmax"
                and o.o().o().o().i(1).op == "Reshape"
                and o.o().o().o().i(0).i().op == "Mul"
                and o.o().o().o().i(0).i().i().op == "MatMul"
                and o.o().o().o().i(0).i().i().i(0).op == "Reshape"
                and o.o().o().o().i(0).i().i().i(1).op == "Transpose"
                and o.o().o().o().i(0).i().i().i(1).i().op == "Reshape"
                and o.o().o().o().i(0).i().i().i(1).i().i().op == "Transpose"
                and o.o().o().o().i(0).i().i().i(1).i().i().i().op == "Reshape"
                and o.o().o().o().i(0).i().i().i(1).i().i().i().i().op == "MatMul"
                and node.name != o.o().o().o().i(0).i().i().i(1).i().i().i().i().name
            ):
                node_q = o.o().o().o().i(0).i().i().i(0).i().i().i()
                node_k = o.o().o().o().i(0).i().i().i(1).i().i().i().i()
                node_v = node
                final_tranpose = o.o().o().o().o(num_dynamic_q).o()
                # 基本图结构校验。
                if node_q.op == "MatMul" and final_tranpose.op == "Transpose":
                    return True, num_dynamic_q, num_dynamic_kv, node_q, node_k, node_v, final_tranpose
        return False, 0, 0, None, None, None, None

    def fuse_kv_insert_fmhca(self, heads, mhca_index, sm):
        nodes = self.graph.nodes
        for idx, _ in enumerate(nodes):
            if idx + 1 > len(nodes) or idx + 2 > len(nodes):
                continue

            detected, num_dynamic_q, num_dynamic_kv, node_q, node_k, node_v, final_tranpose = self.mha_mhca_detected(
                nodes[idx], mha=False
            )
            if detected:
                assert num_dynamic_q == 0 or num_dynamic_q == num_dynamic_kv + 1
                if sm == 75 and node_q.inputs[1].shape[1] // heads == 160:
                    continue
                node_kv = self.fuse_kv(node_k, node_v, mhca_index, heads, num_dynamic_kv)
                self.insert_fmhca(node_q, node_kv, final_tranpose, mhca_index, heads, num_dynamic_q)
                return True
        return False

    def fuse_qkv_insert_fmha(self, heads, mha_index):
        nodes = self.graph.nodes
        for idx, _ in enumerate(nodes):
            if idx + 1 > len(nodes) or idx + 2 > len(nodes):
                continue

            detected, num_dynamic_q, num_dynamic_kv, node_q, node_k, node_v, final_tranpose = self.mha_mhca_detected(
                nodes[idx], mha=True
            )
            if detected:
                assert num_dynamic_q == num_dynamic_kv
                node_qkv = self.fuse_qkv(node_q, node_k, node_v, mha_index, heads, num_dynamic_kv)
                self.insert_fmha(node_qkv, final_tranpose, mha_index, heads, num_dynamic_kv)
                return True
        return False

    def insert_fmhca_plugin(self, num_heads, sm):
        mhca_index = 0
        while self.fuse_kv_insert_fmhca(num_heads, mhca_index, sm):
            mhca_index += 1
        return mhca_index

    def insert_fmha_plugin(self, num_heads):
        mha_index = 0
        while self.fuse_qkv_insert_fmha(num_heads, mha_index):
            mha_index += 1
        return mha_index
