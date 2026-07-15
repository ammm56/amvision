using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvision.Workflows
{

    /// <summary>
    /// WorkflowAppRuntime 对外 app-result 响应。
    /// </summary>
    public sealed class WorkflowAppResultResponse
    {
        /// <summary>
        /// 初始化 app-result 响应。
        /// </summary>
        /// <param name="bodyJson">后端返回的公开结果 JSON 根节点。</param>
        public WorkflowAppResultResponse(JToken bodyJson)
        {
            BodyJson = bodyJson.DeepClone();
        }

        /// <summary>
        /// 后端返回的公开结果 JSON 根节点。
        /// </summary>
        public JToken BodyJson { get; }

        /// <summary>
        /// 把公开结果 JSON 反序列化为指定业务类型。
        /// </summary>
        public T ReadAs<T>(JsonSerializerSettings? settings = null)
        {
            var serializer = JsonSerializer.Create(settings ?? WorkflowJsonDefaults.SerializerSettings);
            var value = BodyJson.ToObject<T>(serializer);
            return value is null
                ? throw new JsonException($"Workflow app result cannot be deserialized as {typeof(T).Name}.")
                : value;
        }

        /// <summary>
        /// 从原始 API 响应构造 app-result 响应。
        /// </summary>
        internal static WorkflowAppResultResponse FromApiResponse(AmvisionWorkflowApiResponse response)
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
        internal static T ReadFromApiResponse<T>(AmvisionWorkflowApiResponse response)
        {
            return FromApiResponse(response).ReadAs<T>();
        }
    }
}
