import type { ModelTaskType } from '@/modules/deployments/services/deployment.service'
import type {
  ClassificationInferenceCategory,
  ClassificationInferencePayload,
  DetectionInferencePayload,
  ObbInferencePayload,
  PoseInferenceKeypoint,
  PoseInferencePayload,
  SegmentationInferencePayload,
  TaskInferencePayload,
} from '../services/inference.service'

export type CanvasViewMode = 'overlay' | 'original' | 'compare'

export interface InferenceLayerVisibility {
  boxes: boolean
  masks: boolean
  keypoints: boolean
  skeleton: boolean
  labels: boolean
}

export interface OverlayFilterOptions {
  minDisplayScore: number
  selectedClasses: string[]
  isolateItemId?: string | null
}

export interface OverlayRenderItem {
  id: string
  index: number
  taskType: ModelTaskType
  classId: number
  className: string
  score: number
  color: string
  bboxXyxy: [number, number, number, number] | null
  obbPolygon: [number, number][] | null
  obbXywhr: [number, number, number, number, number] | null
  angle: number | null
  segments: [number, number][][] | null
  maskArea: number | null
  keypoints: PoseInferenceKeypoint[] | null
  keypointThreshold: number
  logit: number | null
  raw: unknown
}

export interface ClassFrequencySummary {
  className: string
  color: string
  count: number
}

