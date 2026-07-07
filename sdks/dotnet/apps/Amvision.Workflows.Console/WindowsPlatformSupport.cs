#if NET10_0_OR_GREATER
using System.Runtime.Versioning;

// 本程序面向 Windows 上位机和工控机；System.Drawing 在 .NET 10 中属于 Windows 原生图像 API。
[assembly: SupportedOSPlatform("windows6.1")]
#endif
