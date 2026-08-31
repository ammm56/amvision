using System.Drawing;
using System.IO;
using Amvar.Vision;
using Amvar.Vision.Tools;

namespace AMVision.Console
{
    /// <summary>
    /// key name 与 id 示例共用的输入参数和图片转换方法。
    /// </summary>
    internal static class SdkCallInputs
    {
        // Resources/Img 仅存放开发者自己的本地调试图片，不纳入 Git 管理。
        public const string ModelImagePath = @"Resources\Img\image-crop-20260803140324-012.png";
        public const string ImagePath = @"Resources\Img\Image_20260721103308382.bmp";
        public const string ModelImageMediaType = "image/png";
        public const string ImageMediaType = "image/bmp";
        public const string WorkflowRequestFilePath = @"Resources\Requests\request.json";
        public const string WorkflowRequestFileMediaType = "application/json";
        public const string WorkflowFirstListFilePath = @"Resources\Requests\a.txt";
        public const string WorkflowSecondListFilePath = @"Resources\Requests\b.txt";
        public const string WorkflowRunId = "workflow-run-xxx";
        public const string ModelInferenceTaskId = "inference-task-xxx";
        public const string ModelDeploymentInputUri = "runtime/inputs/image.jpg";
        public const string ModelDeploymentInputFileId = "project-file-xxx";

        public static string LoadModelImageBase64()
        {
            return ImageConversionTools.ImageFileToDataUrl(ModelImagePath);
        }

        public static string LoadImageBase64()
        {
            return ImageConversionTools.ImageFileToDataUrl(ImagePath);
        }

        public static byte[] LoadModelImageBytes()
        {
            return File.ReadAllBytes(ModelImagePath);
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

        /// <summary>创建单文件 multipart 上传示例。</summary>
        public static WorkflowUploadFile CreateWorkflowRequestFile()
        {
            return WorkflowUploadFile.FromFile(
                WorkflowRequestFilePath,
                WorkflowRequestFileMediaType);
        }

        /// <summary>创建保持顺序的多文件 multipart 上传示例。</summary>
        public static WorkflowUploadFile[] CreateWorkflowRequestFiles()
        {
            return new[]
            {
                WorkflowUploadFile.FromFile(WorkflowFirstListFilePath, "text/plain"),
                WorkflowUploadFile.FromFile(WorkflowSecondListFilePath, "text/plain")
            };
        }
    }
}
