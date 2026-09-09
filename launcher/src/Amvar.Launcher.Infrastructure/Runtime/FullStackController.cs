using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Runtime;
using Amvar.Launcher.Infrastructure.Contracts;
using Amvar.Launcher.Infrastructure.Processes;
using Amvar.Launcher.Infrastructure.Serialization;

namespace Amvar.Launcher.Infrastructure.Runtime;

/// <summary>只拥有本次创建的同步 batch 子树；磁盘中的外部 root 永不自动接管。</summary>
public sealed class FullStackController(string requestDirectory, ILauncherLog log, int listeningPort = 5600) : IStackController, IDisposable
{
    private readonly ProcessInspector inspector = new();
    private ScriptProcess? launcher;
    private string? root;
    private ProcessIdentityDocument? ownedRoot;
    private readonly List<ProcessIdentityDocument> knownComponents = [];
    private ScriptProcess? stop;
    private string? stopRequest;
    public bool HasOwnedSession => launcher is not null;
    private static string StateFile(string path) => Path.Combine(path, "logs", "full-stack", "runtime-state.json");

    public Task StartAsync(ProjectInstallation installation, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (launcher != null) throw new InvalidOperationException("本次会话已经创建启动任务。");
        var path = installation.RootDirectory;
        foreach (var relative in new[] { "start-amvision-full.bat", "stop-amvision-full.bat", "python/python.exe", "launchers/inspect_process.py" })
            if (!File.Exists(Path.Combine(path, relative))) throw new FileNotFoundException("发行目录缺少 " + relative);
        if (!Directory.Exists(Path.Combine(path, "manifests", "release-profiles")) || !File.Exists(Path.Combine(path, "frontend", "index.html")))
            throw new IOException("发行目录缺少 manifest 或前端静态资源。");
        root = path;
        // 创建与赋值之间没有 await；Coordinator 等待本方法结束后才执行停止。
        launcher = ScriptProcess.Start(path, "start-amvision-full.bat", log);
        return Task.CompletedTask;
    }

    private async Task<FullSupervisorStateV1?> ReadState(string path, CancellationToken token)
    {
        var file = StateFile(path);
        if (!File.Exists(file)) return null;
        var state = LauncherJson.Read<FullSupervisorStateV1>(await File.ReadAllTextAsync(file, token), false);
        if (state.FormatId != "amvision.full-supervisor-state.v1" || !ProcessIdentityDocument.SamePath(state.AppRoot, path))
            throw new IOException("服务状态文件格式或项目目录不匹配。");
        return state;
    }

    private async Task<bool> Alive(ProcessIdentityDocument identity, CancellationToken token) =>
        (await inspector.InspectAsync(root!, identity.Pid, token)).Identity is { } current && identity.Matches(current);

