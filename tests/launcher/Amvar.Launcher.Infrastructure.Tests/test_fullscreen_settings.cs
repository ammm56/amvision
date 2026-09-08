using Amvar.Launcher.Infrastructure.Contracts;
using Amvar.Launcher.Infrastructure.Serialization;

namespace Amvar.Launcher.Infrastructure.Tests;

public sealed class FullscreenSettingsTests
{
    [Fact]
    public void Old_configuration_defaults_to_windowed_and_roundtrip_preserves_startup_preference()
    {
        var old = LauncherJson.Read<LauncherSettingsDocumentV1>("{\"schema_version\":1}").ToSettings();
        Assert.False(old.StartFullscreen);
        var document = LauncherSettingsDocumentV1.From(old with { StartFullscreen = true });
        var reloaded = LauncherJson.Read<LauncherSettingsDocumentV1>(LauncherJson.Write(document)).ToSettings();
        Assert.True(reloaded.StartFullscreen);
    }
    [Theory]
    [InlineData("null")]
    [InlineData("\"true\"")]
    [InlineData("1")]
    public void Invalid_fullscreen_values_are_rejected(string value) =>
        Assert.Throws<Newtonsoft.Json.JsonSerializationException>(() => LauncherJson.Read<LauncherSettingsDocumentV1>("{\"schema_version\":1,\"start_fullscreen\":" + value + "}"));
}
