import type { ModelTaskType } from './services/model.service'

export type TrainingParameterInputKind = 'text' | 'number' | 'select'
export type TrainingParameterValueKind = 'string' | 'int' | 'float' | 'bool'

export interface TrainingParameterFieldOption {
  label: string
  value: string
}

export interface TrainingParameterField {
  key: string
  label: string
  inputKind: TrainingParameterInputKind
  valueKind: TrainingParameterValueKind
  defaultValue?: string
  min?: number
  max?: number
  step?: number
  placeholder?: string
  wide?: boolean
  options?: TrainingParameterFieldOption[]
}

export type TrainingParameterValues = Record<string, string>

const boolOptions: TrainingParameterFieldOption[] = [
  { label: '开启', value: 'true' },
  { label: '关闭', value: 'false' },
]

const deviceOptions: TrainingParameterFieldOption[] = [
  { label: '自动选择（默认）', value: '' },
  { label: 'cpu', value: 'cpu' },
  { label: 'cuda', value: 'cuda' },
  { label: 'cuda:0', value: 'cuda:0' },
]

function numberField(
  key: string,
  label: string,
  {
    integer = false,
    min,
    max,
    step,
    placeholder,
    wide = false,
    defaultValue = '',
  }: {
  integer?: boolean
  min?: number
  max?: number
  step?: number
  placeholder?: string
  wide?: boolean
  defaultValue?: string
} = {},
): TrainingParameterField {
  return {
    key,
    label,
    inputKind: 'number',
    valueKind: integer ? 'int' : 'float',
    defaultValue,
    min,
    max,
    step,
    placeholder,
    wide,
  }
}

function selectField(
  key: string,
  label: string,
  options: TrainingParameterFieldOption[],
  {
    valueKind = 'string',
    wide = false,
    defaultValue = '',
  }: {
  valueKind?: TrainingParameterValueKind
  wide?: boolean
  defaultValue?: string
} = {},
): TrainingParameterField {
  return {
    key,
    label,
    inputKind: 'select',
    valueKind,
    defaultValue,
    options,
    wide,
  }
}

const detectionYoloXFields: TrainingParameterField[] = [
  selectField('device', '训练设备', deviceOptions),
  numberField('seed', '随机种子', { integer: true, min: 0, step: 1, defaultValue: '0' }),
  numberField('num_workers', '数据加载 worker 数', { integer: true, min: 0, step: 1, defaultValue: '0' }),
  numberField('max_labels', '单图最大标签数', { integer: true, min: 1, step: 1, defaultValue: '120' }),
  numberField('evaluation_confidence_threshold', '验证置信度阈值', { min: 0, max: 1, step: 0.01, defaultValue: '0.01' }),
  numberField('evaluation_nms_threshold', '验证 NMS 阈值', { min: 0, max: 1, step: 0.01, defaultValue: '0.65' }),
  numberField('flip_prob', '水平翻转概率', { min: 0, max: 1, step: 0.01, defaultValue: '0.0' }),
  numberField('hsv_prob', 'HSV 增强概率', { min: 0, max: 1, step: 0.01, defaultValue: '0.0' }),
  numberField('mosaic_prob', 'Mosaic 概率', { min: 0, max: 1, step: 0.01, defaultValue: '0.0' }),
  numberField('mixup_prob', 'MixUp 概率', { min: 0, max: 1, step: 0.01, defaultValue: '0.0' }),
  selectField('enable_mixup', '启用 MixUp', boolOptions, { valueKind: 'bool', defaultValue: 'false' }),
  numberField('mosaic_scale_min', 'Mosaic 缩放最小值', { step: 0.1, defaultValue: '0.1' }),
  numberField('mosaic_scale_max', 'Mosaic 缩放最大值', { step: 0.1, defaultValue: '2.0' }),
  numberField('mixup_scale_min', 'MixUp 缩放最小值', { step: 0.1, defaultValue: '0.5' }),
  numberField('mixup_scale_max', 'MixUp 缩放最大值', { step: 0.1, defaultValue: '1.5' }),
  numberField('multiscale_range', '多尺度训练范围', { integer: true, min: 0, step: 1, defaultValue: '0' }),
  selectField('ema', '启用 EMA', boolOptions, { valueKind: 'bool', defaultValue: 'true' }),
  numberField('warmup_epochs', 'Warmup 轮数', { integer: true, min: 0, step: 1, defaultValue: '5' }),
  numberField('no_aug_epochs', '最后 no-aug 轮数', { integer: true, min: 0, step: 1, defaultValue: '15' }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, step: 0.0001, defaultValue: '0.05' }),
]

