using System;
using Amvision.Workflows;
namespace Amvision.Workflows.Tools
{
/// <summary>
/// 表示一帧连续 HWC BGR24 图片数据。
/// </summary>
public sealed class Bgr24ImageFrame
{
    /// <summary>
    /// 初始化 BGR24 图片帧。
    /// </summary>
    /// <param name="bytes">连续 B/G/R 像素 bytes。</param>
    /// <param name="width">图片宽度。</param>
    /// <param name="height">图片高度。</param>
    public Bgr24ImageFrame(byte[] bytes, int width, int height)
    {
        Bytes = bytes;
        Width = width;
        Height = height;
    }

    /// <summary>
    /// 连续 B/G/R 像素 bytes，每个像素 3 bytes。
    /// </summary>
    public byte[] Bytes { get; }

    /// <summary>
    /// 图片宽度。
    /// </summary>
    public int Width { get; }

    /// <summary>
    /// 图片高度。
    /// </summary>
    public int Height { get; }
}
}
