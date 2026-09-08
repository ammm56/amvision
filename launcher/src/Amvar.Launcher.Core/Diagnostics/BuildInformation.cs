namespace Amvar.Launcher.Core.Diagnostics;

/// <summary>关于窗口及发行元数据共同使用的值模型。</summary>
public sealed record class BuildInformation(string Name, string Version, DateTimeOffset BuiltAt,
    string Commit, string License, string Repository, string Website);
