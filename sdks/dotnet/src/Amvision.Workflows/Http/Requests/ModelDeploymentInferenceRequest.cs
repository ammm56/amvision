using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Amvision.Workflows;

/// <summary>
/// 模型部署 JSON 推理请求。
/// </summary>
public sealed class ModelDeploymentInferenceRequest
{
    /// <summary>
    /// 异步推理任务所属 Project id。
    /// </summary>
    [JsonPropertyName("project_id")]
    public string? ProjectId { get; set; }

    /// <summary>
    /// 异步推理任务使用的 DeploymentInstance id。
    /// </summary>
    [JsonPropertyName("deployment_instance_id")]
    public string? DeploymentInstanceId { get; set; }

    /// <summary>
    /// 模型类型；通常不需要设置，后端可从 DeploymentInstance 解析。
    /// </summary>
    [JsonPropertyName("model_type")]
    public string? ModelType { get; set; }

    /// <summary>
    /// 本地对象存储中的文件 id。
    /// </summary>
    [JsonPropertyName("input_file_id")]
    public string? InputFileId { get; set; }

    /// <summary>
    /// 输入图片 URI。
    /// </summary>
    [JsonPropertyName("input_uri")]
    public string? InputUri { get; set; }

    /// <summary>
    /// 输入图片 base64。
    /// </summary>
    [JsonPropertyName("image_base64")]
    public string? ImageBase64 { get; set; }

    /// <summary>
    /// 输入传输模式，例如 storage 或 memory。
    /// </summary>
    [JsonPropertyName("input_transport_mode")]
    public string InputTransportMode { get; set; } = "storage";

    /// <summary>
    /// detection/segmentation/pose/obb 常用 score threshold。
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
    /// 是否保存结果预览图。
    /// </summary>
    [JsonPropertyName("save_result_image")]
    public bool? SaveResultImage { get; set; }

    /// <summary>
    /// 是否返回预览图 base64。
    /// </summary>
    [JsonPropertyName("return_preview_image_base64")]
    public bool? ReturnPreviewImageBase64 { get; set; }

    /// <summary>
    /// 异步推理任务显示名称。
    /// </summary>
    [JsonPropertyName("display_name")]
    public string? DisplayName { get; set; }

    /// <summary>
    /// 任务特定的扩展选项。
    /// </summary>
    [JsonPropertyName("extra_options")]
    public IDictionary<string, object?> ExtraOptions { get; } = new Dictionary<string, object?>();

    /// <summary>
    /// 从 input_uri 创建推理请求。
    /// </summary>
    public static ModelDeploymentInferenceRequest FromUri(string inputUri)
    {
        if (string.IsNullOrWhiteSpace(inputUri))
        {
            throw new ArgumentException("inputUri cannot be empty.", nameof(inputUri));
        }

        return new ModelDeploymentInferenceRequest
        {
            InputUri = inputUri.Trim()
        };
    }

    /// <summary>
    /// 从 input_file_id 创建推理请求。
    /// </summary>
    public static ModelDeploymentInferenceRequest FromFileId(string inputFileId)
    {
        if (string.IsNullOrWhiteSpace(inputFileId))
        {
            throw new ArgumentException("inputFileId cannot be empty.", nameof(inputFileId));
        }

        return new ModelDeploymentInferenceRequest
        {
            InputFileId = inputFileId.Trim()
        };
    }

    /// <summary>
    /// 从 image_base64 创建推理请求。
    /// </summary>
    public static ModelDeploymentInferenceRequest FromBase64(string imageBase64)
    {
        if (string.IsNullOrWhiteSpace(imageBase64))
        {
            throw new ArgumentException("imageBase64 cannot be empty.", nameof(imageBase64));
        }

        return new ModelDeploymentInferenceRequest
        {
            ImageBase64 = NormalizeBase64(imageBase64),
            InputTransportMode = "memory"
        };
    }

    /// <summary>
    /// 校验直接推理请求字段。
    /// </summary>
    internal void ValidateForDirectInference()
    {
        Validate(requireTaskFields: false);
    }

    /// <summary>
    /// 校验异步推理任务请求字段。
    /// </summary>
    internal void ValidateForInferenceTask()
    {
        Validate(requireTaskFields: true);
    }

    private static string NormalizeBase64(string imageBase64)
    {
        var normalized = imageBase64.Trim();
        var commaIndex = normalized.IndexOf(',');
        if (normalized.StartsWith("data:", StringComparison.OrdinalIgnoreCase) && commaIndex > 0)
        {
            normalized = normalized.Substring(commaIndex + 1);
        }

        _ = Convert.FromBase64String(normalized);
        return normalized;
    }

    private void Validate(bool requireTaskFields)
    {
        if (requireTaskFields)
        {
            if (string.IsNullOrWhiteSpace(ProjectId))
            {
                throw new InvalidOperationException("ProjectId cannot be empty when creating an inference task.");
            }

            if (string.IsNullOrWhiteSpace(DeploymentInstanceId))
            {
                throw new InvalidOperationException("DeploymentInstanceId cannot be empty when creating an inference task.");
            }
        }

        if (string.IsNullOrWhiteSpace(InputTransportMode))
        {
            throw new InvalidOperationException("InputTransportMode cannot be empty.");
        }

        var inputCount = 0;
        inputCount += string.IsNullOrWhiteSpace(InputFileId) ? 0 : 1;
        inputCount += string.IsNullOrWhiteSpace(InputUri) ? 0 : 1;
        inputCount += string.IsNullOrWhiteSpace(ImageBase64) ? 0 : 1;
        if (inputCount != 1)
        {
            throw new InvalidOperationException("Exactly one of InputFileId, InputUri or ImageBase64 must be set.");
        }

        ValidateThreshold(ScoreThreshold, nameof(ScoreThreshold));
        ValidateThreshold(MaskThreshold, nameof(MaskThreshold));
        ValidateThreshold(KeypointConfidenceThreshold, nameof(KeypointConfidenceThreshold));
        if (TopK is not null && TopK.Value <= 0)
        {
            throw new InvalidOperationException("TopK must be greater than zero.");
        }
    }

    private static void ValidateThreshold(double? value, string name)
    {
        if (value is not null && (value.Value < 0 || value.Value > 1))
        {
            throw new InvalidOperationException($"{name} must be between 0 and 1.");
        }
    }
}
