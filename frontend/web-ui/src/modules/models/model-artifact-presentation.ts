import type { PlatformBaseModelBuild } from './services/model.service'

const validationStages: Record<string, string> = {
  onnx: 'validate-onnx',
  'onnx-optimized': 'validate-onnx-optimized',
  'openvino-ir': 'validate-openvino',
  'tensorrt-engine': 'validate-tensorrt',
}

export function modelBuildValidation(build?: PlatformBaseModelBuild | null): boolean | null {
  const stage = validationStages[build?.build_format ?? '']
  if (!build || !stage) return null
  for (const value of [build.metadata.runtime_smoke, build.metadata.validation_summary]) {
    if (!value || typeof value !== 'object') continue
    const evidence = value as Record<string, unknown>
    if (evidence.stage === stage && typeof (evidence.passed ?? evidence.allclose) === 'boolean') {
      return evidence.passed !== false && evidence.allclose !== false && evidence.finite !== false
    }
  }
  return null
}

export function saveProjectModelDownload(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name.replace(/[\\/:*?"<>|\x00-\x1f]/g, '_') || 'model-file'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
