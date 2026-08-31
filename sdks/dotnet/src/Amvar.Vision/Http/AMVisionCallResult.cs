using System;
using Amvar.Vision.SharedMemory;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision
{
    /// <summary>
    /// 保留一次 SDK 调用的原始结果，不替调用方判断成功、失败或异常。
    /// 三个属性中只会有一个非空：Data、HttpResponse 或 Exception。
    /// </summary>
    /// <typeparam name="T">后端成功响应映射的数据类型。</typeparam>
    public sealed class AMVisionCallResult<T>
    {
        private AMVisionCallResult(T data, AMVisionApiResponse? httpResponse, Exception? exception)
        {
            Data = data;
            HttpResponse = httpResponse;
            Exception = exception;
        }

        /// <summary>
        /// 后端正常响应映射的数据；没有正常数据时为空。
        /// </summary>
        [JsonProperty("data")]
        public T Data { get; }

        /// <summary>
        /// 后端非 2xx HTTP 响应，包含原始状态码、正文和 JSON；没有 HTTP 错误响应时为空。
        /// </summary>
        [JsonProperty("httpresponse")]
        public AMVisionApiResponse? HttpResponse { get; }

        /// <summary>
        /// 没有后端响应时发生的配置、参数、超时、网络或协议异常；没有异常时为空。
        /// </summary>
        [JsonProperty("exception")]
        [JsonConverter(typeof(AMVisionCallExceptionJsonConverter))]
        public Exception? Exception { get; }

        internal static AMVisionCallResult<T> FromData(T data)
        {
            return new AMVisionCallResult<T>(data, null, null);
        }

        internal static AMVisionCallResult<T> FromHttpResponse(AMVisionApiResponse response)
        {
            return new AMVisionCallResult<T>(default!, response, null);
        }

        internal static AMVisionCallResult<T> FromException(Exception exception)
        {
            return new AMVisionCallResult<T>(default!, null, exception);
        }
    }

    /// <summary>
    /// 把异常稳定序列化为全小写字段，同时保留 C# Exception 调用边界。
    /// </summary>
    internal sealed class AMVisionCallExceptionJsonConverter : JsonConverter
    {
        private const int MaxInnerExceptionDepth = 8;

        public override bool CanRead => false;

        public override bool CanConvert(Type objectType)
        {
            return typeof(Exception).IsAssignableFrom(objectType);
        }

        public override object? ReadJson(
            JsonReader reader,
            Type objectType,
            object? existingValue,
            JsonSerializer serializer)
        {
            throw new NotSupportedException("AMVision call exceptions are output-only JSON values.");
        }

        public override void WriteJson(
            JsonWriter writer,
            object? value,
            JsonSerializer serializer)
        {
            if (!(value is Exception exception))
            {
                writer.WriteNull();
                return;
            }

            BuildException(exception, depth: 0).WriteTo(writer);
        }

        private static JObject BuildException(Exception exception, int depth)
        {
            var result = new JObject
            {
                ["type"] = exception.GetType().FullName ?? exception.GetType().Name,
                ["message"] = exception.Message,
                ["source"] = StringOrNull(exception.Source),
                ["stacktrace"] = StringOrNull(exception.StackTrace),
                ["hresult"] = exception.HResult
            };

            AddSdkExceptionDetails(result, exception);

            if (exception.InnerException == null)
            {
                result["innerexception"] = JValue.CreateNull();
            }
            else if (depth >= MaxInnerExceptionDepth)
            {
                result["innerexception"] = new JObject
                {
                    ["type"] = exception.InnerException.GetType().FullName
                        ?? exception.InnerException.GetType().Name,
                    ["message"] = exception.InnerException.Message,
                    ["truncated"] = true
                };
            }
            else
            {
                result["innerexception"] = BuildException(exception.InnerException, depth + 1);
            }

            return result;
        }

        private static void AddSdkExceptionDetails(JObject result, Exception exception)
        {
            if (exception is AMVisionApiException apiException)
            {
                result["statuscode"] = (int)apiException.StatusCode;
                result["errorcode"] = StringOrNull(apiException.ErrorCode);
                result["details"] = CopyDetails(apiException.Details);
                result["httpmethod"] = StringOrNull(apiException.HttpMethod);
                result["requestpath"] = StringOrNull(apiException.RequestPath);
                result["responsebody"] = StringOrNull(apiException.ResponseBody);
                return;
            }

            if (exception is AMVisionTriggerException triggerException)
            {
                result["errorcode"] = triggerException.ErrorCode;
                result["details"] = CopyDetails(triggerException.Details);
                result["rawreplyjson"] = StringOrNull(triggerException.RawReplyJson);
                return;
            }

            if (exception is SharedMemoryTriggerException sharedMemoryException)
            {
                result["errorcode"] = sharedMemoryException.ErrorCode;
                return;
            }

            if (exception is AMVisionTransportException transportException)
            {
                result["httpmethod"] = transportException.HttpMethod;
                result["requestpath"] = transportException.RequestPath;
            }
        }

        private static JObject CopyDetails(
            System.Collections.Generic.IReadOnlyDictionary<string, JToken> details)
        {
            var result = new JObject();
            foreach (var item in details)
            {
                result[item.Key] = item.Value.DeepClone();
            }

            return result;
        }

        private static JToken StringOrNull(string? value)
        {
            return value == null ? JValue.CreateNull() : new JValue(value);
        }
    }
}
