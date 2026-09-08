using System.Runtime.InteropServices;

namespace Amvar.Launcher.Desktop.Services.Interop;

// 按 Microsoft WebView2.idl 的稳定 IUnknown ABI 定义，仅使用快捷键注册/注销。
// 前置方法保留准确的 vtable 顺序；不依赖 Avalonia 内部类型或反射。
[ComImport, Guid("4D00C0D1-9434-4EB6-8078-8697A560334F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface ICoreWebView2Controller
{
    int GetIsVisible();
    void SetIsVisible(int value);
    WebViewRect GetBounds();
    void SetBounds(WebViewRect value);
    double GetZoomFactor();
    void SetZoomFactor(double value);
    void AddZoomFactorChanged(IntPtr handler, out long token);
    void RemoveZoomFactorChanged(long token);
    void SetBoundsAndZoomFactor(WebViewRect bounds, double zoom);
    void MoveFocus(int reason);
    void AddMoveFocusRequested(IntPtr handler, out long token);
    void RemoveMoveFocusRequested(long token);
    void AddGotFocus(IntPtr handler, out long token);
    void RemoveGotFocus(long token);
    void AddLostFocus(IntPtr handler, out long token);
    void RemoveLostFocus(long token);
    void AddAcceleratorKeyPressed(ICoreWebView2AcceleratorKeyPressedEventHandler handler, out long token);
    void RemoveAcceleratorKeyPressed(long token);
}

[ComVisible(true), Guid("B29C7E28-FA79-41A8-8E44-65811C76DCB2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface ICoreWebView2AcceleratorKeyPressedEventHandler
{
    void Invoke(IntPtr sender, ICoreWebView2AcceleratorKeyPressedEventArgs args);
}

[ComImport, Guid("9F760F8A-FB79-42BE-9990-7B56900FA9C7"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface ICoreWebView2AcceleratorKeyPressedEventArgs
{
    int GetKeyEventKind();
    uint GetVirtualKey();
    int GetKeyEventLParam();
    PhysicalKeyStatus GetPhysicalKeyStatus();
    int GetHandled();
    void SetHandled(int handled);
}

[StructLayout(LayoutKind.Sequential)]
public struct WebViewRect { public int Left, Top, Right, Bottom; }

[StructLayout(LayoutKind.Sequential)]
public struct PhysicalKeyStatus
{
    public uint RepeatCount, ScanCode;
    public int IsExtendedKey, IsMenuKeyDown, WasKeyDown, IsKeyReleased;
}
