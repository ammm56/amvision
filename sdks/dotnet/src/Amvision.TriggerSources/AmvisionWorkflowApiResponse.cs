using System.Collections.Generic;
using System.Net;
using System.Text.Json;

namespace Amvision.TriggerSources;

/// <summary>
/// 描述 backend-service HTTP 控制面调用返回的 JSON 响应。
/// </summary>
public sealed class AmvisionWorkflowApiResponse
{
    private AmvisionWorkflowApiResponse(
        HttpStatusCode statusCode,
        string content,
        JsonElement? bodyJson,
        string? errorCode,
        string? errorMessage,
        IReadOnlyDictionary<string, JsonElement> errorDetails)
    {
        StatusCode = statusCode;
        Content = content;
        BodyJson = bodyJson;
        ErrorCode = errorCode;
        ErrorMessage = errorMessage;
        ErrorDetails = errorDetails;
    }

    /// <summary>
    /// HTTP 状态码。
    /// </summary>
    public HttpStatusCode StatusCode { get; }

    /// <summary>
    /// 是否为 2xx 成功响应。
    /// </summary>
    public bool IsSuccessStatusCode => (int)StatusCode is >= 200 and <= 299;

    /// <summary>
    /// 原始响应文本。
    /// </summary>
    public string Content { get; }

    /// <summary>
    /// 解析后的 JSON 根元素；非 JSON 响应时为空。
    /// </summary>
    public JsonElement? BodyJson { get; }

    /// <summary>
    /// backend-service 错误码；非错误响应或无法解析时为空。
    /// </summary>
    public string? ErrorCode { get; }

    /// <summary>
    /// backend-service 错误消息；非错误响应或无法解析时为空。
    /// </summary>
    public string? ErrorMessage { get; }

    /// <summary>
    /// backend-service 错误详情；非错误响应时为空字典。
    /// </summary>
    public IReadOnlyDictionary<string, JsonElement> ErrorDetails { get; }

    /// <summary>
    /// 按 HTTP 响应状态和文本构造 SDK 响应对象。
    /// </summary>
    /// <param name="statusCode">HTTP 状态码。</param>
    /// <param name="content">响应文本。</param>
    /// <returns>解析后的 SDK 响应。</returns>
    internal static AmvisionWorkflowApiResponse Create(HttpStatusCode statusCode, string content)
    {
        JsonElement? bodyJson = null;
        string? errorCode = null;
        string? errorMessage = null;
        var errorDetails = new Dictionary<string, JsonElement>();

        if (!string.IsNullOrWhiteSpace(content))
        {
            try
            {
                using var document = JsonDocument.Parse(content);
                bodyJson = document.RootElement.Clone();
                if (bodyJson is JsonElement root && root.ValueKind == JsonValueKind.Object)
                {
                    if (root.TryGetProperty("error", out var errorElement)
                        && errorElement.ValueKind == JsonValueKind.Object)
                    {
                        errorCode = TryReadStringProperty(errorElement, "code");
                        errorMessage = TryReadStringProperty(errorElement, "message");
                        if (errorElement.TryGetProperty("details", out var detailsElement)
                            && detailsElement.ValueKind == JsonValueKind.Object)
                        {
                            foreach (var property in detailsElement.EnumerateObject())
                            {
                                errorDetails[property.Name] = property.Value.Clone();
                            }
                        }
                    }
                    else if (root.TryGetProperty("error_code", out _))
                    {
                        errorCode = TryReadStringProperty(root, "error_code");
                        errorMessage = TryReadStringProperty(root, "error_message");
                    }
                }
            }
            catch (JsonException)
            {
            }
        }

        return new AmvisionWorkflowApiResponse(
            statusCode,
            content,
            bodyJson,
            errorCode,
            errorMessage,
            errorDetails
        );
    }

    /// <summary>
    /// 读取 JSON 对象中的字符串字段。
    /// </summary>
    /// <param name="root">JSON 对象。</param>
    /// <param name="propertyName">字段名。</param>
    /// <returns>字段字符串值或空。</returns>
    private static string? TryReadStringProperty(JsonElement root, string propertyName)
    {
        return root.TryGetProperty(propertyName, out var property)
            && property.ValueKind == JsonValueKind.String
            ? property.GetString()
            : null;
    }
}