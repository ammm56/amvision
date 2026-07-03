using System.Collections.Generic;
using System.Net;
using System.Text.Json;

namespace Amvision.Workflows;

/// <summary>
/// backend-service HTTP 管理 API 返回非 2xx 状态时抛出的 SDK 异常。
/// </summary>
public sealed class AmvisionWorkflowApiException : System.Exception
{
    /// <summary>
    /// 初始化 HTTP 管理 API 异常。
    /// </summary>
    /// <param name="statusCode">HTTP 状态码。</param>
    /// <param name="errorCode">后端错误码。</param>
    /// <param name="message">错误消息。</param>
    /// <param name="details">错误详情。</param>
    public AmvisionWorkflowApiException(
        HttpStatusCode statusCode,
        string? errorCode,
        string message,
        IReadOnlyDictionary<string, JsonElement> details)
        : base(message)
    {
        StatusCode = statusCode;
        ErrorCode = errorCode;
        Details = details;
    }

    /// <summary>
    /// HTTP 状态码。
    /// </summary>
    public HttpStatusCode StatusCode { get; }

    /// <summary>
    /// 后端错误码。
    /// </summary>
    public string? ErrorCode { get; }

    /// <summary>
    /// 后端错误详情。
    /// </summary>
    public IReadOnlyDictionary<string, JsonElement> Details { get; }
}
