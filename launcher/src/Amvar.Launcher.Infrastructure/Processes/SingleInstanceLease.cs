using System.IO.Pipes;
using System.Security.Cryptography;
using System.Text;

namespace Amvar.Launcher.Infrastructure.Processes;

/// <summary>按用户与安装目录互斥；后启动的实例只发送显示窗口信号。</summary>
public sealed class SingleInstanceLease : IDisposable
{
    private readonly FileStream lease;
    private readonly string pipeName;
    private readonly CancellationTokenSource cancellation = new();
    private Task listener = Task.CompletedTask;
    private SingleInstanceLease(FileStream lease, string pipeName) { this.lease = lease; this.pipeName = pipeName; }
    public static async Task<SingleInstanceLease?> AcquireAsync(string dataDirectory, string installation)
    {
        var normalized = Path.GetFullPath(installation).TrimEnd(Path.DirectorySeparatorChar);
        if (OperatingSystem.IsWindows()) normalized = normalized.ToUpperInvariant();
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(Environment.UserName + "|" + normalized)))[..24];
        var name = "amvar-launcher-" + hash;
        // 锁按用户安装目录共享，不依赖当前工作目录或可执行文件副本。
        var lockDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "amvar", "launcher");
        Directory.CreateDirectory(lockDirectory);
        try { return new(new FileStream(Path.Combine(lockDirectory, name + ".lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None), name); }
        catch (IOException)
        {
            using var pipe = new NamedPipeClientStream(".", name, PipeDirection.Out, PipeOptions.Asynchronous);
            await pipe.ConnectAsync(5000);
            await pipe.WriteAsync(new byte[] { 1 });
            return null;
        }
    }
    public void Listen(Action activate) => listener = ListenAsync(activate);
    private async Task ListenAsync(Action activate)
    {
        while (!cancellation.IsCancellationRequested)
        {
            try
            {
                await using var server = new NamedPipeServerStream(pipeName, PipeDirection.In, 1,
                    PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                await server.WaitForConnectionAsync(cancellation.Token);
                using var readTimeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation.Token);
                readTimeout.CancelAfter(TimeSpan.FromSeconds(2));
                var signal = new byte[1];
                if (await server.ReadAsync(signal, readTimeout.Token) == 1 && signal[0] == 1) activate();
            }
            catch (OperationCanceledException) { }
            catch (IOException) { await Task.Delay(100, cancellation.Token).ConfigureAwait(false); }
        }
    }
    public void Dispose()
    {
        cancellation.Cancel();
        lease.Dispose();
        // 释放异步监听后再释放 token；不阻塞 UI 线程。
        _ = listener.ContinueWith(_ => cancellation.Dispose(), TaskScheduler.Default);
    }
}