export const COCO_POSE_SKELETON_EDGES: ReadonlyArray<readonly [number, number]> = [
  [0, 1],
  [0, 2],
  [1, 3],
  [2, 4],
  [5, 6],
  [5, 7],
  [7, 9],
  [6, 8],
  [8, 10],
  [5, 11],
  [6, 12],
  [11, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
]

const CLASS_COLOR_PALETTE = [
  '#1d6ef2',
  '#f97316',
  '#00d992',
  '#8b5cf6',
  '#0ea5e9',
  '#ec4899',
  '#ef4444',
  '#84cc16',
  '#14b8a6',
  '#f59e0b',
] as const

export function getClassColor(classId: number): string {
  const safeIndex = Math.abs(Math.trunc(classId)) % CLASS_COLOR_PALETTE.length
  return CLASS_COLOR_PALETTE[safeIndex]
}

export function resolveClassLabel(classId: number, className?: string | null, labels?: string[]): string {
  const trimmed = typeof className === 'string' ? className.trim() : ''
  if (trimmed) return trimmed
  const mapped = Array.isArray(labels) ? labels[classId] : undefined
  if (typeof mapped === 'string' && mapped.trim()) return mapped.trim()
  return `#${classId}`
}

export function computeObbCorners(bboxXywhr: [number, number, number, number, number]): [number, number][] {
  const [cx, cy, w, h, rawAngle] = bboxXywhr
  const rad = Math.abs(rawAngle) > Math.PI * 2 ? (rawAngle * Math.PI) / 180 : rawAngle
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  const hw = w / 2
  const hh = h / 2
  const corners: [number, number][] = [
    [-hw, -hh],
    [hw, -hh],
    [hw, hh],
    [-hw, hh],
  ]
  return corners.map(([dx, dy]) => [
    Number((cx + dx * cos - dy * sin).toFixed(2)),
    Number((cy + dx * sin + dy * cos).toFixed(2)),
  ])
}

export function formatXywh(bboxXyxy: [number, number, number, number]): { x: number; y: number; w: number; h: number } {
  const [x1, y1, x2, y2] = bboxXyxy
  return {
    x: Math.round(x1),
    y: Math.round(y1),
    w: Math.max(0, Math.round(x2 - x1)),
    h: Math.max(0, Math.round(y2 - y1)),
  }
}

export function formatObbAngleDeg(item: OverlayRenderItem): number | null {
  const rawAngle =
    typeof item.angle === 'number'
      ? item.angle
      : item.obbXywhr && Number.isFinite(item.obbXywhr[4])
        ? item.obbXywhr[4]
        : null
  if (rawAngle === null || !Number.isFinite(rawAngle)) return null
  if (Math.abs(rawAngle) <= Math.PI * 2 + 0.001) {
    return (rawAngle * 180) / Math.PI
  }
  return rawAngle
}

export function normalizeInferenceOverlayItems(
  taskType: ModelTaskType,
  payload: TaskInferencePayload | Record<string, unknown> | null | undefined,
): OverlayRenderItem[] {
  if (!payload || typeof payload !== 'object') return []
  const labels = Array.isArray((payload as TaskInferencePayload).labels)
    ? (payload as TaskInferencePayload).labels
    : []

  if (taskType === 'detection') {
    const dets = Array.isArray((payload as DetectionInferencePayload).detections)
      ? (payload as DetectionInferencePayload).detections
      : []
    return dets.map((item, idx) => ({
      id: `det-${idx}`,
      index: idx + 1,
      taskType,
      classId: item.class_id,
      className: resolveClassLabel(item.class_id, item.class_name, labels),
      score: item.score,
      color: getClassColor(item.class_id),
      bboxXyxy: item.bbox_xyxy,
      obbPolygon: null,
      obbXywhr: null,
      angle: null,
      segments: null,
      maskArea: null,
      keypoints: null,
      keypointThreshold: 0,
      logit: null,
      raw: item,
    }))
  }

  if (taskType === 'classification') {
    const cats = Array.isArray((payload as ClassificationInferencePayload).categories)
      ? (payload as ClassificationInferencePayload).categories
      : []
    return cats.map((cat: ClassificationInferenceCategory, idx) => ({
      id: `cls-${idx}`,
      index: idx + 1,
      taskType,
      classId: cat.class_id,
      className: resolveClassLabel(cat.class_id, cat.class_name, labels),
      score: cat.probability,
      color: getClassColor(cat.class_id),
      bboxXyxy: null,
      obbPolygon: null,
      obbXywhr: null,
      angle: null,
      segments: null,
      maskArea: null,
      keypoints: null,
      keypointThreshold: 0,
      logit: typeof cat.logit === 'number' ? cat.logit : null,
      raw: cat,
    }))
  }

  if (taskType === 'segmentation') {
    const instances = Array.isArray((payload as SegmentationInferencePayload).instances)
      ? (payload as SegmentationInferencePayload).instances
      : []
    return instances.map((inst, idx) => ({
      id: `seg-${idx}`,
      index: idx + 1,
      taskType,
      classId: inst.class_id,
      className: resolveClassLabel(inst.class_id, inst.class_name, labels),
      score: inst.score,
      color: getClassColor(inst.class_id),
      bboxXyxy: inst.bbox_xyxy,
      obbPolygon: null,
      obbXywhr: null,
      angle: null,
      segments: Array.isArray(inst.segments) ? inst.segments : [],
      maskArea: typeof inst.mask_area === 'number' ? inst.mask_area : null,
      keypoints: null,
      keypointThreshold: 0,
      logit: null,
      raw: inst,
    }))
  }

  if (taskType === 'pose') {
    const posePayload = payload as PoseInferencePayload
    const instances = Array.isArray(posePayload.instances) ? posePayload.instances : []
    const kpThreshold = Number(posePayload.keypoint_confidence_threshold ?? 0.3)
    return instances.map((inst, idx) => ({
      id: `pose-${idx}`,
      index: idx + 1,
      taskType,
      classId: inst.class_id,
      className: resolveClassLabel(inst.class_id, inst.class_name, labels),
      score: inst.score,
      color: getClassColor(inst.class_id),
      bboxXyxy: inst.bbox_xyxy,
      obbPolygon: null,
      obbXywhr: null,
      angle: null,
      segments: null,
      maskArea: null,
      keypoints: Array.isArray(inst.keypoints) ? inst.keypoints : [],
      keypointThreshold: Number.isFinite(kpThreshold) ? kpThreshold : 0.3,
      logit: null,
      raw: inst,
    }))
  }

  if (taskType === 'obb') {
    const obbPayload = payload as ObbInferencePayload
    const instances = Array.isArray(obbPayload.instances) ? obbPayload.instances : []
    return instances.map((inst, idx) => ({
      id: `obb-${idx}`,
      index: idx + 1,
      taskType,
      classId: inst.class_id,
      className: resolveClassLabel(inst.class_id, inst.class_name, labels),
      score: inst.score,
      color: getClassColor(inst.class_id),
      bboxXyxy: inst.bbox_xyxy,
      obbPolygon:
        Array.isArray(inst.bbox_xywhr) && inst.bbox_xywhr.length === 5
          ? computeObbCorners(inst.bbox_xywhr)
          : null,
      obbXywhr: Array.isArray(inst.bbox_xywhr) && inst.bbox_xywhr.length === 5 ? inst.bbox_xywhr : null,
      angle: typeof inst.angle === 'number' ? inst.angle : null,
      segments: null,
      maskArea: null,
      keypoints: null,
      keypointThreshold: 0,
      logit: null,
      raw: inst,
    }))
  }

  return []
}

export function filterOverlayItems(
  items: OverlayRenderItem[],
  filter: OverlayFilterOptions,
): OverlayRenderItem[] {
  const classSet = filter.selectedClasses.length > 0 ? new Set(filter.selectedClasses) : null
  const minScore = Number.isFinite(filter.minDisplayScore) ? filter.minDisplayScore : 0
  return items.filter((item) => {
    if (filter.isolateItemId && item.id !== filter.isolateItemId) return false
    if (item.score < minScore) return false
    if (classSet && !classSet.has(item.className)) return false
    return true
  })
}

export function summarizeOverlayClasses(items: OverlayRenderItem[]): ClassFrequencySummary[] {
  const counts = new Map<string, ClassFrequencySummary>()
  for (const item of items) {
    const existing = counts.get(item.className)
    if (existing) {
      existing.count += 1
    } else {
      counts.set(item.className, {
        className: item.className,
        color: item.color,
        count: 1,
      })
    }
  }
  return Array.from(counts.values())
}

export function pointsToSvgString(points: readonly [number, number][]): string {
  return points.map(([x, y]) => `${x},${y}`).join(' ')
}

export async function renderAnnotatedPreviewBlob(options: {
  imageSrc: string
  taskType: ModelTaskType
  items: OverlayRenderItem[]
  maskOpacity?: number
}): Promise<Blob> {
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const el = new Image()
    el.crossOrigin = 'anonymous'
    el.onload = () => resolve(el)
    el.onerror = () => reject(new Error('加载预览原图失败'))
    el.src = options.imageSrc
  })

  const w = Math.max(1, img.naturalWidth || img.width)
  const h = Math.max(1, img.naturalHeight || img.height)
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    throw new Error('当前环境不支持生成带标注预览图')
  }

  ctx.drawImage(img, 0, 0, w, h)
  const refSize = Math.max(w, h)
  const lineWidth = Math.max(2, refSize * 0.0028)
  const fontSize = Math.max(13, Math.round(refSize * 0.018))
  const padX = Math.max(6, Math.round(fontSize * 0.45))
  const tagH = Math.round(fontSize * 1.45)
  const alpha = Math.min(0.85, Math.max(0.1, options.maskOpacity ?? 0.35))

  for (const item of options.items) {
    if (options.taskType === 'segmentation' && item.segments) {
      for (const poly of item.segments) {
        if (poly.length < 2) continue
        ctx.save()
        ctx.beginPath()
        poly.forEach(([px, py], i) => (i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)))
        ctx.closePath()
        ctx.globalAlpha = alpha
        ctx.fillStyle = item.color
        ctx.fill()
        ctx.globalAlpha = 1
        ctx.strokeStyle = item.color
        ctx.lineWidth = lineWidth
        ctx.stroke()
        ctx.restore()
      }
    } else if (options.taskType === 'obb' && item.obbPolygon && item.obbPolygon.length >= 3) {
      ctx.save()
      ctx.beginPath()
      item.obbPolygon.forEach(([px, py], i) => (i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)))
      ctx.closePath()
      ctx.strokeStyle = item.color
      ctx.lineWidth = lineWidth
      ctx.stroke()
      ctx.restore()
    } else if (item.bboxXyxy) {
      const [x1, y1, x2, y2] = item.bboxXyxy
      ctx.save()
      ctx.strokeStyle = item.color
      ctx.lineWidth = lineWidth
      ctx.strokeRect(x1, y1, Math.max(1, x2 - x1), Math.max(1, y2 - y1))
      ctx.restore()
    }

    if (options.taskType === 'pose' && item.keypoints) {
      for (const [s, e] of COCO_POSE_SKELETON_EDGES) {
        const a = item.keypoints[s]
        const b = item.keypoints[e]
        if (!a || !b) continue
        if ((a.confidence ?? 1) < item.keypointThreshold || (b.confidence ?? 1) < item.keypointThreshold) continue
        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        ctx.lineTo(b.x, b.y)
        ctx.strokeStyle = '#00d992'
        ctx.lineWidth = lineWidth
        ctx.stroke()
      }
      for (const kp of item.keypoints) {
        if ((kp.confidence ?? 1) < item.keypointThreshold) continue
        ctx.beginPath()
        ctx.arc(kp.x, kp.y, Math.max(3, refSize * 0.005), 0, Math.PI * 2)
        ctx.fillStyle = '#00d992'
        ctx.fill()
        ctx.strokeStyle = '#ffffff'
        ctx.lineWidth = Math.max(1.5, lineWidth * 0.5)
        ctx.stroke()
      }
    }

    const anchor =
      item.obbPolygon && item.obbPolygon.length > 0
        ? item.obbPolygon.reduce((top, pt) => (pt[1] < top[1] ? pt : top), item.obbPolygon[0])
        : item.bboxXyxy
          ? [item.bboxXyxy[0], item.bboxXyxy[1]]
          : null

    if (anchor) {
      const label = `${item.index}  ${item.className}  ${item.score.toFixed(2)}`
      ctx.save()
      ctx.font = `600 ${fontSize}px sans-serif`
      const textW = ctx.measureText(label).width
      const boxW = textW + padX * 2
      const boxY = Math.max(tagH, anchor[1]) - tagH
      ctx.fillStyle = item.color
      ctx.fillRect(anchor[0], boxY, boxW, tagH)
      ctx.fillStyle = '#ffffff'
      ctx.textBaseline = 'middle'
      ctx.fillText(label, anchor[0] + padX, boxY + tagH / 2)
      ctx.restore()
    }
  }

  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new Error('导出预览图像失败'))
    }, 'image/png')
  })
}
