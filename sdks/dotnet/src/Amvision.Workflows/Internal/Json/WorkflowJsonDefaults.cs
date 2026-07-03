using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.Workflows;

internal static class WorkflowJsonDefaults
{
    internal static readonly JsonSerializerOptions SerializerOptions = new JsonSerializerOptions
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNamingPolicy = null,
        WriteIndented = false
    };
}
