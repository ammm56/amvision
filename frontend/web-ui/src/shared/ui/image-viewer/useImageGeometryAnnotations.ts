import { computed, type ComputedRef, type Ref } from 'vue'

export interface GeometryCircle {
  centerX: number
  centerY: number
  radius: number
}

export interface GeometryOverlay {
  kind: string
  id: string | null
  bboxXyxy: [number, number, number, number] | null
  circle: GeometryCircle | null
}

export interface RoiScreenAnnotation {
  key: string
  boxX: number
  boxY: number
  boxWidth: number
  boxHeight: number
  title: string
  detail: string
}

export interface CircleScreenAnnotation extends RoiScreenAnnotation {
  kind: 'reference' | 'selected' | 'detected' | 'draft'
  centerX: number
  centerY: number
  rimX: number
  rimY: number
  leaderPoints: string
  tickX1: number
  tickY1: number
  tickX2: number
  tickY2: number
  positionText: string
  sizeText: string
}

interface ImageGeometryAnnotationsOptions {
  overlays: ComputedRef<GeometryOverlay[]>
  draftBboxXyxy: ComputedRef<[number, number, number, number] | null>
  draftCircle: ComputedRef<GeometryCircle | null>
  interactionTool: ComputedRef<string>
  viewportWidth: Ref<number>
  viewportHeight: Ref<number>
  reservedRightPx: ComputedRef<number>
  sourceToViewport: (sourceX: number, sourceY: number) => { x: number; y: number }
  translate: (key: string) => string
}

/**
 * 将原图几何坐标转换成独立的屏幕标注。
 *
 * CAD 尺寸框不进入随图缩放的 SVG，避免低倍率下使用反向 scale 放大标注，
 * 也避免浏览器为超大 SVG 绘制边界错误分块。
 */
