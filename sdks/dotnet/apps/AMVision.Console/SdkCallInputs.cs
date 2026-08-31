using System.Collections.Generic;
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

        /// <summary>构建 HTTP Runtime 的 image-ref.v1 ObjectStore 引用示例。</summary>
        public static IDictionary<string, object> CreateWorkflowImageReference()
        {
            return new Dictionary<string, object>
            {
                ["transport_kind"] = "storage",
                ["object_key"] = "projects/project-1/inputs/example-image.png",
                ["media_type"] = "image/png"
            };
        }

        /// <summary>构建 HTTP Runtime 的 file-ref.v1 ObjectStore 引用示例。</summary>
        public static IDictionary<string, object> CreateWorkflowFileReference(
            string fileName = "request.json")
        {
            var checksum = new string('a', 64);
            return new Dictionary<string, object>
            {
                ["transport_kind"] = "storage",
                ["storage_ref"] = "object-store",
                ["object_key"] = "projects/project-1/inputs/" + fileName,
                ["file_name"] = fileName,
                ["media_type"] = "application/json",
                ["content_length"] = 2,
                ["checksum_algorithm"] = "sha256",
                ["checksum"] = checksum,
                ["immutable_version"] = "sha256:" + checksum
            };
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