const detectionYoloPrimaryFields: TrainingParameterField[] = [
  numberField('learning_rate', '学习率', { min: 0, step: 0.0001, defaultValue: '0.001' }),
  numberField('weight_decay', '权重衰减', { min: 0, step: 0.0001, defaultValue: '0.0001' }),
  numberField('class_loss_weight', '分类损失权重', { min: 0, step: 0.1, defaultValue: '0.5' }),
  numberField('box_loss_weight', '框回归损失权重', { min: 0, step: 0.1, defaultValue: '7.5' }),
  numberField('dfl_loss_weight', 'DFL 损失权重', { min: 0, step: 0.1, defaultValue: '1.5' }),
  numberField('evaluation_confidence_threshold', '验证置信度阈值', { min: 0, max: 1, step: 0.01, defaultValue: '0.01' }),
  numberField('evaluation_nms_threshold', '验证 NMS 阈值', { min: 0, max: 1, step: 0.01, defaultValue: '0.65' }),
  numberField('assign_topk', '正样本匹配 topk', { integer: true, min: 1, step: 1, defaultValue: '10' }),
  numberField('assign_alpha', '正样本匹配 alpha', { min: 0, step: 0.1, defaultValue: '0.5' }),
  numberField('assign_beta', '正样本匹配 beta', { min: 0, step: 0.1, defaultValue: '6.0' }),
  numberField('grad_clip_norm', '梯度裁剪上限', { min: 0, step: 0.1, defaultValue: '10.0' }),
  numberField('flip_prob', '水平翻转概率', { min: 0, max: 1, step: 0.01, defaultValue: '0.0' }),
  numberField('hsv_prob', 'HSV 增强概率', { min: 0, max: 1, step: 0.01, defaultValue: '0.0' }),
  numberField('mosaic_prob', 'Mosaic 概率', { min: 0, max: 1, step: 0.01, defaultValue: '0.0' }),
  numberField('mixup_prob', 'MixUp 概率', { min: 0, max: 1, step: 0.01, defaultValue: '0.0' }),
  selectField('enable_mixup', '启用 MixUp', boolOptions, { valueKind: 'bool', defaultValue: 'false' }),
  numberField('degrees', '仿射旋转角度', { step: 0.1, defaultValue: '10.0' }),
  numberField('translate', '仿射平移比例', { step: 0.01, defaultValue: '0.1' }),
  numberField('shear', '仿射错切角度', { step: 0.1, defaultValue: '2.0' }),
  numberField('mosaic_scale_min', 'Mosaic 缩放最小值', { step: 0.1, defaultValue: '0.1' }),
  numberField('mosaic_scale_max', 'Mosaic 缩放最大值', { step: 0.1, defaultValue: '2.0' }),
  numberField('mixup_scale_min', 'MixUp 缩放最小值', { step: 0.1, defaultValue: '0.5' }),
  numberField('mixup_scale_max', 'MixUp 缩放最大值', { step: 0.1, defaultValue: '1.5' }),
]

const detectionRfdetrFields: TrainingParameterField[] = [
  selectField('device', '训练设备', deviceOptions),
  numberField('learning_rate', '学习率', { min: 0, step: 0.0001, defaultValue: '0.0001' }),
  numberField('class_cost', '分类匹配代价', { min: 0, step: 0.1, defaultValue: '2.0' }),
  numberField('bbox_cost', '框匹配代价', { min: 0, step: 0.1, defaultValue: '5.0' }),
  numberField('giou_cost', 'GIoU 匹配代价', { min: 0, step: 0.1, defaultValue: '2.0' }),
  numberField('class_loss_weight', '分类损失权重', { min: 0, step: 0.1, defaultValue: '1.0' }),
  numberField('bbox_loss_weight', '框回归损失权重', { min: 0, step: 0.1, defaultValue: '5.0' }),
  numberField('giou_loss_weight', 'GIoU 损失权重', { min: 0, step: 0.1, defaultValue: '2.0' }),
]

