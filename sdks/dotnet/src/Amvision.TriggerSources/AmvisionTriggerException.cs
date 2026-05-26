using System;
using System.Collections.Generic;
using System.Text.Json;

namespace Amvision.TriggerSources;

/// <summary>
/// TriggerSource 协议错误或服务错误对应的 SDK 异常。
/// </summary>
public class AmvisionTriggerException : Exception
{
    /// <summary>
    /// 使用错误码、错误消息和可选详情创建 SDK 异常。
    /// </summary>
    /// <param name="errorCode">TriggerSource 错误码。</param>
    /// <param name="message">错误消息。</param>
    /// <param name="details">错误详情。</param>
    public AmvisionTriggerException(string errorCode, string message, IReadOnlyDictionary<string, JsonElement>? details = null)
        : base(message)
    {
        ErrorCode = errorCode;
        Details = details ?? new Dictionary<string, JsonElement>();
    }

    /// <summary>
    /// TriggerSource 错误码。
    /// </summary>
    public string ErrorCode { get; }

    /// <summary>
    /// TriggerSource 错误详情。
    /// </summary>
    public IReadOnlyDictionary<string, JsonElement> Details { get; }
}

/// <summary>
/// TriggerSource 调用超时时的 SDK 异常。
/// </summary>
public sealed class AmvisionTriggerTimeoutException : AmvisionTriggerException
{
    /// <summary>
    /// 使用超时消息创建 SDK timeout 异常。
    /// </summary>
    /// <param name="message">超时错误消息。</param>
    public AmvisionTriggerTimeoutException(string message)
        : base("timeout", message)
    {
    }
}