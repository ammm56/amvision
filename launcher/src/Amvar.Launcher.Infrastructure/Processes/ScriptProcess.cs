using System.Diagnostics;
using System.Text;
using Amvar.Launcher.Core.Abstractions;

namespace Amvar.Launcher.Infrastructure.Processes;

/// <summary>固定发行脚本执行器；参数通过环境变量传递，路径保持在双引号内。</summary>
public sealed class ScriptProcess : IDisposable
{
    public Process Process { get; }
    private readonly Task drain;
    private ScriptProcess(Process process, ILauncherLog log)
    {
        Process = process;
        drain = Task.WhenAll(Drain(process.StandardOutput, log), Drain(process.StandardError, log));
    }
    public static ScriptProcess Start(string root, string scriptName, ILauncherLog log, string? stopTarget = null)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("当前只实现 Windows 服务脚本管理。");
        var script = Path.Combine(root, scriptName);
        if (!File.Exists(script)) throw new FileNotFoundException("缺少发行脚本。", script);
        var info = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "cmd.exe"))
        {
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            Arguments = "/d /v:off /s /c \"\"%AMVAR_SCRIPT%\" --app-root \"%AMVAR_ROOT%\""
                + (stopTarget == null ? "" : " --expected-root-identity-file \"%AMVAR_STOP_TARGET%\" --graceful-only --graceful-timeout-seconds 30") + "\""
        };
        info.Environment["AMVAR_SCRIPT"] = script;
        info.Environment["AMVAR_ROOT"] = root;
        if (stopTarget != null) info.Environment["AMVAR_STOP_TARGET"] = stopTarget;
        info.Environment.Remove("AMVISION_PYTHON_EXECUTABLE");
        info.Environment.Remove("PYTHONHOME");
        info.Environment.Remove("PYTHONPATH");
        info.Environment["PYTHONUTF8"] = "1";
        info.Environment["PYTHONIOENCODING"] = "utf-8";
        foreach (var name in info.Environment.Keys.Where(n => n.StartsWith("CONDA_", StringComparison.OrdinalIgnoreCase)).ToArray())
            info.Environment.Remove(name);
        return new(Process.Start(info) ?? throw new IOException("无法创建启动脚本进程。"), log);
    }
    private static async Task Drain(StreamReader reader, ILauncherLog log)
    {
        var buffer = new char[2048];
        int read;
        while ((read = await reader.ReadAsync(buffer)) != 0) log.Write(new string(buffer, 0, read));
    }
    public async Task<int> WaitAsync(CancellationToken token)
    {
        await Process.WaitForExitAsync(token);
        await drain.WaitAsync(token);
        return Process.ExitCode;
    }
    // 释放句柄不是停止；调用方必须先确认生命周期已完成。
    public void Dispose() => Process.Dispose();
}
