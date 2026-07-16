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
        /// 创建 WorkflowAppRuntime。
        /// </summary>
        public async Task<AMVisionApiResponse> CreateWorkflowAppRuntimeAsync(
            WorkflowAppRuntimeCreateRequest request,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/app-runtimes";
            var requestBody = SerializeJson(request);
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                requestPath,
                requestBody,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 创建 WorkflowAppRuntime，并返回 typed response。
        /// </summary>
        public async Task<WorkflowAppRuntimeResponse> CreateWorkflowAppRuntimeResponseAsync(
            WorkflowAppRuntimeCreateRequest request,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await CreateWorkflowAppRuntimeAsync(request, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowAppRuntimeResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 按 Project id 列出 WorkflowAppRuntime。
        /// </summary>
        public async Task<AMVisionApiResponse> ListWorkflowAppRuntimesAsync(
            string projectId,
            int offset = 0,
            int limit = 100,
            CancellationToken cancellationToken = default)
        {
            var path = WithQuery(
                $"{WorkflowApiPrefix}/app-runtimes",
                ("project_id", RequireId(projectId, nameof(projectId))),
                ("offset", offset),
                ("limit", limit));
            var apiResponse = await SendAsync(
                HttpMethod.Get,
                path,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 按 Project id 列出 WorkflowAppRuntime，并返回 typed responses。
        /// </summary>
        public async Task<IReadOnlyList<WorkflowAppRuntimeResponse>> ListWorkflowAppRuntimeResponsesAsync(
            string projectId,
            int offset = 0,
            int limit = 100,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await ListWorkflowAppRuntimesAsync(projectId, offset, limit, cancellationToken).ConfigureAwait(false);
            var typedResponses = ReadJsonList<WorkflowAppRuntimeResponse>(apiResponse);
            return typedResponses;
        }

        /// <summary>
        /// 读取一条 WorkflowAppRuntime。
        /// </summary>
        public async Task<AMVisionApiResponse> GetWorkflowAppRuntimeAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}";
            var apiResponse = await SendAsync(
                HttpMethod.Get,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 读取一条 WorkflowAppRuntime，并返回 typed response。
        /// </summary>
        public async Task<WorkflowAppRuntimeResponse> GetWorkflowAppRuntimeResponseAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetWorkflowAppRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowAppRuntimeResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 读取 WorkflowAppRuntime 事件。
        /// </summary>
        public async Task<AMVisionApiResponse> GetWorkflowAppRuntimeEventsAsync(
            string workflowRuntimeId,
            long? afterSequence = null,
            int? limit = null,
            CancellationToken cancellationToken = default)
        {
            var path = WithQuery(
                $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/events",
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
        /// 读取 WorkflowAppRuntime 事件，并返回 typed responses。
        /// </summary>
        public async Task<IReadOnlyList<WorkflowAppRuntimeEventResponse>> GetWorkflowAppRuntimeEventResponsesAsync(
            string workflowRuntimeId,
            long? afterSequence = null,
            int? limit = null,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetWorkflowAppRuntimeEventsAsync(workflowRuntimeId, afterSequence, limit, cancellationToken).ConfigureAwait(false);
            var typedResponses = ReadJsonList<WorkflowAppRuntimeEventResponse>(apiResponse);
            return typedResponses;
        }

        /// <summary>
        /// 启动一个 WorkflowAppRuntime。
        /// </summary>
        public async Task<AMVisionApiResponse> StartWorkflowAppRuntimeAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/start";
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 启动一个 WorkflowAppRuntime，并返回 typed response。
        /// </summary>
        public async Task<WorkflowAppRuntimeResponse> StartWorkflowAppRuntimeResponseAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await StartWorkflowAppRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowAppRuntimeResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 停止一个 WorkflowAppRuntime。
        /// </summary>
        public async Task<AMVisionApiResponse> StopWorkflowAppRuntimeAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/stop";
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 停止一个 WorkflowAppRuntime，并返回 typed response。
        /// </summary>
        public async Task<WorkflowAppRuntimeResponse> StopWorkflowAppRuntimeResponseAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await StopWorkflowAppRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowAppRuntimeResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 重启一个 WorkflowAppRuntime。
        /// </summary>
        public async Task<AMVisionApiResponse> RestartWorkflowAppRuntimeAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/restart";
            var apiResponse = await SendAsync(
                HttpMethod.Post,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 重启一个 WorkflowAppRuntime，并返回 typed response。
        /// </summary>
        public async Task<WorkflowAppRuntimeResponse> RestartWorkflowAppRuntimeResponseAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await RestartWorkflowAppRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowAppRuntimeResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 查询一个 WorkflowAppRuntime 的当前 health。
        /// </summary>
        public async Task<AMVisionApiResponse> GetWorkflowAppRuntimeHealthAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/health";
            var apiResponse = await SendAsync(
                HttpMethod.Get,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 查询一个 WorkflowAppRuntime 的当前 health，并返回 typed response。
        /// </summary>
        public async Task<WorkflowAppRuntimeResponse> GetWorkflowAppRuntimeHealthResponseAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await GetWorkflowAppRuntimeHealthAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false);
            var typedResponse = ReadJson<WorkflowAppRuntimeResponse>(apiResponse);
            return typedResponse;
        }

        /// <summary>
        /// 列出一个 WorkflowAppRuntime 的 worker instances。
        /// </summary>
        public async Task<AMVisionApiResponse> ListWorkflowAppRuntimeInstancesAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/instances";
            var apiResponse = await SendAsync(
                HttpMethod.Get,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }

        /// <summary>
        /// 列出一个 WorkflowAppRuntime 的 worker instances，并返回 typed responses。
        /// </summary>
        public async Task<IReadOnlyList<WorkflowAppRuntimeInstanceResponse>> ListWorkflowAppRuntimeInstanceResponsesAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var apiResponse = await ListWorkflowAppRuntimeInstancesAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false);
            var typedResponses = ReadJsonList<WorkflowAppRuntimeInstanceResponse>(apiResponse);
            return typedResponses;
        }

        /// <summary>
        /// 删除一条 WorkflowAppRuntime。
        /// </summary>
        public async Task<AMVisionApiResponse> DeleteWorkflowAppRuntimeAsync(
            string workflowRuntimeId,
            CancellationToken cancellationToken = default)
        {
            var requestPath = $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}";
            var apiResponse = await SendAsync(
                HttpMethod.Delete,
                requestPath,
                content: null,
                cancellationToken).ConfigureAwait(false);
            return apiResponse;
        }
    }
}
