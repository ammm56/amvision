using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.Workflows
{

    /// <summary>
    /// 模型部署同步推理响应。
    /// </summary>
    public sealed class ModelDeploymentInferenceResponse
    {
        [JsonPropertyName("request_id")]
        public string? RequestId { get; set; }

        [JsonPropertyName("inference_task_id")]
        public string? InferenceTaskId { get; set; }

        [JsonPropertyName("deployment_instance_id")]
        public string? DeploymentInstanceId { get; set; }

        [JsonPropertyName("instance_id")]
        public string? InstanceId { get; set; }

        [JsonPropertyName("model_version_id")]
        public string? ModelVersionId { get; set; }

        [JsonPropertyName("model_build_id")]
        public string? ModelBuildId { get; set; }

        [JsonPropertyName("input_uri")]
        public string? InputUri { get; set; }

        [JsonPropertyName("input_source_kind")]
        public string? InputSourceKind { get; set; }

        [JsonPropertyName("input_file_id")]
        public string? InputFileId { get; set; }

        [JsonPropertyName("score_threshold")]
        public double? ScoreThreshold { get; set; }

        [JsonPropertyName("save_result_image")]
        public bool? SaveResultImage { get; set; }

        [JsonPropertyName("return_preview_image_base64")]
        public bool? ReturnPreviewImageBase64 { get; set; }

        [JsonPropertyName("image_width")]
        public int? ImageWidth { get; set; }

        [JsonPropertyName("image_height")]
        public int? ImageHeight { get; set; }

        [JsonPropertyName("item_count")]
        public int? ItemCount { get; set; }

        [JsonPropertyName("detection_count")]
        public int? DetectionCount { get; set; }

        [JsonPropertyName("latency_ms")]
        public double? LatencyMs { get; set; }

        [JsonPropertyName("decode_ms")]
        public double? DecodeMs { get; set; }

        [JsonPropertyName("preprocess_ms")]
        public double? PreprocessMs { get; set; }

        [JsonPropertyName("infer_ms")]
        public double? InferMs { get; set; }

        [JsonPropertyName("postprocess_ms")]
        public double? PostprocessMs { get; set; }

        [JsonPropertyName("serialize_ms")]
        public double? SerializeMs { get; set; }

        [JsonPropertyName("labels")]
        public IList<string> Labels { get; set; } = new List<string>();

        [JsonPropertyName("detections")]
        public IList<ModelInferenceDetectionItemResponse> Detections { get; set; } = new List<ModelInferenceDetectionItemResponse>();

        [JsonPropertyName("runtime_session_info")]
        public IDictionary<string, JsonElement> RuntimeSessionInfo { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("preview_image_uri")]
        public string? PreviewImageUri { get; set; }

        [JsonPropertyName("preview_image_base64")]
        public string? PreviewImageBase64 { get; set; }

        [JsonPropertyName("result_object_key")]
        public string? ResultObjectKey { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JsonElement> ExtensionData { get; set; } = new Dictionary<string, JsonElement>();
    }

    /// <summary>
    /// detection/obb 等模型推理结果项。
    /// </summary>
    public sealed class ModelInferenceDetectionItemResponse
    {
        [JsonPropertyName("bbox_xyxy")]
        public IList<double> BboxXyxy { get; set; } = new List<double>();

        [JsonPropertyName("score")]
        public double? Score { get; set; }

        [JsonPropertyName("class_id")]
        public int? ClassId { get; set; }

        [JsonPropertyName("class_name")]
        public string? ClassName { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JsonElement> ExtensionData { get; set; } = new Dictionary<string, JsonElement>();
    }

    /// <summary>
    /// 异步模型推理任务创建响应。
    /// </summary>
    public sealed class ModelInferenceTaskSubmissionResponse
    {
        [JsonPropertyName("inference_task_id")]
        public string InferenceTaskId { get; set; } = string.Empty;

        [JsonPropertyName("status")]
        public string Status { get; set; } = string.Empty;

        [JsonPropertyName("queue_name")]
        public string? QueueName { get; set; }

        [JsonPropertyName("queue_task_id")]
        public string? QueueTaskId { get; set; }

        [JsonPropertyName("deployment_instance_id")]
        public string? DeploymentInstanceId { get; set; }

        [JsonPropertyName("input_uri")]
        public string? InputUri { get; set; }

        [JsonPropertyName("input_source_kind")]
        public string? InputSourceKind { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JsonElement> ExtensionData { get; set; } = new Dictionary<string, JsonElement>();
    }

    /// <summary>
    /// 异步模型推理任务详情响应。
    /// </summary>
    public sealed class ModelInferenceTaskDetailResponse
    {
        [JsonPropertyName("inference_task_id")]
        public string InferenceTaskId { get; set; } = string.Empty;

        [JsonPropertyName("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonPropertyName("deployment_instance_id")]
        public string DeploymentInstanceId { get; set; } = string.Empty;

        [JsonPropertyName("status")]
        public string Status { get; set; } = string.Empty;

        [JsonPropertyName("display_name")]
        public string? DisplayName { get; set; }

        [JsonPropertyName("result_object_key")]
        public string? ResultObjectKey { get; set; }

        [JsonPropertyName("error_message")]
        public string? ErrorMessage { get; set; }

        [JsonPropertyName("task_spec")]
        public IDictionary<string, JsonElement> TaskSpec { get; set; } = new Dictionary<string, JsonElement>();

        [JsonPropertyName("events")]
        public IList<JsonElement> Events { get; set; } = new List<JsonElement>();

        [JsonExtensionData]
        public IDictionary<string, JsonElement> ExtensionData { get; set; } = new Dictionary<string, JsonElement>();
    }

    /// <summary>
    /// 异步模型推理任务结果响应。
    /// </summary>
    public sealed class ModelInferenceTaskResultResponse
    {
        [JsonPropertyName("inference_task_id")]
        public string InferenceTaskId { get; set; } = string.Empty;

        [JsonPropertyName("task_state")]
        public string? TaskState { get; set; }

        [JsonPropertyName("file_status")]
        public string? FileStatus { get; set; }

        [JsonPropertyName("object_key")]
        public string? ObjectKey { get; set; }

        [JsonPropertyName("payload")]
        public IDictionary<string, JsonElement> Payload { get; set; } = new Dictionary<string, JsonElement>();

        [JsonExtensionData]
        public IDictionary<string, JsonElement> ExtensionData { get; set; } = new Dictionary<string, JsonElement>();
    }
}
