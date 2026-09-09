"""YOLO26 ONNX 导出入口。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.models.yolo26_core.export.plan import (
    Yolo26ExportTaskPlan,
)
from backend.service.application.models.yolo_core_common.export import (
    export_yolo_onnx,
    validate_yolo_onnx,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.yolo26_core.export.validation_graph import (
    annotate_topk_graph,
    instrument_topk_graph,
    read_topk_contract,
)
from backend.service.application.models.yolo26_core.export.topk_validation import (
    validate_topk_outputs,
)
from backend.service.application.models.yolo26_core.postprocess.export import (
    postprocess_yolo26_detection_export_tensor,
    postprocess_yolo26_extra_export_tensor,
)
from backend.service.application.models.yolo_core_common.export.execution import (
    _build_dummy_input,
    _build_runtime_input_tensor_payload,
    _validate_input_tensor_against_session,
    _validate_task_export_outputs,
    normalize_yolo_export_model_outputs,
    use_yolo_model_export_mode,
    validate_yolo_onnx_graph_output_contract,
)


def export_yolo26_onnx(
    *,
    session: object,
    output_path: Path,
    output_object_key: str,
    export_plan: Yolo26ExportTaskPlan,
) -> dict[str, object]:
    """把 YOLO26 PyTorch session 导出为 ONNX。"""

    summary = export_yolo_onnx(
        session=session,
        output_path=output_path,
        output_object_key=output_object_key,
        export_plan=export_plan,
    )
    if export_plan.task_type != "classification":
        annotate_topk_graph(
            path=output_path,
            task_type=export_plan.task_type,
            class_count=len(session.runtime_target.labels),
        )
    return summary


def validate_yolo26_onnx(
    *,
    session: object,
    onnx_path: Path,
    onnx_module: object,
    onnxruntime_module: object,
    export_plan: Yolo26ExportTaskPlan,
) -> dict[str, object]:
    """校验 YOLO26 ONNX 文件和 PyTorch 输出是否一致。"""

    if export_plan.task_type == "classification":
        return validate_yolo_onnx(
            session=session,
            onnx_path=onnx_path,
            onnx_module=onnx_module,
            onnxruntime_module=onnxruntime_module,
            export_plan=export_plan,
        )
    model = onnx_module.load(str(onnx_path))
    onnx_module.checker.check_model(model)
    validate_yolo_onnx_graph_output_contract(
        onnx_model=model, expected_output_names=export_plan.output_names
    )
    contract = read_topk_contract(model)
    if contract is None:
        raise ServiceConfigurationError("YOLO26 ONNX 缺少候选验证契约，请重新导出")
    observed_model = instrument_topk_graph(model, contract)
    dummy = _build_dummy_input(session=session)
    heads = [
        module
        for module in session.model.modules()
        if hasattr(module, "validation_raw_output")
    ]
    if len(heads) != 1:
        raise ServiceConfigurationError("YOLO26 模型缺少唯一的候选验证 head")
    head = heads[0]
    previous = head.validation_raw_output
    try:
        with (
            session.imports.torch.no_grad(),
            use_yolo_model_export_mode(session.model, enabled=True),
        ):
            head.validation_raw_output = False
            torch_outputs = normalize_yolo_export_model_outputs(
                session.model(dummy), session.imports
            )
            head.validation_raw_output = True
            raw_outputs = normalize_yolo_export_model_outputs(
                session.model(dummy), session.imports
            )
    finally:
        head.validation_raw_output = previous
    observed = onnxruntime_module.InferenceSession(
        observed_model.SerializeToString(), providers=["CPUExecutionProvider"]
    )
    public = onnxruntime_module.InferenceSession(
        str(onnx_path), providers=["CPUExecutionProvider"]
    )
    input_info = public.get_inputs()[0]
    input_tensor = _build_runtime_input_tensor_payload(
        name=input_info.name, shape=input_info.shape, dtype=input_info.type
    )
    _validate_input_tensor_against_session(
        session=session, input_tensor=input_tensor, artifact_format="onnx"
    )
    feed = {input_info.name: dummy.detach().cpu().numpy()}
    ort_outputs = public.run(list(export_plan.output_names), feed)
    observed_outputs = observed.run(
        [*export_plan.output_names, contract.candidates_name], feed
    )
    for outputs in (torch_outputs, ort_outputs):
        _validate_task_export_outputs(task_type=export_plan.task_type, outputs=outputs)
    # raw forward 与公开 forward 是两次执行。先从实际 raw 候选生成观测选择，
    # 再由完整输出交接校验公开 forward，不把两次执行混称同一次 Gather。
    raw_tensor = session.imports.torch.from_numpy(raw_outputs[0])
    extra_channels = raw_tensor.shape[-1] - 4 - contract.class_count
    options = dict(
        torch_module=session.imports.torch,
        prediction=raw_tensor,
        num_classes=contract.class_count,
        max_detections=300,
    )
    source_rows = (
        postprocess_yolo26_extra_export_tensor(**options, extra_channels=extra_channels)
        if extra_channels
        else postprocess_yolo26_detection_export_tensor(**options)
    ).numpy()
    summary = validate_topk_outputs(
        source_candidates=raw_outputs[0],
        target_candidates=observed_outputs[-1],
        source_outputs=torch_outputs,
        source_observed_outputs=[source_rows, *raw_outputs[1:]],
        target_outputs=ort_outputs,
        target_observed_outputs=observed_outputs[:-1],
        class_count=contract.class_count,
        build_precision="fp32",
        np_module=session.imports.np,
    )
    summary.update(strict_numeric_validation=True, input_tensor=input_tensor)
    if not summary["passed"]:
        raise ServiceConfigurationError(
            "YOLO26 ONNX 候选或 TopK 语义校验失败", details=summary
        )
    return summary


__all__ = [
    "export_yolo26_onnx",
    "validate_yolo26_onnx",
]
