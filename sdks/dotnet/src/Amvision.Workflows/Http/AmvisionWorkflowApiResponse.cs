using System.Collections.Generic;
using System.Net;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
namespace Amvision.Workflows
{

    /// <summary>
    /// 描述 backend-service HTTP 管理 API 调用返回的 JSON 响应。
    /// </summary>
    public sealed class AmvisionWorkflowApiResponse
    {
        private AmvisionWorkflowApiResponse(
            HttpStatusCode statusCode,
            string content,
            JToken? bodyJson,
            string? errorCode,
            string? errorMessage,
            IReadOnlyDictionary<string, JToken> errorDetails)
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
        public bool IsSuccessStatusCode => (int)StatusCode >= 200 && (int)StatusCode <= 299;

        /// <summary>
        /// 原始响应文本。
        /// </summary>
        public string Content { get; }

        /// <summary>
        /// 解析后的 JSON 根元素；非 JSON 响应时为空。
        /// </summary>
        public JToken? BodyJson { get; }

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
        public IReadOnlyDictionary<string, JToken> ErrorDetails { get; }

        /// <summary>
        /// 非 2xx 响应时抛出 <see cref="AmvisionWorkflowApiException" />。
        /// </summary>
        public void EnsureSuccessStatusCode()
        {
            if (IsSuccessStatusCode)
            {
                return;
            }

            throw new AmvisionWorkflowApiException(
                StatusCode,
                ErrorCode,
                ErrorMessage ?? Content,
                ErrorDetails);
        }

        /// <summary>
        /// 把响应 JSON 反序列化为指定类型。
        /// </summary>
        /// <typeparam name="T">目标类型。</typeparam>
        /// <param name="settings">可选 JSON 选项。</param>
        /// <returns>反序列化后的对象。</returns>
        public T ReadJson<T>(JsonSerializerSettings? settings = null)
        {
            EnsureSuccessStatusCode();
            if (!(BodyJson is JToken bodyJson))
            {
                throw new JsonException("HTTP response body is not JSON.");
            }

            var serializer = JsonSerializer.Create(settings ?? WorkflowJsonDefaults.SerializerSettings);
            var value = bodyJson.ToObject<T>(serializer);
            return value is null
                ? throw new JsonException("HTTP response body cannot be deserialized as " + typeof(T).Name + ".")
                : value;
        }

        /// <summary>
        /// 按 HTTP 响应状态和文本构造 SDK 响应对象。
        /// </summary>
        /// <param name="statusCode">HTTP 状态码。</param>
        /// <param name="content">响应文本。</param>
        /// <returns>解析后的 SDK 响应。</returns>
        internal static AmvisionWorkflowApiResponse Create(HttpStatusCode statusCode, string content)
        {
            JToken? bodyJson = null;
            string? errorCode = null;
            string? errorMessage = null;
            var errorDetails = new Dictionary<string, JToken>();

            if (!string.IsNullOrWhiteSpace(content))
            {
                try
                {
                    bodyJson = JToken.Parse(content);
                    if (bodyJson is JObject root)
                    {
                        if (root["error"] is JObject errorElement)
                        {
                            errorCode = TryReadStringProperty(errorElement, "code");
                            errorMessage = TryReadStringProperty(errorElement, "message");
                            if (errorElement["details"] is JObject detailsElement)
                            {
                                foreach (var property in detailsElement.Properties())
                                {
                                    errorDetails[property.Name] = property.Value.DeepClone();
                                }
                            }
                        }
                        else if (root["error_code"] != null)
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
        private static string? TryReadStringProperty(JObject root, string propertyName)
        {
            var property = root[propertyName];
            return property != null && property.Type == JTokenType.String
                ? property.Value<string>()
                : null;
        }
    }
}
