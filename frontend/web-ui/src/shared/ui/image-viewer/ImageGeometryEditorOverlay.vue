<template>
  <g
    class="image-geometry-editor"
    :class="{ 'image-geometry-editor--editable': editable }"
  >
    <g
      v-for="(bbox, index) in bboxes"
      :key="`bbox-${index}`"
      class="image-geometry-editor__item"
      :class="{
        'image-geometry-editor__item--editable': isToolEditable('bbox'),
        'image-geometry-editor__item--selected': isSelected('bbox', index),
      }"
      @mouseenter="setHovered('bbox', index)"
      @mouseleave="clearHover('bbox', index)"
    >
      <rect
        class="image-geometry-editor__shape"
        :class="{
          'image-geometry-editor__shape--editable': isToolEditable('bbox'),
          'image-geometry-editor__shape--selected': isSelected('bbox', index),
        }"
        :x="bbox[0]"
        :y="bbox[1]"
        :width="bbox[2] - bbox[0]"
        :height="bbox[3] - bbox[1]"
        @mousedown.stop.prevent="beginMove('bbox', index, $event)"
      />
      <template v-if="isToolEditable('bbox')">
        <rect
          v-for="handle in resizeHandles"
          :key="handle"
          class="image-geometry-editor__handle"
          :class="`image-geometry-editor__handle--${handle}`"
          :x="readHandlePoint(bbox, handle)[0] - controlSize / 2"
          :y="readHandlePoint(bbox, handle)[1] - controlSize / 2"
          :width="controlSize"
          :height="controlSize"
          @mousedown.stop.prevent="beginResize('bbox', index, handle, $event)"
        />
        <g
          class="image-geometry-editor__delete"
          :transform="`translate(${readDeleteX(bbox[2])}, ${readDeleteY(bbox[1])})`"
          @mousedown.stop.prevent
          @click.stop.prevent="deleteBbox(index)"
        >
          <circle :r="controlSize" />
          <path :d="deletePath" />
        </g>
      </template>
    </g>

    <g
      v-for="(polygon, index) in polygons"
      :key="`polygon-${index}`"
      class="image-geometry-editor__item"
      :class="{
        'image-geometry-editor__item--editable': isToolEditable('polygon'),
        'image-geometry-editor__item--selected': isSelected('polygon', index),
      }"
      @mouseenter="setHovered('polygon', index)"
      @mouseleave="clearHover('polygon', index)"
    >
      <polygon
        class="image-geometry-editor__shape"
        :class="{
          'image-geometry-editor__shape--editable': isToolEditable('polygon'),
          'image-geometry-editor__shape--selected': isSelected('polygon', index),
        }"
        :points="readPolygonPoints(polygon)"
        @mousedown.stop.prevent="beginMove('polygon', index, $event)"
      />
      <template v-if="isToolEditable('polygon')">
        <circle
          v-for="(point, vertexIndex) in polygon"
          :key="`vertex-${vertexIndex}`"
          class="image-geometry-editor__vertex"
          :cx="point[0]"
          :cy="point[1]"
          :r="controlSize * 0.55"
          @mousedown.stop.prevent="beginVertexMove(index, vertexIndex, $event)"
        />
        <rect
          v-for="handle in resizeHandles"
          :key="handle"
          class="image-geometry-editor__handle"
          :class="`image-geometry-editor__handle--${handle}`"
          :x="readHandlePoint(readPolygonBbox(polygon), handle)[0] - controlSize / 2"
          :y="readHandlePoint(readPolygonBbox(polygon), handle)[1] - controlSize / 2"
          :width="controlSize"
          :height="controlSize"
          @mousedown.stop.prevent="beginResize('polygon', index, handle, $event)"
        />
        <g
          class="image-geometry-editor__delete"
          :transform="readPolygonDeleteTransform(polygon)"
          @mousedown.stop.prevent
          @click.stop.prevent="deletePolygon(index)"
        >
          <circle :r="controlSize" />
          <path :d="deletePath" />
        </g>
      </template>
    </g>

    <g
      v-for="(point, index) in positivePoints"
      :key="`positive-${index}`"
      class="image-geometry-editor__point-item"
      :class="{
        'image-geometry-editor__point-item--editable': isToolEditable('positive-point'),
        'image-geometry-editor__point-item--selected': isSelected('positive-point', index),
      }"
      @mouseenter="setHovered('positive-point', index)"
      @mouseleave="clearHover('positive-point', index)"
    >
      <circle
        class="image-geometry-editor__point image-geometry-editor__point--positive"
        :class="{ 'image-geometry-editor__point--editable': isToolEditable('positive-point') }"
        :cx="point[0]"
        :cy="point[1]"
        :r="controlSize * 0.65"
        @mousedown.stop.prevent="beginPointMove('positive-point', index, $event)"
      />
      <g
        v-if="isToolEditable('positive-point')"
        class="image-geometry-editor__delete"
        :transform="readPointDeleteTransform(point)"
        @mousedown.stop.prevent
        @click.stop.prevent="deletePoint('positive-point', index)"
      >
        <circle :r="controlSize" />
        <path :d="deletePath" />
      </g>
    </g>

    <g
      v-for="(point, index) in negativePoints"
      :key="`negative-${index}`"
      class="image-geometry-editor__point-item"
      :class="{
        'image-geometry-editor__point-item--editable': isToolEditable('negative-point'),
        'image-geometry-editor__point-item--selected': isSelected('negative-point', index),
      }"
      @mouseenter="setHovered('negative-point', index)"
      @mouseleave="clearHover('negative-point', index)"
    >
      <circle
        class="image-geometry-editor__point image-geometry-editor__point--negative"
        :class="{ 'image-geometry-editor__point--editable': isToolEditable('negative-point') }"
        :cx="point[0]"
        :cy="point[1]"
        :r="controlSize * 0.65"
        @mousedown.stop.prevent="beginPointMove('negative-point', index, $event)"
      />
      <g
        v-if="isToolEditable('negative-point')"
        class="image-geometry-editor__delete"
        :transform="readPointDeleteTransform(point)"
        @mousedown.stop.prevent
        @click.stop.prevent="deletePoint('negative-point', index)"
      >
        <circle :r="controlSize" />
        <path :d="deletePath" />
      </g>
    </g>
  </g>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import {
  moveBbox,
  movePoint,
  movePolygon,
  movePolygonVertex,
  readPolygonBounds,
  resizeBbox,
  resizePolygon,
  type GeometryResizeHandle,
  type ImageBboxTuple,
  type ImagePointTuple,
} from './geometryEditing'

