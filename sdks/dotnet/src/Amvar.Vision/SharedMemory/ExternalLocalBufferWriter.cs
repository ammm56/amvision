using System;
using System.Diagnostics;
using System.IO;

namespace Amvar.Vision.SharedMemory
{
    internal sealed class ExternalLocalBufferWriter : IDisposable
    {
        private readonly ByteRangeGuard writerGuard;
        private readonly LocalBufferMappingCache.LocalBufferMappingLease mapping;
        private readonly long capacity;
        private readonly bool collectTimings;
        private long writeElapsedTicks;
        private bool written;
        private bool disposed;

        internal ExternalLocalBufferWriter(
            WorkflowTriggerAllocation allocation,
            long localDeadlineTicks,
            bool collectTimings,
            LocalBufferMappingCache mappingCache)
        {
            if (allocation == null)
            {
                throw new ArgumentNullException(nameof(allocation));
            }

            if (string.IsNullOrWhiteSpace(allocation.Path)
                || string.IsNullOrWhiteSpace(allocation.WriterGuardPath)
                || allocation.Offset < 0
                || allocation.Size <= 0)
            {
                throw new SharedMemoryTriggerException("protocol_error", "Workflow Trigger allocation locator is invalid.");
            }

            this.collectTimings = collectTimings;
            writerGuard = ByteRangeGuard.Acquire(allocation.WriterGuardPath, 0, 1, localDeadlineTicks);
            try
            {
                mapping = (mappingCache ?? throw new ArgumentNullException(nameof(mappingCache))).Acquire(allocation);
                capacity = mapping.Size;
            }
            catch
            {
                writerGuard.Dispose();
                throw;
            }
        }

        internal double WriteElapsedMs => ToMilliseconds(writeElapsedTicks);

        internal unsafe void Write(byte[] content)
        {
            if (content == null)
            {
                throw new ArgumentNullException(nameof(content));
            }

            if (content.LongLength != capacity)
            {
                throw new ArgumentException("Image bytes length must exactly match the allocated LocalBuffer length.", nameof(content));
            }

            ThrowIfWrittenOrDisposed();
            byte* pointer = null;
            var view = mapping.View;
            view.SafeMemoryMappedViewHandle.AcquirePointer(ref pointer);
            try
            {
                if (pointer == null)
                {
                    throw new InvalidOperationException("LocalBuffer mmap view pointer is unavailable.");
                }

                var destination = new Span<byte>(
                    pointer + view.PointerOffset,
                    checked((int)capacity));
                var writeStartedAt = collectTimings ? Stopwatch.GetTimestamp() : 0L;
                content.AsSpan().CopyTo(destination);
                if (collectTimings)
                {
                    writeElapsedTicks += Stopwatch.GetTimestamp() - writeStartedAt;
                }
            }
            finally
            {
                view.SafeMemoryMappedViewHandle.ReleasePointer();
            }

            written = true;
        }

        internal unsafe void Write(Stream source, long contentLength)
        {
            if (source == null)
            {
                throw new ArgumentNullException(nameof(source));
            }

            if (!source.CanRead)
            {
                throw new ArgumentException("Source stream must be readable.", nameof(source));
            }

            if (contentLength != capacity)
            {
                throw new ArgumentException("Stream length must exactly match the allocated LocalBuffer length.", nameof(contentLength));
            }

            ThrowIfWrittenOrDisposed();
            var buffer = new byte[1024 * 1024];
            long total = 0;
            byte* pointer = null;
            var view = mapping.View;
            view.SafeMemoryMappedViewHandle.AcquirePointer(ref pointer);
            try
            {
                if (pointer == null)
                {
                    throw new InvalidOperationException("LocalBuffer mmap view pointer is unavailable.");
                }

                var destination = new Span<byte>(
                    pointer + view.PointerOffset,
                    checked((int)capacity));
                while (total < contentLength)
                {
                    var count = source.Read(buffer, 0, (int)Math.Min(buffer.Length, contentLength - total));
                    if (count <= 0)
                    {
                        throw new EndOfStreamException("Image source ended before the declared content length.");
                    }

                    var writeStartedAt = collectTimings ? Stopwatch.GetTimestamp() : 0L;
                    buffer.AsSpan(0, count).CopyTo(
                        destination.Slice(checked((int)total), count));
                    if (collectTimings)
                    {
                        writeElapsedTicks += Stopwatch.GetTimestamp() - writeStartedAt;
                    }
                    total += count;
                }

                if (source.ReadByte() != -1)
                {
                    throw new InvalidDataException("Image source contains bytes beyond the declared content length.");
                }
            }
            finally
            {
                view.SafeMemoryMappedViewHandle.ReleasePointer();
            }

            written = true;
        }

        internal unsafe void Write(SharedMemoryTriggerBufferWriter fill)
        {
            if (fill == null)
            {
                throw new ArgumentNullException(nameof(fill));
            }

            ThrowIfWrittenOrDisposed();
            byte* pointer = null;
            var view = mapping.View;
            view.SafeMemoryMappedViewHandle.AcquirePointer(ref pointer);
            try
            {
                if (pointer == null)
                {
                    throw new InvalidOperationException("LocalBuffer mmap view pointer is unavailable.");
                }

                var destination = new Span<byte>(
                    pointer + view.PointerOffset,
                    checked((int)capacity));
                var writeStartedAt = collectTimings ? Stopwatch.GetTimestamp() : 0L;
                fill(destination);
                if (collectTimings)
                {
                    writeElapsedTicks += Stopwatch.GetTimestamp() - writeStartedAt;
                }

                written = true;
            }
            finally
            {
                view.SafeMemoryMappedViewHandle.ReleasePointer();
            }
        }

        public void Dispose()
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            mapping.Dispose();
            writerGuard.Dispose();
        }

        private void ThrowIfWrittenOrDisposed()
        {
            if (disposed)
            {
                throw new ObjectDisposedException(nameof(ExternalLocalBufferWriter));
            }

            if (written)
            {
                throw new InvalidOperationException("The LocalBuffer allocation has already been written.");
            }
        }

        private static double ToMilliseconds(long elapsedTicks)
        {
            return elapsedTicks <= 0
                ? 0.0
                : elapsedTicks * 1000.0 / Stopwatch.Frequency;
        }
    }
}
