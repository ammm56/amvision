using System.Text.Json.Serialization;

namespace Amvision.Workflows.Console.Model;

/// <summary>
/// 已存在模型 DeploymentInstance 的调用配置，对应 model_deployments[] 节点。
/// </summary>
internal sealed class ModelDeploymentConfig
{
    /// <summary>
    /// 本程序内部使用的模型部署字典 key。
    /// </summary>
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>
    /// 模型任务类型，例如 detection、classification、segmentation、pose、obb。
    /// </summary>
    [JsonPropertyName("task_type")]
    public string TaskType { get; set; } = ModelTaskTypes.Detection;

    /// <summary>
    /// 前端已创建的 DeploymentInstance id。
    /// </summary>
    [JsonPropertyName("deployment_instance_id")]
    public string DeploymentInstanceId { get; set; } = string.Empty;

    /// <summary>
    /// 调用的 deployment runtime 模式，支持 sync 或 async。
    /// </summary>
    [JsonPropertyName("runtime_mode")]
    public string RuntimeMode { get; set; } = ModelDeploymentRuntimeModes.Sync;

    /// <summary>
    /// 推理输入传输模式，按现场和后端配置填写。
    /// </summary>
    [JsonPropertyName("input_transport_mode")]
    public string InputTransportMode { get; set; } = "memory";

    /// <summary>
    /// 默认图片路径；用于 configured image 调用。
    /// </summary>
    [JsonPropertyName("default_image_path")]
    public string? DefaultImagePath { get; set; }

    /// <summary>
    /// 默认 input URI；用于已有对象存储或本地存储输入。
    /// </summary>
    [JsonPropertyName("default_input_uri")]
    public string? DefaultInputUri { get; set; }

    /// <summary>
    /// 默认 input file id；用于已经上传到后端文件存储的图片。
    /// </summary>
    [JsonPropertyName("default_input_file_id")]
    public string? DefaultInputFileId { get; set; }

    /// <summary>
    /// detection、segmentation、pose、obb 常用 score threshold。
    /// </summary>
    [JsonPropertyName("score_threshold")]
    public double? ScoreThreshold { get; set; }

    /// <summary>
    /// classification top-k。
    /// </summary>
    [JsonPropertyName("top_k")]
    public int? TopK { get; set; }

    /// <summary>
    /// segmentation mask threshold。
    /// </summary>
    [JsonPropertyName("mask_threshold")]
    public double? MaskThreshold { get; set; }

    /// <summary>
    /// pose keypoint confidence threshold。
    /// </summary>
    [JsonPropertyName("keypoint_confidence_threshold")]
    public double? KeypointConfidenceThreshold { get; set; }

    /// <summary>
    /// 是否保存推理结果图；为空时使用后端默认值。
    /// </summary>
    [JsonPropertyName("save_result_image")]
    public bool? SaveResultImage { get; set; }

    /// <summary>
    /// 是否在响应中返回 preview image base64；为空时使用后端默认值。
    /// </summary>
    [JsonPropertyName("return_preview_image_base64")]
    public bool? ReturnPreviewImageBase64 { get; set; }

    /// <summary>
    /// bytes 图片上传时默认文件名。
    /// </summary>
    [JsonPropertyName("default_file_name")]
    public string DefaultFileName { get; set; } = "input-image.bin";

    /// <summary>
    /// bytes 图片上传时默认 media type。
    /// </summary>
    [JsonPropertyName("default_media_type")]
    public string DefaultMediaType { get; set; } = "image/octet-stream";

    /// <summary>
    /// 校验模型部署配置是否能指向一个已存在的后端 DeploymentInstance。
    /// </summary>
    /// <param name="path">配置字段路径。</param>
    public void Validate(string path)
    {
        Name = ConfigValidation.RequireText(Name, $"{path}.name");
        TaskType = ModelTaskTypes.Normalize(ConfigValidation.RequireText(TaskType, $"{path}.task_type"));
        DeploymentInstanceId = ConfigValidation.RequireText(DeploymentInstanceId, $"{path}.deployment_instance_id");
        RuntimeMode = ModelDeploymentRuntimeModes.Normalize(ConfigValidation.RequireText(RuntimeMode, $"{path}.runtime_mode"));
        InputTransportMode = ConfigValidation.RequireText(InputTransportMode, $"{path}.input_transport_mode");
        DefaultFileName = ConfigValidation.RequireText(DefaultFileName, $"{path}.default_file_name");
        DefaultMediaType = ConfigValidation.RequireText(DefaultMediaType, $"{path}.default_media_type");
        ValidateThreshold(ScoreThreshold, $"{path}.score_threshold");
        ValidateThreshold(MaskThreshold, $"{path}.mask_threshold");
        ValidateThreshold(KeypointConfidenceThreshold, $"{path}.keypoint_confidence_threshold");
        if (TopK is not null && TopK.Value <= 0)
        {
            throw new InvalidOperationException($"{path}.top_k must be greater than zero.");
        }
    }

    /// <summary>
    /// 校验 0 到 1 之间的阈值字段。
    /// </summary>
    /// <param name="value">阈值。</param>
    /// <param name="path">配置字段路径。</param>
    private static void ValidateThreshold(double? value, string path)
    {
        if (value is not null && (value.Value < 0 || value.Value > 1))
        {
            throw new InvalidOperationException($"{path} must be between 0 and 1.");
        }
    }
}
