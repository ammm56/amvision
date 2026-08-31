using System;
using System.Drawing;
using System.Threading;
using Amvar.Vision.SharedMemory;

namespace Amvar.Vision
{
    public sealed partial class AMVisionOperationRunner
    {
        /// <summary>发送 ZeroMQ JSON/文本 event-only 输入。</summary>
        public TriggerResult InvokeZeroMqEventWithInputs(
            string triggerSourceName,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            return zeroMqTriggerOperations.InvokeEvent(
                triggerSourceName,
                inputs ?? throw new ArgumentNullException(nameof(inputs)),
                cancellationToken);
        }

        /// <summary>发送配置图片并附带 ZeroMQ JSON/文本输入。</summary>
        public TriggerResult InvokeConfiguredZeroMqImageWithInputs(
            string triggerSourceName,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            return zeroMqTriggerOperations.InvokeConfiguredImage(
                triggerSourceName,
                inputs ?? throw new ArgumentNullException(nameof(inputs)),
                cancellationToken);
        }

        /// <summary>发送图片文件并附带 ZeroMQ JSON/文本输入。</summary>
        public TriggerResult InvokeZeroMqImageFromFileWithInputs(
            string triggerSourceName,
            string imagePath,
            WorkflowTriggerInputs inputs,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            return zeroMqTriggerOperations.InvokeImageFromFile(
                triggerSourceName,
                imagePath,
                mediaType,
                inputs ?? throw new ArgumentNullException(nameof(inputs)),
                cancellationToken);
        }

        /// <summary>发送图片 bytes 并附带 ZeroMQ JSON/文本输入。</summary>
        public TriggerResult InvokeZeroMqImageBytesWithInputs(
            string triggerSourceName,
            byte[] imageBytes,
            WorkflowTriggerInputs inputs,
            string mediaType = "image/octet-stream",
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            return zeroMqTriggerOperations.InvokeImageBytes(
                triggerSourceName,
                imageBytes,
                mediaType,
                inputs ?? throw new ArgumentNullException(nameof(inputs)),
                cancellationToken);
        }

        /// <summary>解码 Base64 图片后发送，并附带 ZeroMQ JSON/文本输入。</summary>
        public TriggerResult InvokeZeroMqImageBase64WithInputs(
            string triggerSourceName,
            string imageBase64,
            WorkflowTriggerInputs inputs,
            string? mediaType = null,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            return zeroMqTriggerOperations.InvokeImageBase64(
                triggerSourceName,
                imageBase64,
                mediaType,
                inputs ?? throw new ArgumentNullException(nameof(inputs)),
                cancellationToken);
        }

        /// <summary>发送 BGR24 图片并附带 ZeroMQ JSON/文本输入。</summary>
        public TriggerResult InvokeZeroMqBgr24WithInputs(
            string triggerSourceName,
            byte[] bgr24Bytes,
            int width,
            int height,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            return zeroMqTriggerOperations.InvokeBgr24(
                triggerSourceName,
                bgr24Bytes,
                width,
                height,
                inputs ?? throw new ArgumentNullException(nameof(inputs)),
                cancellationToken);
        }

        /// <summary>转换 Bitmap 后发送，并附带 ZeroMQ JSON/文本输入。</summary>
        public TriggerResult InvokeZeroMqBgr24FromBitmapWithInputs(
            string triggerSourceName,
            Bitmap bitmap,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            return zeroMqTriggerOperations.InvokeBgr24FromBitmap(
                triggerSourceName,
                bitmap,
                inputs ?? throw new ArgumentNullException(nameof(inputs)),
                cancellationToken);
        }

        /// <summary>转换图片文件后发送，并附带 ZeroMQ JSON/文本输入。</summary>
        public TriggerResult InvokeZeroMqBgr24FromFileWithInputs(
            string triggerSourceName,
            string imagePath,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            return zeroMqTriggerOperations.InvokeBgr24FromFile(
                triggerSourceName,
                imagePath,
                inputs ?? throw new ArgumentNullException(nameof(inputs)),
                cancellationToken);
        }

        /// <summary>发送配置 BGR24 图片并附带 ZeroMQ JSON/文本输入。</summary>
        public TriggerResult InvokeConfiguredZeroMqBgr24ImageWithInputs(
            string triggerSourceName,
            WorkflowTriggerInputs inputs,
            CancellationToken cancellationToken = default)
        {
            EnsureNotDisposed();
            return zeroMqTriggerOperations.InvokeConfiguredBgr24Image(
                triggerSourceName,
                inputs ?? throw new ArgumentNullException(nameof(inputs)),
                cancellationToken);
        }

        /// <summary>发送 LocalBuffer 图片 bytes 并附带 JSON/文本输入。</summary>
        public SharedMemoryTriggerResult InvokeSharedMemoryImageBytesWithInputs(
            string triggerSourceName,
            byte[] imageBytes,
            string mediaType,
            WorkflowTriggerInputs inputs)
        {
            return InvokeSharedMemoryImageBytes(
                triggerSourceName,
                imageBytes,
                mediaType,
                BuildSharedMemoryRequest(inputs));
        }

        /// <summary>发送 LocalBuffer BGR24 图片并附带 JSON/文本输入。</summary>
        public SharedMemoryTriggerResult InvokeSharedMemoryBgr24WithInputs(
            string triggerSourceName,
            byte[] bgr24Bytes,
            int width,
            int height,
            WorkflowTriggerInputs inputs)
        {
            return InvokeSharedMemoryBgr24(
                triggerSourceName,
                bgr24Bytes,
                width,
                height,
                BuildSharedMemoryRequest(inputs));
        }

        /// <summary>发送 LocalBuffer 图片文件并附带 JSON/文本输入。</summary>
        public SharedMemoryTriggerResult InvokeSharedMemoryImageFromFileWithInputs(
            string triggerSourceName,
            string imagePath,
            WorkflowTriggerInputs inputs,
            string? mediaType = null)
        {
            return InvokeSharedMemoryImageFromFile(
                triggerSourceName,
                imagePath,
                mediaType,
                BuildSharedMemoryRequest(inputs));
        }

        /// <summary>解码 Base64 图片后写入 LocalBuffer，并附带 JSON/文本输入。</summary>
        public SharedMemoryTriggerResult InvokeSharedMemoryImageBase64WithInputs(
            string triggerSourceName,
            string imageBase64,
            WorkflowTriggerInputs inputs,
            string? mediaType = null)
        {
            return InvokeSharedMemoryImageBase64(
                triggerSourceName,
                imageBase64,
                mediaType,
                BuildSharedMemoryRequest(inputs));
        }

        /// <summary>发送本机共享内存 JSON/文本 event-only 输入。</summary>
        public SharedMemoryTriggerResult InvokeSharedMemoryEventWithInputs(
            string triggerSourceName,
            WorkflowTriggerInputs inputs)
        {
            var request = new SharedMemoryTriggerEventRequest();
            (inputs ?? throw new ArgumentNullException(nameof(inputs))).CopyTo(request.Payload);
            return InvokeSharedMemoryEvent(triggerSourceName, request);
        }

        private static SharedMemoryTriggerRequest BuildSharedMemoryRequest(
            WorkflowTriggerInputs inputs)
        {
            var request = new SharedMemoryTriggerRequest();
            (inputs ?? throw new ArgumentNullException(nameof(inputs))).CopyTo(request.Payload);
            return request;
        }
    }
}