const classificationFields: TrainingParameterField[] = [
  selectField('device', '训练设备', deviceOptions),
  numberField('learning_rate', '学习率', { min: 0, step: 0.0001, defaultValue: '0.001' }),
  numberField('weight_decay', '权重衰减', { min: 0, step: 0.0001, defaultValue: '0.0001' }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, step: 0.0001, defaultValue: '0.01' }),
]

const segmentationYoloPrimaryFields: TrainingParameterField[] = [
  selectField('device', '训练设备', deviceOptions),
  numberField('learning_rate', '学习率', { min: 0, step: 0.0001, defaultValue: '1.0' }),
  numberField('weight_decay', '权重衰减', { min: 0, step: 0.0001, defaultValue: '0.01' }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, step: 0.0001, defaultValue: '0.01' }),
  numberField('class_loss_weight', '分类损失权重', { min: 0, step: 0.1, defaultValue: '0.5' }),
  numberField('box_loss_weight', '框回归损失权重', { min: 0, step: 0.1, defaultValue: '7.5' }),
  numberField('dfl_loss_weight', 'DFL 损失权重', { min: 0, step: 0.1, defaultValue: '1.5' }),
  numberField('mask_loss_weight', '掩码损失权重', { min: 0, step: 0.1, defaultValue: '1.0' }),
  numberField('assign_topk', '正样本匹配 topk', { integer: true, min: 1, step: 1, defaultValue: '10' }),
  numberField('assign_alpha', '正样本匹配 alpha', { min: 0, step: 0.1, defaultValue: '0.5' }),
  numberField('assign_beta', '正样本匹配 beta', { min: 0, step: 0.1, defaultValue: '6.0' }),
  numberField('grad_clip_norm', '梯度裁剪上限', { min: 0, step: 0.1, defaultValue: '10.0' }),
]

const segmentationRfdetrFields: TrainingParameterField[] = [
  selectField('device', '训练设备', deviceOptions),
  numberField('learning_rate', '学习率', { min: 0, step: 0.0001, defaultValue: '0.0001' }),
  numberField('weight_decay', '权重衰减', { min: 0, step: 0.0001, defaultValue: '0.0001' }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, step: 0.0001, defaultValue: '0.01' }),
  numberField('class_cost', '分类匹配代价', { min: 0, step: 0.1, defaultValue: '2.0' }),
  numberField('bbox_cost', '框匹配代价', { min: 0, step: 0.1, defaultValue: '5.0' }),
  numberField('giou_cost', 'GIoU 匹配代价', { min: 0, step: 0.1, defaultValue: '2.0' }),
  numberField('class_loss_weight', '分类损失权重', { min: 0, step: 0.1, defaultValue: '1.0' }),
  numberField('bbox_loss_weight', '框回归损失权重', { min: 0, step: 0.1, defaultValue: '5.0' }),
  numberField('giou_loss_weight', 'GIoU 损失权重', { min: 0, step: 0.1, defaultValue: '2.0' }),
  numberField('mask_ce_weight', '掩码 CE 损失权重', { min: 0, step: 0.1, defaultValue: '5.0' }),
  numberField('mask_dice_weight', '掩码 Dice 损失权重', { min: 0, step: 0.1, defaultValue: '5.0' }),
]

const poseFields: TrainingParameterField[] = [
  selectField('device', '训练设备', deviceOptions),
  numberField('learning_rate', '学习率', { min: 0, step: 0.0001, defaultValue: '0.001' }),
  numberField('weight_decay', '权重衰减', { min: 0, step: 0.0001, defaultValue: '0.0001' }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, step: 0.0001, defaultValue: '0.01' }),
  numberField('class_loss_weight', '分类损失权重', { min: 0, step: 0.1, defaultValue: '0.5' }),
  numberField('box_loss_weight', '框回归损失权重', { min: 0, step: 0.1, defaultValue: '7.5' }),
  numberField('dfl_loss_weight', 'DFL 损失权重', { min: 0, step: 0.1, defaultValue: '1.5' }),
  numberField('kpt_loss_weight', '关键点损失权重', { min: 0, step: 0.1, defaultValue: '12.0' }),
  numberField('assign_topk', '正样本匹配 topk', { integer: true, min: 1, step: 1, defaultValue: '10' }),
  numberField('assign_alpha', '正样本匹配 alpha', { min: 0, step: 0.1, defaultValue: '0.5' }),
  numberField('assign_beta', '正样本匹配 beta', { min: 0, step: 0.1, defaultValue: '6.0' }),
  numberField('grad_clip_norm', '梯度裁剪上限', { min: 0, step: 0.1, defaultValue: '10.0' }),
]

