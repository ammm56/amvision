using System;
using System.Threading.Tasks;

namespace Amvar.Vision
{
    /// <summary>
    /// 不抛出调用边界：保留成功数据、后端 HTTP 错误响应或本地异常，由调用方自行判断。
    /// </summary>
    public sealed partial class AMVisionOperationRunner
    {
        public async Task<AMVisionCallResult<T>> CallAsync<T>(
            Func<AMVisionOperationRunner, Task<T>> operation)
        {
            if (operation == null)
            {
                return AMVisionCallResult<T>.FromException(new ArgumentNullException(nameof(operation)));
            }

            try
            {
                var data = await operation(this).ConfigureAwait(false);
                return AMVisionCallResult<T>.FromData(data);
            }
            catch (AMVisionApiException exception)
            {
                var response = AMVisionApiResponse.Create(
                    exception.StatusCode,
                    exception.ResponseBody ?? string.Empty,
                    exception.HttpMethod,
                    exception.RequestPath);
                return AMVisionCallResult<T>.FromHttpResponse(response);
            }
            catch (Exception exception)
            {
                return AMVisionCallResult<T>.FromException(exception);
            }
        }

        public AMVisionCallResult<T> Call<T>(Func<AMVisionOperationRunner, T> operation)
        {
            if (operation == null)
            {
                return AMVisionCallResult<T>.FromException(new ArgumentNullException(nameof(operation)));
            }

            try
            {
                return AMVisionCallResult<T>.FromData(operation(this));
            }
            catch (AMVisionApiException exception)
            {
                var response = AMVisionApiResponse.Create(
                    exception.StatusCode,
                    exception.ResponseBody ?? string.Empty,
                    exception.HttpMethod,
                    exception.RequestPath);
                return AMVisionCallResult<T>.FromHttpResponse(response);
            }
            catch (Exception exception)
            {
                return AMVisionCallResult<T>.FromException(exception);
            }
        }
    }
}
