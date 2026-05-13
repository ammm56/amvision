using System;
using System.Collections.Generic;

namespace Amvision.TriggerSources;

/// <summary>
/// SDK 发送 ZeroMQ REQ multipart 消息所需的最小 transport 接口。
/// </summary>
public interface IZeroMqRequestTransport : IDisposable
{
    /// <summary>
    /// 发送 request frames 并返回 response frames。
    /// </summary>
    /// <param name="frames">要发送的 multipart frames。</param>
    /// <param name="timeout">发送后等待响应的超时时间。</param>
    /// <returns>ZeroMQ REP 返回的 multipart frames。</returns>
    IReadOnlyList<byte[]> Send(IReadOnlyList<byte[]> frames, TimeSpan timeout);
}