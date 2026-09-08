using Amvar.Launcher.Core.Configuration;
using Amvar.Launcher.Core.Application;
using Amvar.Launcher.Infrastructure.Configuration;

namespace Amvar.Launcher.Infrastructure.Tests;

public sealed class SettingsTests : IDisposable
{
    private readonly string directory = Path.Combine(FindRoot(), ".tmp", "launcher", Guid.NewGuid().ToString("N"));
    private string FilePath => Path.Combine(directory, "launcher.json");
    private JsonSettingsStore Store => new(FilePath);
    private static string FindRoot()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root != null && !File.Exists(Path.Combine(root.FullName, "AGENTS.md"))) root = root.Parent;
        return root?.FullName ?? throw new InvalidOperationException("Repository root missing");
    }
    private async Task Write(string json) { Directory.CreateDirectory(directory); await File.WriteAllTextAsync(FilePath, json); }
    [Fact] public async Task Defaults_roundtrip_preserves_false_unicode_and_geometry()
    {
        Assert.Equal(SettingsLoadKind.Missing, (await Store.LoadAsync(default)).Kind);
        var value = new LauncherSettings { ManageService = false, ProjectRoot = "视觉 项目", Window = new(1360, 900, true) };
        await Store.SaveAsync(value, default);
        Assert.Equal(value, (await Store.LoadAsync(default)).Settings);
    }
    [Theory]
    [InlineData("{\"schema_version\":1,\"manage_service\":\"false\"}")]
    [InlineData("{\"schema_version\":1,\"manage_service\":0}")]
    [InlineData("{\"schema_version\":1,\"manage_service\":null}")]
    [InlineData("{\"schema_version\":1,\"theme\":4}")]
    [InlineData("{\"schema_version\":1,\"theme\":\"other\"}")]
    [InlineData("{\"schema_version\":1,\"window\":null}")]
    [InlineData("{\"schema_version\":1,\"unknown\":true}")]
    [InlineData("{\"schema_version\":1,\"manage_service\":true,\"manage_service\":false}")]
    [InlineData("{}")]
    public async Task Invalid_config_is_reported_and_not_overwritten_by_geometry(string json)
    {
        await Write(json);
        var service = new SettingsService(Store);
        Assert.Equal(SettingsLoadKind.Corrupt, (await service.LoadAsync()).Kind);
        await service.SaveWindowAsync(new());
        Assert.Equal(json, await File.ReadAllTextAsync(FilePath));
    }
    [Fact] public async Task Unknown_version_cannot_be_overwritten_even_by_explicit_save()
    {
        await Write("{\"schema_version\":2}");
        var service = new SettingsService(Store);
        await service.LoadAsync();
        await Assert.ThrowsAsync<InvalidOperationException>(() => service.SaveAsync(new()));
        Assert.Contains(":2", await File.ReadAllTextAsync(FilePath));
    }
    [Fact] public async Task Geometry_save_retains_service_management_setting()
    {
        var service = new SettingsService(Store);
        await service.LoadAsync();
        await service.SaveAsync(new() { ManageService = false });
        await service.SaveWindowAsync(new(1400, 850));
        Assert.False((await Store.LoadAsync(default)).Settings.ManageService);
    }
    public void Dispose() { if (Directory.Exists(directory)) Directory.Delete(directory, true); }
    [Fact] public async Task Geometry_save_does_not_replace_external_corruption_or_new_preferences()
    {
        var service = new SettingsService(Store);
        await service.LoadAsync();
        await service.SaveAsync(new());
        await Store.SaveAsync(new() { ManageService = false, ProjectRoot = "external" }, default);
        await service.SaveWindowAsync(new(1400, 850));
        Assert.False((await Store.LoadAsync(default)).Settings.ManageService);
        await Write("broken");
        await service.SaveWindowAsync(new());
        Assert.Equal("broken", await File.ReadAllTextAsync(FilePath));
    }
}
