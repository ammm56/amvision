using System.Text;
using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Configuration;
using Amvar.Launcher.Infrastructure.Contracts;
using Amvar.Launcher.Infrastructure.Serialization;

namespace Amvar.Launcher.Infrastructure.Configuration;

public sealed class JsonSettingsStore(string filePath) : ISettingsStore
{
    public async Task<SettingsLoadResult> LoadAsync(CancellationToken token)
    {
        if (!File.Exists(filePath)) return new(SettingsLoadKind.Missing, new());
        try
        {
            var json = await File.ReadAllTextAsync(filePath, token);
            if (LauncherJson.Read<SettingsHeader>(json, false).SchemaVersion != 1)
                return new(SettingsLoadKind.UnsupportedVersion, new(), "配置版本不支持，原文件已保留。");
            var settings = LauncherJson.Read<LauncherSettingsDocumentV1>(json).ToSettings();
            settings.Validate();
            return new(SettingsLoadKind.Valid, settings);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        { return new(SettingsLoadKind.Corrupt, new(), $"配置读取失败：{ex.Message}"); }
    }

    public async Task SaveAsync(LauncherSettings settings, CancellationToken token)
    {
        settings.Validate();
        // 即便文件由外部编辑升级，也不能被旧进程的自动保存覆盖。
        var current = await LoadAsync(token);
        if (current.Kind == SettingsLoadKind.UnsupportedVersion) throw new InvalidOperationException(current.Error);
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(filePath))!);
        var temporary = filePath + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            await File.WriteAllTextAsync(temporary, LauncherJson.Write(LauncherSettingsDocumentV1.From(settings)), new UTF8Encoding(false), token);
            token.ThrowIfCancellationRequested();
            File.Move(temporary, filePath, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