type EditableKind = 'bbox' | 'polygon' | 'positive-point' | 'negative-point'

interface SelectedGeometry {
  kind: EditableKind
  index: number
}

interface DragState {
  kind: 'move' | 'resize' | 'vertex'
  targetKind: EditableKind
  index: number
  svg: SVGSVGElement
  startPoint: ImagePointTuple
  initialBbox?: ImageBboxTuple
  initialPolygon?: ImagePointTuple[]
  initialPoint?: ImagePointTuple
  handle?: GeometryResizeHandle
  vertexIndex?: number
  changed: boolean
}

const props = defineProps<{
  editable: boolean
  activeTool: string
  canvasWidth: number
  canvasHeight: number
  bboxes: ImageBboxTuple[]
  polygons: ImagePointTuple[][]
  positivePoints: ImagePointTuple[]
  negativePoints: ImagePointTuple[]
}>()

const emit = defineEmits<{
  'update:bboxes': [value: ImageBboxTuple[]]
  'update:polygons': [value: ImagePointTuple[][]]
  'update:positivePoints': [value: ImagePointTuple[]]
  'update:negativePoints': [value: ImagePointTuple[]]
  changed: []
}>()

const selected = ref<SelectedGeometry | null>(null)
const hovered = ref<SelectedGeometry | null>(null)
const dragState = ref<DragState | null>(null)
const resizeHandles: GeometryResizeHandle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']
const controlSize = computed(() => Math.max(4, Math.max(props.canvasWidth, props.canvasHeight) / 160))
const deletePath = computed(() => {
  const arm = controlSize.value * 0.38
  return `M ${-arm} ${-arm} L ${arm} ${arm} M ${arm} ${-arm} L ${-arm} ${arm}`
})

function isSelected(kind: EditableKind, index: number): boolean {
  return selected.value?.kind === kind && selected.value.index === index
}

function setHovered(kind: EditableKind, index: number): void {
  if (!isToolEditable(kind)) return
  hovered.value = { kind, index }
}

function clearHover(kind: EditableKind, index: number): void {
  if (hovered.value?.kind === kind && hovered.value.index === index) hovered.value = null
}

function readHandlePoint(bbox: ImageBboxTuple, handle: GeometryResizeHandle): ImagePointTuple {
  const [x1, y1, x2, y2] = bbox
  const centerX = (x1 + x2) / 2
  const centerY = (y1 + y2) / 2
  return [
    handle.includes('w') ? x1 : handle.includes('e') ? x2 : centerX,
    handle.includes('n') ? y1 : handle.includes('s') ? y2 : centerY,
  ]
}

