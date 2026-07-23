"""detection 公共任务规格定义。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DetectionInferenceTaskSpec:
    """描述 detection 推理任务的规格。

    字段：
    - project_id：所属项目 id。
    - deployment_instance_id：执行推理使用的 DeploymentInstance id。
    - input_file_id：平台内输入文件 id。
    - input_uri：外部输入 URI。
    - input_source_kind：输入来源类型。
    - input_transport_mode：输入传输模式；storage 表示本地文件，memory 表示内存字节直通。
    - normalized_input：提交时固化的统一输入快照；worker 执行阶段优先消费该对象。
    - async_inference_owner_id：创建任务时持有 async deployment owner 的稳定 service id。
    - score_threshold：推理阈值。
    - save_result_image：是否保存结果图。
    - return_preview_image_base64：是否直接返回 base64 预览图。
    - runtime_target_snapshot：提交时固化的运行时快照。
    - runtime_configuration：提交时固化的完整 deployment 运行时配置。
    - extra_options：附加推理选项。
    """

    project_id: str
    deployment_instance_id: str
    input_file_id: str | None = None
    input_uri: str | None = None
    input_source_kind: str = "input_uri"
    input_transport_mode: str = "storage"
    normalized_input: dict[str, object] = field(default_factory=dict)
    async_inference_owner_id: str | None = None
    score_threshold: float | None = None
    save_result_image: bool = False
    return_preview_image_base64: bool = False
    runtime_target_snapshot: dict[str, object] = field(default_factory=dict)
    runtime_configuration: dict[str, object] = field(default_factory=dict)
    extra_options: dict[str, object] = field(default_factory=dict)