const obbFields: TrainingParameterField[] = [
  selectField('device', '训练设备', deviceOptions),
  numberField('learning_rate', '学习率', { min: 0, step: 0.0001, defaultValue: '0.001' }),
  numberField('weight_decay', '权重衰减', { min: 0, step: 0.0001, defaultValue: '0.0001' }),
]

function normalizeModelType(modelType: string | null | undefined): string {
  return String(modelType ?? '').trim().toLowerCase()
}

export function supportsTrainingWarmStart(taskType: ModelTaskType): boolean {
  return taskType === 'detection'
}

export function getDefaultTrainingEvaluationInterval(
  taskType: ModelTaskType,
  modelType: string | null | undefined,
): number {
  const normalizedModelType = normalizeModelType(modelType)
  if (taskType === 'classification') {
    return 1
  }
  if (taskType === 'segmentation' && normalizedModelType === 'rfdetr') {
    return 1
  }
  return 5
}

export function getDefaultTrainingModelParameterValues(
  taskType: ModelTaskType,
  modelType: string | null | undefined,
): TrainingParameterValues {
  const fields = getModelLayerTrainingFields(taskType, modelType)
  return Object.fromEntries(fields.map((field) => [field.key, field.defaultValue ?? '']))
}

export function getModelLayerTrainingFields(
  taskType: ModelTaskType,
  modelType: string | null | undefined,
): TrainingParameterField[] {
  const normalizedModelType = normalizeModelType(modelType)
  if (!normalizedModelType) {
    return []
  }
  if (taskType === 'detection') {
    if (normalizedModelType === 'yolox') return detectionYoloXFields
    if (normalizedModelType === 'rfdetr') return detectionRfdetrFields
    return detectionYoloPrimaryFields
  }
  if (taskType === 'classification') {
    return classificationFields
  }
  if (taskType === 'segmentation') {
    return normalizedModelType === 'rfdetr' ? segmentationRfdetrFields : segmentationYoloPrimaryFields
  }
  if (taskType === 'pose') {
    return poseFields
  }
  if (taskType === 'obb') {
    return obbFields
  }
  return []
}

