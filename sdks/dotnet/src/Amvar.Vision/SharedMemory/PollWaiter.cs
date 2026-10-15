using System;
using System.Runtime.InteropServices;
using System.Threading;
using Microsoft.Win32.SafeHandles;

namespace Amvar.Vision.SharedMemory
{
    /// <summary>单个同步等待阶段拥有的阻塞计时器；不忙轮询、不跨线程共享句柄。</summary>
    internal sealed class PollWaiter : IDisposable
    {
        private SafeWaitHandle? timer;
        private bool initialized;

        private void EnsureInitialized()
        {
            if (initialized) return;
            initialized = true;
            if (Environment.OSVersion.Platform != PlatformID.Win32NT) return;
            try
            {
                // Windows 10 1803+ 的高分辨率、自动复位、匿名计时器。
                var created = CreateWaitableTimerExW(IntPtr.Zero, null, 2, 0x00100002);
                if (created.IsInvalid) created.Dispose();
                else timer = created;
            }
            catch (EntryPointNotFoundException) { }
            catch (DllNotFoundException) { }
        }

        /// <summary>按指定间隔阻塞；不支持高分辨率计时器的平台沿用 Sleep。</summary>
        internal void Wait(TimeSpan interval)
        {
            if (interval <= TimeSpan.Zero) throw new ArgumentOutOfRangeException(nameof(interval));
            // 无争用的 guard 不等待，不为它创建内核计时器。
            EnsureInitialized();
            if (timer != null)
            {
                var dueTime = -Math.Max(1, interval.Ticks);
                if (SetWaitableTimer(timer, ref dueTime, 0, IntPtr.Zero, IntPtr.Zero, false))
                {
                    var timeout = (uint)Math.Min(uint.MaxValue - 1d, Math.Ceiling(interval.TotalMilliseconds) + 1000d);
                    if (WaitForSingleObject(timer, timeout) == 0) return;
                    throw new InvalidOperationException("High-resolution mailbox poll wait failed.");
                }
            }
            Thread.Sleep((int)Math.Min(int.MaxValue, Math.Max(1, Math.Ceiling(interval.TotalMilliseconds))));
        }

        public void Dispose() => timer?.Dispose();

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeWaitHandle CreateWaitableTimerExW(IntPtr attributes, string? name, uint flags, uint access);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SetWaitableTimer(SafeWaitHandle timer, ref long dueTime, int period,
            IntPtr completionRoutine, IntPtr argument, [MarshalAs(UnmanagedType.Bool)] bool resume);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint WaitForSingleObject(SafeWaitHandle handle, uint milliseconds);
    }
}
