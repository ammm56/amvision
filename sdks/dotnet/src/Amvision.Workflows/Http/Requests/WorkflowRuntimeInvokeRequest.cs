using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.Workflows;

/// <summary>
/// 描述一次 WorkflowAppRuntime invoke HTTP JSON 请求。
/// </summary>
public sealed class WorkflowRuntimeInvokeRequest
{
    private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNamingPolicy = null,
        WriteIndented = false
    };

    /// <summary>
    /// input_bindings 对象。
    /// </summary>
    public IDictionary<string, object?> InputBindings { get; } = new Dictionary<string, object?>();

    /// <summary>
    /// 是否把 InputBindings 直接写成顶层公开 input 字段。
    /// </summary>
    public bool UseDirectInputBindings { get; set; }

    /// <summary>
    /// execution_metadata 对象。
    /// </summary>
    public IDictionary<string, object?> ExecutionMetadata { get; } = new Dictionary<string, object?>();

    /// <summary>
    /// 可选 timeout_seconds。
    /// </summary>
    public int? TimeoutSeconds { get; set; }

    /// <summary>
    /// 将当前请求对象序列化为 backend-service 兼容 JSON。
    /// </summary>
    /// <returns>请求 JSON 文本。</returns>
    public string ToJson()
    {
        Validate();
        var payload = UseDirectInputBindings
            ? new Dictionary<string, object?>(InputBindings)
            : new Dictionary<string, object?>
            {
                ["input_bindings"] = new Dictionary<string, object?>(InputBindings)
            };
        payload["execution_metadata"] = new Dictionary<string, object?>(ExecutionMetadata);
        if (TimeoutSeconds is not null)
        {
            payload["timeout_seconds"] = TimeoutSeconds.Value;
        }

        return JsonSerializer.Serialize(payload, JsonOptions);
    }

    /// <summary>
    /// 从原始 JSON 文本解析出 invoke 请求对象。
    /// </summary>
    /// <param name="json">原始请求 JSON。</param>
    /// <returns>解析后的请求对象。</returns>
    public static WorkflowRuntimeInvokeRequest Parse(string json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            throw new ArgumentException("json cannot be empty.", nameof(json));
        }

        using var document = JsonDocument.Parse(json);
        if (document.RootElement.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidOperationException("Workflow runtime invoke JSON must be an object.");
        }

        var request = new WorkflowRuntimeInvokeRequest();
        if (document.RootElement.TryGetProperty("input_bindings", out var inputBindingsElement))
        {
            if (inputBindingsElement.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidOperationException("input_bindings must be an object.");
            }

            foreach (var property in document.RootElement.EnumerateObject())
            {
                if (property.Name is not ("input_bindings" or "execution_metadata" or "timeout_seconds"))
                {
                    throw new InvalidOperationException(
                        "Workflow runtime invoke JSON cannot mix input_bindings and direct input fields.");
                }
            }

            foreach (var property in inputBindingsElement.EnumerateObject())
            {
                request.InputBindings[property.Name] = property.Value.Clone();
            }
        }
        else
        {
            request.UseDirectInputBindings = true;
            foreach (var property in document.RootElement.EnumerateObject())
            {
                if (property.Name is "execution_metadata" or "timeout_seconds")
                {
                    continue;
                }

                request.InputBindings[property.Name] = property.Value.Clone();
            }
        }

        if (document.RootElement.TryGetProperty("execution_metadata", out var executionMetadataElement))
        {
            if (executionMetadataElement.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidOperationException("execution_metadata must be an object.");
            }

            foreach (var property in executionMetadataElement.EnumerateObject())
            {
                request.ExecutionMetadata[property.Name] = property.Value.Clone();
            }
        }

        if (document.RootElement.TryGetProperty("timeout_seconds", out var timeoutElement))
        {
            if (timeoutElement.ValueKind != JsonValueKind.Number
                || !timeoutElement.TryGetInt32(out var timeoutSeconds)
                || timeoutSeconds <= 0)
            {
                throw new InvalidOperationException("timeout_seconds must be a positive integer.");
            }

            request.TimeoutSeconds = timeoutSeconds;
        }

        request.Validate();
        return request;
    }

    /// <summary>
    /// 校验当前 invoke 请求的基础字段。
    /// </summary>
    internal void Validate()
    {
        if (TimeoutSeconds is not null && TimeoutSeconds.Value <= 0)
        {
            throw new InvalidOperationException("TimeoutSeconds must be greater than zero.");
        }
    }
}
