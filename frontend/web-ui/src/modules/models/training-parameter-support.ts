import { translate } from '@/platform/i18n'
import type {
  ModelTaskType,
  TrainingParameterSchemaItem,
} from './services/model.service'

export type TrainingParameterInputKind = 'text' | 'number' | 'select'
export type TrainingParameterValueKind = 'string' | 'int' | 'float' | 'bool'
export type TrainingParameterGroup = 'model' | 'augmentation'

export interface TrainingParameterFieldOption {
  label: string
  value: string
}

export interface TrainingParameterField {
  key: string
  label: string
  inputKind: TrainingParameterInputKind
  valueKind: TrainingParameterValueKind
  group?: TrainingParameterGroup
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

const optionalBoolOptions: TrainingParameterFieldOption[] = [
  { label: '自动', value: '' },
  ...boolOptions,
]

const classificationAutoAugmentOptions: TrainingParameterFieldOption[] = [
  { label: 'RandAugment（默认）', value: 'randaugment' },
  { label: 'AutoAugment', value: 'autoaugment' },
  { label: 'AugMix', value: 'augmix' },
  { label: '关闭', value: 'none' },
]

const classificationCropModeOptions: TrainingParameterFieldOption[] = [
  { label: '等比缩放并中心裁剪', value: 'none' },
  { label: '随机比例裁剪', value: 'random_resized_crop' },
]

const yoloOptimizerOptions: TrainingParameterFieldOption[] = [
  { label: 'Auto（默认）', value: 'auto' },
  { label: 'MuSGD', value: 'musgd' },
  { label: 'SGD', value: 'sgd' },
  { label: 'AdamW', value: 'adamw' },
  { label: 'Adam', value: 'adam' },
  { label: 'NAdam', value: 'nadam' },
  { label: 'RAdam', value: 'radam' },
  { label: 'RMSProp', value: 'rmsprop' },
]

const rfdetrSchedulerOptions: TrainingParameterFieldOption[] = [
  { label: 'Step（默认）', value: 'step' },
  { label: 'Cosine', value: 'cosine' },
]

const classificationCropScaleKeys = new Set(['crop_scale_min', 'crop_scale_max'])
const classificationManualAugmentationKeys = new Set([
  'rotation_degrees',
  'translate_ratio',
  'scale_min',
  'scale_max',
  'brightness_gain',
  'contrast_gain',
  'gamma_min',
  'gamma_max',
  'hue_gain',
  'saturation_gain',
  'value_gain',
])

export function buildTrainingDeviceOptions(
  devices: Record<string, unknown> | null | undefined,
): TrainingParameterFieldOption[] {
  const options: TrainingParameterFieldOption[] = [
    { label: '自动选择（默认）', value: '' },
    { label: 'cpu', value: 'cpu' },
  ]
  const gpuCount = readGpuDeviceCount(devices)
  if (gpuCount <= 0) return options
  options.push({ label: 'cuda', value: 'cuda' })
  for (let index = 0; index < gpuCount; index += 1) {
    options.push({ label: `cuda:${index}`, value: `cuda:${index}` })
  }
  return options
}

function readRecord(
  record: Record<string, unknown> | null | undefined,
  key: string,
): Record<string, unknown> | null {
  const value = record?.[key]
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function readPositiveInteger(value: unknown): number {
  const numberValue = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numberValue) || numberValue <= 0) return 0
  return Math.floor(numberValue)
}

function readGpuDeviceCount(devices: Record<string, unknown> | null | undefined): number {
  const gpu = readRecord(devices, 'gpu')
  const rows = Array.isArray(gpu?.devices) ? gpu.devices : []
  if (rows.length > 0) return rows.length
  return Math.max(
    readPositiveInteger(gpu?.count),
    readPositiveInteger(gpu?.device_count),
    readPositiveInteger(readRecord(devices, 'cuda')?.device_count),
    readPositiveInteger(readRecord(devices, 'cuda')?.count),
  )
}

const rfdetrAugmentationBackendOptions: TrainingParameterFieldOption[] = [
  { label: 'CPU（默认）', value: 'cpu' },
  { label: '自动选择', value: 'auto' },
  { label: 'GPU', value: 'gpu' },
]

const rfdetrAugmentationPresetOptions: TrainingParameterFieldOption[] = [
  { label: '默认：水平翻转', value: 'default' },
  { label: '保守：小数据集', value: 'conservative' },
  { label: '强增强：大数据集', value: 'aggressive' },
  { label: '航拍：俯视图像', value: 'aerial' },
  { label: '工业：光照与噪声', value: 'industrial' },
]

const yoloDetectionDefaultLearningRate = '0.01'
const yoloDetectionDefaultWeightDecay = '0.0005'
const yoloTaskDefaultLearningRate = '0.01'
const yoloTaskDefaultWeightDecay = '0.0005'

function withTrainingParameterGroup(
  fields: TrainingParameterField[],
  group: TrainingParameterGroup,
): TrainingParameterField[] {
  return fields.map((field) => ({ ...field, group }))
}

export function isTrainingAugmentationField(field: TrainingParameterField): boolean {
  return field.group === 'augmentation'
}

const ordinaryYoloAugmentationFields: TrainingParameterField[] = withTrainingParameterGroup([
  numberField('flip_prob', '水平翻转概率', { min: 0, max: 1, step: 0.01, defaultValue: '0.5' }),
  numberField('hsv_h', 'HSV 色相增益', { min: 0, max: 0.5, step: 0.001, defaultValue: '0.015' }),
  numberField('hsv_s', 'HSV 饱和度增益', { min: 0, max: 1, step: 0.01, defaultValue: '0.7' }),
  numberField('hsv_v', 'HSV 明度增益', { min: 0, max: 1, step: 0.01, defaultValue: '0.4' }),
  numberField('mosaic_prob', 'Mosaic 概率', { min: 0, max: 1, step: 0.01, defaultValue: '1.0' }),
  numberField('mixup_prob', 'MixUp 概率', { min: 0, max: 1, step: 0.01, defaultValue: '0.0' }),
  numberField('affine_prob', '仿射增强概率', { min: 0, max: 1, step: 0.01, defaultValue: '1.0' }),
  numberField('degrees', '仿射旋转角度', { min: 0, max: 180, step: 0.1, defaultValue: '0.0' }),
  numberField('translate', '仿射平移比例', { min: 0, max: 1, step: 0.01, defaultValue: '0.1' }),
  numberField('scale', '仿射缩放比例', { min: 0, max: 10, step: 0.01, defaultValue: '0.5' }),
  numberField('shear', '仿射错切角度', { min: 0, max: 180, step: 0.1, defaultValue: '0.0' }),
  numberField('perspective', '透视变换比例', { min: 0, max: 1, step: 0.0001, defaultValue: '0.0' }),
  numberField('close_mosaic', '最后关闭 Mosaic 轮数', { integer: true, min: 0, max: 10000, step: 1, defaultValue: '10' }),
  numberField('multi_scale', '多尺度范围比例', { min: 0, max: 0.9, step: 0.01, defaultValue: '0.0' }),
  numberField('multi_scale_stride', '多尺度步长', { integer: true, min: 1, max: 1024, step: 1, defaultValue: '32' }),
], 'augmentation')

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

