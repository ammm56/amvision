using System.Text.Json;
using Amvision.TriggerSources;

if (args.Length < 3 || args.Length > 5)
{
    Console.Error.WriteLine("Usage: ZeroMqImageInvoke <endpoint> <trigger_source_id> <image_path> [media_type] [deployment_instance_id]");
    Console.Error.WriteLine("如果只提供一个可选参数且它不是 media type，示例程序会把它当作 deployment_instance_id，并按图片扩展名猜测 media_type。");
    return 2;
}

var endpoint = args[0];
var triggerSourceId = args[1];
var imagePath = args[2];
string resolvedImagePath;
try
{
    resolvedImagePath = ResolveImagePath(imagePath);
}
catch (FileNotFoundException exception)
{
    Console.Error.WriteLine(exception.Message);
    return 1;
}

var (mediaType, deploymentInstanceId) = ParseOptionalArguments(args, resolvedImagePath);

using var client = new AmvisionTriggerClient(new AmvisionTriggerClientOptions
{
    Endpoint = endpoint,
    TriggerSourceId = triggerSourceId,
    DefaultInputBinding = "request_image",
    Timeout = TimeSpan.FromSeconds(5)
});

var request = new ImageTriggerRequest
{
    ImageBytes = File.ReadAllBytes(resolvedImagePath),
    MediaType = mediaType,
    Metadata =
    {
        ["source"] = "dotnet-example"
    }
};

if (!string.IsNullOrWhiteSpace(deploymentInstanceId))
{
    request.Payload["deployment_request"] = new Dictionary<string, object?>
    {
        ["value"] = new Dictionary<string, object?>
        {
            ["deployment_instance_id"] = deploymentInstanceId
        }
    };
}

try
{
    var result = client.InvokeImage(request);

    Console.WriteLine($"state={result.State}");
    Console.WriteLine($"workflow_run_id={result.WorkflowRunId}");
    Console.WriteLine($"event_id={result.EventId}");
    return 0;
}
catch (AmvisionTriggerException exception)
{
    Console.Error.WriteLine($"error_code={exception.ErrorCode}");
    Console.Error.WriteLine($"error_message={exception.Message}");
    if (exception.Details.Count > 0)
    {
        Console.Error.WriteLine($"details={JsonSerializer.Serialize(exception.Details)}");
    }
    return 1;
}

static (string MediaType, string? DeploymentInstanceId) ParseOptionalArguments(string[] args, string imagePath)
{
    var guessedMediaType = GuessMediaType(imagePath);
    if (args.Length <= 3)
    {
        return (guessedMediaType, null);
    }

    if (args.Length == 4)
    {
        var optionalValue = args[3].Trim();
        if (LooksLikeMediaType(optionalValue))
        {
            return (optionalValue, null);
        }

        return (guessedMediaType, optionalValue);
    }

    var mediaType = string.IsNullOrWhiteSpace(args[3]) ? guessedMediaType : args[3].Trim();
    var deploymentInstanceId = string.IsNullOrWhiteSpace(args[4]) ? null : args[4].Trim();
    return (mediaType, deploymentInstanceId);
}

static string ResolveImagePath(string imagePath)
{
    if (File.Exists(imagePath))
    {
        return imagePath;
    }

    var fileName = Path.GetFileName(imagePath);
    if (!string.IsNullOrWhiteSpace(fileName) && string.IsNullOrWhiteSpace(Path.GetDirectoryName(imagePath)))
    {
        var workspaceSamplePath = Path.Combine(
            Environment.CurrentDirectory,
            "data",
            "files",
            "validation-inputs",
            fileName
        );
        if (File.Exists(workspaceSamplePath))
        {
            return workspaceSamplePath;
        }
    }

    var sampleHint = string.IsNullOrWhiteSpace(fileName)
        ? string.Empty
        : $" 如果使用仓库内样例，请传 data/files/validation-inputs/{fileName}。";
    throw new FileNotFoundException(
        $"找不到图片文件：{imagePath}。当前工作目录：{Environment.CurrentDirectory}。{sampleHint}"
    );
}

static bool LooksLikeMediaType(string value)
{
    return !string.IsNullOrWhiteSpace(value) && value.Contains('/') && !value.Contains('\\');
}

// 根据文件扩展名推断 media type。
static string GuessMediaType(string path)
{
    var extension = Path.GetExtension(path).ToLowerInvariant();
    return extension switch
    {
        ".jpg" or ".jpeg" => "image/jpeg",
        ".png" => "image/png",
        ".bmp" => "image/bmp",
        _ => "image/octet-stream"
    };
}