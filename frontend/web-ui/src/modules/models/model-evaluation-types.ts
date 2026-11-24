import type { AdditionalEvaluationKind, ModelEvaluationRecord } from './services/model-evaluation.service'

export const evaluationTypes = {
  detection: ['目标检测', 'Detection'],
  classification: ['图像分类', 'Classification'],
  segmentation: ['实例分割', 'Instance segmentation'],
  pose: ['姿态估计', 'Pose estimation'],
  obb: ['旋转框检测', 'Oriented boxes'],
  semantic: ['语义分割', 'Semantic segmentation'],
  anomaly: ['异常检测', 'Anomaly detection'],
} as const

export const evaluationHeadline = {
  classification: { label: 'Top-1', key: 'top1_accuracy' },
  segmentation: { label: 'Mask mAP50–95', key: 'mask_map50_95' },
  pose: { label: 'OKS AP50–95', key: 'oks_ap50_95' },
  obb: { label: 'Rotated mAP50–95', key: 'map50_95' },
  semantic: { label: 'mIoU', key: 'miou' },
  anomaly: { label: 'AUROC', key: 'image_auroc' },
} as const satisfies Record<AdditionalEvaluationKind, { label: string; key: string }>

export function evaluationTypeOptions(zh: boolean) {
  return Object.entries(evaluationTypes).map(([value, name]) => ({ value, label: name[zh ? 0 : 1] }))
}

export function evaluationModelVersionId(task?: ModelEvaluationRecord | null): string {
  return task?.model_version_id || task?.metadata?.model_version_id || task?.result?.model_version_id || ''
}

export function classificationEvaluationExportId(task: ModelEvaluationRecord): string {
  return task.dataset_export_id || task.metadata?.dataset_export_id || task.result?.dataset_export_id
    || /^classification evaluation (dataset-export-[\w-]+)$/.exec(task.display_name)?.[1] || ''
}

export function usesDefaultClassificationEvaluationName(task: ModelEvaluationRecord): boolean {
  return task.uses_default_name ?? (!task.display_name
    || task.display_name === `classification evaluation ${classificationEvaluationExportId(task)}`)
}

export function classificationEvaluationTitle(task: ModelEvaluationRecord, modelVersionName: string, zh: boolean): string {
  if (!usesDefaultClassificationEvaluationName(task)) return task.display_name
  const title = zh ? '图像分类评估' : 'Classification evaluation'
  return modelVersionName ? `${title} · ${modelVersionName}` : title
}
