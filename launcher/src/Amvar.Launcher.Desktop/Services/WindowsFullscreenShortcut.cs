using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using Avalonia.Platform;
using Amvar.Launcher.Desktop.Services.Interop;

namespace Amvar.Launcher.Desktop.Services;

/// <summary>通过官方 WebView2 COM 事件处理网页焦点内的 F11，不接管其他快捷键。</summary>
[SupportedOSPlatform("windows")]
public sealed class WindowsFullscreenShortcut : IDisposable
{
    private readonly ICoreWebView2Controller controller;
    private readonly ShortcutHandler handler;
    private readonly long token;
    private bool disposed;

    public WindowsFullscreenShortcut(IWindowsWebView2PlatformHandle handle, Action toggle)
    {
        controller = (ICoreWebView2Controller)Marshal.GetObjectForIUnknown(handle.CoreWebView2Controller);
        handler = new(toggle);
        controller.AddAcceleratorKeyPressed(handler, out token);
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        try { controller.RemoveAcceleratorKeyPressed(token); }
        finally { Marshal.ReleaseComObject(controller); }
    }

    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    private sealed class ShortcutHandler(Action toggle) : ICoreWebView2AcceleratorKeyPressedEventHandler
    {
        public void Invoke(IntPtr sender, ICoreWebView2AcceleratorKeyPressedEventArgs args)
        {
            if (args.GetVirtualKey() != 0x7A || HasModifier()) return;
            args.SetHandled(1);
            if (args.GetKeyEventKind() == 0 && args.GetPhysicalKeyStatus().WasKeyDown == 0)
                toggle();
        }

        private static bool HasModifier() => IsPressed(0x10) || IsPressed(0x11) || IsPressed(0x12) || IsPressed(0x5B) || IsPressed(0x5C);
        private static bool IsPressed(int key) => (GetKeyState(key) & 0x8000) != 0;
        [DllImport("user32.dll")] private static extern short GetKeyState(int virtualKey);
    }
}
