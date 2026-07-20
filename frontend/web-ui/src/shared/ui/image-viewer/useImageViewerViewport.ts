import { computed, onUnmounted, ref, watch, type ComputedRef, type Ref } from 'vue'

interface ImageViewerViewportOptions {
  viewportRef: Ref<HTMLElement | null>
  imageWidth: ComputedRef<number>
  imageHeight: ComputedRef<number>
  reservedRightPx?: ComputedRef<number>
}

interface ViewportPoint {
  x: number
  y: number
}

const MIN_SCALE = 0.05
const MAX_SCALE = 8

/**
 * 管理 ImageViewer 的缩放和平移。
 *
 * 原图坐标、视口坐标和 CSS transform 只在这里换算，避免交互工具与标注组件
 * 分别维护一套缩放公式后产生漂移。
 */
export function useImageViewerViewport(options: ImageViewerViewportOptions) {
  const scale = ref(1)
  const offsetX = ref(0)
  const offsetY = ref(0)
  const viewportWidth = ref(0)
  const viewportHeight = ref(0)
  const panState = ref<{ startX: number; startY: number; offsetX: number; offsetY: number } | null>(null)
  let resizeObserver: ResizeObserver | null = null

  const imageFrameStyle = computed(() => ({
    width: `${options.imageWidth.value}px`,
    height: `${options.imageHeight.value}px`,
    transform: `translate(-50%, -50%) translate(${offsetX.value}px, ${offsetY.value}px) scale(${scale.value})`,
  }))

  const imageElementStyle = computed(() => ({
    width: `${options.imageWidth.value}px`,
    height: `${options.imageHeight.value}px`,
  }))

  watch(options.viewportRef, (viewport, previousViewport) => {
    if (previousViewport) resizeObserver?.unobserve(previousViewport)
    if (!viewport) return
    updateViewportSize()
    resizeObserver ??= new ResizeObserver(updateViewportSize)
    resizeObserver.observe(viewport)
  }, { immediate: true })

  function updateViewportSize(): void {
    const viewport = options.viewportRef.value
    if (!viewport) return
    const bounds = viewport.getBoundingClientRect()
    viewportWidth.value = Math.max(0, bounds.width)
    viewportHeight.value = Math.max(0, bounds.height)
  }

  function fitImage(): void {
    updateViewportSize()
    const sourceWidth = options.imageWidth.value
    const sourceHeight = options.imageHeight.value
    if (sourceWidth <= 0 || sourceHeight <= 0 || viewportWidth.value <= 0 || viewportHeight.value <= 0) return
    const reservedRight = readReservedRight()
    const availableWidth = Math.max(1, viewportWidth.value - reservedRight)
    scale.value = clampScale(Math.min(availableWidth / sourceWidth, viewportHeight.value / sourceHeight, 1))
    offsetX.value = -reservedRight / 2
    offsetY.value = 0
  }

  function showOriginalSize(): void {
    scale.value = 1
    offsetX.value = -readReservedRight() / 2
    offsetY.value = 0
  }

  function resetView(): void {
    scale.value = 1
    offsetX.value = 0
    offsetY.value = 0
    stopPan()
  }

  function zoomIn(): void {
    zoomAtViewportCenter(1.25)
  }

  function zoomOut(): void {
    zoomAtViewportCenter(1 / 1.25)
  }

  function handleWheel(event: WheelEvent): void {
    const viewport = options.viewportRef.value
    if (!viewport) return
    const bounds = viewport.getBoundingClientRect()
    zoomAtViewportPoint(
      event.clientX - bounds.left,
      event.clientY - bounds.top,
      event.deltaY < 0 ? 1.12 : 1 / 1.12,
    )
  }

  function zoomAtViewportCenter(factor: number): void {
    updateViewportSize()
    const reservedRight = readReservedRight()
    zoomAtViewportPoint(
      Math.max(0, viewportWidth.value - reservedRight) / 2,
      viewportHeight.value / 2,
      factor,
    )
  }

  function zoomAtViewportPoint(viewportX: number, viewportY: number, factor: number): void {
    const oldScale = scale.value
    const nextScale = clampScale(oldScale * factor)
    if (nextScale === oldScale) return
    const centerX = viewportWidth.value / 2
    const centerY = viewportHeight.value / 2
    const pointerX = viewportX - centerX
    const pointerY = viewportY - centerY
    const scaleRatio = nextScale / oldScale
    offsetX.value = calculateAnchoredOffset(pointerX, offsetX.value, scaleRatio)
    offsetY.value = calculateAnchoredOffset(pointerY, offsetY.value, scaleRatio)
    scale.value = nextScale
  }

  function sourceToViewport(sourceX: number, sourceY: number): ViewportPoint {
    return {
      x: viewportWidth.value / 2 + offsetX.value + (sourceX - options.imageWidth.value / 2) * scale.value,
      y: viewportHeight.value / 2 + offsetY.value + (sourceY - options.imageHeight.value / 2) * scale.value,
    }
  }

  function startPan(event: MouseEvent): void {
    if (event.button !== 0) return
    panState.value = {
      startX: event.clientX,
      startY: event.clientY,
      offsetX: offsetX.value,
      offsetY: offsetY.value,
    }
    document.addEventListener('mousemove', movePan)
    document.addEventListener('mouseup', stopPan)
  }

  function movePan(event: MouseEvent): void {
    const pan = panState.value
    if (!pan) return
    offsetX.value = pan.offsetX + event.clientX - pan.startX
    offsetY.value = pan.offsetY + event.clientY - pan.startY
  }

  function stopPan(): void {
    panState.value = null
    document.removeEventListener('mousemove', movePan)
    document.removeEventListener('mouseup', stopPan)
  }

  function readReservedRight(): number {
    const requested = options.reservedRightPx?.value ?? 0
    return Math.min(Math.max(0, requested), Math.max(0, viewportWidth.value - 1))
  }

  onUnmounted(() => {
    stopPan()
    resizeObserver?.disconnect()
    resizeObserver = null
  })

  return {
    scale,
    offsetX,
    offsetY,
    viewportWidth,
    viewportHeight,
    imageFrameStyle,
    imageElementStyle,
    fitImage,
    showOriginalSize,
    resetView,
    zoomIn,
    zoomOut,
    handleWheel,
    sourceToViewport,
    startPan,
    stopPan,
  }
}

function clampScale(value: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value))
}

/** 根据缩放锚点更新单轴偏移，保持锚点下的原图坐标不变。 */
export function calculateAnchoredOffset(pointer: number, offset: number, scaleRatio: number): number {
  return pointer - (pointer - offset) * scaleRatio
}
