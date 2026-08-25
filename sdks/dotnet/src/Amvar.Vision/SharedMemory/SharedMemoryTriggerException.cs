using System;

namespace Amvar.Vision.SharedMemory
{
    /// <summary>本机共享内存 Trigger 协议、容量或生命周期错误。</summary>
    public sealed class SharedMemoryTriggerException : Exception
    {
        /// <summary>使用稳定错误码创建异常。</summary>
        public SharedMemoryTriggerException(string errorCode, string message, Exception? innerException = null)
            : base(message, innerException)
        {
            ErrorCode = errorCode;
        }

        /// <summary>稳定错误码。</summary>
        public string ErrorCode { get; }
    }
}