const yoloRuntimeFields: TrainingParameterField[] = [
  numberField('num_workers', '数据加载 worker 数', {
    integer: true,
    min: 0,
    max: 64,
    step: 1,
    defaultValue: '2',
  }),
  numberField('prefetch_factor', '每个 worker 预取批次数', {
    integer: true,
    min: 1,
    max: 32,
    step: 1,
    defaultValue: '2',
  }),
  selectField('pin_memory', '固定页内存', optionalBoolOptions, {
    valueKind: 'bool',
    defaultValue: '',
  }),
  selectField('persistent_workers', '常驻数据加载 worker', optionalBoolOptions, {
    valueKind: 'bool',
    defaultValue: '',
  }),
]

const rfdetrRuntimeFields: TrainingParameterField[] = [
  numberField('num_workers', '数据加载 worker 数', {
    integer: true,
    min: 0,
    max: 64,
    step: 1,
    defaultValue: '2',
  }),
]

const ordinaryYoloEvaluationThresholdFields: TrainingParameterField[] = [
  numberField('evaluation_confidence_threshold', '验证置信度阈值', {
    min: 0,
    max: 1,
    step: 0.001,
    defaultValue: '0.001',
  }),
  numberField('evaluation_nms_threshold', '验证 NMS 阈值', {
    min: 0,
    max: 1,
    step: 0.01,
    defaultValue: '0.7',
  }),
]

const obbYoloEvaluationThresholdFields: TrainingParameterField[] = [
  numberField('evaluation_confidence_threshold', '验证置信度阈值', {
    min: 0,
    max: 1,
    step: 0.01,
    defaultValue: '0.01',
  }),
  numberField('evaluation_nms_threshold', '验证 NMS 阈值', {
    min: 0,
    max: 1,
    step: 0.01,
    defaultValue: '0.7',
  }),
]

const detectionYoloXAugmentationFields: TrainingParameterField[] = withTrainingParameterGroup([
  numberField('flip_prob', '水平翻转概率', { min: 0, max: 1, step: 0.01, defaultValue: '0.5' }),
  numberField('hsv_prob', 'HSV 增强概率', { min: 0, max: 1, step: 0.01, defaultValue: '1.0' }),
  numberField('mosaic_prob', 'Mosaic 概率', { min: 0, max: 1, step: 0.01, defaultValue: '1.0' }),
  numberField('mixup_prob', 'MixUp 概率', { min: 0, max: 1, step: 0.01, defaultValue: '1.0' }),
  selectField('enable_mixup', '启用 MixUp', boolOptions, { valueKind: 'bool', defaultValue: 'true' }),
  numberField('degrees', '仿射旋转角度', { min: 0, max: 180, step: 0.1, defaultValue: '10.0' }),
  numberField('translate', '仿射平移比例', { min: 0, max: 1, step: 0.01, defaultValue: '0.1' }),
  numberField('shear', '仿射错切角度', { min: 0, max: 180, step: 0.1, defaultValue: '2.0' }),
  numberField('mosaic_scale_min', 'Mosaic 缩放最小值', { min: 0.01, max: 10, step: 0.01, defaultValue: '0.1' }),
  numberField('mosaic_scale_max', 'Mosaic 缩放最大值', { min: 0.01, max: 10, step: 0.01, defaultValue: '2.0' }),
  numberField('mixup_scale_min', 'MixUp 缩放最小值', { min: 0.01, max: 10, step: 0.01, defaultValue: '0.5' }),
  numberField('mixup_scale_max', 'MixUp 缩放最大值', { min: 0.01, max: 10, step: 0.01, defaultValue: '1.5' }),
  numberField('multiscale_range', '多尺度训练范围', { integer: true, min: 0, max: 64, step: 1, defaultValue: '5' }),
  numberField('no_aug_epochs', '最后 no-aug 轮数', { integer: true, min: 0, max: 10000, step: 1, defaultValue: '15' }),
], 'augmentation')

const classificationYoloAugmentationFields: TrainingParameterField[] = withTrainingParameterGroup([
  numberField('flip_prob', '水平翻转概率（0–1）', { min: 0, max: 1, step: 0.01, defaultValue: '0.5' }),
  selectField('crop_mode', '裁剪方式', classificationCropModeOptions, {
    defaultValue: 'random_resized_crop',
  }),
  numberField('crop_scale_min', '随机裁剪面积比例最小值（0.08–1）', { min: 0.08, max: 1, step: 0.01, defaultValue: '0.5' }),
  numberField('crop_scale_max', '随机裁剪面积比例最大值（0.08–1）', { min: 0.08, max: 1, step: 0.01, defaultValue: '1.0' }),
  selectField('auto_augment', '自动增强策略', classificationAutoAugmentOptions, {
    defaultValue: 'randaugment',
  }),
  numberField('rotation_degrees', '最大旋转角度（±0–180°）', { min: 0, max: 180, step: 0.1, defaultValue: '0' }),
  numberField('translate_ratio', '最大平移比例（±0–0.5）', { min: 0, max: 0.5, step: 0.01, defaultValue: '0' }),
  numberField('scale_min', '仿射缩放最小值（0.1–2）', { min: 0.1, max: 2, step: 0.01, defaultValue: '1' }),
  numberField('scale_max', '仿射缩放最大值（0.1–2）', { min: 0.1, max: 2, step: 0.01, defaultValue: '1' }),
  numberField('brightness_gain', '亮度增益范围（0–1）', { min: 0, max: 1, step: 0.01, defaultValue: '0' }),
  numberField('contrast_gain', '对比度增益范围（0–1）', { min: 0, max: 1, step: 0.01, defaultValue: '0' }),
  numberField('gamma_min', 'Gamma 最小值（0.1–5）', { min: 0.1, max: 5, step: 0.01, defaultValue: '1' }),
  numberField('gamma_max', 'Gamma 最大值（0.1–5）', { min: 0.1, max: 5, step: 0.01, defaultValue: '1' }),
  numberField('hue_gain', '色相增益范围（0–0.5）', { min: 0, max: 0.5, step: 0.001, defaultValue: '0' }),
  numberField('saturation_gain', '饱和度增益范围（0–1）', { min: 0, max: 1, step: 0.01, defaultValue: '0' }),
  numberField('value_gain', '明度增益范围（0–1）', { min: 0, max: 1, step: 0.01, defaultValue: '0' }),
  numberField('random_erasing_prob', '随机擦除概率（0–1）', { min: 0, max: 1, step: 0.01, defaultValue: '0.4' }),
], 'augmentation')