function readPolygonBbox(points: ImagePointTuple[]): ImageBboxTuple {
  const bounds = readPolygonBounds(points)
  return [bounds.x1, bounds.y1, bounds.x2, bounds.y2]
}

function readPolygonPoints(points: ImagePointTuple[]): string {
  return points.map(([x, y]) => `${x},${y}`).join(' ')
}

function readDeleteX(x: number): number {
  return Math.min(props.canvasWidth - controlSize.value, x + controlSize.value * 1.2)
}

function readDeleteY(y: number): number {
  return Math.max(controlSize.value, y - controlSize.value * 1.2)
}

function readPolygonDeleteTransform(points: ImagePointTuple[]): string {
  const bounds = readPolygonBounds(points)
  return `translate(${readDeleteX(bounds.x2)}, ${readDeleteY(bounds.y1)})`
}

function readPointDeleteTransform(point: ImagePointTuple): string {
  return `translate(${readDeleteX(point[0] + controlSize.value * 0.8)}, ${readDeleteY(point[1] - controlSize.value * 0.8)})`
}

function beginMove(targetKind: 'bbox' | 'polygon', index: number, event: MouseEvent): void {
  if (!isToolEditable(targetKind)) return
  const context = readSvgContext(event)
  if (!context) return
  selected.value = { kind: targetKind, index }
  dragState.value = {
    kind: 'move',
    targetKind,
    index,
    svg: context.svg,
    startPoint: context.point,
    initialBbox: targetKind === 'bbox' ? [...props.bboxes[index]] : undefined,
    initialPolygon: targetKind === 'polygon' ? clonePolygon(props.polygons[index]) : undefined,
    changed: false,
  }
  startDragListeners()
}

function beginPointMove(
  targetKind: 'positive-point' | 'negative-point',
  index: number,
  event: MouseEvent,
): void {
  if (!isToolEditable(targetKind)) return
  const context = readSvgContext(event)
  if (!context) return
  const source = targetKind === 'positive-point' ? props.positivePoints : props.negativePoints
  selected.value = { kind: targetKind, index }
  dragState.value = {
    kind: 'move',
    targetKind,
    index,
    svg: context.svg,
    startPoint: context.point,
    initialPoint: [...source[index]],
    changed: false,
  }
  startDragListeners()
}

function beginResize(
  targetKind: 'bbox' | 'polygon',
  index: number,
  handle: GeometryResizeHandle,
  event: MouseEvent,
): void {
  if (!isToolEditable(targetKind)) return
  const context = readSvgContext(event)
  if (!context) return
  selected.value = { kind: targetKind, index }
  dragState.value = {
    kind: 'resize',
    targetKind,
    index,
    handle,
    svg: context.svg,
    startPoint: context.point,
    initialBbox: targetKind === 'bbox' ? [...props.bboxes[index]] : undefined,
    initialPolygon: targetKind === 'polygon' ? clonePolygon(props.polygons[index]) : undefined,
    changed: false,
  }
  startDragListeners()
}

function beginVertexMove(index: number, vertexIndex: number, event: MouseEvent): void {
  if (!isToolEditable('polygon')) return
  const context = readSvgContext(event)
  if (!context) return
  selected.value = { kind: 'polygon', index }
  dragState.value = {
    kind: 'vertex',
    targetKind: 'polygon',
    index,
    vertexIndex,
    svg: context.svg,
    startPoint: context.point,
    initialPolygon: clonePolygon(props.polygons[index]),
    changed: false,
  }
  startDragListeners()
}

