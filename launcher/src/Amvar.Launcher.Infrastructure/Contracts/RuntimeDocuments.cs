using Newtonsoft.Json;

namespace Amvar.Launcher.Infrastructure.Contracts;

public sealed class ProcessIdentityDocument
{
    [JsonProperty("pid", Required = Required.Always)] public int Pid { get; set; }
    [JsonProperty("create_time", Required = Required.Always)] public double CreateTime { get; set; }
    [JsonProperty("executable", Required = Required.Always)] public string Executable { get; set; } = "";
    [JsonProperty("working_directory", Required = Required.Always)] public string WorkingDirectory { get; set; } = "";
    [JsonProperty("command_line", Required = Required.Always)] public List<string> CommandLine { get; set; } = [];
    public bool Matches(ProcessIdentityDocument other) => Pid == other.Pid && Math.Abs(CreateTime - other.CreateTime) < .01 &&
        SamePath(Executable, other.Executable) && SamePath(WorkingDirectory, other.WorkingDirectory) &&
        CommandLine.SequenceEqual(other.CommandLine);
    public static bool SamePath(string a, string b) => string.Equals(Path.GetFullPath(a), Path.GetFullPath(b),
        OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal);
}
public sealed class FullSupervisorStateV1
{
    [JsonProperty("format_id", Required = Required.Always)] public string FormatId { get; set; } = "";
    [JsonProperty("app_root", Required = Required.Always)] public string AppRoot { get; set; } = "";
    [JsonProperty("root_process", Required = Required.Always)] public ProcessIdentityDocument RootProcess { get; set; } = new();
    [JsonProperty("components", Required = Required.Always)] public List<SupervisedComponentDocument> Components { get; set; } = [];
}
public sealed class SupervisedComponentDocument
{
    [JsonProperty("name", Required = Required.Always)] public string Name { get; set; } = "";
    [JsonProperty("process")] public ProcessIdentityDocument? Process { get; set; }
}
public sealed class LauncherStatusDocumentV1
{
    [JsonProperty("format_id", Required = Required.Always)] public string FormatId { get; set; } = "";
    [JsonProperty("root_process", Required = Required.Always)] public ProcessIdentityDocument RootProcess { get; set; } = new();
    [JsonProperty("state", Required = Required.Always)] public string State { get; set; } = "";
    [JsonProperty("error")] public LauncherStatusError? Error { get; set; }
}
public sealed class LauncherStatusError
{
    [JsonProperty("code")] public string Code { get; set; } = "";
    [JsonProperty("message")] public string Message { get; set; } = "";
}
public sealed class StopTargetDocumentV1
{
    [JsonProperty("format_id")] public string FormatId { get; set; } = "amvision.launcher-stop-target.v1";
    [JsonProperty("root_process")] public required ProcessIdentityDocument RootProcess { get; init; }
}
public sealed class ProcessInspectionDocument
{
    [JsonProperty("format_id", Required = Required.Always)] public string FormatId { get; set; } = "";
    [JsonProperty("identity", Required = Required.AllowNull)] public ProcessIdentityDocument? Identity { get; set; }
    [JsonProperty("ancestor_pids", Required = Required.Always)] public List<int> AncestorPids { get; set; } = [];
    [JsonProperty("listeners")] public List<ListenerProcessDocument> Listeners { get; set; } = [];
}
public sealed class ListenerProcessDocument
{
    [JsonProperty("identity", Required = Required.Always)] public ProcessIdentityDocument Identity { get; set; } = new();
    [JsonProperty("ancestor_pids", Required = Required.Always)] public List<int> AncestorPids { get; set; } = [];
}
public sealed class ServiceHealthResponse
{
    [JsonProperty("status", Required = Required.Always)] public string Status { get; set; } = "";
    [JsonProperty("request_id", Required = Required.Always)] public string RequestId { get; set; } = "";
}
