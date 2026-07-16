using System.Collections.Generic;
using System.Net;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision
{
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
            IReadOnlyDictionary<string, JToken>? details)
            : this(
                statusCode,
                errorCode,
                message,
                details,
                httpMethod: null,
                requestPath: null,
                responseBody: null,
                innerException: null)
        {
        }

        /// <summary>
        /// 初始化包含请求上下文的 HTTP 管理 API 异常。
        /// </summary>
        /// <param name="statusCode">HTTP 状态码。</param>
        /// <param name="errorCode">后端错误码。</param>
        /// <param name="message">错误消息。</param>
        /// <param name="details">错误详情。</param>
        /// <param name="httpMethod">HTTP method。</param>
        /// <param name="requestPath">请求相对路径。</param>
        /// <param name="responseBody">原始响应文本。</param>
        /// <param name="innerException">底层异常。</param>
        internal AmvisionWorkflowApiException(
            HttpStatusCode statusCode,
            string? errorCode,
            string message,
            IReadOnlyDictionary<string, JToken>? details,
            string? httpMethod,
            string? requestPath,
            string? responseBody,
            System.Exception? innerException)
            : base(BuildMessage(statusCode, message, httpMethod, requestPath), innerException)
        {
            StatusCode = statusCode;
            ErrorCode = errorCode;
            Details = details ?? new Dictionary<string, JToken>();
            HttpMethod = httpMethod;
            RequestPath = requestPath;
            ResponseBody = responseBody;
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
        public IReadOnlyDictionary<string, JToken> Details { get; }

        /// <summary>
        /// 触发异常的 HTTP method；调用方直接构造异常时为空。
        /// </summary>
        public string? HttpMethod { get; }

        /// <summary>
        /// 触发异常的 HTTP 相对路径；调用方直接构造异常时为空。
        /// </summary>
        public string? RequestPath { get; }

        /// <summary>
        /// 后端返回的原始响应文本；没有响应体时为空。
        /// </summary>
        public string? ResponseBody { get; }

        /// <summary>
        /// 构造包含状态码和请求路径的异常消息，便于现场日志定位。
        /// </summary>
        /// <param name="statusCode">HTTP 状态码。</param>
        /// <param name="message">后端错误消息。</param>
        /// <param name="httpMethod">HTTP method。</param>
        /// <param name="requestPath">请求相对路径。</param>
        /// <returns>带请求上下文的异常消息。</returns>
        private static string BuildMessage(
            HttpStatusCode statusCode,
            string message,
            string? httpMethod,
            string? requestPath)
        {
            var statusText = $"{(int)statusCode} {statusCode}";
            var baseMessage = string.IsNullOrWhiteSpace(message)
                ? $"AMVISION HTTP API returned {statusText}."
                : message;

            if (string.IsNullOrWhiteSpace(httpMethod) || string.IsNullOrWhiteSpace(requestPath))
            {
                return baseMessage;
            }

            return $"{baseMessage} ({httpMethod} {requestPath}, HTTP {statusText})";
        }
    }
}
