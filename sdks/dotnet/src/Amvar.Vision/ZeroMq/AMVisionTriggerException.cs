using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision
{

    /// <summary>
    /// TriggerSource 协议错误或服务错误对应的 SDK 异常。
    /// </summary>
    public class AMVisionTriggerException : Exception
    {
        /// <summary>
        /// 使用错误码、错误消息和可选详情创建 SDK 异常。
        /// </summary>
        /// <param name="errorCode">TriggerSource 错误码。</param>
        /// <param name="message">错误消息。</param>
        /// <param name="details">错误详情。</param>
        /// <param name="innerException">底层异常。</param>
        public AMVisionTriggerException(
            string errorCode,
            string message,
            IReadOnlyDictionary<string, JToken>? details = null,
            Exception? innerException = null,
            string? rawReplyJson = null)
            : base(message, innerException)
        {
            ErrorCode = errorCode;
            Details = details ?? new Dictionary<string, JToken>();
            RawReplyJson = rawReplyJson;
        }

        /// <summary>
        /// TriggerSource 错误码。
        /// </summary>
        public string ErrorCode { get; }

        /// <summary>
        /// TriggerSource 错误详情。
        /// </summary>
        public IReadOnlyDictionary<string, JToken> Details { get; }

        /// <summary>
        /// backend-service ZeroMQ adapter 返回的原始 reply JSON；传输失败或没有 reply 时为空。
        /// </summary>
        public string? RawReplyJson { get; }
    }

    /// <summary>
    /// TriggerSource 调用超时时的 SDK 异常。
    /// </summary>
    public sealed class AMVisionTriggerTimeoutException : AMVisionTriggerException
    {
        /// <summary>
        /// 使用超时消息创建 SDK timeout 异常。
        /// </summary>
        /// <param name="message">超时错误消息。</param>
        public AMVisionTriggerTimeoutException(string message)
            : base("timeout", message)
        {
        }
    }
}
