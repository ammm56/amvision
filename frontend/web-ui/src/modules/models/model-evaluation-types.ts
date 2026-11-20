import type { AdditionalEvaluationKind } from './services/model-evaluation.service'

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
