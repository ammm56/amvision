using System.Collections.Generic;
using System.Drawing;
using System.Threading;
using System.Threading.Tasks;

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
    }
}