export function normalizeTrainingParameterNumber(
  field: TrainingParameterField,
  rawValue: string,
): string {
  if (field.inputKind !== 'number') return rawValue
  const numericValue = Number(rawValue)
  if (!Number.isFinite(numericValue)) {
    return field.defaultValue ?? ''
  }
  let normalizedValue = numericValue
  if (field.min !== undefined) normalizedValue = Math.max(field.min, normalizedValue)
  if (field.max !== undefined) normalizedValue = Math.min(field.max, normalizedValue)
  if (field.valueKind === 'int') normalizedValue = Math.round(normalizedValue)
  return String(normalizedValue)
}

const rfdetrAugmentationFields: TrainingParameterField[] = withTrainingParameterGroup([
  selectField('rfdetr_augmentation_preset', 'RF-DETR 增强预设', rfdetrAugmentationPresetOptions, {
    defaultValue: 'default',
  }),
  selectField('scale_jitter', '启用尺度抖动裁剪', boolOptions, {
    valueKind: 'bool',
    defaultValue: 'true',
  }),
  selectField('augmentation_backend', '增强执行后端', rfdetrAugmentationBackendOptions, {
    defaultValue: 'cpu',
  }),
], 'augmentation')

const detectionYoloXFields: TrainingParameterField[] = [
  numberField('seed', '随机种子', { integer: true, min: 0, max: 4294967295, step: 1, defaultValue: '0' }),
  numberField('num_workers', '数据加载 worker 数', { integer: true, min: 0, max: 64, step: 1, defaultValue: '0' }),
  numberField('prefetch_factor', '每个 worker 预取批次数', { integer: true, min: 1, max: 32, step: 1, defaultValue: '2' }),
  selectField('persistent_workers', '常驻数据加载 worker', optionalBoolOptions, { valueKind: 'bool', defaultValue: '' }),
  numberField('max_labels', '单图最大标签数', { integer: true, min: 1, max: 10000, step: 1, defaultValue: '120' }),
  numberField('evaluation_confidence_threshold', '验证置信度阈值', { min: 0, max: 1, step: 0.01, defaultValue: '0.01' }),
  numberField('evaluation_nms_threshold', '验证 NMS 阈值', { min: 0, max: 1, step: 0.01, defaultValue: '0.65' }),
  ...detectionYoloXAugmentationFields,
  selectField('ema', '启用 EMA', boolOptions, { valueKind: 'bool', defaultValue: 'true' }),
  numberField('warmup_epochs', 'Warmup 轮数', { integer: true, min: 0, max: 10000, step: 1, defaultValue: '5' }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, max: 1, step: 0.0001, defaultValue: '0.05' }),
]