export function useImageGeometryAnnotations(options: ImageGeometryAnnotationsOptions) {
  const roiAnnotations = computed<RoiScreenAnnotation[]>(() => {
    const searchOverlay = options.overlays.value.find(
      (overlay) => overlay.kind === 'search-roi' && overlay.bboxXyxy,
    )
    const bbox = options.draftBboxXyxy.value && options.interactionTool.value === 'rect'
      ? options.draftBboxXyxy.value
      : searchOverlay?.bboxXyxy
    if (!bbox) return []
    return [buildRoiAnnotation(bbox)]
  })

  const circleAnnotations = computed<CircleScreenAnnotation[]>(() => {
    const referenceOverlays = options.overlays.value.filter(
      (overlay) => overlay.kind === 'reference-circle' && overlay.circle,
    )
    const selectedOverlays = options.overlays.value.filter(
      (overlay) => overlay.kind === 'selected-circle' && overlay.circle,
    )
    const fallbackDetected = selectedOverlays.length === 0
      ? options.overlays.value.find((overlay) => overlay.kind === 'detected-circle' && overlay.circle)
      : null
    const candidates: Array<{
      key: string
      kind: CircleScreenAnnotation['kind']
      title: string
      circle: GeometryCircle
    }> = []
    referenceOverlays.forEach((overlay, index) => {
      if (!overlay.circle) return
      candidates.push({
        key: `reference-${overlay.id ?? index}`,
        kind: 'reference',
        title: options.translate('imageViewer.geometry.referenceCircle'),
        circle: overlay.circle,
      })
    })
    selectedOverlays.forEach((overlay, index) => {
      if (!overlay.circle) return
      const suffix = selectedOverlays.length > 1 ? ` ${index + 1}` : ''
      candidates.push({
        key: `selected-${overlay.id ?? index}`,
        kind: 'selected',
        title: `${options.translate('imageViewer.geometry.selectedCircle')}${suffix}`,
        circle: overlay.circle,
      })
    })
    if (fallbackDetected?.circle) {
      candidates.push({
        key: `detected-${fallbackDetected.id ?? 'first'}`,
        kind: 'detected',
        title: options.translate('imageViewer.geometry.detectedCircle'),
        circle: fallbackDetected.circle,
      })
    }
    if (options.draftCircle.value && options.interactionTool.value === 'circle') {
      candidates.push({
        key: 'draft-circle',
        kind: 'draft',
        title: options.translate('imageViewer.geometry.draftCircle'),
        circle: options.draftCircle.value,
      })
    }
    const occupiedBoxes = roiAnnotations.value.map((annotation) => ({
      x: annotation.boxX,
      y: annotation.boxY,
      width: annotation.boxWidth,
      height: annotation.boxHeight,
    }))
    return candidates.map((candidate, index) => {
      const annotation = buildCircleAnnotation(
        candidate.circle,
        candidate.key,
        candidate.kind,
        candidate.title,
        index,
        occupiedBoxes,
      )
      occupiedBoxes.push({
        x: annotation.boxX,
        y: annotation.boxY,
        width: annotation.boxWidth,
        height: annotation.boxHeight,
      })
      return annotation
    })
  })

  const layerViewBox = computed(() => (
    options.viewportWidth.value > 0 && options.viewportHeight.value > 0
      ? `0 0 ${options.viewportWidth.value} ${options.viewportHeight.value}`
      : ''
  ))

  function buildRoiAnnotation(bbox: [number, number, number, number]): RoiScreenAnnotation {
    const [x1, y1, x2, y2] = bbox
    const anchor = options.sourceToViewport(x1, y1)
    const boxWidth = 238
    const boxHeight = 42
    const inset = 7
    const visibleRight = readVisibleRight()
    return {
      key: 'search-roi-dimension',
      boxX: clampNumber(anchor.x + inset, inset, Math.max(inset, visibleRight - boxWidth - inset)),
      boxY: clampNumber(anchor.y + inset, inset, Math.max(inset, options.viewportHeight.value - boxHeight - inset)),
      boxWidth,
      boxHeight,
      title: options.translate('imageViewer.geometry.searchRoi'),
      detail: `X ${formatGeometryNumber(x1)} · Y ${formatGeometryNumber(y1)} · W ${formatGeometryNumber(Math.max(0, x2 - x1))} · H ${formatGeometryNumber(Math.max(0, y2 - y1))} px`,
    }
  }

  function buildCircleAnnotation(
    circle: GeometryCircle,
    key: string,
    kind: CircleScreenAnnotation['kind'],
    title: string,
    index: number,
    occupiedBoxes: ScreenBox[],
  ): CircleScreenAnnotation {
    const directions: Record<CircleScreenAnnotation['kind'], [number, number]> = {
      reference: [-1, -1],
      selected: [1, 1],
      detected: [1, -1],
      draft: [-1, 1],
    }
    let [directionX, directionY] = directions[kind]
    const center = options.sourceToViewport(circle.centerX, circle.centerY)
    const diagonal = Math.SQRT1_2
    const rim = options.sourceToViewport(
      circle.centerX + directionX * diagonal * circle.radius,
      circle.centerY + directionY * diagonal * circle.radius,
    )
    const boxWidth = 224
    const boxHeight = 61
    const inset = 6
    const gap = 7
    const visibleRight = readVisibleRight()
    if (directionX < 0 && rim.x - boxWidth - 31 < inset) directionX = 1
    if (directionX > 0 && rim.x + boxWidth + 31 > visibleRight - inset) directionX = -1
    if (directionY < 0 && rim.y - boxHeight - 31 < inset) directionY = 1
    if (directionY > 0 && rim.y + boxHeight + 31 > options.viewportHeight.value - inset) directionY = -1
    const adjustedRim = options.sourceToViewport(
      circle.centerX + directionX * diagonal * circle.radius,
      circle.centerY + directionY * diagonal * circle.radius,
    )
    const leaderLength = 24 + index * 7
    const elbowX = adjustedRim.x + directionX * leaderLength
    const elbowY = adjustedRim.y + directionY * leaderLength
    const preferredBoxX = directionX > 0 ? elbowX + gap : elbowX - gap - boxWidth
    const preferredBoxY = directionY > 0 ? elbowY : elbowY - boxHeight
    const placedBox = placeScreenBox(
      preferredBoxX,
      preferredBoxY,
      boxWidth,
      boxHeight,
      inset,
      visibleRight,
      options.viewportHeight.value,
      occupiedBoxes,
    )
    const boxX = placedBox.x
    const boxY = placedBox.y
    const boxEdgeX = boxX > elbowX ? boxX : boxX + boxWidth
    const boxEdgeY = clampNumber(elbowY, boxY + 8, boxY + boxHeight - 8)
    const radialX = directionX * diagonal
    const radialY = directionY * diagonal
    const perpendicularX = -radialY
    const perpendicularY = radialX
    return {
      key: `circle-dimension-${key}`,
      kind,
      centerX: center.x,
      centerY: center.y,
      rimX: adjustedRim.x,
      rimY: adjustedRim.y,
      leaderPoints: `${adjustedRim.x},${adjustedRim.y} ${elbowX},${elbowY} ${boxEdgeX},${boxEdgeY}`,
      tickX1: adjustedRim.x - perpendicularX * 5,
      tickY1: adjustedRim.y - perpendicularY * 5,
      tickX2: adjustedRim.x + perpendicularX * 5,
      tickY2: adjustedRim.y + perpendicularY * 5,
      boxX,
      boxY,
      boxWidth,
      boxHeight,
      title,
      detail: '',
      positionText: `X ${formatGeometryNumber(circle.centerX)} · Y ${formatGeometryNumber(circle.centerY)}`,
      sizeText: `R ${formatGeometryNumber(circle.radius)} px · Ø ${formatGeometryNumber(circle.radius * 2)} px`,
    }
  }

  function readVisibleRight(): number {
    const reservedRight = Math.min(
      Math.max(0, options.reservedRightPx.value),
      Math.max(0, options.viewportWidth.value - 1),
    )
    return Math.max(1, options.viewportWidth.value - reservedRight)
  }

  return { roiAnnotations, circleAnnotations, layerViewBox }
}

