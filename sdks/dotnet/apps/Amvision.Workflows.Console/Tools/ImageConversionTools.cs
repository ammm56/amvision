using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;

namespace Amvision.Workflows.Console.Tools;

/// <summary>
/// 图片文件和 Windows 原生 Bitmap 的转换目标格式。
/// </summary>
public enum ImageFileFormat
{
    /// <summary>
    /// JPEG 编码，适合工业现场大图压缩传输。
    /// </summary>
    Jpeg,

    /// <summary>
    /// PNG 编码，适合需要无损压缩或保留透明通道的图片。
    /// </summary>
    Png,

    /// <summary>
    /// BMP 编码，适合 Windows 原始位图交换，但文件体积通常较大。
    /// </summary>
    Bmp
}

/// <summary>
/// 使用 .NET Framework 原生 System.Drawing 实现 jpeg / png / bmp / base64 / Bitmap 互转。
/// </summary>
public static class ImageConversionTools
{
    /// <summary>
    /// 默认 JPEG 质量，兼顾现场传输体积和视觉识别质量。
    /// </summary>
    private const long DefaultJpegQuality = 80L;

    /// <summary>
    /// 从磁盘读取 jpeg / png / bmp 图片，并按文件扩展名编码为纯 base64。
    /// </summary>
    /// <param name="imagePath">图片文件路径。</param>
    /// <returns>不带 data URL 前缀的 base64 字符串。</returns>
    public static string ImageFileToBase64(string imagePath)
    {
        return ImageFileToBase64(imagePath, InferFormatFromPath(imagePath), DefaultJpegQuality);
    }

    /// <summary>
    /// 从磁盘读取 jpeg / png / bmp 图片，并转换为指定格式的纯 base64。
    /// </summary>
    /// <param name="imagePath">图片文件路径。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    /// <returns>不带 data URL 前缀的 base64 字符串。</returns>
    public static string ImageFileToBase64(
        string imagePath,
        ImageFileFormat targetFormat,
        long jpegQuality = DefaultJpegQuality)
    {
        return Convert.ToBase64String(ConvertImageFileToBytes(imagePath, targetFormat, jpegQuality));
    }

    /// <summary>
    /// 从磁盘读取 jpeg / png / bmp 图片，并按文件扩展名编码为 data URL。
    /// </summary>
    /// <param name="imagePath">图片文件路径。</param>
    /// <returns>包含 media type 的 data URL。</returns>
    public static string ImageFileToDataUrl(string imagePath)
    {
        return ImageFileToDataUrl(imagePath, InferFormatFromPath(imagePath), DefaultJpegQuality);
    }

    /// <summary>
    /// 从磁盘读取 jpeg / png / bmp 图片，并转换为指定格式的 data URL。
    /// </summary>
    /// <param name="imagePath">图片文件路径。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    /// <returns>包含 media type 的 data URL。</returns>
    public static string ImageFileToDataUrl(
        string imagePath,
        ImageFileFormat targetFormat,
        long jpegQuality = DefaultJpegQuality)
    {
        return $"data:{GetMediaType(targetFormat)};base64,{ImageFileToBase64(imagePath, targetFormat, jpegQuality)}";
    }

    /// <summary>
    /// 从磁盘读取 jpeg / png / bmp 图片，并转换为目标格式 bytes。
    /// </summary>
    /// <param name="imagePath">图片文件路径。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    /// <returns>目标格式图片 bytes。</returns>
    public static byte[] ConvertImageFileToBytes(
        string imagePath,
        ImageFileFormat targetFormat,
        long jpegQuality = DefaultJpegQuality)
    {
        using var bitmap = LoadBitmapFromFile(imagePath);
        return BitmapToBytes(bitmap, targetFormat, jpegQuality);
    }