function moveGeometry(event: MouseEvent): void {
  const drag = dragState.value
  if (!drag) return
  const point = readSvgPoint(event, drag.svg)
  if (!point) return
  drag.changed = drag.changed
    || Math.abs(point[0] - drag.startPoint[0]) > 0.01
    || Math.abs(point[1] - drag.startPoint[1]) > 0.01
  if (!drag.changed) return

  if (
    (drag.targetKind === 'positive-point' || drag.targetKind === 'negative-point')
    && drag.initialPoint
  ) {
    const source = drag.targetKind === 'positive-point' ? props.positivePoints : props.negativePoints
    const nextPoints = source.map(([x, y]) => [x, y] as ImagePointTuple)
    nextPoints[drag.index] = movePoint(
      drag.initialPoint,
      point[0] - drag.startPoint[0],
      point[1] - drag.startPoint[1],
      props.canvasWidth,
      props.canvasHeight,
    )
    if (drag.targetKind === 'positive-point') emit('update:positivePoints', nextPoints)
    else emit('update:negativePoints', nextPoints)
    return
  }

  if (drag.targetKind === 'bbox' && drag.initialBbox) {
    const nextBboxes = props.bboxes.map((bbox) => [...bbox] as ImageBboxTuple)
    nextBboxes[drag.index] = drag.kind === 'move'
      ? moveBbox(
          drag.initialBbox,
          point[0] - drag.startPoint[0],
          point[1] - drag.startPoint[1],
          props.canvasWidth,
          props.canvasHeight,
        )
      : resizeBbox(
          drag.initialBbox,
          drag.handle!,
          point,
          props.canvasWidth,
          props.canvasHeight,
        )
    emit('update:bboxes', nextBboxes)
    return
  }

  if (drag.targetKind !== 'polygon' || !drag.initialPolygon) return
  const nextPolygons = props.polygons.map(clonePolygon)
  if (drag.kind === 'move') {
    nextPolygons[drag.index] = movePolygon(
      drag.initialPolygon,
      point[0] - drag.startPoint[0],
      point[1] - drag.startPoint[1],
      props.canvasWidth,
      props.canvasHeight,
    )
  } else if (drag.kind === 'resize') {
    nextPolygons[drag.index] = resizePolygon(
      drag.initialPolygon,
      drag.handle!,
      point,
      props.canvasWidth,
      props.canvasHeight,
    )
  } else {
    nextPolygons[drag.index] = movePolygonVertex(
      drag.initialPolygon,
      drag.vertexIndex!,
      point,
      props.canvasWidth,
      props.canvasHeight,
    )
  }
  emit('update:polygons', nextPolygons)
}

function finishGeometryMove(): void {
  const changed = dragState.value?.changed === true
  dragState.value = null
  stopDragListeners()
  if (changed) emit('changed')
}

function deleteBbox(index: number): void {
  if (!isToolEditable('bbox')) return
  emit('update:bboxes', props.bboxes.filter((_, itemIndex) => itemIndex !== index))
  resetSelection()
  emit('changed')
}

function deletePolygon(index: number): void {
  if (!isToolEditable('polygon')) return
  emit('update:polygons', props.polygons.filter((_, itemIndex) => itemIndex !== index).map(clonePolygon))
  resetSelection()
  emit('changed')
}

function deletePoint(kind: 'positive-point' | 'negative-point', index: number): void {
  if (!isToolEditable(kind)) return
  const points = kind === 'positive-point' ? props.positivePoints : props.negativePoints
  const nextPoints = points.filter((_, itemIndex) => itemIndex !== index).map((point) => [...point] as ImagePointTuple)
  if (kind === 'positive-point') emit('update:positivePoints', nextPoints)
  else emit('update:negativePoints', nextPoints)
  resetSelection()
  emit('changed')
}

function isToolEditable(kind: EditableKind): boolean {
  return props.editable && props.activeTool === kind
}

function readSvgContext(event: MouseEvent): { svg: SVGSVGElement; point: ImagePointTuple } | null {
  const target = event.currentTarget
  const svg = target instanceof SVGSVGElement
    ? target
    : target instanceof SVGElement
      ? target.ownerSVGElement
      : null
  if (!svg) return null
  const point = readSvgPoint(event, svg)
  return point ? { svg, point } : null
}

function readSvgPoint(event: MouseEvent, svg: SVGSVGElement): ImagePointTuple | null {
  const matrix = svg.getScreenCTM()
  if (!matrix) return null
  const point = svg.createSVGPoint()
  point.x = event.clientX
  point.y = event.clientY
  const transformed = point.matrixTransform(matrix.inverse())
  return [transformed.x, transformed.y]
}

function startDragListeners(): void {
  stopDragListeners()
  document.addEventListener('mousemove', moveGeometry)
  document.addEventListener('mouseup', finishGeometryMove)
}

function stopDragListeners(): void {
  document.removeEventListener('mousemove', moveGeometry)
  document.removeEventListener('mouseup', finishGeometryMove)
}

function resetSelection(): void {
  selected.value = null
  hovered.value = null
}

function clonePolygon(points: ImagePointTuple[]): ImagePointTuple[] {
  return points.map(([x, y]) => [x, y])
}

watch(
  () => [props.editable, props.activeTool] as const,
  () => {
    finishGeometryMove()
    resetSelection()
  },
)

onUnmounted(stopDragListeners)
</script>
