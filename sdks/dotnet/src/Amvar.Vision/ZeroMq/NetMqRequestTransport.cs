using System;
using System.Collections.Generic;
using NetMQ;
using NetMQ.Sockets;

namespace Amvar.Vision
{

    /// <summary>
    /// ZeroMQ REQ transport 的 NetMQ 实现。
    /// </summary>
    public sealed class NetMqRequestTransport : IZeroMqRequestTransport
    {
        /// <summary>
        /// 保护 RequestSocket 的发送、接收、重建和释放；REQ socket 不能并发使用。
        /// </summary>
        private readonly object syncRoot = new object();

        /// <summary>
        /// ZeroMQ endpoint，用于 socket 异常或 timeout 后重新连接。
        /// </summary>
        private readonly string endpoint;

        /// <summary>
        /// 当前复用的 RequestSocket。
        /// </summary>
        private RequestSocket socket;

        /// <summary>
        /// 标记 transport 是否已经释放。
        /// </summary>
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

            this.endpoint = endpoint.Trim();
            socket = CreateSocket(this.endpoint);
        }

        /// <summary>
        /// 发送 multipart request 并等待 multipart reply。
        /// </summary>
        /// <param name="frames">要发送的 multipart frames。</param>
        /// <param name="timeout">等待响应的超时时间。</param>
        /// <returns>ZeroMQ REP 返回的 multipart frames。</returns>
        public IReadOnlyList<byte[]> Send(IReadOnlyList<byte[]> frames, TimeSpan timeout)
        {
            lock (syncRoot)
            {
                if (disposed)
                {
                    throw new ObjectDisposedException(nameof(NetMqRequestTransport));
                }

                if (frames is null)
                {
                    throw new ArgumentNullException(nameof(frames));
                }

                if (frames.Count == 0)
                {
                    throw new ArgumentException("At least one frame is required.", nameof(frames));
                }

                try
                {
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
                catch
                {
                    if (!disposed)
                    {
                        ResetSocket();
                    }

                    throw;
                }
            }
        }

        /// <summary>
        /// 释放底层 RequestSocket。
        /// </summary>
        public void Dispose()
        {
            lock (syncRoot)
            {
                if (disposed)
                {
                    return;
                }

                socket.Dispose();
                disposed = true;
            }
        }

        /// <summary>
        /// 创建并连接一个新的 RequestSocket。
        /// </summary>
        /// <param name="endpoint">ZeroMQ endpoint。</param>
        /// <returns>已连接的 RequestSocket。</returns>
        private static RequestSocket CreateSocket(string endpoint)
        {
            var requestSocket = new RequestSocket();
            requestSocket.Options.Linger = TimeSpan.Zero;
            requestSocket.Connect(endpoint);
            return requestSocket;
        }

        /// <summary>
        /// 释放当前 socket 并重新连接，用于恢复 REQ socket 超时或异常后的状态机。
        /// </summary>
        private void ResetSocket()
        {
            socket.Dispose();
            socket = CreateSocket(endpoint);
        }
    }
}
