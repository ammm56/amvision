using System;
using System.Net.Http;

namespace Amvision.Workflows
{
    /// <summary>
    /// backend-service HTTP 请求在网络、超时或客户端发送阶段失败时抛出的 SDK 异常。
    /// </summary>
    public sealed class AmvisionWorkflowTransportException : Exception
    {
        /// <summary>
        /// 初始化传输层异常。
        /// </summary>
        /// <param name="message">错误消息。</param>
        /// <param name="method">HTTP method。</param>
        /// <param name="requestPath">请求相对路径。</param>
        /// <param name="innerException">底层异常。</param>
        public AmvisionWorkflowTransportException(
            string message,
            HttpMethod method,
            string requestPath,
            Exception innerException)
            : base(BuildMessage(message, method, requestPath), RequireInnerException(innerException))
        {
            HttpMethod = GetMethodName(method);
            RequestPath = NormalizeRequestPath(requestPath);
        }

        /// <summary>
        /// 触发异常的 HTTP method。
        /// </summary>
        public string HttpMethod { get; }

        /// <summary>
        /// 触发异常的 HTTP 相对路径。
        /// </summary>
        public string RequestPath { get; }

        /// <summary>
        /// 构造包含请求上下文的异常消息。
        /// </summary>
        /// <param name="message">错误消息。</param>
        /// <param name="method">HTTP method。</param>
        /// <param name="requestPath">请求相对路径。</param>
        /// <returns>带请求上下文的异常消息。</returns>
        private static string BuildMessage(string message, HttpMethod method, string requestPath)
        {
            var normalizedMessage = string.IsNullOrWhiteSpace(message)
                ? "AMVISION HTTP 请求发送失败。"
                : message;
            var methodName = GetMethodName(method);
            var normalizedPath = NormalizeRequestPath(requestPath);

            return $"{normalizedMessage} ({methodName} {normalizedPath})";
        }

        /// <summary>
        /// 获取可用于日志输出的 HTTP method 名称。
        /// </summary>
        /// <param name="method">HTTP method。</param>
        /// <returns>HTTP method 名称；缺失时返回占位符。</returns>
        private static string GetMethodName(HttpMethod method)
        {
            return method == null ? "-" : method.Method;
        }

        /// <summary>
        /// 规范化请求路径，避免异常消息出现空白路径。
        /// </summary>
        /// <param name="requestPath">请求相对路径。</param>
        /// <returns>规范化后的请求相对路径。</returns>
        private static string NormalizeRequestPath(string requestPath)
        {
            return string.IsNullOrWhiteSpace(requestPath) ? "-" : requestPath;
        }

        /// <summary>
        /// 确保传输异常始终保留原始底层异常。
        /// </summary>
        /// <param name="innerException">底层异常。</param>
        /// <returns>非空的底层异常。</returns>
        private static Exception RequireInnerException(Exception innerException)
        {
            if (innerException == null)
            {
                throw new ArgumentNullException(nameof(innerException));
            }

            return innerException;
        }
    }
}
