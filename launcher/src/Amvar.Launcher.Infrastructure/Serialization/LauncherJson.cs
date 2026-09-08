using System.Globalization;
using Newtonsoft.Json;
using Newtonsoft.Json.Converters;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json.Serialization;

namespace Amvar.Launcher.Infrastructure.Serialization;

/// <summary>仅 Infrastructure 使用 JSON DOM 做重复键检查；对外仍是具名 DTO。</summary>
public static class LauncherJson
{
    public static JsonSerializerSettings Settings(bool strict = true) => new()
    {
        TypeNameHandling = TypeNameHandling.None,
        MissingMemberHandling = strict ? MissingMemberHandling.Error : MissingMemberHandling.Ignore,
        Formatting = Formatting.Indented,
        MaxDepth = 32,
        Converters = { new StrictScalarConverter(), new StringEnumConverter(new SnakeCaseNamingStrategy(), false) }
    };

    public static T Read<T>(string json, bool strict = true)
    {
        using var reader = new JsonTextReader(new StringReader(json)) { DateParseHandling = DateParseHandling.None };
        var value = JToken.Load(reader, new JsonLoadSettings { DuplicatePropertyNameHandling = DuplicatePropertyNameHandling.Error });
        if (reader.Read()) throw new JsonSerializationException("JSON 文件含多余内容。");
        return value.ToObject<T>(JsonSerializer.Create(Settings(strict))) ?? throw new JsonSerializationException("JSON 不能为空。");
    }
    public static string Write<T>(T value) => JsonConvert.SerializeObject(value, Settings()) + Environment.NewLine;

    private sealed class StrictScalarConverter : JsonConverter
    {
        public override bool CanConvert(Type type) => type == typeof(bool) || type == typeof(int) || type == typeof(string);
        public override bool CanWrite => false;
        public override object? ReadJson(JsonReader reader, Type type, object? existingValue, JsonSerializer serializer)
        {
            var expected = type == typeof(bool) ? JsonToken.Boolean : type == typeof(int) ? JsonToken.Integer : JsonToken.String;
            if (reader.TokenType != expected) throw new JsonSerializationException($"字段 {reader.Path} 类型错误，需要 {expected}。");
            return Convert.ChangeType(reader.Value, type, CultureInfo.InvariantCulture);
        }
        public override void WriteJson(JsonWriter writer, object? value, JsonSerializer serializer) => throw new NotSupportedException();
    }
}
