using System.Collections.Generic;
using System.Drawing;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision.SharedMemory;

namespace Amvar.Vision
{
    /// <summary>
    /// 通过 trigger_source_id 精确调用 TriggerSource 的入口。
    /// </summary>
    public sealed partial class AMVisionOperationRunner
    {
        private string GetTriggerSourceNameById(string triggerSourceId)
        {
            return catalog.GetTriggerSourceById(triggerSourceId).TriggerSource.Name;
        }

        public Task<IReadOnlyList<WorkflowTriggerSourceResponse>> ListTriggerSourcesByRuntimeIdAsync(
            string workflowRuntimeId, CancellationToken cancellationToken = default)
        {
            return ListTriggerSourcesAsync(GetRuntimeNameById(workflowRuntimeId), cancellationToken);
        }

        public Task<WorkflowTriggerSourceResponse> GetTriggerSourceByIdAsync(
            string triggerSourceId, CancellationToken cancellationToken = default)
        {
            return GetTriggerSourceAsync(GetTriggerSourceNameById(triggerSourceId), cancellationToken);
        }

        public Task<WorkflowTriggerSourceResponse> EnableTriggerSourceByIdAsync(
            string triggerSourceId, CancellationToken cancellationToken = default)
        {
            return EnableTriggerSourceAsync(GetTriggerSourceNameById(triggerSourceId), cancellationToken);
        }

        public Task<WorkflowTriggerSourceResponse> DisableTriggerSourceByIdAsync(
            string triggerSourceId, CancellationToken cancellationToken = default)
        {
            return DisableTriggerSourceAsync(GetTriggerSourceNameById(triggerSourceId), cancellationToken);
        }

        public Task<WorkflowTriggerSourceHealthResponse> GetTriggerSourceHealthByIdAsync(
            string triggerSourceId, CancellationToken cancellationToken = default)
        {
            return GetTriggerSourceHealthAsync(GetTriggerSourceNameById(triggerSourceId), cancellationToken);
        }

        public TriggerResult InvokeZeroMqEventById(
            string triggerSourceId, IDictionary<string, object?>? payload = null,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqEvent(GetTriggerSourceNameById(triggerSourceId), payload, cancellationToken);
        }

        public TriggerResult InvokeConfiguredZeroMqImageById(
            string triggerSourceId, CancellationToken cancellationToken = default)
        {
            return InvokeConfiguredZeroMqImage(GetTriggerSourceNameById(triggerSourceId), cancellationToken);
        }

        public TriggerResult InvokeZeroMqImageFromFileById(
            string triggerSourceId, string imagePath, string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqImageFromFile(
                GetTriggerSourceNameById(triggerSourceId), imagePath, mediaType, cancellationToken);
        }

        public TriggerResult InvokeZeroMqImageBytesById(
            string triggerSourceId, byte[] imageBytes,
            string mediaType = "image/octet-stream", CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqImageBytes(
                GetTriggerSourceNameById(triggerSourceId), imageBytes, mediaType, cancellationToken);
        }

        public TriggerResult InvokeZeroMqImageBase64ById(
            string triggerSourceId, string imageBase64, string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqImageBase64(
                GetTriggerSourceNameById(triggerSourceId), imageBase64, mediaType, cancellationToken);
        }

        public TriggerResult InvokeZeroMqBgr24ById(
            string triggerSourceId, byte[] bgr24Bytes, int width, int height,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqBgr24(
                GetTriggerSourceNameById(triggerSourceId), bgr24Bytes, width, height, cancellationToken);
        }

        public TriggerResult InvokeZeroMqBgr24FromBitmapById(
            string triggerSourceId, Bitmap bitmap,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqBgr24FromBitmap(
                GetTriggerSourceNameById(triggerSourceId), bitmap, cancellationToken);
        }

        public TriggerResult InvokeZeroMqBgr24FromFileById(
            string triggerSourceId, string imagePath,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqBgr24FromFile(
                GetTriggerSourceNameById(triggerSourceId), imagePath, cancellationToken);
        }

        public TriggerResult InvokeConfiguredZeroMqBgr24ImageById(
            string triggerSourceId, CancellationToken cancellationToken = default)
        {
            return InvokeConfiguredZeroMqBgr24Image(
                GetTriggerSourceNameById(triggerSourceId), cancellationToken);
        }

        public TriggerResult InvokeSharedMemoryImageBytesById(
            string triggerSourceId,
            byte[] imageBytes,
            string mediaType,
            SharedMemoryTriggerRequest? request = null)
        {
            return InvokeSharedMemoryImageBytes(
                GetTriggerSourceNameById(triggerSourceId),
                imageBytes,
                mediaType,
                request);
        }

        public TriggerResult InvokeSharedMemoryBgr24ById(
            string triggerSourceId,
            byte[] bgr24Bytes,
            int width,
            int height,
            SharedMemoryTriggerRequest? request = null)
        {
            return InvokeSharedMemoryBgr24(
                GetTriggerSourceNameById(triggerSourceId),
                bgr24Bytes,
                width,
                height,
                request);
        }

        public TriggerResult InvokeSharedMemoryBgr24ById(
            string triggerSourceId,
            int width,
            int height,
            SharedMemoryTriggerBufferWriter fill,
            SharedMemoryTriggerRequest? request = null)
        {
            return InvokeSharedMemoryBgr24(
                GetTriggerSourceNameById(triggerSourceId),
                width,
                height,
                fill,
                request);
        }

        public TriggerResult InvokeSharedMemoryBgr24ById(
            string triggerSourceId,
            byte[] bgr24Bytes,
            int width,
            int height,
            int rowStride,
            SharedMemoryTriggerRequest? request = null)
        {
            return InvokeSharedMemoryBgr24(
                GetTriggerSourceNameById(triggerSourceId),
                bgr24Bytes,
                width,
                height,
                rowStride,
                request);
        }

