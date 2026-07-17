using System.Drawing;
using System.IO;
using Amvar.Vision.Tools;

namespace AMVision.Console
{
    /// <summary>
    /// key name 与 id 示例共用的输入参数和图片转换方法。
    /// </summary>
    internal static class SdkCallInputs
    {
        public const string ImagePath = @"Resources\Img\qrcode50.jpg";
        public const string ImageMediaType = "image/jpeg";
        public const string WorkflowRunId = "workflow-run-xxx";
        public const string ModelInferenceTaskId = "inference-task-xxx";
        public const string ModelDeploymentInputUri = "runtime/inputs/image.jpg";
        public const string ModelDeploymentInputFileId = "project-file-xxx";

        public static string LoadImageBase64()
        {
            return ImageConversionTools.ImageFileToDataUrl(ImagePath);
        }

        public static byte[] LoadImageBytes()
        {
            return File.ReadAllBytes(ImagePath);
        }

        public static Bgr24ImageFrame LoadBgr24ImageFrame()
        {
            return ImageConversionTools.ImageFileToBgr24(ImagePath);
        }

        public static Bitmap LoadBitmap()
        {
            return new Bitmap(ImagePath);
        }
    }
}
