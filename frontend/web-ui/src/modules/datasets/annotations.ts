import { loadCanvasFont, workbenchFontFamily } from '@/shared/ui/canvas-font'
import type {
  DatasetAnnotation,
  DatasetSample,
} from './services/dataset-workspace.service'

/** 类别着色独立于主题与选择状态，在缩略图和大图中保持一致。 */
export const annotationColor = (id: number | null) =>
  ['#2485ed', '#f39a29', '#b163dc', '#e65b83', '#16a6a3', '#8caa34'][
    Math.abs(id ?? 0) % 6
  ]

/** 仅供缩略图取景，不改变原始标注；无几何标签保留整张图。 */
export function annotationBounds(annotation: DatasetAnnotation): number[] | null {
  const box = annotation.bbox_xywh
  if (box?.length === 4 && box.every(Number.isFinite) && box[2] > 0 && box[3] > 0) return box
  let values = annotation.polygon_xy || []
  if (!values.length && Array.isArray(annotation.segmentation)) values = annotation.segmentation.flat()
  if (!values.length && annotation.keypoints) {
    values = annotation.keypoints.flatMap((value, index, points) => index % 3 === 0 && points[index + 2] > 0 ? [value, points[index + 1]] : [])
  }
  if (values.length < 4 || values.length % 2 || !values.every(Number.isFinite)) return null
  let x = Infinity, y = Infinity, right = -Infinity, bottom = -Infinity
  for (let index = 0; index < values.length; index += 2) {
    x = Math.min(x, values[index]); y = Math.min(y, values[index + 1])
    right = Math.max(right, values[index]); bottom = Math.max(bottom, values[index + 1])
  }
  const width = right - x, height = bottom - y
  return width > 0 && height > 0 ? [x, y, width, height] : null
}
export function annotationPoints(
  annotation: DatasetAnnotation,
): [number, number][] {
  const values = annotation.polygon_xy
  if (
    !values ||
    values.length < 6 ||
    values.length % 2 ||
    !values.every(Number.isFinite)
  )
    return []
  return Array.from({ length: values.length / 2 }, (_, i) => [
    values[i * 2],
    values[i * 2 + 1],
  ])
}

/** 与后端 COCO 解码一致；仅解析游程，不分配原图尺寸的数组。 */
export function decodeMaskRuns(
  mask: Record<string, unknown>,
): { runs: number[]; width: number; height: number } | null {
  const size = mask.size
  if (
    !Array.isArray(size) ||
    size.length !== 2 ||
    !size.every((n) => Number.isSafeInteger(n) && n > 0)
  )
    return null
  const [height, width] = size as number[]
  if (!Number.isSafeInteger(height * width)) return null
  let runs: number[] = []
  if (Array.isArray(mask.counts)) runs = mask.counts
  else if (typeof mask.counts === 'string') {
    let position = 0
    while (position < mask.counts.length) {
      let value = 0,
        shift = 0,
        chunk = 0
      do {
        if (position >= mask.counts.length || shift > 45) return null
        chunk = mask.counts.charCodeAt(position++) - 48
        if (chunk < 0 || chunk > 63) return null
        value += (chunk & 31) * 2 ** shift
        shift += 5
      } while (chunk & 32)
      if (chunk & 16) value -= 2 ** shift
      if (runs.length > 2) value += runs[runs.length - 2]
      if (!Number.isSafeInteger(value) || value < 0) return null
      runs.push(value)
    }
  } else return null
  if (
    !runs.every((n) => Number.isSafeInteger(n) && n >= 0) ||
    runs.reduce((a, b) => a + b, 0) !== width * height
  )
    return null
  return { runs, width, height }
}