    public async Task<StackObservation> ObserveAsync(ProjectInstallation installation, CancellationToken token)
    {
        var path = installation.RootDirectory;
        var state = await ReadState(path, token);
        if (launcher == null)
        {
            if (state == null) return new(StackPhase.Absent);
            var external = await inspector.InspectAsync(path, state.RootProcess.Pid, token);
            return external.Identity is { } identity && identity.Matches(state.RootProcess)
                ? new(StackPhase.Starting) : new(StackPhase.Absent);
        }
        if (state != null && ownedRoot == null)
        {
            var candidate = await inspector.InspectAsync(path, state.RootProcess.Pid, token);
            if (candidate.Identity is { } identity && identity.Matches(state.RootProcess) &&
                !launcher.Process.HasExited && candidate.AncestorPids.Contains(launcher.Process.Id) &&
                identity.CreateTime >= new DateTimeOffset(launcher.Process.StartTime.ToUniversalTime()).ToUnixTimeMilliseconds() / 1000.0 - .01)
                ownedRoot = state.RootProcess;
        }
        if (ownedRoot == null)
            return launcher.Process.HasExited ? new(StackPhase.Failed, "启动任务已退出，未接管任何外部服务。") : new(StackPhase.Starting);
        if (!await Alive(ownedRoot, token)) return new(StackPhase.Failed, "本次视觉服务已退出。");
        if (state == null || !state.RootProcess.Matches(ownedRoot)) return new(StackPhase.Failed, "服务状态已改变，不能绑定到其他实例。");
        var currentComponents = state.Components.Select(c => c.Process).OfType<ProcessIdentityDocument>().ToArray();
        // 恢复换代后只移除已验证退出的旧身份，避免长期观察无限保留进程历史。
        foreach (var previous in knownComponents.ToArray())
            if (!currentComponents.Any(current => current.Matches(previous)) && !await Alive(previous, token))
                knownComponents.Remove(previous);
        foreach (var component in currentComponents)
            if (!knownComponents.Any(existing => existing.Matches(component))) knownComponents.Add(component);
        var statusFile = Path.Combine(path, "logs", "full-stack", "launcher-status.json");
        if (!File.Exists(statusFile)) return new(StackPhase.Starting);
        var status = LauncherJson.Read<LauncherStatusDocumentV1>(await File.ReadAllTextAsync(statusFile, token), false);
        if (status.FormatId is not ("amvision.launcher-status.v1" or "amvision.launcher-status.v2"))
            return new(StackPhase.Failed, "不支持的服务状态版本，请使用同一发行包的启动器。");
        if (!status.RootProcess.Matches(ownedRoot)) return new(StackPhase.Failed, "服务状态身份不匹配。");
        if (status.State == "running")
        {
            var endpoint = await inspector.InspectAsync(path, ownedRoot.Pid, token, listeningPort);
            if (endpoint.Identity == null || !endpoint.Identity.Matches(ownedRoot)) return new(StackPhase.Failed, "本次服务身份已改变。");
            if (endpoint.Listeners.Count == 0) return new(StackPhase.Degraded, "视觉服务进程存活，但 HTTP 监听不可用。");
            if (endpoint.Listeners.Any(listener => !listener.Identity.Matches(ownedRoot) && !listener.AncestorPids.Contains(ownedRoot.Pid)))
                return new(StackPhase.Failed, "工作台端口由其他进程占用。");
        }
        return status.State switch
        {
            "running" => new(StackPhase.Running), "starting" => new(StackPhase.Starting),
            "degraded" when status.FormatId == "amvision.launcher-status.v2" => new(StackPhase.Degraded, "视觉服务接入异常，正在确认。"),
            "recovering" when status.FormatId == "amvision.launcher-status.v2" => new(StackPhase.Recovering),
            "stopping" => new(StackPhase.Stopping), "failed" => new(StackPhase.Failed, status.Error?.Message),
            _ => new(StackPhase.Failed, "未知服务阶段。")
        };
    }

    public async Task<StackStopResult> StopAsync(CancellationToken token)
    {
        if (launcher == null) return new(true);
        try
        {
            while (ownedRoot == null && !launcher.Process.HasExited)
            {
                await ObserveAsync(new(root!), token);
                if (ownedRoot == null) await Task.Delay(200, token);
            }
            if (ownedRoot == null) { await launcher.WaitAsync(token); return new(true); }
            if (await Alive(ownedRoot, token))
            {
                if (stop == null || stop.Process.HasExited)
                {
                    if (stop != null) { await stop.WaitAsync(token); stop.Dispose(); CleanupRequest(); }
                    Directory.CreateDirectory(requestDirectory);
                    stopRequest = Path.Combine(requestDirectory, Guid.NewGuid().ToString("N") + ".json");
                    await File.WriteAllTextAsync(stopRequest, LauncherJson.Write(new StopTargetDocumentV1 { RootProcess = ownedRoot }), token);
                    stop = ScriptProcess.Start(root!, "stop-amvision-full.bat", log, stopRequest);
                }
                var code = await stop.WaitAsync(token);
                CleanupRequest();
                if (code != 0) return new(false, "服务尚未停止，请查看日志后重试退出。");
            }
            if (await Alive(ownedRoot, token)) return new(false, "本次 root 仍在运行。");
            foreach (var component in knownComponents)
                if (await Alive(component, token)) return new(false, "本次服务仍有组件未退出。");
            await launcher.WaitAsync(token);
            return new(true);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        { log.Write("停止服务失败", ex); return new(false, ex.Message); }
    }
    private void CleanupRequest()
    {
        if (stopRequest != null && (stop == null || stop.Process.HasExited))
        { File.Delete(stopRequest); stopRequest = null; }
    }
    public void Dispose()
    {
        CleanupRequest();
        launcher?.Dispose();
        stop?.Dispose();
    }
}