    /// <summary>
    /// 将 jpeg / png / bmp 图片文件转换为目标路径扩展名对应的格式。
    /// </summary>
    /// <param name="sourcePath">源图片路径。</param>
    /// <param name="targetPath">目标图片路径，按扩展名推断目标格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    public static void ConvertImageFile(
        string sourcePath,
        string targetPath,
        long jpegQuality = DefaultJpegQuality)
    {
        ConvertImageFile(sourcePath, targetPath, InferFormatFromPath(targetPath), jpegQuality);
    }

    /// <summary>
    /// 将 jpeg / png / bmp 图片文件转换为指定格式并写入目标路径。
    /// </summary>
    /// <param name="sourcePath">源图片路径。</param>
    /// <param name="targetPath">目标图片路径。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    public static void ConvertImageFile(
        string sourcePath,
        string targetPath,
        ImageFileFormat targetFormat,
        long jpegQuality = DefaultJpegQuality)
    {
        var bytes = ConvertImageFileToBytes(sourcePath, targetFormat, jpegQuality);
        WriteBytesToFile(targetPath, bytes);
    }

    /// <summary>
    /// 将 BMP 文件压缩为 PNG 文件。
    /// </summary>
    /// <param name="bmpPath">BMP 源文件路径。</param>
    /// <param name="targetPngPath">PNG 目标文件路径。</param>
    public static void ConvertBmpToPngFile(string bmpPath, string targetPngPath)
    {
        RequireSourceFormat(bmpPath, ImageFileFormat.Bmp, nameof(bmpPath));
        ConvertImageFile(bmpPath, targetPngPath, ImageFileFormat.Png);
    }

    /// <summary>
    /// 将 BMP 文件压缩为 JPEG 文件。
    /// </summary>
    /// <param name="bmpPath">BMP 源文件路径。</param>
    /// <param name="targetJpegPath">JPEG 目标文件路径。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    public static void ConvertBmpToJpegFile(
        string bmpPath,
        string targetJpegPath,
        long jpegQuality = DefaultJpegQuality)
    {
        RequireSourceFormat(bmpPath, ImageFileFormat.Bmp, nameof(bmpPath));
        ConvertImageFile(bmpPath, targetJpegPath, ImageFileFormat.Jpeg, jpegQuality);
    }

    /// <summary>
    /// 将 BMP 文件压缩为 PNG base64。
    /// </summary>
    /// <param name="bmpPath">BMP 源文件路径。</param>
    /// <returns>PNG 编码的纯 base64 字符串。</returns>
    public static string ConvertBmpToPngBase64(string bmpPath)
    {
        RequireSourceFormat(bmpPath, ImageFileFormat.Bmp, nameof(bmpPath));
        return ImageFileToBase64(bmpPath, ImageFileFormat.Png);
    }

    /// <summary>
    /// 将 BMP 文件压缩为 JPEG base64。
    /// </summary>
    /// <param name="bmpPath">BMP 源文件路径。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    /// <returns>JPEG 编码的纯 base64 字符串。</returns>
    public static string ConvertBmpToJpegBase64(string bmpPath, long jpegQuality = DefaultJpegQuality)
    {
        RequireSourceFormat(bmpPath, ImageFileFormat.Bmp, nameof(bmpPath));
        return ImageFileToBase64(bmpPath, ImageFileFormat.Jpeg, jpegQuality);
    }

    /// <summary>
    /// 从磁盘读取图片到独立 Bitmap，读取完成后不再锁定源文件。
    /// </summary>
    /// <param name="imagePath">图片文件路径。</param>
    /// <returns>可由调用方独立释放的 Bitmap。</returns>
    public static Bitmap LoadBitmapFromFile(string imagePath)
    {
        var normalizedPath = RequireExistingImagePath(imagePath, nameof(imagePath));
        var bytes = File.ReadAllBytes(normalizedPath);
        return BytesToBitmap(bytes);
    }

    /// <summary>
    /// 将 Windows 原生 Bitmap 转换为目标格式的纯 base64。
    /// </summary>
    /// <param name="bitmap">System.Drawing.Bitmap 对象。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    /// <returns>不带 data URL 前缀的 base64 字符串。</returns>
    public static string BitmapToBase64(
        Bitmap bitmap,
        ImageFileFormat targetFormat,
        long jpegQuality = DefaultJpegQuality)
    {
        return Convert.ToBase64String(BitmapToBytes(bitmap, targetFormat, jpegQuality));
    }

    /// <summary>
    /// 将 Windows 原生 Bitmap 转换为目标格式的 data URL。
    /// </summary>
    /// <param name="bitmap">System.Drawing.Bitmap 对象。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    /// <returns>包含 media type 的 data URL。</returns>
    public static string BitmapToDataUrl(
        Bitmap bitmap,
        ImageFileFormat targetFormat,
        long jpegQuality = DefaultJpegQuality)
    {
        return $"data:{GetMediaType(targetFormat)};base64,{BitmapToBase64(bitmap, targetFormat, jpegQuality)}";
    }

    /// <summary>
    /// 将 Windows 原生 Bitmap 转换为目标格式 bytes。
    /// </summary>
    /// <param name="bitmap">System.Drawing.Bitmap 对象。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    /// <returns>目标格式图片 bytes。</returns>
    public static byte[] BitmapToBytes(
        Bitmap bitmap,
        ImageFileFormat targetFormat,
        long jpegQuality = DefaultJpegQuality)
    {
        if (bitmap is null)
        {
            throw new ArgumentNullException(nameof(bitmap));
        }

        using var memoryStream = new MemoryStream();
        SaveBitmap(bitmap, memoryStream, targetFormat, jpegQuality);
        return memoryStream.ToArray();
    }

    /// <summary>
    /// 将 Windows 原生 Bitmap 保存为目标格式图片文件。
    /// </summary>
    /// <param name="bitmap">System.Drawing.Bitmap 对象。</param>
    /// <param name="targetPath">目标图片路径。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    public static void BitmapToImageFile(
        Bitmap bitmap,
        string targetPath,
        ImageFileFormat targetFormat,
        long jpegQuality = DefaultJpegQuality)
    {
        WriteBytesToFile(targetPath, BitmapToBytes(bitmap, targetFormat, jpegQuality));
    }

    /// <summary>
    /// 将 Windows 原生 Bitmap 保存为目标路径扩展名对应的图片文件。
    /// </summary>
    /// <param name="bitmap">System.Drawing.Bitmap 对象。</param>
    /// <param name="targetPath">目标图片路径，按扩展名推断目标格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    public static void BitmapToImageFile(
        Bitmap bitmap,
        string targetPath,
        long jpegQuality = DefaultJpegQuality)
    {
        BitmapToImageFile(bitmap, targetPath, InferFormatFromPath(targetPath), jpegQuality);
    }

    /// <summary>
    /// 将 JPEG base64 转换为 Windows 原生 Bitmap。
    /// </summary>
    /// <param name="imageBase64">纯 base64 字符串，或 data:image/jpeg;base64,...。</param>
    /// <returns>可由调用方独立释放的 Bitmap。</returns>
    public static Bitmap JpegBase64ToBitmap(string imageBase64)
    {
        return Base64ToBitmap(imageBase64);
    }

    /// <summary>
    /// 将 PNG base64 转换为 Windows 原生 Bitmap。
    /// </summary>
    /// <param name="imageBase64">纯 base64 字符串，或 data:image/png;base64,...。</param>
    /// <returns>可由调用方独立释放的 Bitmap。</returns>
    public static Bitmap PngBase64ToBitmap(string imageBase64)
    {
        return Base64ToBitmap(imageBase64);
    }

    /// <summary>
    /// 将 BMP base64 转换为 Windows 原生 Bitmap。
    /// </summary>
    /// <param name="imageBase64">纯 base64 字符串，或 data:image/bmp;base64,...。</param>
    /// <returns>可由调用方独立释放的 Bitmap。</returns>
    public static Bitmap BmpBase64ToBitmap(string imageBase64)
    {
        return Base64ToBitmap(imageBase64);
    }

    /// <summary>
    /// 将 base64 或 data URL 解码为 Windows 原生 Bitmap。
    /// </summary>
    /// <param name="imageBase64">纯 base64 字符串，或 data:image/...;base64,...。</param>
    /// <returns>可由调用方独立释放的 Bitmap。</returns>
    public static Bitmap Base64ToBitmap(string imageBase64)
    {
        return BytesToBitmap(DecodeBase64OrDataUrl(imageBase64, out _));
    }

    /// <summary>
    /// 将 base64 或 data URL 转换为指定格式图片 bytes。
    /// </summary>
    /// <param name="imageBase64">纯 base64 字符串，或 data:image/...;base64,...。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    /// <returns>目标格式图片 bytes。</returns>
    public static byte[] Base64ToImageBytes(
        string imageBase64,
        ImageFileFormat targetFormat,
        long jpegQuality = DefaultJpegQuality)
    {
        using var bitmap = Base64ToBitmap(imageBase64);
        return BitmapToBytes(bitmap, targetFormat, jpegQuality);
    }

    /// <summary>
    /// 将 base64 或 data URL 转换为指定格式图片文件。
    /// </summary>
    /// <param name="imageBase64">纯 base64 字符串，或 data:image/...;base64,...。</param>
    /// <param name="targetPath">目标图片路径。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    public static void Base64ToImageFile(
        string imageBase64,
        string targetPath,
        ImageFileFormat targetFormat,
        long jpegQuality = DefaultJpegQuality)
    {
        WriteBytesToFile(targetPath, Base64ToImageBytes(imageBase64, targetFormat, jpegQuality));
    }

    /// <summary>
    /// 将 base64 或 data URL 转换为目标路径扩展名对应的图片文件。
    /// </summary>
    /// <param name="imageBase64">纯 base64 字符串，或 data:image/...;base64,...。</param>
    /// <param name="targetPath">目标图片路径，按扩展名推断目标格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    public static void Base64ToImageFile(
        string imageBase64,
        string targetPath,
        long jpegQuality = DefaultJpegQuality)
    {
        Base64ToImageFile(imageBase64, targetPath, InferFormatFromPath(targetPath), jpegQuality);
    }

    /// <summary>
    /// 将 base64 或 data URL 重新编码为指定格式的纯 base64。
    /// </summary>
    /// <param name="imageBase64">纯 base64 字符串，或 data:image/...;base64,...。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    /// <returns>目标格式纯 base64 字符串。</returns>
    public static string ConvertBase64ImageFormat(
        string imageBase64,
        ImageFileFormat targetFormat,
        long jpegQuality = DefaultJpegQuality)
    {
        return Convert.ToBase64String(Base64ToImageBytes(imageBase64, targetFormat, jpegQuality));
    }

    /// <summary>
    /// 将图片编码 bytes 转换为 Windows 原生 Bitmap。
    /// </summary>
    /// <param name="imageBytes">jpeg / png / bmp 图片 bytes。</param>
    /// <returns>可由调用方独立释放的 Bitmap。</returns>
    public static Bitmap BytesToBitmap(byte[] imageBytes)
    {
        if (imageBytes is null || imageBytes.Length == 0)
        {
            throw new ArgumentException("imageBytes cannot be empty.", nameof(imageBytes));
        }

        using var sourceStream = new MemoryStream(imageBytes);
        using var sourceImage = Image.FromStream(sourceStream, useEmbeddedColorManagement: true, validateImageData: true);
        return new Bitmap(sourceImage);
    }

    /// <summary>
    /// 按文件扩展名推断 jpeg / png / bmp 格式。
    /// </summary>
    /// <param name="path">图片路径。</param>
    /// <returns>图片格式。</returns>
    public static ImageFileFormat InferFormatFromPath(string path)
    {
        var normalizedPath = RequireText(path, nameof(path));
        var extension = Path.GetExtension(normalizedPath).ToLowerInvariant();
        return extension switch
        {
            ".jpg" or ".jpeg" => ImageFileFormat.Jpeg,
            ".png" => ImageFileFormat.Png,
            ".bmp" => ImageFileFormat.Bmp,
            _ => throw new NotSupportedException($"Unsupported image format extension: {extension}")
        };
    }

    /// <summary>
    /// 获取图片格式对应的 media type。
    /// </summary>
    /// <param name="format">图片格式。</param>
    /// <returns>MIME media type。</returns>
    public static string GetMediaType(ImageFileFormat format)
    {
        return format switch
        {
            ImageFileFormat.Jpeg => "image/jpeg",
            ImageFileFormat.Png => "image/png",
            ImageFileFormat.Bmp => "image/bmp",
            _ => throw new ArgumentOutOfRangeException(nameof(format), format, "Unsupported image file format.")
        };
    }

    /// <summary>
    /// 保存 Bitmap 到 stream；JPEG 会按指定质量编码。
    /// </summary>
    /// <param name="bitmap">System.Drawing.Bitmap 对象。</param>
    /// <param name="stream">目标 stream。</param>
    /// <param name="targetFormat">目标图片格式。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    private static void SaveBitmap(
        Bitmap bitmap,
        Stream stream,
        ImageFileFormat targetFormat,
        long jpegQuality)
    {
        switch (targetFormat)
        {
            case ImageFileFormat.Jpeg:
                SaveJpeg(bitmap, stream, jpegQuality);
                break;
            case ImageFileFormat.Png:
                bitmap.Save(stream, ImageFormat.Png);
                break;
            case ImageFileFormat.Bmp:
                bitmap.Save(stream, ImageFormat.Bmp);
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(targetFormat), targetFormat, "Unsupported image file format.");
        }
    }

    /// <summary>
    /// 保存 JPEG；透明像素会合成到白色背景，避免 JPEG 不支持 alpha 导致 GDI+ 异常。
    /// </summary>
    /// <param name="bitmap">System.Drawing.Bitmap 对象。</param>
    /// <param name="stream">目标 stream。</param>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    private static void SaveJpeg(Bitmap bitmap, Stream stream, long jpegQuality)
    {
        ValidateJpegQuality(jpegQuality);
        using var jpegBitmap = CreateJpegCompatibleBitmap(bitmap);
        var encoder = RequireEncoder(ImageFormat.Jpeg);
        using var encoderParameters = new EncoderParameters(1);
        encoderParameters.Param[0] = new EncoderParameter(Encoder.Quality, jpegQuality);
        jpegBitmap.Save(stream, encoder, encoderParameters);
    }

    /// <summary>
    /// 创建 JPEG 可编码的 24bpp RGB Bitmap。
    /// </summary>
    /// <param name="bitmap">源 Bitmap。</param>
    /// <returns>不包含 alpha 通道的 Bitmap。</returns>
    private static Bitmap CreateJpegCompatibleBitmap(Bitmap bitmap)
    {
        var jpegBitmap = new Bitmap(bitmap.Width, bitmap.Height, PixelFormat.Format24bppRgb);
        using var graphics = Graphics.FromImage(jpegBitmap);
        graphics.Clear(Color.White);
        graphics.DrawImage(bitmap, 0, 0, bitmap.Width, bitmap.Height);
        return jpegBitmap;
    }

    /// <summary>
    /// 查找指定 ImageFormat 的系统编码器。
    /// </summary>
    /// <param name="imageFormat">System.Drawing.Imaging.ImageFormat。</param>
    /// <returns>图片编码器。</returns>
    private static ImageCodecInfo RequireEncoder(ImageFormat imageFormat)
    {
        var encoder = ImageCodecInfo.GetImageEncoders()
            .FirstOrDefault(item => item.FormatID == imageFormat.Guid);
        return encoder ?? throw new InvalidOperationException($"Image encoder is not available: {imageFormat}");
    }

    /// <summary>
    /// 解码纯 base64 或 data URL，data URL 的 media type 会通过 out 参数返回。
    /// </summary>
    /// <param name="imageBase64">纯 base64 字符串，或 data:image/...;base64,...。</param>
    /// <param name="mediaType">data URL 中的 media type；纯 base64 时为空。</param>
    /// <returns>图片编码 bytes。</returns>
    private static byte[] DecodeBase64OrDataUrl(string imageBase64, out string? mediaType)
    {
        mediaType = null;
        var normalizedBase64 = RequireText(imageBase64, nameof(imageBase64));
        var commaIndex = normalizedBase64.IndexOf(',');
        if (normalizedBase64.StartsWith("data:", StringComparison.OrdinalIgnoreCase) && commaIndex > 0)
        {
            var header = normalizedBase64.Substring(5, commaIndex - 5);
            var separatorIndex = header.IndexOf(';');
            var headerMediaType = separatorIndex >= 0 ? header.Substring(0, separatorIndex) : header;
            if (!string.IsNullOrWhiteSpace(headerMediaType))
            {
                mediaType = headerMediaType.Trim();
            }

            normalizedBase64 = normalizedBase64.Substring(commaIndex + 1).Trim();
        }

        return Convert.FromBase64String(normalizedBase64);
    }

    /// <summary>
    /// 校验 JPEG 质量参数。
    /// </summary>
    /// <param name="jpegQuality">JPEG 质量，范围 1 到 100。</param>
    private static void ValidateJpegQuality(long jpegQuality)
    {
        if (jpegQuality < 1L || jpegQuality > 100L)
        {
            throw new ArgumentOutOfRangeException(nameof(jpegQuality), jpegQuality, "jpegQuality must be between 1 and 100.");
        }
    }

    /// <summary>
    /// 校验源文件扩展名是否为预期格式。
    /// </summary>
    /// <param name="imagePath">图片路径。</param>
    /// <param name="expectedFormat">预期格式。</param>
    /// <param name="parameterName">参数名。</param>
    private static void RequireSourceFormat(string imagePath, ImageFileFormat expectedFormat, string parameterName)
    {
        var actualFormat = InferFormatFromPath(RequireExistingImagePath(imagePath, parameterName));
        if (actualFormat != expectedFormat)
        {
            throw new ArgumentException($"Image file must be {expectedFormat}.", parameterName);
        }
    }

    /// <summary>
    /// 校验图片路径不为空、扩展名受支持且文件存在。
    /// </summary>
    /// <param name="imagePath">图片文件路径。</param>
    /// <param name="parameterName">参数名。</param>
    /// <returns>完整图片路径。</returns>
    private static string RequireExistingImagePath(string imagePath, string parameterName)
    {
        var normalizedPath = ConfiguredPathResolver.ResolveExistingFile(
            RequireText(imagePath, parameterName),
            sourceFile: null,
            message: "Image file does not exist.");
        _ = InferFormatFromPath(normalizedPath);
        return normalizedPath;
    }

    /// <summary>
    /// 将 bytes 写入文件，目标目录不存在时自动创建。
    /// </summary>
    /// <param name="targetPath">目标文件路径。</param>
    /// <param name="bytes">待写入 bytes。</param>
    private static void WriteBytesToFile(string targetPath, byte[] bytes)
    {
        var normalizedTargetPath = Path.GetFullPath(RequireText(targetPath, nameof(targetPath)));
        var directory = Path.GetDirectoryName(normalizedTargetPath);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }

        File.WriteAllBytes(normalizedTargetPath, bytes);
    }

    /// <summary>
    /// 校验字符串参数不为空并去除首尾空白。
    /// </summary>
    /// <param name="value">参数值。</param>
    /// <param name="parameterName">参数名。</param>
    /// <returns>清理后的字符串。</returns>
    private static string RequireText(string value, string parameterName)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException($"{parameterName} cannot be empty.", parameterName);
        }

        return value.Trim();
    }
}
