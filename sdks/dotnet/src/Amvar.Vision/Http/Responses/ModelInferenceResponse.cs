using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json;

namespace Amvar.Vision
{

    /// <summary>
    /// 模型部署同步推理响应。
    /// </summary>
    public sealed class ModelDeploymentInferenceResponse
    {
        [JsonProperty("request_id")]
        public string? RequestId { get; set; }

        [JsonProperty("inference_task_id")]
        public string? InferenceTaskId { get; set; }

        [JsonProperty("deployment_instance_id")]
        public string? DeploymentInstanceId { get; set; }

        [JsonProperty("instance_id")]
        public string? InstanceId { get; set; }

        [JsonProperty("model_version_id")]
        public string? ModelVersionId { get; set; }

        [JsonProperty("model_build_id")]
        public string? ModelBuildId { get; set; }

        [JsonProperty("input_uri")]
        public string? InputUri { get; set; }

        [JsonProperty("input_source_kind")]
        public string? InputSourceKind { get; set; }

        [JsonProperty("input_file_id")]
        public string? InputFileId { get; set; }

        [JsonProperty("score_threshold")]
        public double? ScoreThreshold { get; set; }

        [JsonProperty("save_result_image")]
        public bool? SaveResultImage { get; set; }

        [JsonProperty("return_preview_image_base64")]
        public bool? ReturnPreviewImageBase64 { get; set; }

        [JsonProperty("image_width")]
        public int? ImageWidth { get; set; }

        [JsonProperty("image_height")]
        public int? ImageHeight { get; set; }

        [JsonProperty("item_count")]
        public int? ItemCount { get; set; }

        [JsonProperty("detection_count")]
        public int? DetectionCount { get; set; }

        [JsonProperty("latency_ms")]
        public double? LatencyMs { get; set; }

        [JsonProperty("decode_ms")]
        public double? DecodeMs { get; set; }

        [JsonProperty("preprocess_ms")]
        public double? PreprocessMs { get; set; }

        [JsonProperty("infer_ms")]
        public double? InferMs { get; set; }

        [JsonProperty("postprocess_ms")]
        public double? PostprocessMs { get; set; }

        [JsonProperty("serialize_ms")]
        public double? SerializeMs { get; set; }

        [JsonProperty("labels")]
        public IList<string> Labels { get; set; } = new List<string>();

        [JsonProperty("detections")]
        public IList<ModelInferenceDetectionItemResponse> Detections { get; set; } = new List<ModelInferenceDetectionItemResponse>();

        [JsonProperty("runtime_session_info")]
        public IDictionary<string, JToken> RuntimeSessionInfo { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("preview_image_uri")]
        public string? PreviewImageUri { get; set; }

        [JsonProperty("preview_image_base64")]
        public string? PreviewImageBase64 { get; set; }

        [JsonProperty("result_object_key")]
        public string? ResultObjectKey { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JToken> ExtensionData { get; set; } = new Dictionary<string, JToken>();
    }

    /// <summary>
    /// detection/obb 等模型推理结果项。
    /// </summary>
    public sealed class ModelInferenceDetectionItemResponse
    {
        [JsonProperty("bbox_xyxy")]
        public IList<double> BboxXyxy { get; set; } = new List<double>();

        [JsonProperty("score")]
        public double? Score { get; set; }

        [JsonProperty("class_id")]
        public int? ClassId { get; set; }

        [JsonProperty("class_name")]
        public string? ClassName { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JToken> ExtensionData { get; set; } = new Dictionary<string, JToken>();
    }

    /// <summary>
    /// 异步模型推理任务创建响应。
    /// </summary>
    public sealed class ModelInferenceTaskSubmissionResponse
    {
        [JsonProperty("inference_task_id")]
        public string InferenceTaskId { get; set; } = string.Empty;

        [JsonProperty("status")]
        public string Status { get; set; } = string.Empty;

        [JsonProperty("queue_name")]
        public string? QueueName { get; set; }

        [JsonProperty("queue_task_id")]
        public string? QueueTaskId { get; set; }

        [JsonProperty("deployment_instance_id")]
        public string? DeploymentInstanceId { get; set; }

        [JsonProperty("input_uri")]
        public string? InputUri { get; set; }

        [JsonProperty("input_source_kind")]
        public string? InputSourceKind { get; set; }

        [JsonExtensionData]
        public IDictionary<string, JToken> ExtensionData { get; set; } = new Dictionary<string, JToken>();
    }

    /// <summary>
    /// 异步模型推理任务详情响应。
    /// </summary>
    public sealed class ModelInferenceTaskDetailResponse
    {
        [JsonProperty("inference_task_id")]
        public string InferenceTaskId { get; set; } = string.Empty;

        [JsonProperty("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonProperty("deployment_instance_id")]
        public string DeploymentInstanceId { get; set; } = string.Empty;

        [JsonProperty("status")]
        public string Status { get; set; } = string.Empty;

        [JsonProperty("display_name")]
        public string? DisplayName { get; set; }

        [JsonProperty("result_object_key")]
        public string? ResultObjectKey { get; set; }

        [JsonProperty("error_message")]
        public string? ErrorMessage { get; set; }

        [JsonProperty("task_spec")]
        public IDictionary<string, JToken> TaskSpec { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("events")]
        public IList<JToken> Events { get; set; } = new List<JToken>();

        [JsonExtensionData]
        public IDictionary<string, JToken> ExtensionData { get; set; } = new Dictionary<string, JToken>();
    }

    /// <summary>
    /// 异步模型推理任务结果响应。
    /// </summary>
    public sealed class ModelInferenceTaskResultResponse
    {
        [JsonProperty("inference_task_id")]
        public string InferenceTaskId { get; set; } = string.Empty;

        [JsonProperty("task_state")]
        public string? TaskState { get; set; }

        [JsonProperty("file_status")]
        public string? FileStatus { get; set; }

        [JsonProperty("object_key")]
        public string? ObjectKey { get; set; }

        [JsonProperty("payload")]
        public IDictionary<string, JToken> Payload { get; set; } = new Dictionary<string, JToken>();

        [JsonExtensionData]
        public IDictionary<string, JToken> ExtensionData { get; set; } = new Dictionary<string, JToken>();
    }
}
