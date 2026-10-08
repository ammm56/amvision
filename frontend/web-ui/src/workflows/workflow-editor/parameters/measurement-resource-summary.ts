import { formatResultValue } from '@/shared/ui/image-viewer/result-geometry'

type Translate = (key: string, values?: Record<string, string | number>) => string

/** 摘要只陈述已保存的证据；数值为零不代表存在验证点或完成实物验收。 */
export function calibrationSummary(calibration: Record<string, unknown>, t: Translate): string[][] {
  const unit = calibration.unit === 'millimeter' ? 'mm' : calibration.unit === 'meter' ? 'm' : String(calibration.unit)
  const evidence = calibration.evidence as Record<string, unknown> | null | undefined
  const controlCount = Array.isArray(evidence?.control_points) ? evidence.control_points.length : 0
  const validationCount = Array.isArray(evidence?.validation_points) ? evidence.validation_points.length : 0
  const polygon = Array.isArray(calibration.valid_polygon) ? calibration.valid_polygon : []
  return [
    [t('spec'), `${calibration.image_width} × ${calibration.image_height} px`],
    [t('plane'), String(calibration.plane_id)],
    [t('unit'), unit],
    [t('domain'), t('vertices', { count: polygon.length })],
    [t('fit'), controlCount >= 3 ? `${formatResultValue(calibration.fit_rms)} ${unit} · ${t('points', { count: controlCount })}` : t('noFit')],
    [t('error'), validationCount >= 2 ? `${formatResultValue(calibration.validation_max_error)} ${unit} · ${t('points', { count: validationCount })}` : t('noValidation')],
  ]
}

export const calibrationSummaryMessages = {
  'zh-CN': {
    spec: '原图规格', plane: '平面', unit: '单位', domain: '有效域', vertices: '{count} 个顶点',
    fit: '拟合 RMS', error: '独立验证最大误差', points: '{count} 个点',
    noFit: '未提供拟合点数据', noValidation: '未提供独立验证数据',
    evidenceHelp: '点集和误差用于核对该资源，不等同于实物计量验收。',
  },
  'en-US': {
    spec: 'Image size', plane: 'Plane', unit: 'Unit', domain: 'Valid domain', vertices: '{count} vertices',
    fit: 'Fit RMS', error: 'Independent maximum error', points: '{count} points',
    noFit: 'No fitting point data', noValidation: 'No independent validation data',
    evidenceHelp: 'Points and errors describe this resource; they do not establish physical metrology acceptance.',
  },
}