        public TriggerResult InvokeSharedMemoryMono8ById(
            string triggerSourceId,
            byte[] mono8Bytes,
            int width,
            int height,
            int rowStride,
            SharedMemoryTriggerRequest? request = null)
        {
            return InvokeSharedMemoryMono8(
                GetTriggerSourceNameById(triggerSourceId),
                mono8Bytes,
                width,
                height,
                rowStride,
                request);
        }

        public TriggerResult InvokeSharedMemoryBitmapById(
            string triggerSourceId,
            Bitmap bitmap,
            SharedMemoryTriggerRequest? request = null)
        {
            return InvokeSharedMemoryBitmap(
                GetTriggerSourceNameById(triggerSourceId),
                bitmap,
                request);
        }

        public TriggerResult InvokeSharedMemoryImageFromFileById(
            string triggerSourceId,
            string imagePath,
            string? mediaType = null,
            SharedMemoryTriggerRequest? request = null)
        {
            return InvokeSharedMemoryImageFromFile(
                GetTriggerSourceNameById(triggerSourceId),
                imagePath,
                mediaType,
                request);
        }

        public TriggerResult InvokeSharedMemoryImageBase64ById(
            string triggerSourceId,
            string imageBase64,
            string? mediaType = null,
            SharedMemoryTriggerRequest? request = null)
        {
            return InvokeSharedMemoryImageBase64(
                GetTriggerSourceNameById(triggerSourceId),
                imageBase64,
                mediaType,
                request);
        }

        public TriggerResult InvokeSharedMemoryEventById(
            string triggerSourceId,
            SharedMemoryTriggerEventRequest request)
        {
            return InvokeSharedMemoryEvent(
                GetTriggerSourceNameById(triggerSourceId),
                request);
        }

        public TriggerResult InvokeZeroMqEventWithInputsById(
            string triggerSourceId,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqEventWithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                inputs,
                cancellationToken);
        }

        public TriggerResult InvokeConfiguredZeroMqImageWithInputsById(
            string triggerSourceId,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            return InvokeConfiguredZeroMqImageWithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                inputs,
                cancellationToken);
        }

        public TriggerResult InvokeZeroMqImageFromFileWithInputsById(
            string triggerSourceId,
            string imagePath,
            WorkflowTriggerInputs inputs,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqImageFromFileWithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                imagePath,
                inputs,
                mediaType,
                cancellationToken);
        }

        public TriggerResult InvokeZeroMqImageBytesWithInputsById(
            string triggerSourceId,
            byte[] imageBytes,
            WorkflowTriggerInputs inputs,
            string mediaType = "image/octet-stream",
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqImageBytesWithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                imageBytes,
                inputs,
                mediaType,
                cancellationToken);
        }

        public TriggerResult InvokeZeroMqImageBase64WithInputsById(
            string triggerSourceId,
            string imageBase64,
            WorkflowTriggerInputs inputs,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqImageBase64WithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                imageBase64,
                inputs,
                mediaType,
                cancellationToken);
        }

        public TriggerResult InvokeZeroMqBgr24WithInputsById(
            string triggerSourceId,
            byte[] bgr24Bytes,
            int width,
            int height,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqBgr24WithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                bgr24Bytes,
                width,
                height,
                inputs,
                cancellationToken);
        }

        public TriggerResult InvokeZeroMqBgr24FromBitmapWithInputsById(
            string triggerSourceId,
            Bitmap bitmap,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqBgr24FromBitmapWithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                bitmap,
                inputs,
                cancellationToken);
        }

        public TriggerResult InvokeZeroMqBgr24FromFileWithInputsById(
            string triggerSourceId,
            string imagePath,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            return InvokeZeroMqBgr24FromFileWithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                imagePath,
                inputs,
                cancellationToken);
        }

        public TriggerResult InvokeConfiguredZeroMqBgr24ImageWithInputsById(
            string triggerSourceId,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            return InvokeConfiguredZeroMqBgr24ImageWithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                inputs,
                cancellationToken);
        }

        public TriggerResult InvokeSharedMemoryImageBytesWithInputsById(
            string triggerSourceId,
            byte[] imageBytes,
            string mediaType,
            WorkflowTriggerInputs inputs)
        {
            return InvokeSharedMemoryImageBytesWithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                imageBytes,
                mediaType,
                inputs);
        }

        public TriggerResult InvokeSharedMemoryBgr24WithInputsById(
            string triggerSourceId,
            byte[] bgr24Bytes,
            int width,
            int height,
            WorkflowTriggerInputs inputs)
        {
            return InvokeSharedMemoryBgr24WithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                bgr24Bytes,
                width,
                height,
                inputs);
        }

        public TriggerResult InvokeSharedMemoryImageFromFileWithInputsById(
            string triggerSourceId,
            string imagePath,
            WorkflowTriggerInputs inputs,
            string? mediaType = null)
        {
            return InvokeSharedMemoryImageFromFileWithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                imagePath,
                inputs,
                mediaType);
        }

        public TriggerResult InvokeSharedMemoryImageBase64WithInputsById(
            string triggerSourceId,
            string imageBase64,
            WorkflowTriggerInputs inputs,
            string? mediaType = null)
        {
            return InvokeSharedMemoryImageBase64WithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                imageBase64,
                inputs,
                mediaType);
        }

        public TriggerResult InvokeSharedMemoryEventWithInputsById(
            string triggerSourceId,
            WorkflowTriggerInputs inputs)
        {
            return InvokeSharedMemoryEventWithInputs(
                GetTriggerSourceNameById(triggerSourceId),
                inputs);
        }
    }
}
