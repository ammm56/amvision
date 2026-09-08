using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Configuration;

namespace Amvar.Launcher.Core.Application;

/// <summary>保存有效配置，隔离编辑副本；自动几何保存不能覆盖损坏或新版文件。</summary>
public sealed class SettingsService(ISettingsStore store)
{
    private readonly SemaphoreSlim gate = new(1, 1);
    public SettingsLoadResult? Loaded { get; private set; }
    public LauncherSettings Current => Loaded?.Settings ?? new();

    public async Task<SettingsLoadResult> LoadAsync(CancellationToken token = default)
    {
        await gate.WaitAsync(token);
        try { return Loaded = await store.LoadAsync(token); }
        finally { gate.Release(); }
    }
    public async Task SaveAsync(LauncherSettings settings, CancellationToken token = default)
    {
        settings.Validate();
        await gate.WaitAsync(token);
        try
        {
            if (Loaded?.Kind == SettingsLoadKind.UnsupportedVersion)
                throw new InvalidOperationException("配置版本不支持，不能覆盖该文件。");
            await store.SaveAsync(settings, token);
            Loaded = new(SettingsLoadKind.Valid, settings);
        }
        finally { gate.Release(); }
    }
    public async Task SaveWindowAsync(WindowPreferences window, CancellationToken token = default)
    {
        await gate.WaitAsync(token);
        try
        {
            if (Loaded?.CanPersist != true) return;
            var latest = await store.LoadAsync(token);
            if (!latest.CanPersist) { Loaded = latest; return; }
            var settings = latest.Settings with { Window = window };
            settings.Validate();
            await store.SaveAsync(settings, token);
            Loaded = new(SettingsLoadKind.Valid, settings);
        }
        finally { gate.Release(); }
    }
}
