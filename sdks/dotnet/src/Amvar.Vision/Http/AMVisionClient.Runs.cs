using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision
{

    public sealed partial class AMVisionClient
    {
        /// <summary>
        /// 创建一条异步 WorkflowRun。
        /// </summary>
        public async Task<AMVisionApiResponse> CreateWorkflowRunAsync(
            string workflowRuntimeId,
            WorkflowRuntimeInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            if (request is null)
            {
                throw new ArgumentNullException(nameof(request));
            }
            var requestPath = $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/runs";
            var requestBody = request.ToJson();
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                requestPath,
                requestBody,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 创建一条异步 WorkflowRun，并返回 typed response。
        /// </summary>
        public async Task<WorkflowRunResponse> CreateWorkflowRunResponseAsync(
            string workflowRuntimeId,
            WorkflowRuntimeInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await CreateWorkflowRunAsync(workflowRuntimeId, request, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowRunResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 通过 image-base64.v1 创建一条异步 WorkflowRun。
        /// </summary>
        public async Task<AMVisionApiResponse> CreateWorkflowRunWithImageBase64Async(
            string workflowRuntimeId,
            WorkflowRuntimeImageInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            if (request is null)
            {
                throw new ArgumentNullException(nameof(request));
            }

            var apiResponse = await CreateWorkflowRunAsync(
                workflowRuntimeId,
                request.ToWorkflowRuntimeInvokeRequest(),
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 通过 image-base64.v1 创建一条异步 WorkflowRun，并返回 typed response。
        /// </summary>
        public async Task<WorkflowRunResponse> CreateWorkflowRunWithImageBase64ResponseAsync(
            string workflowRuntimeId,
            WorkflowRuntimeImageInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await CreateWorkflowRunWithImageBase64Async(workflowRuntimeId, request, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowRunResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 通过 multipart/form-data 创建一条异步 WorkflowRun。
        /// </summary>
        public async Task<AMVisionApiResponse> CreateWorkflowRunUploadAsync(
            string workflowRuntimeId,
            WorkflowRuntimeMultipartInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            if (request is null)
            {
                throw new ArgumentNullException(nameof(request));
            }

            var requestPath = $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/runs/upload";
            var multipartContent = request.ToMultipartContent();
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                requestPath,
                multipartContent,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 通过 multipart/form-data 创建一条异步 WorkflowRun，并返回 typed response。
        /// </summary>
        public async Task<WorkflowRunResponse> CreateWorkflowRunUploadResponseAsync(
            string workflowRuntimeId,
            WorkflowRuntimeMultipartInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await CreateWorkflowRunUploadAsync(workflowRuntimeId, request, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowRunResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 通过通用 JSON 请求调用 WorkflowAppRuntime，默认返回 WorkflowRun 运行回执。
        /// </summary>
        public async Task<AMVisionApiResponse> InvokeWorkflowAppRuntimeAsync(
            string workflowRuntimeId,
            WorkflowRuntimeInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeAsync(
                workflowRuntimeId,
                request,
                WorkflowResponseModes.Run,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 通过通用 JSON 请求调用 WorkflowAppRuntime。
        /// </summary>
        public async Task<AMVisionApiResponse> InvokeWorkflowAppRuntimeAsync(
            string workflowRuntimeId,
            WorkflowRuntimeInvokeRequest request,
            string responseMode,
            CancellationToken cancellationToken = default)
        {
            if (request is null)
            {
                throw new ArgumentNullException(nameof(request));
            }
            var path = WithQuery(
                $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/invoke",
                ("response_mode", WorkflowResponseModes.Normalize(responseMode)));
            var requestBody = request.ToJson();
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                path,
                requestBody,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 通过通用 JSON 请求调用 WorkflowAppRuntime，并返回 WorkflowRun typed response。
        /// </summary>
        public async Task<WorkflowRunResponse> InvokeWorkflowAppRuntimeResponseAsync(
            string workflowRuntimeId,
            WorkflowRuntimeInvokeRequest request,
            string responseMode = WorkflowResponseModes.Run,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeAsync(workflowRuntimeId, request, responseMode, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowRunResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 通过通用 JSON 请求调用 WorkflowAppRuntime，并返回公开 app-result。
        /// </summary>
        public async Task<WorkflowAppResultResponse> InvokeWorkflowAppRuntimeAppResultResponseAsync(
            string workflowRuntimeId,
            WorkflowRuntimeInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeAsync(workflowRuntimeId, request, WorkflowResponseModes.AppResult, cancellationToken).ConfigureAwait(false);
            var appResult = WorkflowAppResultResponse.FromApiResponse(apiResponse);
            return appResult;
        }

        /// <summary>
        /// 通过通用 JSON 请求调用 WorkflowAppRuntime，并把公开 app-result 反序列化为业务类型。
        /// </summary>
        public async Task<T> InvokeWorkflowAppRuntimeAppResultAsync<T>(
            string workflowRuntimeId,
            WorkflowRuntimeInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeAsync(workflowRuntimeId, request, WorkflowResponseModes.AppResult, cancellationToken).ConfigureAwait(false);
            var appResult = WorkflowAppResultResponse.ReadFromApiResponse<T>(apiResponse);
            return appResult;
        }

        /// <summary>
        /// 通过 image-base64.v1 方式调用 WorkflowAppRuntime，默认返回 WorkflowRun 运行回执。
        /// </summary>
        public async Task<AMVisionApiResponse> InvokeWorkflowAppRuntimeWithImageBase64Async(
            string workflowRuntimeId,
            WorkflowRuntimeImageInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeWithImageBase64Async(
                workflowRuntimeId,
                request,
                WorkflowResponseModes.Run,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 通过 image-base64.v1 方式调用 WorkflowAppRuntime。
        /// </summary>
        public async Task<AMVisionApiResponse> InvokeWorkflowAppRuntimeWithImageBase64Async(
            string workflowRuntimeId,
            WorkflowRuntimeImageInvokeRequest request,
            string responseMode,
            CancellationToken cancellationToken = default)
        {
            if (request is null)
            {
                throw new ArgumentNullException(nameof(request));
            }
            var apiResponse = await InvokeWorkflowAppRuntimeAsync(
                workflowRuntimeId,
                request.ToWorkflowRuntimeInvokeRequest(),
                responseMode,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 通过 image-base64.v1 方式调用 WorkflowAppRuntime，并返回 WorkflowRun typed response。
        /// </summary>
        public async Task<WorkflowRunResponse> InvokeWorkflowAppRuntimeWithImageBase64ResponseAsync(
            string workflowRuntimeId,
            WorkflowRuntimeImageInvokeRequest request,
            string responseMode = WorkflowResponseModes.Run,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeWithImageBase64Async(workflowRuntimeId, request, responseMode, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowRunResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 通过 image-base64.v1 调用 WorkflowAppRuntime，并返回公开 app-result。
        /// </summary>
        public async Task<WorkflowAppResultResponse> InvokeWorkflowAppRuntimeWithImageBase64AppResultResponseAsync(
            string workflowRuntimeId,
            WorkflowRuntimeImageInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeWithImageBase64Async(workflowRuntimeId, request, WorkflowResponseModes.AppResult, cancellationToken).ConfigureAwait(false);
            var appResult = WorkflowAppResultResponse.FromApiResponse(apiResponse);
            return appResult;
        }

        /// <summary>
        /// 通过 image-base64.v1 调用 WorkflowAppRuntime，并把公开 app-result 反序列化为业务类型。
        /// </summary>
        public async Task<T> InvokeWorkflowAppRuntimeWithImageBase64AppResultAsync<T>(
            string workflowRuntimeId,
            WorkflowRuntimeImageInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeWithImageBase64Async(workflowRuntimeId, request, WorkflowResponseModes.AppResult, cancellationToken).ConfigureAwait(false);
            var appResult = WorkflowAppResultResponse.ReadFromApiResponse<T>(apiResponse);
            return appResult;
        }

        /// <summary>
        /// 通过 multipart/form-data 同步调用 WorkflowAppRuntime，默认返回 WorkflowRun 运行回执。
        /// </summary>
        public async Task<AMVisionApiResponse> InvokeWorkflowAppRuntimeUploadAsync(
            string workflowRuntimeId,
            WorkflowRuntimeMultipartInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeUploadAsync(
                workflowRuntimeId,
                request,
                WorkflowResponseModes.Run,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 通过 multipart/form-data 同步调用 WorkflowAppRuntime。
        /// </summary>
        public async Task<AMVisionApiResponse> InvokeWorkflowAppRuntimeUploadAsync(
            string workflowRuntimeId,
            WorkflowRuntimeMultipartInvokeRequest request,
            string responseMode,
            CancellationToken cancellationToken = default)
        {
            if (request is null)
            {
                throw new ArgumentNullException(nameof(request));
            }

            var path = WithQuery(
                $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/invoke/upload",
                ("response_mode", WorkflowResponseModes.Normalize(responseMode)));
            var multipartContent = request.ToMultipartContent();
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                path,
                multipartContent,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 通过 multipart/form-data 同步调用 WorkflowAppRuntime，并返回 WorkflowRun typed response。
        /// </summary>
        public async Task<WorkflowRunResponse> InvokeWorkflowAppRuntimeUploadResponseAsync(
            string workflowRuntimeId,
            WorkflowRuntimeMultipartInvokeRequest request,
            string responseMode = WorkflowResponseModes.Run,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeUploadAsync(workflowRuntimeId, request, responseMode, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowRunResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 通过 multipart/form-data 同步调用 WorkflowAppRuntime，并返回公开 app-result。
        /// </summary>
        public async Task<WorkflowAppResultResponse> InvokeWorkflowAppRuntimeUploadAppResultResponseAsync(
            string workflowRuntimeId,
            WorkflowRuntimeMultipartInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeUploadAsync(workflowRuntimeId, request, WorkflowResponseModes.AppResult, cancellationToken).ConfigureAwait(false);
            var appResult = WorkflowAppResultResponse.FromApiResponse(apiResponse);
            return appResult;
        }

        /// <summary>
        /// 通过 multipart/form-data 同步调用 WorkflowAppRuntime，并把公开 app-result 反序列化为业务类型。
        /// </summary>
        public async Task<T> InvokeWorkflowAppRuntimeUploadAppResultAsync<T>(
            string workflowRuntimeId,
            WorkflowRuntimeMultipartInvokeRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await InvokeWorkflowAppRuntimeUploadAsync(workflowRuntimeId, request, WorkflowResponseModes.AppResult, cancellationToken).ConfigureAwait(false);
            var appResult = WorkflowAppResultResponse.ReadFromApiResponse<T>(apiResponse);
            return appResult;
        }

        /// <summary>
        /// 读取一条 WorkflowRun，默认返回 WorkflowRun 运行回执。
        /// </summary>
        public async Task<AMVisionApiResponse> GetWorkflowRunAsync(
            string workflowRunId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetWorkflowRunAsync(
                workflowRunId,
                WorkflowResponseModes.Run,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 读取一条 WorkflowRun。
        /// </summary>
        public async Task<AMVisionApiResponse> GetWorkflowRunAsync(
            string workflowRunId,
            string responseMode,
            CancellationToken cancellationToken = default)
        {
            var path = WithQuery(
                $"{WorkflowApiPrefix}/runs/{EncodePathSegment(RequireId(workflowRunId, nameof(workflowRunId)))}",
                ("response_mode", WorkflowResponseModes.Normalize(responseMode)));
            var apiResponse = await SendAsync(
                HttpMethod.Get,
                path,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 读取一条 WorkflowRun，并返回 typed response。
        /// </summary>
        public async Task<WorkflowRunResponse> GetWorkflowRunResponseAsync(
            string workflowRunId,
            string responseMode = WorkflowResponseModes.Run,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetWorkflowRunAsync(workflowRunId, responseMode, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowRunResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 读取一条 WorkflowRun 的公开 app-result。
        /// </summary>
        public async Task<WorkflowAppResultResponse> GetWorkflowRunAppResultResponseAsync(
            string workflowRunId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetWorkflowRunAsync(workflowRunId, WorkflowResponseModes.AppResult, cancellationToken).ConfigureAwait(false);
            var appResult = WorkflowAppResultResponse.FromApiResponse(apiResponse);
            return appResult;
        }

        /// <summary>
        /// 读取一条 WorkflowRun 的公开 app-result，并反序列化为业务类型。
        /// </summary>
        public async Task<T> GetWorkflowRunAppResultAsync<T>(
            string workflowRunId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetWorkflowRunAsync(workflowRunId, WorkflowResponseModes.AppResult, cancellationToken).ConfigureAwait(false);
            var appResult = WorkflowAppResultResponse.ReadFromApiResponse<T>(apiResponse);
            return appResult;
        }

        /// <summary>
        /// 读取 WorkflowRun 事件。
        /// </summary>
        public async Task<AMVisionApiResponse> GetWorkflowRunEventsAsync(
            string workflowRunId,
            long? afterSequence = null,
            int? limit = null,
            CancellationToken cancellationToken = default)
        {
            var path = WithQuery(
                $"{WorkflowApiPrefix}/runs/{EncodePathSegment(RequireId(workflowRunId, nameof(workflowRunId)))}/events",
                ("after_sequence", afterSequence),
                ("limit", limit));
            var apiResponse = await SendAsync(
                HttpMethod.Get,
                path,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 读取 WorkflowRun 事件，并返回 typed responses。
        /// </summary>
        public async Task<IReadOnlyList<WorkflowRunEventResponse>> GetWorkflowRunEventResponsesAsync(
            string workflowRunId,
            long? afterSequence = null,
            int? limit = null,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetWorkflowRunEventsAsync(workflowRunId, afterSequence, limit, cancellationToken).ConfigureAwait(false);
            var typedResponses = ReadJsonList<WorkflowRunEventResponse>(apiResponse);
            return typedResponses;
        }

        /// <summary>
        /// 取消一条异步 WorkflowRun。
        /// </summary>
        public async Task<AMVisionApiResponse> CancelWorkflowRunAsync(
            string workflowRunId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/runs/{EncodePathSegment(RequireId(workflowRunId, nameof(workflowRunId)))}/cancel";
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 取消一条异步 WorkflowRun，并返回 typed response。
        /// </summary>
        public async Task<WorkflowRunResponse> CancelWorkflowRunResponseAsync(
            string workflowRunId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await CancelWorkflowRunAsync(workflowRunId, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowRunResponse>(apiResponse);
            return typedResponse;
        }
    }
}
