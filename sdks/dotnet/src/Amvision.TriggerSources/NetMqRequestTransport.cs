using System;
using System.Collections.Generic;
using NetMQ;
using NetMQ.Sockets;

namespace Amvision.TriggerSources;

/// <summary>
/// ZeroMQ REQ transport 的 NetMQ 实现。
/// </summary>
public sealed class NetMqRequestTransport : IZeroMqRequestTransport
{
    private readonly RequestSocket socket;
    private bool disposed;

    /// <summary>
    /// 创建并连接一个 NetMQ RequestSocket。
    /// </summary>
    /// <param name="endpoint">ZeroMQ endpoint。</param>
    public NetMqRequestTransport(string endpoint)
    {
        if (string.IsNullOrWhiteSpace(endpoint))
        {
            throw new ArgumentException("Endpoint cannot be empty.", nameof(endpoint));
        }

        socket = new RequestSocket();
        socket.Options.Linger = TimeSpan.Zero;
        socket.Connect(endpoint);
    }

    /// <summary>
    /// 发送 multipart request 并等待 multipart reply。
    /// </summary>
    /// <param name="frames">要发送的 multipart frames。</param>
    /// <param name="timeout">等待响应的超时时间。</param>
    /// <returns>ZeroMQ REP 返回的 multipart frames。</returns>
    public IReadOnlyList<byte[]> Send(IReadOnlyList<byte[]> frames, TimeSpan timeout)
    {
        if (disposed)
        {
            throw new ObjectDisposedException(nameof(NetMqRequestTransport));
        }

        if (frames.Count == 0)
        {
            throw new ArgumentException("At least one frame is required.", nameof(frames));
        }

        var outgoing = new NetMQMessage();
        foreach (var frame in frames)
        {
            outgoing.Append(frame);
        }

        socket.SendMultipartMessage(outgoing);

        var incoming = new NetMQMessage();
        if (!socket.TryReceiveMultipartMessage(timeout, ref incoming))
        {
            throw new AmvisionTriggerTimeoutException("Timed out waiting for ZeroMQ TriggerSource reply.");
        }

        var response = new List<byte[]>(incoming.FrameCount);
        foreach (var frame in incoming)
        {
            response.Add(frame.ToByteArray());
        }

        return response;
    }

    /// <summary>
    /// 释放底层 RequestSocket。
    /// </summary>
    public void Dispose()
    {
        if (disposed)
        {
            return;
        }

        socket.Dispose();
        disposed = true;
    }
}