using System.Drawing;
using Amvar.Vision.SharedMemory;

namespace Amvar.Vision
{
    public sealed partial class AMVisionOperationRunner
    {
        /// <summary>按配置 key 原样写入 encoded 或 raw 图片 bytes。</summary>
        public TriggerResult InvokeSharedMemoryImageBytes(
            string triggerSourceName,
            byte[] imageBytes,
            string mediaType,
            SharedMemoryTriggerRequest? request = null)
        {
            EnsureNotDisposed();
            return MaterializeSharedMemoryResult(localSharedMemoryTriggerOperations.InvokeImageBytes(
                triggerSourceName,
                imageBytes,
                mediaType,
                request));
        }

        /// <summary>按配置 key 直接写入连续 HWC BGR24。</summary>
        public TriggerResult InvokeSharedMemoryBgr24(
            string triggerSourceName,
            byte[] bgr24Bytes,
            int width,
            int height,
            SharedMemoryTriggerRequest? request = null)
        {
            EnsureNotDisposed();
            return MaterializeSharedMemoryResult(localSharedMemoryTriggerOperations.InvokeBgr24(
                triggerSourceName,
                bgr24Bytes,
                width,
                height,
                rowStride: null,
                request));
        }

        /// <summary>按配置 key 通过受限 lease Span 直接填充连续 HWC BGR24。</summary>
        public TriggerResult InvokeSharedMemoryBgr24(
            string triggerSourceName,
            int width,
            int height,
            SharedMemoryTriggerBufferWriter fill,
            SharedMemoryTriggerRequest? request = null)
        {
            EnsureNotDisposed();
            return MaterializeSharedMemoryResult(localSharedMemoryTriggerOperations.InvokeBgr24(
                triggerSourceName,
                width,
                height,
                fill,
                request));
        }

        /// <summary>按配置 key 规范化带正/负 stride 的 BGR24 后写入。</summary>
        public TriggerResult InvokeSharedMemoryBgr24(
            string triggerSourceName,
            byte[] bgr24Bytes,
            int width,
            int height,
            int rowStride,
            SharedMemoryTriggerRequest? request = null)
        {
            EnsureNotDisposed();
            return MaterializeSharedMemoryResult(localSharedMemoryTriggerOperations.InvokeBgr24(
                triggerSourceName,
                bgr24Bytes,
                width,
                height,
                rowStride,
                request));
        }

        /// <summary>按配置 key 把 Mono8 转为连续 BGR24 后写入。</summary>
        public TriggerResult InvokeSharedMemoryMono8(
            string triggerSourceName,
            byte[] mono8Bytes,
            int width,
            int height,
            int rowStride,
            SharedMemoryTriggerRequest? request = null)
        {
            EnsureNotDisposed();
            return MaterializeSharedMemoryResult(localSharedMemoryTriggerOperations.InvokeMono8(
                triggerSourceName,
                mono8Bytes,
                width,
                height,
                rowStride,
                request));
        }

        /// <summary>按配置 key 把 Bitmap 转为 BGR24 后写入。</summary>
        public TriggerResult InvokeSharedMemoryBitmap(
            string triggerSourceName,
            Bitmap bitmap,
            SharedMemoryTriggerRequest? request = null)
        {
            EnsureNotDisposed();
            return MaterializeSharedMemoryResult(localSharedMemoryTriggerOperations.InvokeBitmap(
                triggerSourceName,
                bitmap,
                request));
        }

        /// <summary>按配置 key 保留文件中的 encoded 图片表示并写入。</summary>
        public TriggerResult InvokeSharedMemoryImageFromFile(
            string triggerSourceName,
            string imagePath,
            string? mediaType = null,
            SharedMemoryTriggerRequest? request = null)
        {
            EnsureNotDisposed();
            return MaterializeSharedMemoryResult(localSharedMemoryTriggerOperations.InvokeImageFromFile(
                triggerSourceName,
                imagePath,
                mediaType,
                request));
        }

        /// <summary>按配置 key 只还原 Base64/Data URL 为 encoded bytes 后写入。</summary>
        public TriggerResult InvokeSharedMemoryImageBase64(
            string triggerSourceName,
            string imageBase64,
            string? mediaType = null,
            SharedMemoryTriggerRequest? request = null)
        {
            EnsureNotDisposed();
            return MaterializeSharedMemoryResult(localSharedMemoryTriggerOperations.InvokeImageBase64(
                triggerSourceName,
                imageBase64,
                mediaType,
                request));
        }

        /// <summary>按配置 key 发布不带图片的 event-only 请求。</summary>
        public TriggerResult InvokeSharedMemoryEvent(
            string triggerSourceName,
            SharedMemoryTriggerEventRequest request)
        {
            EnsureNotDisposed();
            return MaterializeSharedMemoryResult(localSharedMemoryTriggerOperations.InvokeEvent(
                triggerSourceName,
                request));
        }

        /// <summary>把底层 mmap lease 物化为协议中立结果，并在返回前完成确定性 ACK。</summary>
        private static TriggerResult MaterializeSharedMemoryResult(
            SharedMemoryTriggerResult result)
        {
            if (result == null)
            {
                throw new SharedMemoryTriggerException(
                    "protocol_error",
                    "Shared-memory Trigger returned no result.");
            }

            return result.CopyResultAndRelease();
        }
    }
}
