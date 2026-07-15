using Amvision.Workflows.Configuration;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace Amvision.Workflows.Tools
{
    /// <summary>
    /// 从 Config/config_*.json 读取现场配置，并构建 Runtime、TriggerSource 和 ModelDeployment 配置索引。
    /// </summary>
    internal static class WorkflowConfigLoader
    {
        /// <summary>
        /// 根节点允许的字段；用于阻止旧配置字段被 JSON 反序列化静默忽略。
        /// </summary>
        private static readonly ISet<string> RootPropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "backend",
            "runtime",
            "invoke",
            "trigger_sources",
            "model_deployments"
        };

        /// <summary>
        /// backend 节点允许的字段。
        /// </summary>
        private static readonly ISet<string> BackendPropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "base_api_url",
            "access_token",
            "project_id",
            "http_timeout_seconds"
        };

        /// <summary>
        /// runtime 节点允许的字段。
        /// </summary>
        private static readonly ISet<string> RuntimePropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "name",
            "workflow_runtime_id"
        };

        /// <summary>
        /// invoke 节点允许的字段。
        /// </summary>
        private static readonly ISet<string> InvokePropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "image_path",
            "image_input_binding",
            "timeout_seconds",
            "event_limit",
            "event_preview_count",
            "source",
            "sync_scenario",
            "async_scenario",
            "use_direct_input_bindings"
        };

        /// <summary>
        /// trigger_sources[] 节点允许的字段。
        /// </summary>
        private static readonly ISet<string> TriggerSourcePropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "name",
            "trigger_source_id",
            "zero_mq"
        };

        /// <summary>
        /// zero_mq 节点允许的调用字段。
        /// </summary>
        private static readonly ISet<string> ZeroMqPropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "bind_endpoint",
            "default_input_binding",
            "max_image_bytes",
            "timeout_seconds"
        };

        /// <summary>
        /// model_deployments[] 节点允许的字段。
        /// </summary>
        private static readonly ISet<string> ModelDeploymentPropertyNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "name",
            "task_type",
            "deployment_instance_id",
            "runtime_mode",
            "input_transport_mode",
            "default_image_path",
            "default_input_uri",
            "default_input_file_id",
            "score_threshold",
            "top_k",
            "mask_threshold",
            "keypoint_confidence_threshold",
            "save_result_image",
            "return_preview_image_base64",
            "default_file_name",
            "default_media_type"
        };

        /// <summary>
        /// 从默认 Config 目录加载全部 config_*.json。
        /// </summary>
        /// <returns>按 runtime key、TriggerSource key 和 model deployment key 索引好的配置 catalog。</returns>
        public static WorkflowConfigurationCatalog LoadDefault()
        {
            return LoadDirectory(FindConfigDirectory());
        }

        /// <summary>
        /// 从指定目录加载所有 config_*.json，并校验 key 唯一性和配置字段。
        /// </summary>
        /// <param name="configDirectory">Config 目录路径。</param>
        /// <returns>按 key 查询的配置 catalog。</returns>
        public static WorkflowConfigurationCatalog LoadDirectory(string configDirectory)
        {
            var normalizedDirectory = Path.GetFullPath(ConfigValidation.RequireText(configDirectory, nameof(configDirectory)));
            if (!Directory.Exists(normalizedDirectory))
            {
                throw new DirectoryNotFoundException($"Config directory does not exist: {normalizedDirectory}");
            }

            var files = Directory.GetFiles(normalizedDirectory, "config_*.json")
                .OrderBy(item => item, StringComparer.OrdinalIgnoreCase)
                .ToArray();
            if (files.Length == 0)
            {
                throw new FileNotFoundException("No config_*.json files were found in Config directory.", normalizedDirectory);
            }

            var runtimes = new Dictionary<string, ConfiguredRuntime>(StringComparer.OrdinalIgnoreCase);
            var triggerSources = new Dictionary<string, ConfiguredTriggerSource>(StringComparer.OrdinalIgnoreCase);
            var modelDeployments = new Dictionary<string, ConfiguredModelDeployment>(StringComparer.OrdinalIgnoreCase);
            foreach (var file in files)
            {
                var config = LoadFile(file);
                if (config.Runtime != null)
                {
                    var invoke = config.Invoke ?? new InvokeConfig();
                    var runtime = new ConfiguredRuntime(config.Backend, config.Runtime, invoke, file);
                    if (runtimes.ContainsKey(config.Runtime.Name))
                    {
                        throw new InvalidOperationException($"Duplicate runtime config key: {config.Runtime.Name}");
                    }

                    runtimes[config.Runtime.Name] = runtime;
                    foreach (var triggerSource in config.TriggerSources)
                    {
                        if (triggerSources.ContainsKey(triggerSource.Name))
                        {
                            throw new InvalidOperationException($"Duplicate TriggerSource config key: {triggerSource.Name}");
                        }

                        triggerSources[triggerSource.Name] = new ConfiguredTriggerSource(
                            config.Backend,
                            config.Runtime,
                            triggerSource,
                            file);
                    }
                }
                else if (config.TriggerSources.Count > 0)
                {
                    throw new InvalidOperationException($"{Path.GetFileName(file)}.runtime is required when trigger_sources is not empty.");
                }

                foreach (var modelDeployment in config.ModelDeployments)
                {
                    if (modelDeployments.TryGetValue(modelDeployment.Name, out var existingModelDeployment))
                    {
                        if (ModelDeploymentsEquivalent(existingModelDeployment.ModelDeployment, modelDeployment))
                        {
                            continue;
                        }

                        throw new InvalidOperationException(
                            $"Model deployment config key has conflicting values: {modelDeployment.Name}. Existing file: {existingModelDeployment.SourceFile}; current file: {file}");
                    }

                    modelDeployments[modelDeployment.Name] = new ConfiguredModelDeployment(
                        config.Backend,
                        modelDeployment,
                        file);
                }
            }

            return new WorkflowConfigurationCatalog(runtimes, triggerSources, modelDeployments);
        }

        /// <summary>
        /// 判断两个 model_deployments[] 配置是否指向同一个调用目标；完全一致时允许跨文件去重。
        /// </summary>
        /// <param name="left">已加入 catalog 的配置。</param>
        /// <param name="right">当前配置文件中的配置。</param>
        /// <returns>字段一致时返回 true。</returns>
        private static bool ModelDeploymentsEquivalent(ModelDeploymentConfig left, ModelDeploymentConfig right)
        {
            return TextEquals(left.Name, right.Name)
                && TextEquals(left.TaskType, right.TaskType)
                && TextEquals(left.DeploymentInstanceId, right.DeploymentInstanceId)
                && TextEquals(left.RuntimeMode, right.RuntimeMode)
                && TextEquals(left.InputTransportMode, right.InputTransportMode)
                && TextEquals(left.DefaultImagePath, right.DefaultImagePath)
                && TextEquals(left.DefaultInputUri, right.DefaultInputUri)
                && TextEquals(left.DefaultInputFileId, right.DefaultInputFileId)
                && left.ScoreThreshold == right.ScoreThreshold
                && left.TopK == right.TopK
                && left.MaskThreshold == right.MaskThreshold
                && left.KeypointConfidenceThreshold == right.KeypointConfidenceThreshold
                && left.SaveResultImage == right.SaveResultImage
                && left.ReturnPreviewImageBase64 == right.ReturnPreviewImageBase64
                && TextEquals(left.DefaultFileName, right.DefaultFileName)
                && TextEquals(left.DefaultMediaType, right.DefaultMediaType);
        }

        /// <summary>
        /// 比较配置文本字段；空白和 null 都按未配置处理。
        /// </summary>
        /// <param name="left">左侧文本。</param>
        /// <param name="right">右侧文本。</param>
        /// <returns>文本一致时返回 true。</returns>
        private static bool TextEquals(string? left, string? right)
        {
            return string.Equals(
                ConfigValidation.NormalizeOptional(left),
                ConfigValidation.NormalizeOptional(right),
                StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// 读取单个配置文件，并执行完整字段校验。
        /// </summary>
        /// <param name="configPath">配置文件路径。</param>
        /// <returns>反序列化后的配置文件模型。</returns>
        private static WorkflowAppConfigFile LoadFile(string configPath)
        {
            var json = File.ReadAllText(configPath);
            ValidateKnownProperties(configPath, json);

            using var textReader = new StringReader(json);
            using var jsonReader = CreateJsonReader(textReader);
            var serializer = JsonSerializer.Create(WorkflowJsonDefaults.SerializerSettings);
            var config = serializer.Deserialize<WorkflowAppConfigFile>(jsonReader)
                ?? throw new InvalidOperationException($"Config file cannot be deserialized: {configPath}");
            config.Validate(Path.GetFileName(configPath));
            return config;
        }

        /// <summary>
        /// 校验配置文件只包含当前 SDK 支持的字段，避免旧字段被静默忽略。
        /// </summary>
        /// <param name="configPath">配置文件路径。</param>
        /// <param name="json">配置文件 JSON 内容。</param>
        private static void ValidateKnownProperties(string configPath, string json)
        {
            using var textReader = new StringReader(json);
            using var jsonReader = CreateJsonReader(textReader);
            var root = JToken.ReadFrom(jsonReader);
            var fileName = Path.GetFileName(configPath);

            ValidateObjectProperties(root, RootPropertyNames, fileName);
            foreach (var property in ((JObject)root).Properties())
            {
                var path = $"{fileName}.{property.Name}";
                switch (property.Name.ToLowerInvariant())
                {
                    case "backend":
                        ValidateObjectProperties(property.Value, BackendPropertyNames, path);
                        break;
                    case "runtime":
                        ValidateObjectProperties(property.Value, RuntimePropertyNames, path);
                        break;
                    case "invoke":
                        ValidateObjectProperties(property.Value, InvokePropertyNames, path);
                        break;
                    case "trigger_sources":
                        ValidateTriggerSourceArray(property.Value, path);
                        break;
                    case "model_deployments":
                        ValidateModelDeploymentArray(property.Value, path);
                        break;
                }
            }
        }

        /// <summary>
        /// 创建支持注释和尾逗号的 Newtonsoft.Json reader。
        /// </summary>
        /// <param name="textReader">JSON 文本读取器。</param>
        /// <returns>JsonTextReader。</returns>
        private static JsonTextReader CreateJsonReader(TextReader textReader)
        {
            return new JsonTextReader(textReader)
            {
                DateParseHandling = DateParseHandling.None
            };
        }

        /// <summary>
        /// 校验对象节点的字段集合是否都在允许列表内。
        /// </summary>
        /// <param name="element">JSON 节点。</param>
        /// <param name="allowedPropertyNames">允许的字段名集合。</param>
        /// <param name="path">错误提示中的字段路径。</param>
        private static void ValidateObjectProperties(JToken element, ISet<string> allowedPropertyNames, string path)
        {
            if (!(element is JObject jsonObject))
            {
                throw new InvalidOperationException($"{path} must be a JSON object.");
            }

            foreach (var property in jsonObject.Properties())
            {
                if (!allowedPropertyNames.Contains(property.Name))
                {
                    throw new InvalidOperationException($"{path}.{property.Name} is not supported by this SDK.");
                }
            }
        }

        /// <summary>
        /// 校验 TriggerSource 数组和每个 ZeroMQ 调用配置。
        /// </summary>
        /// <param name="element">trigger_sources JSON 节点。</param>
        /// <param name="path">错误提示中的字段路径。</param>
        private static void ValidateTriggerSourceArray(JToken element, string path)
        {
            if (!(element is JArray jsonArray))
            {
                throw new InvalidOperationException($"{path} must be a JSON array.");
            }

            for (var index = 0; index < jsonArray.Count; index++)
            {
                var item = jsonArray[index];
                var itemPath = $"{path}[{index}]";
                ValidateObjectProperties(item, TriggerSourcePropertyNames, itemPath);

                var jsonObject = (JObject)item;
                if (!jsonObject.TryGetValue("zero_mq", StringComparison.OrdinalIgnoreCase, out var zeroMqToken))
                {
                    throw new InvalidOperationException($"{itemPath}.zero_mq is required.");
                }

                ValidateObjectProperties(zeroMqToken, ZeroMqPropertyNames, $"{itemPath}.zero_mq");
            }
        }

        /// <summary>
        /// 校验模型 DeploymentInstance 调用配置数组。
        /// </summary>
        /// <param name="element">model_deployments JSON 节点。</param>
        /// <param name="path">错误提示中的字段路径。</param>
        private static void ValidateModelDeploymentArray(JToken element, string path)
        {
            if (!(element is JArray jsonArray))
            {
                throw new InvalidOperationException($"{path} must be a JSON array.");
            }

            for (var index = 0; index < jsonArray.Count; index++)
            {
                ValidateObjectProperties(jsonArray[index], ModelDeploymentPropertyNames, $"{path}[{index}]");
            }
        }

        /// <summary>
        /// 查找包含 config_*.json 的 Config 目录，兼容开发态和发布态路径。
        /// </summary>
        /// <returns>可用的 Config 目录路径。</returns>
        private static string FindConfigDirectory()
        {
            foreach (var candidate in EnumerateCandidateDirectories())
            {
                if (Directory.Exists(candidate)
                    && Directory.GetFiles(candidate, "config_*.json").Length > 0)
                {
                    return candidate;
                }
            }

            throw new DirectoryNotFoundException("Cannot find Config directory with config_*.json files.");
        }

        /// <summary>
        /// 按优先级枚举候选 Config 目录。
        /// </summary>
        /// <returns>候选目录路径序列。</returns>
        private static IEnumerable<string> EnumerateCandidateDirectories()
        {
            var baseDirectory = AppDomain.CurrentDomain.BaseDirectory;
            yield return Path.Combine(baseDirectory, "Config");
            yield return Path.Combine(Environment.CurrentDirectory, "Config");

            var directory = new DirectoryInfo(baseDirectory);
            while (directory != null)
            {
                yield return Path.Combine(directory.FullName, "Config");
                directory = directory.Parent;
            }
        }
    }
}
