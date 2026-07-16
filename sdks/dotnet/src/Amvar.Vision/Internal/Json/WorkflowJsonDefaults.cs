using System;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision
{

    internal static class WorkflowJsonDefaults
    {
        internal static readonly JsonSerializerSettings SerializerSettings = new JsonSerializerSettings
        {
            NullValueHandling = NullValueHandling.Ignore,
            MissingMemberHandling = MissingMemberHandling.Ignore,
            DateParseHandling = DateParseHandling.None
        };

        internal static string Serialize(object value)
        {
            if (value == null)
            {
                throw new ArgumentNullException(nameof(value));
            }

            return JsonConvert.SerializeObject(value, SerializerSettings);
        }

        internal static byte[] SerializeToUtf8Bytes(object value)
        {
            return Encoding.UTF8.GetBytes(Serialize(value));
        }

        internal static T Deserialize<T>(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                throw new JsonException("JSON content is empty.");
            }

            var value = JsonConvert.DeserializeObject<T>(json, SerializerSettings);
            if (value == null)
            {
                throw new JsonException("JSON content cannot be deserialized as " + typeof(T).Name + ".");
            }

            return value;
        }

        internal static T ToObject<T>(JToken token)
        {
            if (token == null)
            {
                throw new ArgumentNullException(nameof(token));
            }

            var serializer = JsonSerializer.Create(SerializerSettings);
            var value = token.ToObject<T>(serializer);
            if (value == null)
            {
                throw new JsonException("JSON token cannot be converted to " + typeof(T).Name + ".");
            }

            return value;
        }
    }
}
