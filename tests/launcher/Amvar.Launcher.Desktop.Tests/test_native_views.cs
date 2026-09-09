using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Interactivity;
using Avalonia.Platform;
using Avalonia.Controls.Presenters;
using Avalonia.Media;
using Avalonia.Styling;
using Avalonia.VisualTree;
using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Application;
using Amvar.Launcher.Core.Configuration;
using Amvar.Launcher.Infrastructure.Metadata;
using Amvar.Launcher.Desktop.Views;

namespace Amvar.Launcher.Desktop.Tests;

[Collection("Avalonia UI")]
public sealed class NativeViewTests
{
    [Fact]
    public async Task Settings_save_uses_typed_values_and_preserves_geometry()
    {
        using var session = HeadlessUnitTestSession.StartNew(typeof(TestApplication));
        await session.Dispatch(async () =>
        {
            var store = new MemorySettings();
            var service = new SettingsService(store);
            await service.LoadAsync();
            var window = new SettingsWindow(service, "config/launcher.json");
            window.Show();
            window.FindControl<CheckBox>("ManageService")!.IsChecked = false;
            window.FindControl<CheckBox>("StartFullscreen")!.IsChecked = true;
            window.FindControl<TextBox>("ProjectRoot")!.Text = "视觉 项目";
            window.FindControl<Button>("SaveButton")!.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            Assert.True(window.Saved);
            Assert.False(store.Value.ManageService);
            Assert.True(store.Value.StartFullscreen);
            Assert.Equal("视觉 项目", store.Value.ProjectRoot);
            Assert.Equal(1400, store.Value.Window.Width);
            window.Close();
            return true;
        }, CancellationToken.None);
    }
    [Fact]
    public async Task Unknown_configuration_version_disables_save()
    {
        using var session = HeadlessUnitTestSession.StartNew(typeof(TestApplication));
        await session.Dispatch(async () =>
        {
            var service = new SettingsService(new MemorySettings { Kind = SettingsLoadKind.UnsupportedVersion });
            await service.LoadAsync();
            var window = new SettingsWindow(service, "config/launcher.json");
            window.Show();
            Assert.False(window.FindControl<Button>("SaveButton")!.IsEnabled);
            Assert.True(window.FindControl<TextBlock>("Problem")!.IsVisible);
            window.Close();
            return true;
        }, CancellationToken.None);
    }
    [Fact]
    public async Task About_and_main_xaml_load_with_embedded_offline_assets()
    {
        using var session = HeadlessUnitTestSession.StartNew(typeof(TestApplication));
        await session.Dispatch(() =>
        {
            var about = new AboutWindow(BuildInformationReader.Read(typeof(MainWindow).Assembly));
            about.Show();
            Assert.Equal("0.1.6", about.FindControl<SelectableTextBlock>("VersionText")!.Text);
            using var license = new StreamReader(AssetLoader.Open(new Uri("avares://amvar.launcher/Assets/LICENSE.txt")));
            Assert.Contains("PolyForm", license.ReadToEnd());
            using var icon = AssetLoader.Open(new Uri("avares://amvar.launcher/Assets/app.ico"));
            Assert.True(icon.Length > 100);
            var main = new MainWindow { DataContext = new Amvar.Launcher.Desktop.ViewModels.LauncherViewModel() };
            main.Show();
            Assert.NotNull(main.FindControl<Border>("LoadingSurface"));
            main.Close(); about.Close();
        }, CancellationToken.None);
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Settings_hover_and_focus_keep_one_input_outline_and_white_save_text(bool dark)
    {
        using var session = HeadlessUnitTestSession.StartNew(typeof(TestApplication));
        await session.Dispatch(async () =>
        {
            var service = new SettingsService(new MemorySettings());
            await service.LoadAsync();
            var window = new SettingsWindow(service, "config/launcher.json")
                { RequestedThemeVariant = dark ? ThemeVariant.Dark : ThemeVariant.Light };
            window.Show();
            window.UpdateLayout();
            var input = window.FindControl<NumericUpDown>("Timeout")!;
            var textbox = input.GetVisualDescendants().OfType<TextBox>().Single();
            var innerBorder = textbox.GetVisualDescendants().OfType<Border>()
                .Single(border => border.Name == "PART_BorderElement");
            void CheckOutline()
            {
                Assert.False(innerBorder.IsVisible);
                Assert.Equal(new Thickness(1), input.BorderThickness);
            }
            CheckOutline();
            window.MouseMove(textbox.TranslatePoint(new Point(10, 10), window)!.Value);
            Assert.True(textbox.IsPointerOver);
            CheckOutline();
            textbox.Focus();
            Assert.True(textbox.IsFocused);
            CheckOutline();

            var save = window.FindControl<Button>("SaveButton")!;
            var content = save.GetVisualDescendants().OfType<ContentPresenter>()
                .Single(presenter => presenter.Name == "PART_ContentPresenter");
            Assert.Equal(Colors.White, Assert.IsAssignableFrom<ISolidColorBrush>(content.Foreground).Color);
            window.MouseMove(save.TranslatePoint(new Point(10, 10), window)!.Value);
            Assert.True(save.IsPointerOver);
            Assert.Equal(Colors.White, Assert.IsAssignableFrom<ISolidColorBrush>(content.Foreground).Color);
            Assert.Equal(1, content.Opacity);
            window.Close();
            return true;
        }, CancellationToken.None);
    }
    public sealed class TestApplication
    {
        public static AppBuilder BuildAvaloniaApp() => AppBuilder.Configure<Amvar.Launcher.Desktop.App>().UseHeadless(new());
    }
    private sealed class MemorySettings : ISettingsStore
    {
        public LauncherSettings Value = new() { Window = new(1400, 900) };
        public SettingsLoadKind Kind = SettingsLoadKind.Valid;
        public Task<SettingsLoadResult> LoadAsync(CancellationToken token) => Task.FromResult(new SettingsLoadResult(Kind, Value, "配置版本不支持"));
        public Task SaveAsync(LauncherSettings settings, CancellationToken token) { Value = settings; return Task.CompletedTask; }
    }
}
