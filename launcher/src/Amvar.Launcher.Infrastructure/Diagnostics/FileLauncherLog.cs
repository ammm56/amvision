using Amvar.Launcher.Core.Abstractions;

namespace Amvar.Launcher.Infrastructure.Diagnostics;

/// <summary>有界日记日志，始终排空子进程输出；日志故障不能递归破坏退出链。</summary>
public sealed class FileLauncherLog(string directory) : ILauncherLog
{
    private readonly object gate = new();
    public void Write(string message, Exception? exception = null)
    {
        lock (gate)
        {
            try
            {
                Directory.CreateDirectory(directory);
                var path = Path.Combine(directory, $"launcher-{DateTime.Now:yyyyMMdd}.log");
                if (File.Exists(path) && new FileInfo(path).Length > 8 * 1024 * 1024)
                    File.Move(path, path + ".1", true);
                var text = message.Length > 8192 ? message[..8192] : message;
                File.AppendAllText(path, $"{DateTimeOffset.Now:O} {text} {exception?.Message}{Environment.NewLine}");
                foreach (var old in Directory.GetFiles(directory, "launcher-*.log*").OrderDescending().Skip(14)) File.Delete(old);
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }
}
