using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows
{

    public sealed partial class AmvisionWorkflowClient
    {
        /// <summary>
        /// 发送一条 HTTP 管理 API 请求。
        /// </summary>
        private async Task<AmvisionWorkflowApiResponse> SendAsync(
            HttpMethod method,
            string relativePath,
            string? content,
            CancellationToken cancellationToken)
        {
            return await SendAsync(
                method,
                relativePath,
                content is null ? null : new StringContent(content, Encoding.UTF8, "application/json"),
                cancellationToken).ConfigureAwait(false);
        }

        /// <summary>
        /// 发送一条带自定义 HTTP content 的管理 API 请求。
        /// </summary>
        private async Task<AmvisionWorkflowApiResponse> SendAsync(
            HttpMethod method,
            string relativePath,
            HttpContent? httpContent,
            CancellationToken cancellationToken)
        {
            if (disposed)
            {
                throw new ObjectDisposedException(nameof(AmvisionWorkflowClient));
            }

            using var request = new HttpRequestMessage(method, relativePath);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", options.AccessToken.Trim());
            if (httpContent != null)
            {
                request.Content = httpContent;
            }

            using var response = await httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
            var responseText = response.Content is null
                ? string.Empty
                : await response.Content.ReadAsStringAsync().ConfigureAwait(false);
            return AmvisionWorkflowApiResponse.Create(response.StatusCode, responseText);
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
            return JsonSerializer.Serialize(payload, JsonOptions);
        }

        /// <summary>
        /// 读取 typed JSON 响应。
        /// </summary>
        private static T ReadJson<T>(AmvisionWorkflowApiResponse response)
        {
            return response.ReadJson<T>(JsonOptions);
        }

        /// <summary>
        /// 读取 typed JSON 数组响应。
        /// </summary>
        private static IReadOnlyList<T> ReadJsonList<T>(AmvisionWorkflowApiResponse response)
        {
            return response.ReadJson<List<T>>(JsonOptions);
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
    }
}
