using System;

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
        public T Data { get; }

        /// <summary>
        /// 后端非 2xx HTTP 响应，包含原始状态码、正文和 JSON；没有 HTTP 错误响应时为空。
        /// </summary>
        public AMVisionApiResponse? HttpResponse { get; }

        /// <summary>
        /// 没有后端响应时发生的配置、参数、超时、网络或协议异常；没有异常时为空。
        /// </summary>
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
}
