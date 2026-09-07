using System;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision
{

    /// <summary>
    /// WorkflowAppRuntime 对外 app-result 响应。
    /// </summary>
    public sealed class WorkflowAppResultResponse
    {
        /// <summary>Workflow App Result 格式 id。</summary>
        public const string FormatIdValue = "amvision.workflow-app-result.v1";

        /// <summary>
        /// 初始化 app-result 响应。
        /// </summary>
        /// <param name="bodyJson">后端返回的公开结果 JSON 根节点。</param>
        public WorkflowAppResultResponse(JToken bodyJson)
        {
            if (!(bodyJson is JObject root))
            {
                throw new JsonException("Workflow app result response root must be a JSON object.");
            }

            FormatId = root.Value<string>("format_id") ?? string.Empty;
            WorkflowRunId = root.Value<string>("workflow_run_id") ?? string.Empty;
            State = root.Value<string>("state") ?? string.Empty;
            Results = root["results"] is JObject results
                ? (JObject)results.DeepClone()
                : throw new JsonException("Workflow app result response results must be a JSON object.");
            Error = root["error"] == null || root["error"]!.Type == JTokenType.Null
                ? null
                : root["error"]!.ToObject<AMVisionErrorContract>()
                    ?? throw new JsonException("Workflow app result response error is invalid.");
            BodyJson = root.DeepClone();

            if (!string.Equals(FormatId, FormatIdValue, StringComparison.Ordinal))
            {
                throw new JsonException("Workflow app result response format_id is invalid.");
            }
            if (string.IsNullOrWhiteSpace(WorkflowRunId) || string.IsNullOrWhiteSpace(State))
            {
                throw new JsonException("Workflow app result response identity or state is missing.");
            }

            var isErrorState = string.Equals(State, "failed", StringComparison.Ordinal)
                || string.Equals(State, "timed_out", StringComparison.Ordinal)
                || string.Equals(State, "cancelled", StringComparison.Ordinal);
            if (isErrorState != (Error != null))
            {
                throw new JsonException("Workflow app result response state and error are inconsistent.");
            }
            if (!string.Equals(State, "succeeded", StringComparison.Ordinal) && Results.HasValues)
            {
                throw new JsonException("Workflow app result response contains results for a non-success state.");
            }
            if (Error != null
                && (string.IsNullOrWhiteSpace(Error.Code)
                    || string.IsNullOrWhiteSpace(Error.Message)
                    || Error.Details == null))
            {
                throw new JsonException("Workflow app result response error is incomplete.");
            }
        }

        /// <summary>结果格式 id。</summary>
        [JsonProperty("format_id")]
        public string FormatId { get; }

        /// <summary>WorkflowRun id。</summary>
        [JsonProperty("workflow_run_id")]
        public string WorkflowRunId { get; }

        /// <summary>执行状态。</summary>
        [JsonProperty("state")]
        public string State { get; }

        /// <summary>按 App Result binding id 组织的结果。</summary>
        [JsonProperty("results")]
        public JObject Results { get; }

        /// <summary>错误对象；成功时为 null。</summary>
        [JsonProperty("error")]
        public AMVisionErrorContract? Error { get; }

        /// <summary>后端返回的完整 JSON，仅供诊断和兼容读取。</summary>
        [JsonIgnore]
        public JToken BodyJson { get; }

        /// <summary>
        /// 把完整 results 对象反序列化为指定业务类型。
        /// </summary>
        public T ReadAs<T>(JsonSerializerSettings? settings = null)
        {
            var serializer = JsonSerializer.Create(settings ?? WorkflowJsonDefaults.SerializerSettings);
            var value = Results.ToObject<T>(serializer);
            return value is null
                ? throw new JsonException($"Workflow app results cannot be deserialized as {typeof(T).Name}.")
                : value;
        }

        /// <summary>按明确的 binding id 读取一个业务结果。</summary>
        public T ReadBindingAs<T>(string bindingId, JsonSerializerSettings? settings = null)
        {
            if (string.IsNullOrWhiteSpace(bindingId))
            {
                throw new ArgumentException("bindingId cannot be empty.", nameof(bindingId));
            }
            if (!Results.TryGetValue(bindingId, StringComparison.Ordinal, out var result))
            {
                throw new JsonException($"Workflow app result binding '{bindingId}' does not exist.");
            }

            var serializer = JsonSerializer.Create(settings ?? WorkflowJsonDefaults.SerializerSettings);
            var value = result.ToObject<T>(serializer);
            return value is null
                ? throw new JsonException($"Workflow app result binding '{bindingId}' cannot be deserialized as {typeof(T).Name}.")
                : value;
        }

        /// <summary>
        /// 从原始 API 响应构造 app-result 响应。
        /// </summary>
        internal static WorkflowAppResultResponse FromApiResponse(AMVisionApiResponse response)
        {
            response.EnsureSuccessStatusCode();
            if (response.BodyJson is null)
            {
                throw new JsonException("Workflow app result response body is not JSON.");
            }

            return new WorkflowAppResultResponse(response.BodyJson);
        }

        /// <summary>
        /// 从原始 API 响应直接读取业务类型。
        /// </summary>
        internal static T ReadFromApiResponse<T>(AMVisionApiResponse response)
        {
            return FromApiResponse(response).ReadAs<T>();
        }
    }
}