interface ScreenBox {
  x: number
  y: number
  width: number
  height: number
}

function placeScreenBox(
  preferredX: number,
  preferredY: number,
  width: number,
  height: number,
  inset: number,
  visibleRight: number,
  viewportHeight: number,
  occupiedBoxes: ScreenBox[],
): ScreenBox {
  const maxX = Math.max(inset, visibleRight - width - inset)
  const maxY = Math.max(inset, viewportHeight - height - inset)
  const candidates: ScreenBox[] = [
    { x: clampNumber(preferredX, inset, maxX), y: clampNumber(preferredY, inset, maxY), width, height },
  ]
  for (const occupied of occupiedBoxes) {
    candidates.push(
      { x: clampNumber(preferredX, inset, maxX), y: clampNumber(occupied.y + occupied.height + 6, inset, maxY), width, height },
      { x: clampNumber(preferredX, inset, maxX), y: clampNumber(occupied.y - height - 6, inset, maxY), width, height },
      { x: clampNumber(occupied.x + occupied.width + 6, inset, maxX), y: clampNumber(preferredY, inset, maxY), width, height },
      { x: clampNumber(occupied.x - width - 6, inset, maxX), y: clampNumber(preferredY, inset, maxY), width, height },
    )
  }
  return candidates.reduce((best, candidate) => (
    readPlacementScore(candidate, preferredX, preferredY, occupiedBoxes)
      < readPlacementScore(best, preferredX, preferredY, occupiedBoxes)
      ? candidate
      : best
  ))
}

function readPlacementScore(box: ScreenBox, preferredX: number, preferredY: number, occupiedBoxes: ScreenBox[]): number {
  const overlapArea = occupiedBoxes.reduce((total, occupied) => total + readOverlapArea(box, occupied), 0)
  return overlapArea * 1000 + Math.hypot(box.x - preferredX, box.y - preferredY)
}

function readOverlapArea(left: ScreenBox, right: ScreenBox): number {
  const width = Math.max(0, Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x))
  const height = Math.max(0, Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y))
  return width * height
}

function formatGeometryNumber(value: number): string {
  if (!Number.isFinite(value)) return '-'
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.00$/, '')
}

function clampNumber(value: number, minValue: number, maxValue: number): number {
  return Math.min(maxValue, Math.max(minValue, value))
}