export function buildTrainingExtraOptions(
  taskType: ModelTaskType,
  modelType: string | null | undefined,
  values: TrainingParameterValues,
): Record<string, unknown> {
  const normalizedModelType = normalizeModelType(modelType)
  if (!normalizedModelType) {
    return {}
  }

  const result: Record<string, unknown> = {}
  const visibleFields = getModelLayerTrainingFields(taskType, normalizedModelType)
  const visibleFieldMap = new Map(visibleFields.map((field) => [field.key, field]))

  const readFieldValue = (key: string): unknown | undefined => {
    const field = visibleFieldMap.get(key)
    if (!field) {
      return undefined
    }
    const rawValue = String(values[key] ?? '').trim()
    if (!rawValue) {
      return undefined
    }
    if (field.valueKind === 'string') {
      return rawValue
    }
    if (field.valueKind === 'bool') {
      return rawValue === 'true'
    }
    if (field.valueKind === 'int') {
      const parsed = Number.parseInt(rawValue, 10)
      return Number.isFinite(parsed) ? parsed : undefined
    }
    const parsed = Number.parseFloat(rawValue)
    return Number.isFinite(parsed) ? parsed : undefined
  }

  const assignValue = (key: string): void => {
    const value = readFieldValue(key)
    if (value !== undefined) {
      result[key] = value
    }
  }

  const assignPair = (
    key: string,
    minKey: string,
    maxKey: string,
  ): void => {
    const minValue = readFieldValue(minKey)
    const maxValue = readFieldValue(maxKey)
    if (minValue === undefined || maxValue === undefined) {
      return
    }
    result[key] = [minValue, maxValue]
  }

  if (taskType === 'detection') {
    if (normalizedModelType === 'yolox') {
      for (const key of [
        'device',
        'seed',
        'num_workers',
        'max_labels',
        'evaluation_confidence_threshold',
        'evaluation_nms_threshold',
        'flip_prob',
        'hsv_prob',
        'mosaic_prob',
        'mixup_prob',
        'enable_mixup',
        'multiscale_range',
        'ema',
        'warmup_epochs',
        'no_aug_epochs',
        'min_lr_ratio',
      ]) {
        assignValue(key)
      }
      assignPair('mosaic_scale', 'mosaic_scale_min', 'mosaic_scale_max')
      assignPair('mixup_scale', 'mixup_scale_min', 'mixup_scale_max')
      return result
    }
    if (normalizedModelType === 'rfdetr') {
      for (const key of [
        'device',
        'learning_rate',
        'class_cost',
        'bbox_cost',
        'giou_cost',
        'class_loss_weight',
        'bbox_loss_weight',
        'giou_loss_weight',
      ]) {
        assignValue(key)
      }
      return result
    }
    for (const key of [
      'learning_rate',
      'weight_decay',
      'class_loss_weight',
      'box_loss_weight',
      'dfl_loss_weight',
      'evaluation_confidence_threshold',
      'evaluation_nms_threshold',
      'assign_topk',
      'assign_alpha',
      'assign_beta',
      'grad_clip_norm',
      'flip_prob',
      'hsv_prob',
      'mosaic_prob',
      'mixup_prob',
      'enable_mixup',
      'degrees',
      'translate',
      'shear',
    ]) {
      assignValue(key)
    }
    assignPair('mosaic_scale', 'mosaic_scale_min', 'mosaic_scale_max')
    assignPair('mixup_scale', 'mixup_scale_min', 'mixup_scale_max')
    return result
  }

  if (taskType === 'classification') {
    for (const key of ['device', 'learning_rate', 'weight_decay', 'min_lr_ratio']) {
      assignValue(key)
    }
    return result
  }

  if (taskType === 'segmentation') {
    if (normalizedModelType === 'rfdetr') {
      for (const key of [
        'device',
        'learning_rate',
        'weight_decay',
        'min_lr_ratio',
        'class_cost',
        'bbox_cost',
        'giou_cost',
        'class_loss_weight',
        'bbox_loss_weight',
        'giou_loss_weight',
        'mask_ce_weight',
        'mask_dice_weight',
      ]) {
        assignValue(key)
      }
      return result
    }
    for (const key of [
        'device',
        'learning_rate',
        'weight_decay',
        'min_lr_ratio',
        'class_loss_weight',
        'box_loss_weight',
        'dfl_loss_weight',
      'mask_loss_weight',
      'assign_topk',
      'assign_alpha',
      'assign_beta',
      'grad_clip_norm',
    ]) {
      assignValue(key)
    }
    return result
  }

  if (taskType === 'pose') {
    for (const key of [
      'device',
      'learning_rate',
      'weight_decay',
      'min_lr_ratio',
      'class_loss_weight',
      'box_loss_weight',
      'dfl_loss_weight',
      'kpt_loss_weight',
      'assign_topk',
      'assign_alpha',
      'assign_beta',
      'grad_clip_norm',
    ]) {
      assignValue(key)
    }
    return result
  }

  if (taskType === 'obb') {
    for (const key of ['device', 'learning_rate', 'weight_decay']) {
      assignValue(key)
    }
  }

  return result
}

export function validateTrainingModelLayerValues(
  taskType: ModelTaskType,
  modelType: string | null | undefined,
  values: TrainingParameterValues,
): string | null {
  const normalizedModelType = normalizeModelType(modelType)
  if (taskType !== 'detection' || !normalizedModelType) {
    return null
  }

  const checkPair = (
    label: string,
    minKey: string,
    maxKey: string,
  ): string | null => {
    const minValue = String(values[minKey] ?? '').trim()
    const maxValue = String(values[maxKey] ?? '').trim()
    if (!minValue && !maxValue) {
      return null
    }
    if (!minValue || !maxValue) {
      return `${label} 需要同时填写最小值和最大值`
    }
    return null
  }

  if (normalizedModelType === 'yolox' || normalizedModelType === 'yolov8' || normalizedModelType === 'yolo11' || normalizedModelType === 'yolo26') {
    return checkPair('mosaic_scale', 'mosaic_scale_min', 'mosaic_scale_max')
      ?? checkPair('mixup_scale', 'mixup_scale_min', 'mixup_scale_max')
  }

  return null
}
