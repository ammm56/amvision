using System.Diagnostics;
using Amvar.Launcher.Infrastructure.Contracts;
using Amvar.Launcher.Infrastructure.Serialization;

namespace Amvar.Launcher.Infrastructure.Processes;

/// <summary>通过随包只读脚本复用 psutil 身份协议，避免另一套 Windows PEB 解析。</summary>
public sealed class ProcessInspector
{
    public async Task<ProcessInspectionDocument> InspectAsync(string root, int pid, CancellationToken token, int? listeningPort = null)
    {
        var info = new ProcessStartInfo(Path.Combine(root, "python", "python.exe"))
        { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8, StandardErrorEncoding = System.Text.Encoding.UTF8 };
        info.ArgumentList.Add(Path.Combine(root, "launchers", "inspect_process.py"));
        info.ArgumentList.Add("--pid");
        info.ArgumentList.Add(pid.ToString(System.Globalization.CultureInfo.InvariantCulture));
        if (listeningPort.HasValue) { info.ArgumentList.Add("--listening-port"); info.ArgumentList.Add(listeningPort.Value.ToString(System.Globalization.CultureInfo.InvariantCulture)); }
        info.Environment["PYTHONUTF8"] = "1";
        info.Environment.Remove("PYTHONHOME");
        info.Environment.Remove("PYTHONPATH");
        using var process = Process.Start(info) ?? throw new IOException("无法检查服务进程身份。");
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
        timeout.CancelAfter(TimeSpan.FromSeconds(5));
        var output = process.StandardOutput.ReadToEndAsync(timeout.Token);
        var error = process.StandardError.ReadToEndAsync(timeout.Token);
        try
        {
            await process.WaitForExitAsync(timeout.Token);
            if (process.ExitCode != 0) throw new IOException("进程身份检查失败：" + await error);
            var document = LauncherJson.Read<ProcessInspectionDocument>(await output);
            if (document.FormatId != "amvision.launcher-process.v1") throw new IOException("进程身份格式无效。");
            return document;
        }
        finally
        {
            // 只回收本次只读检查进程，不触碰被检查对象。
            if (!process.HasExited) { process.Kill(true); await process.WaitForExitAsync(CancellationToken.None); }
            try { await Task.WhenAll(output, error); } catch (OperationCanceledException) when (timeout.IsCancellationRequested) { }
        }
    }
}
