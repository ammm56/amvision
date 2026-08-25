using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision.SharedMemory
{
    /// <summary>一项逻辑图片输出；多个 attachment 可以共享同一物理 LocalBuffer。</summary>
    public sealed class SharedMemoryImageAttachment
    {
        private readonly SharedMemoryTriggerResult owner;

        internal SharedMemoryImageAttachment(
            SharedMemoryTriggerResult owner,
            string attachmentId,
            string bindingId,
            int itemIndex,
            string payloadId,
            string mediaType,
            long contentLength)
        {
            this.owner = owner;
            AttachmentId = attachmentId;
            BindingId = bindingId;
            ItemIndex = itemIndex;
            PayloadId = payloadId;
            MediaType = mediaType;
            ContentLength = contentLength;
        }

        /// <summary>逻辑 attachment id。</summary>
        public string AttachmentId { get; }

        /// <summary>Workflow public output binding id。</summary>
        public string BindingId { get; }

        /// <summary>image-refs.v1 中的 item index。</summary>
        public int ItemIndex { get; }

        /// <summary>去重后的物理 payload id。</summary>
        public string PayloadId { get; }

        /// <summary>图片 media type。</summary>
        public string MediaType { get; }

        /// <summary>有效图片字节数。</summary>
        public long ContentLength { get; }

        /// <summary>打开零复制只读共享内存 stream；返回 handle 必须释放。</summary>
        public SharedMemoryAttachmentReadHandle OpenRead()
        {
            return owner.OpenRead(PayloadId);
        }

        /// <summary>显式复制为 SDK 自有 byte[]。</summary>
        public byte[] CopyBytes()
        {
            using (var read = OpenRead())
            using (var output = new MemoryStream(checked((int)ContentLength)))
            {
                read.Stream.CopyTo(output);
                return output.ToArray();
            }
        }
    }

    /// <summary>一次正在进行的 attachment 读取；释放后该 stream 不再有效。</summary>
    public sealed class SharedMemoryAttachmentReadHandle : IDisposable
    {
        private readonly Action onDispose;
        private bool disposed;

        internal SharedMemoryAttachmentReadHandle(Stream stream, Action onDispose)
        {
            Stream = stream;
            this.onDispose = onDispose;
        }

        /// <summary>直接读取 mmap view 的只读 stream。</summary>
        public Stream Stream { get; }

        /// <summary>关闭 view 并通知结果对象当前读取结束。</summary>
        public void Dispose()
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            try
            {
                Stream.Dispose();
            }
            finally
            {
                onDispose();
            }
        }
    }

    /// <summary>共享内存 Trigger 结果；图片 view 生命周期持续到 Dispose/DisposeAsync。</summary>
    public sealed class SharedMemoryTriggerResult : IDisposable, IAsyncDisposable
    {
        private readonly object syncRoot = new object();
        private readonly Dictionary<string, PhysicalPayloadReader> physicalReaders;
        private readonly Action releaseAndAcknowledge;
        private int activeReadCount;
        private bool closing;
        private bool disposed;

        internal SharedMemoryTriggerResult(
            TriggerResult triggerResult,
            IEnumerable<PhysicalPayloadReader> readers,
            IEnumerable<PublicLogicalAttachment> logicalAttachments,
            Action releaseAndAcknowledge,
            SharedMemoryTriggerTimings? timings)
        {
            Result = triggerResult ?? throw new ArgumentNullException(nameof(triggerResult));
            this.releaseAndAcknowledge = releaseAndAcknowledge ?? throw new ArgumentNullException(nameof(releaseAndAcknowledge));
            Timings = timings;
            physicalReaders = readers.ToDictionary(item => item.PayloadId, StringComparer.Ordinal);
            Attachments = logicalAttachments.Select(item =>
            {
                if (!physicalReaders.TryGetValue(item.PayloadId, out var reader))
                {
                    throw new SharedMemoryTriggerException("protocol_error", "Logical attachment references an unknown physical payload.");
                }

                return new SharedMemoryImageAttachment(
                    this,
                    item.AttachmentId,
                    item.BindingId,
                    item.ItemIndex,
                    item.PayloadId,
                    reader.MediaType,
                    reader.ContentLength);
            }).ToArray();
        }

        /// <summary>结构化 Workflow Trigger result。</summary>
        public TriggerResult Result { get; }

        /// <summary>按 result_bindings/item 顺序排列的逻辑图片。</summary>
        public IReadOnlyList<SharedMemoryImageAttachment> Attachments { get; }

        /// <summary>显式启用诊断时返回 SDK 本地分阶段耗时，否则为 null。</summary>
        public SharedMemoryTriggerTimings? Timings { get; }

        /// <summary>复制全部逻辑 attachment 后释放共享 view 并 ACK。</summary>
        public IReadOnlyDictionary<string, byte[]> CopyAttachmentsAndRelease()
        {
            var copies = new Dictionary<string, byte[]>(StringComparer.Ordinal);
            try
            {
                foreach (var attachment in Attachments)
                {
                    copies[attachment.AttachmentId] = attachment.CopyBytes();
                }

                return copies;
            }
            finally
            {
                Dispose();
            }
        }

        /// <summary>使全部 view 失效，释放 reader guard，最后只发布一次 ACK。</summary>
        public void Dispose()
        {
            var disposeStartedAt = Timings == null ? 0L : Stopwatch.GetTimestamp();
            PhysicalPayloadReader[] readers;
            lock (syncRoot)
            {
                if (disposed)
                {
                    return;
                }

                closing = true;
                while (activeReadCount > 0)
                {
                    Monitor.Wait(syncRoot);
                }

                disposed = true;
                readers = physicalReaders.Values.ToArray();
            }

            Exception? firstError = null;
            foreach (var reader in readers)
            {
                try
                {
                    reader.Dispose();
                }
                catch (Exception error)
                {
                    firstError = firstError ?? error;
                }
            }

            try
            {
                releaseAndAcknowledge();
            }
            catch (Exception error)
            {
                firstError = firstError ?? error;
            }

            if (Timings != null)
            {
                Timings.DisposeAckMs = ElapsedMilliseconds(disposeStartedAt);
            }

            if (firstError != null)
            {
                throw firstError;
            }
        }

        /// <summary>异步释放入口；当前操作不执行阻塞 I/O。</summary>
        public ValueTask DisposeAsync()
        {
            Dispose();
            return default;
        }

        internal SharedMemoryAttachmentReadHandle OpenRead(string payloadId)
        {
            var accessStartedAt = Timings == null ? 0L : Stopwatch.GetTimestamp();
            PhysicalPayloadReader reader;
            lock (syncRoot)
            {
                if (closing || disposed)
                {
                    throw new ObjectDisposedException(nameof(SharedMemoryTriggerResult));
                }

                if (!physicalReaders.TryGetValue(payloadId, out reader!))
                {
                    throw new KeyNotFoundException("Unknown shared-memory payload: " + payloadId);
                }

                activeReadCount += 1;
            }

            try
            {
                var stream = reader.OpenRead();
                return new SharedMemoryAttachmentReadHandle(
                    stream,
                    () => EndRead(accessStartedAt));
            }
            catch
            {
                EndRead(accessStartedAt);
                throw;
            }
        }

        private void EndRead(long accessStartedAt)
        {
            if (Timings != null)
            {
                Timings.AddAttachmentAccess(ElapsedMilliseconds(accessStartedAt));
            }

            lock (syncRoot)
            {
                activeReadCount -= 1;
                if (activeReadCount == 0)
                {
                    Monitor.PulseAll(syncRoot);
                }
            }
        }

        private static double ElapsedMilliseconds(long startedAt)
        {
            return (Stopwatch.GetTimestamp() - startedAt) * 1000.0 / Stopwatch.Frequency;
        }
    }

    internal sealed class PhysicalPayloadReader : IDisposable
    {
        private readonly ByteRangeGuard readerGuard;
        private readonly string path;
        private readonly long offset;
        private bool disposed;

        internal PhysicalPayloadReader(
            string payloadId,
            string mediaType,
            string path,
            long offset,
            long contentLength,
            ByteRangeGuard readerGuard)
        {
            PayloadId = payloadId;
            MediaType = mediaType;
            this.path = path;
            this.offset = offset;
            ContentLength = contentLength;
            this.readerGuard = readerGuard;
        }

        internal string PayloadId { get; }
        internal string MediaType { get; }
        internal long ContentLength { get; }

        internal Stream OpenRead()
        {
            if (disposed)
            {
                throw new ObjectDisposedException(nameof(PhysicalPayloadReader));
            }

            var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            try
            {
                var map = MemoryMappedFile.CreateFromFile(file, null, 0, MemoryMappedFileAccess.Read, HandleInheritability.None, false);
                try
                {
                    var stream = map.CreateViewStream(offset, ContentLength, MemoryMappedFileAccess.Read);
                    return new OwnedViewStream(stream, map, file);
                }
                catch
                {
                    map.Dispose();
                    throw;
                }
            }
            catch
            {
                file.Dispose();
                throw;
            }
        }

        public void Dispose()
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            readerGuard.Dispose();
        }
    }

    internal sealed class OwnedViewStream : Stream
    {
        private readonly Stream inner;
        private readonly IDisposable map;
        private readonly IDisposable file;
        private bool disposed;

        internal OwnedViewStream(Stream inner, IDisposable map, IDisposable file)
        {
            this.inner = inner;
            this.map = map;
            this.file = file;
        }

        public override bool CanRead => inner.CanRead;
        public override bool CanSeek => inner.CanSeek;
        public override bool CanWrite => false;
        public override long Length => inner.Length;
        public override long Position { get => inner.Position; set => inner.Position = value; }
        public override void Flush() => inner.Flush();
        public override int Read(byte[] buffer, int offset, int count) => inner.Read(buffer, offset, count);
        public override long Seek(long offset, SeekOrigin origin) => inner.Seek(offset, origin);
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();

        protected override void Dispose(bool disposing)
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            if (disposing)
            {
                try
                {
                    inner.Dispose();
                }
                finally
                {
                    map.Dispose();
                    file.Dispose();
                }
            }

            base.Dispose(disposing);
        }
    }
}
