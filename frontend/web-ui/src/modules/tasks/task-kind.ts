import { translate } from '@/platform/i18n'

const EXACT_TASK_KEYS = new Set([
  'dataset-import',
  'dataset-export',
  'dataset-workspace',
  'dataset-quality',
  'dataset-quality-check',
  'dataset-derive',
  'dataset-version-derive',
  'dataset-compare',
  'dataset-annotation-merge',
  'dataset-sample-update',
  'model-package-import',
  'model-package-export',
  'deployment-import',
  'deployment-export',
  'resource-deletion',
  'resource-cleanup',
  'batch-inference',
  'yolo-model-conversion',
])

const TASK_KEYS: Record<string, string> = {
  detection: 'detection',
  classification: 'classification',
  segmentation: 'segmentation',
  'semantic-segmentation': 'semantic',
  semantic: 'semantic',
  pose: 'pose',
  obb: 'obb',
  anomaly: 'anomaly',
}

const FAMILY_LABELS: Record<string, string> = {
  yolox: 'YOLOX',
  yolov8: 'YOLOv8',
  yolo11: 'YOLO11',
  yolo26: 'YOLO26',
  yolo: 'YOLO',
  rfdetr: 'RF-DETR',
}

const ACTION_KEYS = new Set(['training', 'conversion', 'evaluation', 'inference'])

export type Translator = (key: string, params?: Record<string, string | number>) => string

export function formatTaskKind(kind: string | null | undefined, t: Translator = translate): string {
  const raw = typeof kind === 'string' ? kind.trim() : ''
  if (!raw) return '-'

  if (EXACT_TASK_KEYS.has(raw)) {
    return t(`taskKinds.exact.${raw}`)
  }

  const parts = raw.split('-').filter(Boolean)
  if (parts.length >= 2) {
    const actionKey = parts[parts.length - 1]!
    if (ACTION_KEYS.has(actionKey)) {
      const rest = parts.slice(0, -1)
      let family: string | undefined
      let taskKey: string | undefined

      if (rest.length === 1) {
        const token = rest[0]!
        if (FAMILY_LABELS[token]) family = FAMILY_LABELS[token]
        else taskKey = TASK_KEYS[token]
      } else {
        const first = rest[0]!
        const tail = rest.slice(1).join('-')
        if (FAMILY_LABELS[first]) {
          family = FAMILY_LABELS[first]
          taskKey = TASK_KEYS[tail]
        } else {
          taskKey = TASK_KEYS[rest.join('-')]
        }
      }

      const action = t(`taskKinds.actions.${actionKey}`)
      if (taskKey && family) {
        return t('taskKinds.patterns.taskActionFamily', {
          task: t(`taskKinds.tasks.${taskKey}`),
          action,
          family,
        })
      }
      if (taskKey) {
        return t('taskKinds.patterns.taskAction', {
          task: t(`taskKinds.tasks.${taskKey}`),
          action,
        })
      }
      if (family) {
        return t('taskKinds.patterns.familyAction', {
          family,
          action,
        })
      }
    }
  }

  return raw
}