/** 绘制失败时返回对象数，让界面提示而不是冒充无目标。 */
export function paintAnnotations(
  ctx: CanvasRenderingContext2D,
  sample: DatasetSample,
  categories: Map<number, string>,
  width: number,
  height: number,
  selected?: string,
  labelScale = 1,
  poseSchemas: Record<string, unknown> = {},
): number {
  const sx = width / sample.width,
    sy = height / sample.height
  const font = `${12 * labelScale}px ${workbenchFontFamily()}`
  let classRow = 0,
    invalid = 0
  const ordered = [...sample.annotations].sort(
    (a, b) =>
      Number(a.annotation_id === selected) -
      Number(b.annotation_id === selected),
  )
  for (const item of ordered) {
    const color = annotationColor(item.category_id),
      name =
        categories.get(item.category_id ?? -1) || String(item.category_id ?? '')
    ctx.save()
    ctx.strokeStyle = color
    ctx.fillStyle = color
    ctx.lineWidth = (item.annotation_id === selected ? 3 : 1.6) * labelScale
    ctx.font = font
    let x = 8 * labelScale,
      y = (20 + classRow * 22) * labelScale
    if (item.annotation_type === 'classification') classRow++
    else if (item.annotation_type === 'obb') {
      const points = annotationPoints(item)
      if (!points.length) {
        invalid++
        ctx.restore()
        continue
      }
      ctx.beginPath()
      points.forEach(([px, py], i) =>
        i ? ctx.lineTo(px * sx, py * sy) : ctx.moveTo(px * sx, py * sy),
      )
      ctx.closePath()
      ctx.stroke()
      x = points[0][0] * sx
      y = points[0][1] * sy
    } else if (
      item.bbox_xywh?.length === 4 &&
      item.bbox_xywh.every(Number.isFinite)
    ) {
      const [bx, by, bw, bh] = item.bbox_xywh
      if (bw < 0 || bh < 0) {
        invalid++
        ctx.restore()
        continue
      }
      x = bx * sx
      y = by * sy
      ctx.strokeRect(x, y, bw * sx, bh * sy)
    } else if (item.annotation_type === 'detection' || item.bbox_xywh != null) {
      invalid++
      ctx.restore()
      continue
    }
    if (Array.isArray(item.segmentation)) {
      for (const polygon of item.segmentation) {
        if (
          !Array.isArray(polygon) ||
          polygon.length < 6 ||
          polygon.length % 2 ||
          !polygon.every(Number.isFinite)
        ) {
          invalid++
          continue
        }
        ctx.beginPath()
        for (let i = 0; i < polygon.length; i += 2) {
          if (i) ctx.lineTo(polygon[i] * sx, polygon[i + 1] * sy)
          else ctx.moveTo(polygon[i] * sx, polygon[i + 1] * sy)
        }
        ctx.closePath()
        ctx.globalAlpha = 0.25
        ctx.fill()
        ctx.globalAlpha = 1
        ctx.stroke()
      }
    } else if (item.segmentation) {
      const mask = decodeMaskRuns(item.segmentation)
      if (!mask || mask.width !== sample.width || mask.height !== sample.height)
        invalid++
      else {
        let offset = 0
        ctx.globalAlpha = 0.3
        for (let i = 0; i < mask.runs.length; i++) {
          const end = offset + mask.runs[i]
          if (i % 2 && end > offset) {
            const col = Math.floor(offset / mask.height),
              row = offset % mask.height
            const lastCol = Math.floor((end - 1) / mask.height),
              lastRow = ((end - 1) % mask.height) + 1
            if (col === lastCol)
              ctx.fillRect(col * sx, row * sy, sx, (end - offset) * sy)
            else {
              ctx.fillRect(col * sx, row * sy, sx, (mask.height - row) * sy)
              if (lastCol > col + 1)
                ctx.fillRect(
                  (col + 1) * sx,
                  0,
                  (lastCol - col - 1) * sx,
                  height,
                )
              ctx.fillRect(lastCol * sx, 0, sx, lastRow * sy)
            }
          }
          offset = end
        }
        ctx.globalAlpha = 1
      }
    }
    if (item.keypoints) {
      const points = item.keypoints
      const schema = poseSchemas[String(item.category_id)] as
        { skeleton?: number[][] } | undefined
      const valid = (n: number) =>
        n >= 0 &&
        n * 3 + 2 < points.length &&
        points[n * 3 + 2] > 0 &&
        points.slice(n * 3, n * 3 + 3).every(Number.isFinite)
      for (const [from, to] of schema?.skeleton || []) {
        if (!valid(from - 1) || !valid(to - 1)) continue
        ctx.beginPath()
        ctx.moveTo(points[(from - 1) * 3] * sx, points[(from - 1) * 3 + 1] * sy)
        ctx.lineTo(points[(to - 1) * 3] * sx, points[(to - 1) * 3 + 1] * sy)
        ctx.stroke()
      }
      for (let i = 0; i < points.length; i += 3) {
        if (!valid(i / 3)) continue
        ctx.beginPath()
        ctx.arc(
          points[i] * sx,
          points[i + 1] * sy,
          3 * labelScale,
          0,
          Math.PI * 2,
        )
        if (points[i + 2] === 2) ctx.fill()
        else ctx.stroke()
      }
    }
    const labelWidth = ctx.measureText(name).width + 8 * labelScale
    const top = Math.max(0, y - 18 * labelScale),
      left = Math.max(0, Math.min(x, width - labelWidth))
    ctx.fillStyle = color
    ctx.fillRect(left, top, labelWidth, 18 * labelScale)
    ctx.fillStyle = '#ffffff'
    ctx.fillText(name, left + 4 * labelScale, top + 13 * labelScale)
    ctx.restore()
  }
  return invalid
}

/** 大图标注只在浏览器生成显示层，原始 Blob 和磁盘图像不改变。 */
export async function annotatedImage(
  blob: Blob,
  sample: DatasetSample,
  categories: Map<number, string>,
  poseSchemas: Record<string, unknown> = {},
  selected?: string,
) {
  const bitmap = await createImageBitmap(blob, { imageOrientation: 'none' })
  try {
    await loadCanvasFont([...categories.values()].join(''))
    const canvas = document.createElement('canvas')
    const scale = Math.min(1, 4096 / Math.max(bitmap.width, bitmap.height))
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    const ctx = canvas.getContext('2d')!
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const invalid = paintAnnotations(
      ctx,
      sample,
      categories,
      canvas.width,
      canvas.height,
      selected,
      Math.max(1, Math.max(canvas.width / 900, canvas.height / 650)),
      poseSchemas,
    )
    const result = await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (value) =>
          value ? resolve(value) : reject(new Error('标注预览生成失败')),
        'image/jpeg',
        0.94,
      ),
    )
    return { blob: result, width: canvas.width, height: canvas.height, invalid }
  } finally {
    bitmap.close()
  }
}
