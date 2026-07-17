using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision
{
    /// <summary>
    /// Amvar Vision HTTP SDK 客户端，负责封装后端 REST API 调用、认证、响应解析和传输异常处理。
    /// </summary>
    public sealed partial class AMVisionClient
    {
        /// <summary>
        /// 发送一条 HTTP 管理 API 请求。
        /// </summary>
        private async Task<AMVisionApiResponse> SendAsync(
            HttpMethod method,
            string relativePath,
            string? content,
            CancellationToken cancellationToken)
        {
            HttpContent? httpContent = null;
            if (content != null)
            {
                httpContent = new StringContent(content, Encoding.UTF8, "application/json");
            }

            var response = await SendAsync(method, relativePath, httpContent, cancellationToken).ConfigureAwait(false);
            return response;
        }

        /// <summary>
        /// 发送一条带自定义 HTTP content 的管理 API 请求。
        /// </summary>
        private async Task<AMVisionApiResponse> SendAsync(
            HttpMethod method,
            string relativePath,
            HttpContent? httpContent,
            CancellationToken cancellationToken)
        {
            EnsureClientNotDisposed();
            ValidateHttpRequest(method, relativePath);

            using var request = new HttpRequestMessage(method, relativePath);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", options.AccessToken.Trim());
            if (httpContent != null)
            {
                request.Content = httpContent;
            }

            try
            {
                using var response = await httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
                var responseText = await ReadResponseTextAsync(response).ConfigureAwait(false);
                var apiResponse = AMVisionApiResponse.Create(
                    response.StatusCode,
                    responseText,
                    method.Method,
                    relativePath);

                return apiResponse;
            }
            catch (TaskCanceledException ex) when (!cancellationToken.IsCancellationRequested)
            {
                throw new AMVisionTransportException(
                    "Amvar Vision HTTP request timed out.",
                    method,
                    relativePath,
                    ex);
            }
            catch (HttpRequestException ex)
            {
                throw new AMVisionTransportException(
                    "Amvar Vision HTTP request failed.",
                    method,
                    relativePath,
                    ex);
            }
            catch (InvalidOperationException ex)
            {
                throw new AMVisionTransportException(
                    "Amvar Vision HTTP request configuration is invalid.",
                    method,
                    relativePath,
                    ex);
            }
        }

        /// <summary>
        /// 序列化 JSON 请求体。
        /// </summary>
        private static string SerializeJson<T>(T payload)
        {
            if (payload is null)
            {
                throw new ArgumentNullException(nameof(payload));
            }
            return WorkflowJsonDefaults.Serialize(payload);
        }

        /// <summary>
        /// 读取 typed JSON 响应。
        /// </summary>
        private static T ReadJson<T>(AMVisionApiResponse response)
        {
            if (response is null)
            {
                throw new ArgumentNullException(nameof(response));
            }

            var value = response.ReadJson<T>(JsonSettings);
            return value;
        }

        /// <summary>
        /// 读取 typed JSON 数组响应。
        /// </summary>
        private static IReadOnlyList<T> ReadJsonList<T>(AMVisionApiResponse response)
        {
            if (response is null)
            {
                throw new ArgumentNullException(nameof(response));
            }

            var values = response.ReadJson<List<T>>(JsonSettings);
            return values;
        }

        /// <summary>
        /// 规范化 base API URL，确保结尾带斜杠。
        /// </summary>
        private static string NormalizeBaseApiUrl(string baseApiUrl)
        {
            return WorkflowHttpPath.NormalizeBaseApiUrl(baseApiUrl);
        }

        /// <summary>
        /// 拼接 query string。
        /// </summary>
        private static string WithQuery(string relativePath, params (string Name, object? Value)[] query)
        {
            return WorkflowHttpPath.WithQuery(relativePath, query);
        }

        /// <summary>
        /// 校验 id 字段非空。
        /// </summary>
        private static string RequireId(string value, string paramName)
        {
            return WorkflowHttpPath.RequireId(value, paramName);
        }

        /// <summary>
        /// 对路径片段做 URL 编码。
        /// </summary>
        private static string EncodePathSegment(string value)
        {
            return WorkflowHttpPath.EncodePathSegment(value);
        }

        /// <summary>
        /// 确认 client 尚未释放。
        /// </summary>
        private void EnsureClientNotDisposed()
        {
            if (Volatile.Read(ref disposed) != 0)
            {
                throw new ObjectDisposedException(nameof(AMVisionClient));
            }
        }

        /// <summary>
        /// 校验 HTTP 请求基础参数，避免空 path 或空 method 在底层抛出不直观异常。
        /// </summary>
        /// <param name="method">HTTP method。</param>
        /// <param name="relativePath">请求相对路径。</param>
        private static void ValidateHttpRequest(HttpMethod method, string relativePath)
        {
            if (method is null)
            {
                throw new ArgumentNullException(nameof(method));
            }

            if (string.IsNullOrWhiteSpace(relativePath))
            {
                throw new ArgumentException("HTTP request path cannot be empty.", nameof(relativePath));
            }
        }

        /// <summary>
        /// 读取 HTTP 响应文本。
        /// </summary>
        /// <param name="response">HTTP 响应对象。</param>
        /// <returns>响应文本；没有响应体时返回空字符串。</returns>
        private static async Task<string> ReadResponseTextAsync(HttpResponseMessage response)
        {
            if (response.Content is null)
            {
                return string.Empty;
            }

            var responseText = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
            return responseText;
        }
    }
}
