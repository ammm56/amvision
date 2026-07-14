using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows
{

    public sealed partial class AmvisionWorkflowClient
    {
        /// <summary>
        /// 使用 JSON 请求执行模型部署同步推理。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> InferModelDeploymentAsync(
            string taskType,
            string deploymentInstanceId,
            ModelDeploymentInferenceRequest request,
            CancellationToken cancellationToken = default)
        {
            if (request is null)
            {
                throw new ArgumentNullException(nameof(request));
            }

            request.ValidateForDirectInference();
            return SendAsync(
                HttpMethod.Post,
                BuildModelDeploymentInferencePath(taskType, deploymentInstanceId),
                SerializeJson(request),
                cancellationToken);
        }

        /// <summary>
        /// 使用 JSON 请求执行模型部署同步推理，并返回 typed response。
        /// </summary>
        public async Task<ModelDeploymentInferenceResponse> InferModelDeploymentResponseAsync(
            string taskType,
            string deploymentInstanceId,
            ModelDeploymentInferenceRequest request,
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelDeploymentInferenceResponse>(
                await InferModelDeploymentAsync(taskType, deploymentInstanceId, request, cancellationToken).ConfigureAwait(false));
        }

        /// <summary>
        /// 使用 image_base64 执行模型部署同步推理。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> InferModelDeploymentWithImageBase64Async(
            string taskType,
            string deploymentInstanceId,
            string imageBase64,
            CancellationToken cancellationToken = default)
        {
            return InferModelDeploymentAsync(
                taskType,
                deploymentInstanceId,
                ModelDeploymentInferenceRequest.FromBase64(imageBase64),
                cancellationToken);
        }

        /// <summary>
        /// 使用 image_base64 执行模型部署同步推理，并返回 typed response。
        /// </summary>
        public async Task<ModelDeploymentInferenceResponse> InferModelDeploymentWithImageBase64ResponseAsync(
            string taskType,
            string deploymentInstanceId,
            string imageBase64,
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelDeploymentInferenceResponse>(
                await InferModelDeploymentWithImageBase64Async(taskType, deploymentInstanceId, imageBase64, cancellationToken).ConfigureAwait(false));
        }

        /// <summary>
        /// 使用 multipart/form-data 上传图片执行模型部署同步推理。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> InferModelDeploymentUploadAsync(
            string taskType,
            string deploymentInstanceId,
            ModelDeploymentInferenceUploadRequest request,
            CancellationToken cancellationToken = default)
        {
            if (request is null)
            {
                throw new ArgumentNullException(nameof(request));
            }

            return SendAsync(
                HttpMethod.Post,
                BuildModelDeploymentInferencePath(taskType, deploymentInstanceId),
                request.ToDirectInferenceContent(),
                cancellationToken);
        }

        /// <summary>
        /// 使用 multipart/form-data 上传图片执行模型部署同步推理，并返回 typed response。
        /// </summary>
        public async Task<ModelDeploymentInferenceResponse> InferModelDeploymentUploadResponseAsync(
            string taskType,
            string deploymentInstanceId,
            ModelDeploymentInferenceUploadRequest request,
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelDeploymentInferenceResponse>(
                await InferModelDeploymentUploadAsync(taskType, deploymentInstanceId, request, cancellationToken).ConfigureAwait(false));
        }

        /// <summary>
        /// 使用图片 bytes 执行模型部署同步推理。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> InferModelDeploymentWithImageBytesAsync(
            string taskType,
            string deploymentInstanceId,
            byte[] imageBytes,
            string fileName = "input-image.bin",
            string mediaType = "application/octet-stream",
            CancellationToken cancellationToken = default)
        {
            return InferModelDeploymentUploadAsync(
                taskType,
                deploymentInstanceId,
                ModelDeploymentInferenceUploadRequest.FromBytes(imageBytes, fileName, mediaType),
                cancellationToken);
        }

        /// <summary>
        /// 使用图片 bytes 执行模型部署同步推理，并返回 typed response。
        /// </summary>
        public async Task<ModelDeploymentInferenceResponse> InferModelDeploymentWithImageBytesResponseAsync(
            string taskType,
            string deploymentInstanceId,
            byte[] imageBytes,
            string fileName = "input-image.bin",
            string mediaType = "application/octet-stream",
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelDeploymentInferenceResponse>(
                await InferModelDeploymentWithImageBytesAsync(
                    taskType,
                    deploymentInstanceId,
                    imageBytes,
                    fileName,
                    mediaType,
                    cancellationToken).ConfigureAwait(false));
        }

        /// <summary>
        /// 使用本机图片文件执行模型部署同步推理。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> InferModelDeploymentWithImageFileAsync(
            string taskType,
            string deploymentInstanceId,
            string filePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return InferModelDeploymentUploadAsync(
                taskType,
                deploymentInstanceId,
                ModelDeploymentInferenceUploadRequest.FromFile(filePath, mediaType),
                cancellationToken);
        }

        /// <summary>
        /// 使用本机图片文件执行模型部署同步推理，并返回 typed response。
        /// </summary>
        public async Task<ModelDeploymentInferenceResponse> InferModelDeploymentWithImageFileResponseAsync(
            string taskType,
            string deploymentInstanceId,
            string filePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelDeploymentInferenceResponse>(
                await InferModelDeploymentWithImageFileAsync(
                    taskType,
                    deploymentInstanceId,
                    filePath,
                    mediaType,
                    cancellationToken).ConfigureAwait(false));
        }

        /// <summary>
        /// 使用 JSON 请求创建模型异步推理任务。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> CreateModelInferenceTaskAsync(
            string taskType,
            ModelDeploymentInferenceRequest request,
            CancellationToken cancellationToken = default)
        {
            if (request is null)
            {
                throw new ArgumentNullException(nameof(request));
            }

            request.ValidateForInferenceTask();
            return SendAsync(
                HttpMethod.Post,
                BuildModelInferenceTasksPath(taskType),
                SerializeJson(request),
                cancellationToken);
        }

        /// <summary>
        /// 使用 JSON 请求创建模型异步推理任务，并返回 typed response。
        /// </summary>
        public async Task<ModelInferenceTaskSubmissionResponse> CreateModelInferenceTaskResponseAsync(
            string taskType,
            ModelDeploymentInferenceRequest request,
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelInferenceTaskSubmissionResponse>(
                await CreateModelInferenceTaskAsync(taskType, request, cancellationToken).ConfigureAwait(false));
        }

        /// <summary>
        /// 使用 multipart/form-data 上传图片创建模型异步推理任务。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> CreateModelInferenceTaskUploadAsync(
            string taskType,
            ModelDeploymentInferenceUploadRequest request,
            CancellationToken cancellationToken = default)
        {
            if (request is null)
            {
                throw new ArgumentNullException(nameof(request));
            }

            return SendAsync(
                HttpMethod.Post,
                BuildModelInferenceTasksPath(taskType),
                request.ToInferenceTaskContent(),
                cancellationToken);
        }

        /// <summary>
        /// 使用 multipart/form-data 上传图片创建模型异步推理任务，并返回 typed response。
        /// </summary>
        public async Task<ModelInferenceTaskSubmissionResponse> CreateModelInferenceTaskUploadResponseAsync(
            string taskType,
            ModelDeploymentInferenceUploadRequest request,
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelInferenceTaskSubmissionResponse>(
                await CreateModelInferenceTaskUploadAsync(taskType, request, cancellationToken).ConfigureAwait(false));
        }

        /// <summary>
        /// 使用 image_base64 创建模型异步推理任务。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> CreateModelInferenceTaskWithImageBase64Async(
            string taskType,
            string projectId,
            string deploymentInstanceId,
            string imageBase64,
            CancellationToken cancellationToken = default)
        {
            var request = ModelDeploymentInferenceRequest.FromBase64(imageBase64);
            request.ProjectId = projectId;
            request.DeploymentInstanceId = deploymentInstanceId;
            return CreateModelInferenceTaskAsync(taskType, request, cancellationToken);
        }

        /// <summary>
        /// 使用 image_base64 创建模型异步推理任务，并返回 typed response。
        /// </summary>
        public async Task<ModelInferenceTaskSubmissionResponse> CreateModelInferenceTaskWithImageBase64ResponseAsync(
            string taskType,
            string projectId,
            string deploymentInstanceId,
            string imageBase64,
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelInferenceTaskSubmissionResponse>(
                await CreateModelInferenceTaskWithImageBase64Async(
                    taskType,
                    projectId,
                    deploymentInstanceId,
                    imageBase64,
                    cancellationToken).ConfigureAwait(false));
        }

        /// <summary>
        /// 使用图片 bytes 创建模型异步推理任务。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> CreateModelInferenceTaskWithImageBytesAsync(
            string taskType,
            string projectId,
            string deploymentInstanceId,
            byte[] imageBytes,
            string fileName = "input-image.bin",
            string mediaType = "application/octet-stream",
            CancellationToken cancellationToken = default)
        {
            var request = ModelDeploymentInferenceUploadRequest.FromBytes(imageBytes, fileName, mediaType);
            request.ProjectId = projectId;
            request.DeploymentInstanceId = deploymentInstanceId;
            return CreateModelInferenceTaskUploadAsync(taskType, request, cancellationToken);
        }

        /// <summary>
        /// 使用图片 bytes 创建模型异步推理任务，并返回 typed response。
        /// </summary>
        public async Task<ModelInferenceTaskSubmissionResponse> CreateModelInferenceTaskWithImageBytesResponseAsync(
            string taskType,
            string projectId,
            string deploymentInstanceId,
            byte[] imageBytes,
            string fileName = "input-image.bin",
            string mediaType = "application/octet-stream",
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelInferenceTaskSubmissionResponse>(
                await CreateModelInferenceTaskWithImageBytesAsync(
                    taskType,
                    projectId,
                    deploymentInstanceId,
                    imageBytes,
                    fileName,
                    mediaType,
                    cancellationToken).ConfigureAwait(false));
        }

        /// <summary>
        /// 使用本机图片文件创建模型异步推理任务。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> CreateModelInferenceTaskWithImageFileAsync(
            string taskType,
            string projectId,
            string deploymentInstanceId,
            string filePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            var request = ModelDeploymentInferenceUploadRequest.FromFile(filePath, mediaType);
            request.ProjectId = projectId;
            request.DeploymentInstanceId = deploymentInstanceId;
            return CreateModelInferenceTaskUploadAsync(taskType, request, cancellationToken);
        }

        /// <summary>
        /// 使用本机图片文件创建模型异步推理任务，并返回 typed response。
        /// </summary>
        public async Task<ModelInferenceTaskSubmissionResponse> CreateModelInferenceTaskWithImageFileResponseAsync(
            string taskType,
            string projectId,
            string deploymentInstanceId,
            string filePath,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelInferenceTaskSubmissionResponse>(
                await CreateModelInferenceTaskWithImageFileAsync(
                    taskType,
                    projectId,
                    deploymentInstanceId,
                    filePath,
                    mediaType,
                    cancellationToken).ConfigureAwait(false));
        }

        /// <summary>
        /// 读取一条模型异步推理任务。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> GetModelInferenceTaskAsync(
            string taskType,
            string inferenceTaskId,
            bool includeEvents = false,
            CancellationToken cancellationToken = default)
        {
            var path = WithQuery(
                $"{BuildModelInferenceTasksPath(taskType)}/{EncodePathSegment(RequireId(inferenceTaskId, nameof(inferenceTaskId)))}",
                ("include_events", includeEvents));
            return SendAsync(HttpMethod.Get, path, content: null, cancellationToken);
        }

        /// <summary>
        /// 读取一条模型异步推理任务，并返回 typed response。
        /// </summary>
        public async Task<ModelInferenceTaskDetailResponse> GetModelInferenceTaskResponseAsync(
            string taskType,
            string inferenceTaskId,
            bool includeEvents = false,
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelInferenceTaskDetailResponse>(
                await GetModelInferenceTaskAsync(taskType, inferenceTaskId, includeEvents, cancellationToken).ConfigureAwait(false));
        }

        /// <summary>
        /// 读取一条模型异步推理任务结果。
        /// </summary>
        public Task<AmvisionWorkflowApiResponse> GetModelInferenceTaskResultAsync(
            string taskType,
            string inferenceTaskId,
            CancellationToken cancellationToken = default)
        {
            return SendAsync(
                HttpMethod.Get,
                $"{BuildModelInferenceTasksPath(taskType)}/{EncodePathSegment(RequireId(inferenceTaskId, nameof(inferenceTaskId)))}/result",
                content: null,
                cancellationToken);
        }

        /// <summary>
        /// 读取一条模型异步推理任务结果，并返回 typed response。
        /// </summary>
        public async Task<ModelInferenceTaskResultResponse> GetModelInferenceTaskResultResponseAsync(
            string taskType,
            string inferenceTaskId,
            CancellationToken cancellationToken = default)
        {
            return ReadJson<ModelInferenceTaskResultResponse>(
                await GetModelInferenceTaskResultAsync(taskType, inferenceTaskId, cancellationToken).ConfigureAwait(false));
        }

        private static string BuildModelDeploymentInferencePath(string taskType, string deploymentInstanceId)
        {
            return $"{ModelApiPrefix}/{ModelTaskTypes.Normalize(taskType)}/deployment-instances/{EncodePathSegment(RequireId(deploymentInstanceId, nameof(deploymentInstanceId)))}/infer";
        }

        private static string BuildModelInferenceTasksPath(string taskType)
        {
            return $"{ModelApiPrefix}/{ModelTaskTypes.Normalize(taskType)}/inference-tasks";
        }
    }
}