const detectionYoloPrimaryFields: TrainingParameterField[] = [
  ...yoloRuntimeFields,
  selectField('optimizer', '优化器', yoloOptimizerOptions, { defaultValue: 'auto' }),
  numberField('learning_rate', '基础学习率', { min: 0.00001, max: 1, step: 0.00001, defaultValue: yoloDetectionDefaultLearningRate }),
  numberField('weight_decay', '权重衰减', { min: 0, max: 1, step: 0.0001, defaultValue: yoloDetectionDefaultWeightDecay }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, max: 1, step: 0.0001, defaultValue: '0.01' }),
  numberField('class_loss_weight', '分类损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '0.5' }),
  numberField('box_loss_weight', '框回归损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '7.5' }),
  numberField('dfl_loss_weight', 'DFL 损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '1.5' }),
  numberField('evaluation_confidence_threshold', '验证置信度阈值', { min: 0, max: 1, step: 0.001, defaultValue: '0.001' }),
  numberField('evaluation_nms_threshold', '验证 NMS 阈值', { min: 0, max: 1, step: 0.01, defaultValue: '0.7' }),
  numberField('assign_topk', '正样本匹配 topk', { integer: true, min: 1, max: 1000, step: 1, defaultValue: '10' }),
  numberField('assign_alpha', '正样本匹配 alpha', { min: 0, max: 100, step: 0.1, defaultValue: '0.5' }),
  numberField('assign_beta', '正样本匹配 beta', { min: 0, max: 100, step: 0.1, defaultValue: '6.0' }),
  numberField('grad_clip_norm', '梯度裁剪上限', { min: 0.1, max: 10000, step: 0.1, defaultValue: '10.0' }),
  ...ordinaryYoloAugmentationFields,
]

const detectionRfdetrFields: TrainingParameterField[] = [
  ...rfdetrRuntimeFields,
  numberField('learning_rate', '学习率', { min: 0.000001, max: 1, step: 0.000001, defaultValue: '0.0001' }),
  numberField('weight_decay', '权重衰减', { min: 0, max: 1, step: 0.0001, defaultValue: '0.0001' }),
  selectField('lr_scheduler', '学习率调度器', rfdetrSchedulerOptions, { defaultValue: 'step' }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, max: 1, step: 0.0001, defaultValue: '0.01' }),
  numberField('grad_accum_steps', '梯度累积步数', { integer: true, min: 1, max: 1024, step: 1, defaultValue: '4' }),
  numberField('class_cost', '分类匹配代价', { min: 0, max: 1000, step: 0.1, defaultValue: '2.0' }),
  numberField('bbox_cost', '框匹配代价', { min: 0, max: 1000, step: 0.1, defaultValue: '5.0' }),
  numberField('giou_cost', 'GIoU 匹配代价', { min: 0, max: 1000, step: 0.1, defaultValue: '2.0' }),
  numberField('class_loss_weight', '分类损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '1.0' }),
  numberField('bbox_loss_weight', '框回归损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '5.0' }),
  numberField('giou_loss_weight', 'GIoU 损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '2.0' }),
  numberField('evaluation_max_detections', '验证最大检测数', { integer: true, min: 100, max: 10000, step: 1, defaultValue: '500' }),
  selectField('use_ema', '启用 EMA', boolOptions, { valueKind: 'bool', defaultValue: 'true' }),
  selectField('multi_scale', '启用多尺度训练', boolOptions, { valueKind: 'bool', defaultValue: 'true' }),
  selectField('expanded_scales', '启用扩展尺度', boolOptions, { valueKind: 'bool', defaultValue: 'true' }),
  ...rfdetrAugmentationFields,
]

const classificationFields: TrainingParameterField[] = [
  ...yoloRuntimeFields,
  selectField('optimizer', '优化器', yoloOptimizerOptions, { defaultValue: 'auto' }),
  numberField('learning_rate', '基础学习率', { min: 0.00001, max: 1, step: 0.00001, defaultValue: yoloTaskDefaultLearningRate }),
  numberField('weight_decay', '权重衰减', { min: 0, max: 1, step: 0.0001, defaultValue: yoloTaskDefaultWeightDecay }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, max: 1, step: 0.0001, defaultValue: '0.01' }),
  numberField('grad_clip_norm', '梯度裁剪上限', { min: 0.1, max: 10000, step: 0.1, defaultValue: '10.0' }),
  ...classificationYoloAugmentationFields,
]

const segmentationYoloPrimaryFields: TrainingParameterField[] = [
  ...yoloRuntimeFields,
  selectField('optimizer', '优化器', yoloOptimizerOptions, { defaultValue: 'auto' }),
  numberField('learning_rate', '基础学习率', { min: 0.00001, max: 1, step: 0.00001, defaultValue: yoloTaskDefaultLearningRate }),
  numberField('weight_decay', '权重衰减', { min: 0, max: 1, step: 0.0001, defaultValue: yoloTaskDefaultWeightDecay }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, max: 1, step: 0.0001, defaultValue: '0.01' }),
  ...ordinaryYoloEvaluationThresholdFields,
  numberField('class_loss_weight', '分类损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '0.5' }),
  numberField('box_loss_weight', '框回归损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '7.5' }),
  numberField('dfl_loss_weight', 'DFL 损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '1.5' }),
  numberField('mask_loss_weight', '掩码损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '7.5' }),
  numberField('assign_topk', '正样本匹配 topk', { integer: true, min: 1, max: 1000, step: 1, defaultValue: '10' }),
  numberField('assign_alpha', '正样本匹配 alpha', { min: 0, max: 100, step: 0.1, defaultValue: '0.5' }),
  numberField('assign_beta', '正样本匹配 beta', { min: 0, max: 100, step: 0.1, defaultValue: '6.0' }),
  numberField('grad_clip_norm', '梯度裁剪上限', { min: 0.1, max: 10000, step: 0.1, defaultValue: '10.0' }),
  ...ordinaryYoloAugmentationFields,
]

const segmentationRfdetrFields: TrainingParameterField[] = [
  ...rfdetrRuntimeFields,
  numberField('learning_rate', '学习率', { min: 0.000001, max: 1, step: 0.000001, defaultValue: '0.0001' }),
  numberField('weight_decay', '权重衰减', { min: 0, max: 1, step: 0.0001, defaultValue: '0.0001' }),
  selectField('lr_scheduler', '学习率调度器', rfdetrSchedulerOptions, { defaultValue: 'step' }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, max: 1, step: 0.0001, defaultValue: '0.01' }),
  numberField('grad_accum_steps', '梯度累积步数', { integer: true, min: 1, max: 1024, step: 1, defaultValue: '4' }),
  numberField('class_cost', '分类匹配代价', { min: 0, max: 1000, step: 0.1, defaultValue: '2.0' }),
  numberField('bbox_cost', '框匹配代价', { min: 0, max: 1000, step: 0.1, defaultValue: '5.0' }),
  numberField('giou_cost', 'GIoU 匹配代价', { min: 0, max: 1000, step: 0.1, defaultValue: '2.0' }),
  numberField('class_loss_weight', '分类损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '1.0' }),
  numberField('bbox_loss_weight', '框回归损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '5.0' }),
  numberField('giou_loss_weight', 'GIoU 损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '2.0' }),
  numberField('mask_ce_weight', '掩码 CE 损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '5.0' }),
  numberField('mask_dice_weight', '掩码 Dice 损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '5.0' }),
  numberField('evaluation_max_detections', '验证最大检测数', { integer: true, min: 100, max: 10000, step: 1, defaultValue: '500' }),
  selectField('use_ema', '启用 EMA', boolOptions, { valueKind: 'bool', defaultValue: 'true' }),
  selectField('multi_scale', '启用多尺度训练', boolOptions, { valueKind: 'bool', defaultValue: 'true' }),
  selectField('expanded_scales', '启用扩展尺度', boolOptions, { valueKind: 'bool', defaultValue: 'true' }),
  ...rfdetrAugmentationFields,
]

const poseFields: TrainingParameterField[] = [
  ...yoloRuntimeFields,
  selectField('optimizer', '优化器', yoloOptimizerOptions, { defaultValue: 'auto' }),
  numberField('learning_rate', '基础学习率', { min: 0.00001, max: 1, step: 0.00001, defaultValue: yoloTaskDefaultLearningRate }),
  numberField('weight_decay', '权重衰减', { min: 0, max: 1, step: 0.0001, defaultValue: yoloTaskDefaultWeightDecay }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, max: 1, step: 0.0001, defaultValue: '0.01' }),
  ...ordinaryYoloEvaluationThresholdFields,
  numberField('class_loss_weight', '分类损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '0.5' }),
  numberField('box_loss_weight', '框回归损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '7.5' }),
  numberField('dfl_loss_weight', 'DFL 损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '1.5' }),
  numberField('kpt_loss_weight', '关键点损失权重', { min: 0, max: 1000, step: 0.1, defaultValue: '12.0' }),
  numberField('assign_topk', '正样本匹配 topk', { integer: true, min: 1, max: 1000, step: 1, defaultValue: '10' }),
  numberField('assign_alpha', '正样本匹配 alpha', { min: 0, max: 100, step: 0.1, defaultValue: '0.5' }),
  numberField('assign_beta', '正样本匹配 beta', { min: 0, max: 100, step: 0.1, defaultValue: '6.0' }),
  numberField('grad_clip_norm', '梯度裁剪上限', { min: 0.1, max: 10000, step: 0.1, defaultValue: '10.0' }),
  ...ordinaryYoloAugmentationFields,
]

const obbFields: TrainingParameterField[] = [
  ...yoloRuntimeFields,
  selectField('optimizer', '优化器', yoloOptimizerOptions, { defaultValue: 'auto' }),
  numberField('learning_rate', '基础学习率', { min: 0.00001, max: 1, step: 0.00001, defaultValue: yoloTaskDefaultLearningRate }),
  numberField('weight_decay', '权重衰减', { min: 0, max: 1, step: 0.0001, defaultValue: yoloTaskDefaultWeightDecay }),
  numberField('min_lr_ratio', '最小学习率比例', { min: 0, max: 1, step: 0.0001, defaultValue: '0.01' }),
  ...obbYoloEvaluationThresholdFields,
  numberField('grad_clip_norm', '梯度裁剪上限', { min: 0.1, max: 10000, step: 0.1, defaultValue: '10.0' }),
  ...ordinaryYoloAugmentationFields,
]

function normalizeModelType(modelType: string | null | undefined): string {
  return String(modelType ?? '').trim().toLowerCase()
}

export function supportsTrainingWarmStart(taskType: ModelTaskType): boolean {
  return ['detection', 'classification', 'segmentation', 'pose', 'obb'].includes(taskType)
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
  parameterSchema?: TrainingParameterSchemaItem | null,
): TrainingParameterValues {
  const fields = getModelLayerTrainingFields(taskType, modelType, parameterSchema)
  return Object.fromEntries(fields.map((field) => [field.key, field.defaultValue ?? '']))
}

function applyTrainingNumericParameterSpecs(
  fields: TrainingParameterField[],
  parameterSchema: TrainingParameterSchemaItem | null | undefined,
): TrainingParameterField[] {
  if (!parameterSchema) return fields
  const numericSpecs = new Map(parameterSchema.numeric_fields.map((field) => [field.key, field]))
  const numericFieldKeys = new Set(
    fields.filter((field) => field.inputKind === 'number').map((field) => field.key),
  )
  for (const key of numericSpecs.keys()) {
    if (!numericFieldKeys.has(key)) {
      throw new Error(`训练参数目录包含页面未登记的数值字段: ${parameterSchema.task_type}/${parameterSchema.model_type}/${key}`)
    }
  }
  return fields.map((field) => {
    if (field.inputKind !== 'number') return field
    const spec = numericSpecs.get(field.key)
    if (!spec) {
      throw new Error(`训练参数目录缺少数值字段: ${parameterSchema.task_type}/${parameterSchema.model_type}/${field.key}`)
    }
    if (field.valueKind !== spec.value_kind) {
      throw new Error(`训练参数数值类型不一致: ${parameterSchema.task_type}/${parameterSchema.model_type}/${field.key}`)
    }
    return {
      ...field,
      min: spec.minimum,
      max: spec.maximum,
      step: spec.step,
      defaultValue: String(spec.default_value),
    }
  })
}

export function getModelLayerTrainingFields(
  taskType: ModelTaskType,
  modelType: string | null | undefined,
  parameterSchema?: TrainingParameterSchemaItem | null,
): TrainingParameterField[] {
  const normalizedModelType = normalizeModelType(modelType)
  if (!normalizedModelType) {
    return []
  }
  let fields: TrainingParameterField[] = []
  if (taskType === 'detection') {
    fields = normalizedModelType === 'yolox'
      ? detectionYoloXFields
      : normalizedModelType === 'rfdetr'
        ? detectionRfdetrFields
        : detectionYoloPrimaryFields
  } else if (taskType === 'classification') {
    fields = classificationFields
  } else if (taskType === 'segmentation') {
    fields = normalizedModelType === 'rfdetr'
      ? segmentationRfdetrFields
      : segmentationYoloPrimaryFields
  } else if (taskType === 'pose') {
    fields = poseFields
  } else if (taskType === 'obb') {
    fields = obbFields
  }
  if (normalizedModelType === 'yolo26') {
    fields = fields
      .filter((field) => field.key !== 'evaluation_nms_threshold')
      .map((field) => field.key === 'dfl_loss_weight'
        ? { ...field, key: 'l1_loss_weight', label: 'L1 框回归损失权重' }
        : field)
  }
  if (parameterSchema) {
    if (
      parameterSchema.task_type !== taskType
      || normalizeModelType(parameterSchema.model_type) !== normalizedModelType
    ) {
      throw new Error(`训练参数目录与当前模型不匹配: ${taskType}/${normalizedModelType}`)
    }
    if (!parameterSchema.capabilities.supports_nms_threshold) {
      fields = fields.filter((field) => field.key !== 'evaluation_nms_threshold')
    }
    if (parameterSchema.capabilities.distribution_loss_name === 'l1_loss') {
      fields = fields.map((field) => field.key === 'dfl_loss_weight'
        ? { ...field, key: 'l1_loss_weight', label: 'L1 框回归损失权重' }
        : field)
    }
  }
  return applyTrainingNumericParameterSpecs(fields, parameterSchema)
}

function buildFlatTrainingParameterValues(
  taskType: ModelTaskType,
  modelType: string | null | undefined,
  values: TrainingParameterValues,
  options: { augmentationEnabled?: boolean; device?: string } = {},
): Record<string, unknown> {
  const normalizedModelType = normalizeModelType(modelType)
  if (!normalizedModelType) {
    return {}
  }

  const augmentationEnabled = options.augmentationEnabled !== false
  const result: Record<string, unknown> = {}
  const regressionLossWeightKey = normalizedModelType === 'yolo26'
    ? 'l1_loss_weight'
    : 'dfl_loss_weight'
  const trainingDevice = String(options.device ?? '').trim()
  if (trainingDevice) {
    result.device = trainingDevice
  }
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

  const assignOrdinaryYoloAugmentationValues = (): void => {
    for (const key of [
      'flip_prob',
      'hsv_h',
      'hsv_s',
      'hsv_v',
      'mosaic_prob',
      'mixup_prob',
      'affine_prob',
      'degrees',
      'translate',
      'scale',
      'shear',
      'perspective',
      'close_mosaic',
      'multi_scale',
      'multi_scale_stride',
    ]) {
      assignValue(key)
    }
  }

  const disableOrdinaryYoloAugmentationValues = (): void => {
    result.flip_prob = 0
    result.hsv_h = 0
    result.hsv_s = 0
    result.hsv_v = 0
    result.mosaic_prob = 0
    result.mixup_prob = 0
    result.affine_prob = 0
    result.degrees = 0
    result.translate = 0
    result.scale = 0
    result.shear = 0
    result.perspective = 0
    result.close_mosaic = 0
    result.multi_scale = 0
  }

  const disableYoloXAugmentationValues = (): void => {
    result.flip_prob = 0
    result.hsv_prob = 0
    result.mosaic_prob = 0
    result.mixup_prob = 0
    result.enable_mixup = false
    result.degrees = 0
    result.translate = 0
    result.shear = 0
    result.multiscale_range = 0
    result.no_aug_epochs = 0
  }

  const assignClassificationAugmentationValues = (): void => {
    for (const key of [
      'flip_prob',
      'crop_mode',
      'crop_scale_min',
      'crop_scale_max',
      'auto_augment',
      'rotation_degrees',
      'translate_ratio',
      'scale_min',
      'scale_max',
      'brightness_gain',
      'contrast_gain',
      'gamma_min',
      'gamma_max',
      'hue_gain',
      'saturation_gain',
      'value_gain',
      'random_erasing_prob',
    ]) {
      assignValue(key)
    }
  }

  const disableClassificationAugmentationValues = (): void => {
    result.flip_prob = 0
    result.crop_mode = 'none'
    result.crop_scale_min = 1
    result.crop_scale_max = 1
    result.auto_augment = 'none'
    result.rotation_degrees = 0
    result.translate_ratio = 0
    result.scale_min = 1
    result.scale_max = 1
    result.brightness_gain = 0
    result.contrast_gain = 0
    result.gamma_min = 1
    result.gamma_max = 1
    result.hue_gain = 0
    result.saturation_gain = 0
    result.value_gain = 0
    result.random_erasing_prob = 0
    result.disable_augmentation = true
  }

  const assignRfdetrAugmentationValues = (): void => {
    assignValue('rfdetr_augmentation_preset')
    assignValue('scale_jitter')
    assignValue('augmentation_backend')
  }

  const assignYoloOptimizerValues = (): void => {
    assignValue('optimizer')
    if (String(values.optimizer ?? 'auto').trim().toLowerCase() !== 'auto') {
      assignValue('learning_rate')
    }
  }

  const assignRfdetrSchedulerValues = (): void => {
    assignValue('lr_scheduler')
    if (String(values.lr_scheduler ?? 'step').trim().toLowerCase() === 'cosine') {
      assignValue('min_lr_ratio')
    }
  }

  const disableRfdetrAugmentationValues = (): void => {
    result.disable_augmentation = true
  }

  for (const key of [
    'num_workers',
    'prefetch_factor',
    'pin_memory',
    'persistent_workers',
  ]) {
    assignValue(key)
  }

  if (taskType === 'detection') {
    if (normalizedModelType === 'yolox') {
      for (const key of [
        'seed',
        'num_workers',
        'prefetch_factor',
        'persistent_workers',
        'max_labels',
        'evaluation_confidence_threshold',
        'evaluation_nms_threshold',
        'flip_prob',
        'hsv_prob',
        'mosaic_prob',
        'mixup_prob',
        'enable_mixup',
        'degrees',
        'translate',
        'shear',
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
      if (!augmentationEnabled) {
        disableYoloXAugmentationValues()
      }
      return result
    }
    if (normalizedModelType === 'rfdetr') {
      for (const key of [
        'learning_rate',
        'weight_decay',
        'grad_accum_steps',
        'class_cost',
        'bbox_cost',
        'giou_cost',
        'class_loss_weight',
        'bbox_loss_weight',
        'giou_loss_weight',
        'evaluation_max_detections',
        'use_ema',
        'multi_scale',
        'expanded_scales',
      ]) {
        assignValue(key)
      }
      assignRfdetrSchedulerValues()
      assignRfdetrAugmentationValues()
      if (!augmentationEnabled) {
        disableRfdetrAugmentationValues()
      }
      return result
    }
    assignYoloOptimizerValues()
    for (const key of [
      'weight_decay',
      'min_lr_ratio',
      'class_loss_weight',
      'box_loss_weight',
      regressionLossWeightKey,
      'evaluation_confidence_threshold',
      'evaluation_nms_threshold',
      'assign_topk',
      'assign_alpha',
      'assign_beta',
      'grad_clip_norm',
    ]) {
      assignValue(key)
    }
    assignOrdinaryYoloAugmentationValues()
    if (!augmentationEnabled) {
      disableOrdinaryYoloAugmentationValues()
    }
    return result
  }

  if (taskType === 'classification') {
    assignYoloOptimizerValues()
    for (const key of ['weight_decay', 'min_lr_ratio', 'grad_clip_norm']) {
      assignValue(key)
    }
    assignClassificationAugmentationValues()
    if (!augmentationEnabled) {
      disableClassificationAugmentationValues()
    }
    return result
  }

  if (taskType === 'segmentation') {
    if (normalizedModelType === 'rfdetr') {
      for (const key of [
        'learning_rate',
        'weight_decay',
        'grad_accum_steps',
        'class_cost',
        'bbox_cost',
        'giou_cost',
        'class_loss_weight',
        'bbox_loss_weight',
        'giou_loss_weight',
        'mask_ce_weight',
        'mask_dice_weight',
        'evaluation_max_detections',
        'use_ema',
        'multi_scale',
        'expanded_scales',
      ]) {
        assignValue(key)
      }
      assignRfdetrSchedulerValues()
      assignRfdetrAugmentationValues()
      if (!augmentationEnabled) {
        disableRfdetrAugmentationValues()
      }
      return result
    }
    assignYoloOptimizerValues()
    for (const key of [
      'weight_decay',
      'min_lr_ratio',
      'evaluation_confidence_threshold',
      'evaluation_nms_threshold',
      'class_loss_weight',
      'box_loss_weight',
      regressionLossWeightKey,
      'mask_loss_weight',
      'assign_topk',
      'assign_alpha',
      'assign_beta',
      'grad_clip_norm',
    ]) {
      assignValue(key)
    }
    assignOrdinaryYoloAugmentationValues()
    if (!augmentationEnabled) {
      disableOrdinaryYoloAugmentationValues()
    }
    return result
  }

  if (taskType === 'pose') {
    assignYoloOptimizerValues()
    for (const key of [
      'weight_decay',
      'min_lr_ratio',
      'evaluation_confidence_threshold',
      'evaluation_nms_threshold',
      'class_loss_weight',
      'box_loss_weight',
      regressionLossWeightKey,
      'kpt_loss_weight',
      'assign_topk',
      'assign_alpha',
      'assign_beta',
      'grad_clip_norm',
    ]) {
      assignValue(key)
    }
    assignOrdinaryYoloAugmentationValues()
    if (!augmentationEnabled) {
      disableOrdinaryYoloAugmentationValues()
    }
    return result
  }

  if (taskType === 'obb') {
    assignYoloOptimizerValues()
    for (const key of [
      'weight_decay',
      'evaluation_confidence_threshold',
      'evaluation_nms_threshold',
      'min_lr_ratio',
      'grad_clip_norm',
    ]) {
      assignValue(key)
    }
    assignOrdinaryYoloAugmentationValues()
    if (!augmentationEnabled) {
      disableOrdinaryYoloAugmentationValues()
    }
  }

  return result
}

function compactTrainingGroup(values: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== undefined),
  )
}

function readRange(value: unknown): { minimum: unknown; maximum: unknown } | undefined {
  if (!Array.isArray(value) || value.length !== 2) return undefined
  return { minimum: value[0], maximum: value[1] }
}

function buildYoloTaskAugmentationParameters(
  flat: Record<string, unknown>,
  enabled: boolean,
): Record<string, unknown> {
  return compactTrainingGroup({
    enabled,
    horizontal_flip_probability: flat.flip_prob,
    hue_gain: flat.hsv_h,
    saturation_gain: flat.hsv_s,
    value_gain: flat.hsv_v,
    mosaic_probability: flat.mosaic_prob,
    mixup_probability: flat.mixup_prob,
    affine_probability: flat.affine_prob,
    rotation_degrees: flat.degrees,
    translation_ratio: flat.translate,
    scale_ratio: flat.scale,
    shear_degrees: flat.shear,
    perspective_ratio: flat.perspective,
    close_mosaic_epochs: flat.close_mosaic,
    multi_scale_ratio: flat.multi_scale,
    multi_scale_stride: flat.multi_scale_stride,
  })
}

/**
 * 按 task/model 生成后端 v1 严格训练参数。
 *
 * 页面状态仍以便于表单绑定的扁平 key 保存；提交边界在这里一次性转换成
 * runtime/optimization/loss/matching/evaluation/augmentation/advanced 分组。
 */
export function buildTrainingParameters(
  taskType: ModelTaskType,
  modelType: string | null | undefined,
  values: TrainingParameterValues,
  options: {
    augmentationEnabled?: boolean
    device?: string
    parameterSchema?: TrainingParameterSchemaItem | null
  } = {},
): Record<string, unknown> {
  const normalizedModelType = normalizeModelType(modelType)
  if (!normalizedModelType) return {}
  const supportsNmsThreshold = options.parameterSchema
    ? options.parameterSchema.capabilities.supports_nms_threshold
    : normalizedModelType !== 'yolo26'
  const flat = buildFlatTrainingParameterValues(taskType, normalizedModelType, values, options)
  const augmentationEnabled = options.augmentationEnabled !== false
  const runtime = compactTrainingGroup({
    device: flat.device,
    num_workers: flat.num_workers,
    prefetch_factor: flat.prefetch_factor,
    pin_memory: flat.pin_memory,
    persistent_workers: flat.persistent_workers,
  })

  if (taskType === 'detection' && normalizedModelType === 'yolox') {
    return {
      runtime: compactTrainingGroup({
        ...runtime,
        seed: flat.seed,
        num_workers: flat.num_workers,
      }),
      data: compactTrainingGroup({ max_labels_per_image: flat.max_labels }),
      optimization: compactTrainingGroup({
        warmup_epochs: flat.warmup_epochs,
        no_aug_epochs: flat.no_aug_epochs,
        min_lr_ratio: flat.min_lr_ratio,
        ema: flat.ema,
      }),
      evaluation: compactTrainingGroup({
        confidence_threshold: flat.evaluation_confidence_threshold,
        nms_threshold: flat.evaluation_nms_threshold,
      }),
      augmentation: compactTrainingGroup({
        enabled: augmentationEnabled,
        horizontal_flip_probability: flat.flip_prob,
        hsv_probability: flat.hsv_prob,
        mosaic_probability: flat.mosaic_prob,
        mixup_probability: flat.mixup_prob,
        mixup_enabled: flat.enable_mixup,
        rotation_degrees: flat.degrees,
        translation_ratio: flat.translate,
        shear_degrees: flat.shear,
        mosaic_scale: readRange(flat.mosaic_scale),
        mixup_scale: readRange(flat.mixup_scale),
        multiscale_range: flat.multiscale_range,
      }),
    }
  }

  if (normalizedModelType === 'rfdetr') {
    const result: Record<string, unknown> = {
      runtime,
      optimization: compactTrainingGroup({
        learning_rate: flat.learning_rate,
        weight_decay: flat.weight_decay,
        lr_scheduler: flat.lr_scheduler,
        min_lr_ratio: flat.min_lr_ratio,
        grad_accum_steps: flat.grad_accum_steps,
      }),
      loss: compactTrainingGroup({
        class_weight: flat.class_loss_weight,
        bbox_weight: flat.bbox_loss_weight,
        giou_weight: flat.giou_loss_weight,
        mask_ce_weight: flat.mask_ce_weight,
        mask_dice_weight: flat.mask_dice_weight,
      }),
      matching: compactTrainingGroup({
        class_cost: flat.class_cost,
        bbox_cost: flat.bbox_cost,
        giou_cost: flat.giou_cost,
      }),
      evaluation: compactTrainingGroup({
        max_detections: flat.evaluation_max_detections,
      }),
      augmentation: compactTrainingGroup({
        enabled: augmentationEnabled,
        preset: flat.rfdetr_augmentation_preset,
        scale_jitter: flat.scale_jitter,
        backend: flat.augmentation_backend,
      }),
      advanced: compactTrainingGroup({
        use_ema: flat.use_ema,
        multi_scale: flat.multi_scale,
        expanded_scales: flat.expanded_scales,
      }),
    }
    return result
  }

  const optimization = compactTrainingGroup({
    optimizer: flat.optimizer,
    learning_rate: flat.learning_rate,
    weight_decay: flat.weight_decay,
    min_lr_ratio: flat.min_lr_ratio,
    grad_clip_norm: flat.grad_clip_norm,
  })

  if (taskType === 'classification') {
    return {
      runtime,
      optimization,
      augmentation: compactTrainingGroup({
        enabled: augmentationEnabled,
        horizontal_flip_probability: flat.flip_prob,
        crop_mode: flat.crop_mode,
        crop_scale: flat.crop_scale_min === undefined || flat.crop_scale_max === undefined
          ? undefined
          : { minimum: flat.crop_scale_min, maximum: flat.crop_scale_max },
        auto_augment: flat.auto_augment,
        rotation_degrees: flat.rotation_degrees,
        translation_ratio: flat.translate_ratio,
        affine_scale: flat.scale_min === undefined || flat.scale_max === undefined
          ? undefined
          : { minimum: flat.scale_min, maximum: flat.scale_max },
        brightness_gain: flat.brightness_gain,
        contrast_gain: flat.contrast_gain,
        gamma: flat.gamma_min === undefined || flat.gamma_max === undefined
          ? undefined
          : { minimum: flat.gamma_min, maximum: flat.gamma_max },
        hue_gain: flat.hue_gain,
        saturation_gain: flat.saturation_gain,
        value_gain: flat.value_gain,
        random_erasing_probability: flat.random_erasing_prob,
      }),
    }
  }

  const evaluation = compactTrainingGroup({
    confidence_threshold: flat.evaluation_confidence_threshold,
    nms_threshold: supportsNmsThreshold
      ? flat.evaluation_nms_threshold
      : undefined,
  })

  if (taskType === 'obb') {
    return {
      runtime,
      optimization,
      evaluation,
      augmentation: buildYoloTaskAugmentationParameters(flat, augmentationEnabled),
    }
  }

  const loss = compactTrainingGroup({
    class_weight: flat.class_loss_weight,
    box_weight: flat.box_loss_weight,
    dfl_weight: normalizedModelType === 'yolo26' ? undefined : flat.dfl_loss_weight,
    l1_weight: normalizedModelType === 'yolo26' ? flat.l1_loss_weight : undefined,
    mask_weight: flat.mask_loss_weight,
    keypoint_weight: flat.kpt_loss_weight,
  })
  const matching = compactTrainingGroup({
    topk: flat.assign_topk,
    alpha: flat.assign_alpha,
    beta: flat.assign_beta,
  })
  return {
    runtime,
    optimization,
    loss,
    matching,
    evaluation,
    augmentation: buildYoloTaskAugmentationParameters(flat, augmentationEnabled),
  }
}

export function validateTrainingModelLayerValues(
  taskType: ModelTaskType,
  modelType: string | null | undefined,
  values: TrainingParameterValues,
  options: {
    augmentationEnabled?: boolean
    parameterSchema?: TrainingParameterSchemaItem | null
  } = {},
): string | null {
  const normalizedModelType = normalizeModelType(modelType)
  if (!normalizedModelType) {
    return null
  }

  for (const field of getModelLayerTrainingFields(
    taskType,
    normalizedModelType,
    options.parameterSchema,
  )) {
    if (
      options.augmentationEnabled === false
      && isTrainingAugmentationField(field)
    ) continue
    if (isTrainingModelParameterDisabled(field, values)) continue
    if (field.inputKind !== 'number') continue
    const rawValue = String(values[field.key] ?? '').trim()
    if (!rawValue) continue
    const numericValue = Number(rawValue)
    if (
      !Number.isFinite(numericValue)
      || (field.min !== undefined && numericValue < field.min)
      || (field.max !== undefined && numericValue > field.max)
    ) {
      return translate('modelOps.trainingParameters.parameterOutOfRange', {
        label: field.label,
        min: String(field.min ?? '-∞'),
        max: String(field.max ?? '+∞'),
      })
    }
    if (field.step !== undefined) {
      const quotient = numericValue / field.step
      const tolerance = Number.EPSILON * 32 * Math.max(1, Math.abs(quotient))
      if (Math.abs(quotient - Math.round(quotient)) > tolerance) {
        return translate('modelOps.trainingParameters.parameterStepMismatch', {
          label: field.label,
          step: String(field.step),
        })
      }
    }
  }

  const isYoloTask = ['detection', 'segmentation', 'pose', 'obb'].includes(taskType)
  if (
    isYoloTask
    && normalizedModelType === 'yolox'
    && options.augmentationEnabled !== false
  ) {
    const mixupRangeError = checkNumericRangeOrder(
      values,
      'mixup_scale',
      'mixup_scale_min',
      'mixup_scale_max',
    )
    if (mixupRangeError) return mixupRangeError
    return checkNumericRangeOrder(
      values,
      'mosaic_scale',
      'mosaic_scale_min',
      'mosaic_scale_max',
    )
  }

  if (
    taskType === 'classification'
    && ['yolov8', 'yolo11', 'yolo26'].includes(normalizedModelType)
    && options.augmentationEnabled !== false
  ) {
    const cropMode = String(values.crop_mode ?? '').trim()
    const autoAugment = String(values.auto_augment ?? '').trim()
    if (!['none', 'random_resized_crop'].includes(cropMode)) {
      return translate('modelOps.trainingParameters.invalidOption', {
        label: 'crop_mode',
      })
    }
    if (!['none', 'randaugment', 'autoaugment', 'augmix'].includes(autoAugment)) {
      return translate('modelOps.trainingParameters.invalidOption', {
        label: 'auto_augment',
      })
    }
    const cropRangeError = checkNumericRangeOrder(
      values,
      'crop_scale',
      'crop_scale_min',
      'crop_scale_max',
    )
    if (cropRangeError) return cropRangeError
    if (autoAugment === 'none') {
      return checkNumericRangeOrder(values, 'scale', 'scale_min', 'scale_max')
        ?? checkNumericRangeOrder(values, 'gamma', 'gamma_min', 'gamma_max')
    }
  }

  return null
}

function checkNumericRangeOrder(
  values: TrainingParameterValues,
  label: string,
  minKey: string,
  maxKey: string,
): string | null {
  const minimumRaw = String(values[minKey] ?? '').trim()
  const maximumRaw = String(values[maxKey] ?? '').trim()
  if (!minimumRaw && !maximumRaw) return null
  if (!minimumRaw || !maximumRaw) {
    return translate('modelOps.trainingParameters.rangePairRequired', { label })
  }
  const minimum = Number(minimumRaw)
  const maximum = Number(maximumRaw)
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
    return translate('modelOps.trainingParameters.rangePairRequired', { label })
  }
  if (minimum > maximum) {
    return translate('modelOps.trainingParameters.rangeOrderInvalid', { label })
  }
  return null
}

export function isTrainingAugmentationParameterDisabled(
  field: TrainingParameterField,
  values: TrainingParameterValues,
  augmentationEnabled: boolean,
): boolean {
  if (!augmentationEnabled) return true
  if (
    classificationCropScaleKeys.has(field.key)
    && String(values.crop_mode ?? '') !== 'random_resized_crop'
  ) {
    return true
  }
  return classificationManualAugmentationKeys.has(field.key)
    && String(values.auto_augment ?? '') !== 'none'
}

export function isTrainingModelParameterDisabled(
  field: TrainingParameterField,
  values: TrainingParameterValues,
): boolean {
  if (field.key === 'learning_rate') {
    return String(values.optimizer ?? '').trim().toLowerCase() === 'auto'
  }
  if (field.key === 'min_lr_ratio' && 'lr_scheduler' in values) {
    return String(values.lr_scheduler ?? 'step').trim().toLowerCase() !== 'cosine'
  }
  return false
}
