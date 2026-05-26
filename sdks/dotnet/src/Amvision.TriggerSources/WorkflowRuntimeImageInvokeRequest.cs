using System;
using System.Collections.Generic;

namespace Amvision.TriggerSources;

/// <summary>
/// 描述一次按 image-base64.v1 调用 WorkflowAppRuntime 的请求。
/// </summary>
public sealed class WorkflowRuntimeImageInvokeRequest
{
    /// <summary>
    /// 要编码为 image_base64 的图片 bytes。
    /// </summary>
    public byte[] ImageBytes { get; set; } = Array.Empty<byte>();

    /// <summary>
    /// 输入 binding 名称。
    /// </summary>
    public string InputBinding { get; set; } = "request_image_base64";

    /// <summary>
    /// 图片 media type。
    /// </summary>
    public string MediaType { get; set; } = "image/octet-stream";

    /// <summary>
    /// 可选 timeout_seconds。
    /// </summary>
    public int? TimeoutSeconds { get; set; }

    /// <summary>
    /// 写入 execution_metadata 的附加字段。
    /// </summary>
    public IDictionary<string, object?> ExecutionMetadata { get; } = new Dictionary<string, object?>();

    /// <summary>
    /// 转换为通用 invoke 请求对象。
    /// </summary>
    /// <returns>通用 invoke 请求。</returns>
    public WorkflowRuntimeInvokeRequest ToWorkflowRuntimeInvokeRequest()
    {
        Validate();
        var request = new WorkflowRuntimeInvokeRequest
        {
            TimeoutSeconds = TimeoutSeconds
        };
        request.InputBindings[InputBinding.Trim()] = new Dictionary<string, object?>
        {
            ["image_base64"] = Convert.ToBase64String(ImageBytes),
            ["media_type"] = MediaType.Trim()
        };
        foreach (var pair in ExecutionMetadata)
        {
            request.ExecutionMetadata[pair.Key] = pair.Value;
        }

        return request;
    }

    /// <summary>
    /// 校验图片 invoke 请求的基础字段。
    /// </summary>
    internal void Validate()
    {
        if (ImageBytes is null || ImageBytes.Length == 0)
        {
            throw new InvalidOperationException("ImageBytes cannot be empty.");
        }

        if (string.IsNullOrWhiteSpace(InputBinding))
        {
            throw new InvalidOperationException("InputBinding cannot be empty.");
        }

        if (string.IsNullOrWhiteSpace(MediaType))
        {
            throw new InvalidOperationException("MediaType cannot be empty.");
        }

        if (TimeoutSeconds is not null && TimeoutSeconds.Value <= 0)
        {
            throw new InvalidOperationException("TimeoutSeconds must be greater than zero.");
        }
    }
}