import { computed, ref } from 'vue'

import { readProjectObjectContentBlob, readWorkflowPreviewRunArtifactBlob } from '../services/workflow-runtime.service'
import type { WorkflowJsonObject, WorkflowPreviewRun } from '../types'

export interface PreviewImageCircleOverlay {
  centerX: number
  centerY: number
  radius: number
}

export interface PreviewImageOverlay {
  kind: string
  id: string | null
  label: string | null
  pointsXy: Array<[number, number]>
  bboxXyxy: [number, number, number, number] | null
  lineXyxy: [number, number, number, number] | null
  circle: PreviewImageCircleOverlay | null
  targetParameters: string[]
  parameters: Record<string, unknown>
}

export interface PreviewImageInteractionControl {
  parameterName: string
  label: string
  control: string
  min: number | null
  max: number | null
  step: number | null
  value: unknown
  defaultValue: unknown
}

export interface PreviewImageInteractionTool {
  tool: string
  label: string | null
  targetParameters: string[]
  minPoints: number | null
  maxPoints: number | null
  angleToleranceDeg: number | null
  searchPaddingRatio: number | null
  searchPaddingMin: number | null
}

export interface PreviewImageInteraction {
  mode: string
  coordinateSpace: string
  controls: PreviewImageInteractionControl[]
  tools: PreviewImageInteractionTool[]
}

export interface PreviewImageInteractionApplyEvent {
  nodeId: string
  tool: string
  coordinateSpace: string
  targetParameters: string[]
  parameters?: Record<string, unknown>
  angleToleranceDeg?: number | null
  searchPaddingRatio?: number | null
  searchPaddingMin?: number | null
  bboxXyxy?: [number, number, number, number]
  templateBboxXyxy?: [number, number, number, number]
  searchBboxXyxy?: [number, number, number, number]
  pointsXy?: Array<[number, number]>
  circle?: PreviewImageCircleOverlay
  lineXyxy?: [number, number, number, number]
}

export interface PreviewViewerImage {
  nodeId: string
  title: string
  src: string | null
  statusText: string
  transportKind: string
  mediaType: string
  width: number | null
  height: number | null
  objectKey: string | null
  overlays: PreviewImageOverlay[]
  interaction: PreviewImageInteraction | null
}

export interface PreviewGalleryItemView extends PreviewViewerImage {
  caption: string
  cropIndex: number | null
}

export interface PreviewTableColumnView {
  key: string
  label: string
}

export interface PreviewTableViewerState {
  title: string
  columns: PreviewTableColumnView[]
  rows: WorkflowJsonObject[]
  rowCount: number | null
  emptyText: string | null
}

export interface PreviewJsonViewerState {
  title: string
  value: unknown
  statusText: string | null
}

interface PreviewNodeOutput {
  nodeId: string
  nodeTypeId: string
  outputName: string
  payload: WorkflowJsonObject
}

export interface PreviewNodeDisplayRefreshOptions {
  reopenImageViewerNodeId?: string | null
}

interface PreviewImageObjectUrlRevokeOptions {
  closeImageViewer?: boolean
}

type PreviewNodeDisplayKind = 'image' | 'table' | 'gallery' | 'value'

export interface PreviewNodeDisplay {
  nodeId: string
  nodeTypeId: string
  outputName: string
  title: string
  kind: PreviewNodeDisplayKind
  payload: WorkflowJsonObject
  statusText: string
  formattedValue: string
  image: PreviewViewerImage | null
  galleryItems: PreviewGalleryItemView[]
  columns: PreviewTableColumnView[]
  rows: WorkflowJsonObject[]
  rowCount: number | null
  emptyText: string | null
}

export function useWorkflowPreviewDisplays() {
  const previewNodeDisplays = ref<Record<string, PreviewNodeDisplay>>({})
  const activeImageViewer = ref<PreviewViewerImage | null>(null)
  const activePreviewTable = ref<PreviewTableViewerState | null>(null)
  const activePreviewJson = ref<PreviewJsonViewerState | null>(null)
  let previewImageObjectUrls: string[] = []

  const hasPreviewNodeDisplays = computed(() => Object.keys(previewNodeDisplays.value).length > 0)
  const registerPreviewImageObjectUrl = (objectUrl: string): void => {
    previewImageObjectUrls.push(objectUrl)
  }

  async function refreshPreviewNodeDisplays(
    previewRun: WorkflowPreviewRun,
    options: PreviewNodeDisplayRefreshOptions = {},
  ): Promise<void> {
    const reopenImageViewerNodeId = readDisplayText(options.reopenImageViewerNodeId)
    revokePreviewImageObjectUrls({ closeImageViewer: !reopenImageViewerNodeId })
    const nextDisplays: Record<string, PreviewNodeDisplay> = {}
    const previewDisplays = await Promise.all(
      readPreviewDisplayOutputs(previewRun).map((displayOutput) => (
        buildPreviewNodeDisplay(previewRun, displayOutput, registerPreviewImageObjectUrl)
      )),
    )
    for (const previewDisplay of previewDisplays) {
      if (previewDisplay) {
        nextDisplays[previewDisplay.nodeId] = previewDisplay
      }
    }
    previewNodeDisplays.value = nextDisplays
    if (reopenImageViewerNodeId) {
      const refreshedImage = nextDisplays[reopenImageViewerNodeId]?.image ?? null
      activeImageViewer.value = refreshedImage?.src ? refreshedImage : null
    }
  }

  function revokePreviewImageObjectUrls(options: PreviewImageObjectUrlRevokeOptions = {}): void {
    for (const objectUrl of previewImageObjectUrls) {
      URL.revokeObjectURL(objectUrl)
    }
    previewImageObjectUrls = []
    previewNodeDisplays.value = {}
    if (options.closeImageViewer !== false) closeImageViewer()
  }

  function getPreviewNodeDisplay(nodeId: string): PreviewNodeDisplay | null {
    return previewNodeDisplays.value[nodeId] ?? null
  }

  function readPreviewNodeDisplayTooltip(display: PreviewNodeDisplay | null): string {
    if (!display) return ''
    if (display.kind === 'table') {
      return display.rows.length > 0 ? '双击查看完整表格' : (display.statusText || '当前没有表格数据')
    }
    if (display.kind === 'gallery') {
      return display.galleryItems.length > 0 ? '双击查看首张预览图片' : display.statusText
    }
    if (display.kind === 'image') {
      return display.image?.src ? '双击查看预览图片' : display.statusText
    }
    return display.statusText
  }

  function openPreviewDisplayViewer(display: PreviewNodeDisplay | null): void {
    if (!display) return
    if (display.kind === 'value') {
      openPreviewJsonViewer(
        display.title,
        Object.prototype.hasOwnProperty.call(display.payload, 'value') ? display.payload.value : null,
        display.statusText,
      )
      return
    }
    if (display.kind === 'table') {
      openPreviewTableViewer(display)
      return
    }
    openPrimaryPreviewImage(display)
  }

  function openImageViewer(image: PreviewViewerImage | null): void {
    if (!image?.src) return
    activeImageViewer.value = image
  }

  function openPreviewJsonViewer(title: string, value: unknown, statusText: string | null = null): void {
    activePreviewJson.value = {
      title,
      value,
      statusText,
    }
  }

  function openPreviewTableViewer(display: PreviewNodeDisplay | null): void {
    if (!display || display.kind !== 'table') return
    activePreviewTable.value = {
      title: display.title,
      columns: display.columns,
      rows: display.rows,
      rowCount: display.rowCount,
      emptyText: display.emptyText,
    }
  }

  function openPrimaryPreviewImage(display: PreviewNodeDisplay | null): void {
    openImageViewer(display?.image ?? null)
  }

  function closeImageViewer(): void {
    activeImageViewer.value = null
  }

  function closePreviewTableViewer(): void {
    activePreviewTable.value = null
  }

  function closePreviewJsonViewer(): void {
    activePreviewJson.value = null
  }

  return {
    previewNodeDisplays,
    activeImageViewer,
    activePreviewTable,
    activePreviewJson,
    hasPreviewNodeDisplays,
    refreshPreviewNodeDisplays,
    revokePreviewImageObjectUrls,
    getPreviewNodeDisplay,
    readPreviewNodeDisplayTooltip,
    openPreviewDisplayViewer,
    openImageViewer,
    openPreviewJsonViewer,
    closeImageViewer,
    closePreviewTableViewer,
    closePreviewJsonViewer,
  }
}

function readPreviewDisplayOutputs(previewRun: WorkflowPreviewRun): PreviewNodeOutput[] {
  const outputIndex = new Map<string, PreviewNodeOutput>()
  const registerDisplayOutput = (displayOutput: PreviewNodeOutput): void => {
    const nodeId = readDisplayText(displayOutput.nodeId)
    const nodeTypeId = readDisplayText(displayOutput.nodeTypeId)
    const outputName = readDisplayText(displayOutput.outputName)
    if (!nodeId || !nodeTypeId || !outputName || !isPreviewJsonObject(displayOutput.payload)) return
    const key = `${nodeId}:${nodeTypeId}:${outputName}`
    outputIndex.set(key, {
      nodeId,
      nodeTypeId,
      outputName,
      payload: displayOutput.payload,
    })
  }
  for (const record of previewRun.node_records) {
    const nodeId = readDisplayText(record.node_id)
    const nodeTypeId = readDisplayText(record.node_type_id)
    const outputs = record.outputs
    if (!nodeId || !nodeTypeId || !isPreviewJsonObject(outputs)) continue
    for (const [outputName, payload] of Object.entries(outputs)) {
      if (!isPreviewJsonObject(payload)) continue
      const previewType = readDisplayText(payload.type)
      if (!previewType.endsWith('-preview')) continue
      registerDisplayOutput({
        nodeId,
        nodeTypeId,
        outputName,
        payload,
      })
    }
  }
  return [...outputIndex.values()]
}

async function buildPreviewNodeDisplay(
  previewRun: WorkflowPreviewRun,
  displayOutput: PreviewNodeOutput,
  registerObjectUrl: (objectUrl: string) => void,
): Promise<PreviewNodeDisplay | null> {
  const payload = displayOutput.payload
  const previewType = readDisplayText(payload.type)
  if (previewType === 'image-preview') return buildImagePreviewNodeDisplay(previewRun, displayOutput, registerObjectUrl)
  if (previewType === 'table-preview') return buildTablePreviewNodeDisplay(displayOutput)
  if (previewType === 'gallery-preview') return buildGalleryPreviewNodeDisplay(previewRun, displayOutput, registerObjectUrl)
  if (previewType === 'value-preview') return buildValuePreviewNodeDisplay(displayOutput)
  return null
}

async function buildImagePreviewNodeDisplay(
  previewRun: WorkflowPreviewRun,
  displayOutput: PreviewNodeOutput,
  registerObjectUrl: (objectUrl: string) => void,
): Promise<PreviewNodeDisplay | null> {
  const payload = displayOutput.payload
  if (!isPreviewJsonObject(payload.image)) return null
  const title = readDisplayText(payload.title) || displayOutput.nodeId
  const image = await buildPreviewViewerImage(previewRun, payload.image, title, displayOutput.nodeId, registerObjectUrl, payload)
  return {
    nodeId: displayOutput.nodeId,
    nodeTypeId: displayOutput.nodeTypeId,
    outputName: displayOutput.outputName,
    title,
    kind: 'image',
    payload,
    statusText: image.statusText,
    formattedValue: '',
    image,
    galleryItems: [],
    columns: [],
    rows: [],
    rowCount: 1,
    emptyText: null,
  }
}

function buildTablePreviewNodeDisplay(displayOutput: PreviewNodeOutput): PreviewNodeDisplay {
  const payload = displayOutput.payload
  const columns = Array.isArray(payload.columns)
    ? payload.columns.flatMap((column) => {
      if (!isPreviewJsonObject(column)) return []
      const key = readDisplayText(column.key)
      if (!key) return []
      return [{ key, label: readDisplayText(column.label) || key }]
    })
    : []
  const rows = Array.isArray(payload.rows)
    ? payload.rows.map((row) => (isPreviewJsonObject(row) ? row : { value: row }))
    : []
  const rowCount = readDisplayNumber(payload.row_count) ?? rows.length
  const emptyText = readDisplayText(payload.empty_text) || null
  return {
    nodeId: displayOutput.nodeId,
    nodeTypeId: displayOutput.nodeTypeId,
    outputName: displayOutput.outputName,
    title: readDisplayText(payload.title) || displayOutput.nodeId,
    kind: 'table',
    payload,
    statusText: rows.length > 0 ? `${columns.length} 列 / ${rowCount} 行` : emptyText || `${columns.length} 列 / 0 行`,
    formattedValue: '',
    image: null,
    galleryItems: [],
    columns,
    rows,
    rowCount,
    emptyText,
  }
}

async function buildGalleryPreviewNodeDisplay(
  previewRun: WorkflowPreviewRun,
  displayOutput: PreviewNodeOutput,
  registerObjectUrl: (objectUrl: string) => void,
): Promise<PreviewNodeDisplay> {
  const payload = displayOutput.payload
  const rawItems = Array.isArray(payload.items) ? payload.items : []
  const galleryItems = (await Promise.all(rawItems.map(async (rawItem, itemIndex): Promise<PreviewGalleryItemView | null> => {
    if (!isPreviewJsonObject(rawItem) || !isPreviewJsonObject(rawItem.image)) return null
    const caption = readDisplayText(rawItem.caption) || `Image ${itemIndex + 1}`
    const image = await buildPreviewViewerImage(previewRun, rawItem.image, caption, displayOutput.nodeId, registerObjectUrl, rawItem)
    return {
      ...image,
      title: caption,
      caption,
      cropIndex: readDisplayNumber(rawItem.crop_index),
    }
  }))).filter((item): item is PreviewGalleryItemView => item !== null)
  const totalCount = readDisplayNumber(payload.total_count) ?? galleryItems.length
  return {
    nodeId: displayOutput.nodeId,
    nodeTypeId: displayOutput.nodeTypeId,
    outputName: displayOutput.outputName,
    title: readDisplayText(payload.title) || displayOutput.nodeId,
    kind: 'gallery',
    payload,
    statusText: galleryItems.length > 0 ? `${galleryItems.length} 张 / 总计 ${totalCount} 张` : '图库没有可显示图片',
    formattedValue: '',
    image: galleryItems[0] ?? null,
    galleryItems,
    columns: [],
    rows: [],
    rowCount: galleryItems.length,
    emptyText: null,
  }
}

function buildValuePreviewNodeDisplay(displayOutput: PreviewNodeOutput): PreviewNodeDisplay {
  const payload = displayOutput.payload
  const hasValue = Object.prototype.hasOwnProperty.call(payload, 'value')
  const previewValue = hasValue ? payload.value : null
  const emptyText = readDisplayText(payload.empty_text) || null
  return {
    nodeId: displayOutput.nodeId,
    nodeTypeId: displayOutput.nodeTypeId,
    outputName: displayOutput.outputName,
    title: readDisplayText(payload.title) || displayOutput.nodeId,
    kind: 'value',
    payload,
    statusText: readDisplayText(payload.status_text) || emptyText || (hasValue ? 'JSON 预览' : '未返回可显示 value'),
    formattedValue: formatPreviewJson(previewValue) || 'null',
    image: null,
    galleryItems: [],
    columns: [],
    rows: [],
    rowCount: null,
    emptyText,
  }
}

async function buildPreviewViewerImage(
  previewRun: WorkflowPreviewRun,
  imagePayload: WorkflowJsonObject,
  title: string,
  nodeId: string,
  registerObjectUrl: (objectUrl: string) => void,
  previewPayload: WorkflowJsonObject | null = null,
): Promise<PreviewViewerImage> {
  const transportKind = readDisplayText(imagePayload.transport_kind) || 'unknown'
  const mediaType = readDisplayText(imagePayload.media_type)
  const objectKey = readDisplayText(imagePayload.object_key) || null
  const imageBase64 = readDisplayText(imagePayload.image_base64)
  const src = imageBase64
    ? `data:${mediaType || 'image/png'};base64,${imageBase64}`
    : await resolveStoragePreviewImageSrc(previewRun, objectKey, registerObjectUrl)
  return {
    nodeId,
    title,
    src,
    statusText: src ? '预览图已生成' : buildPreviewImageStatusText(transportKind, objectKey),
    transportKind,
    mediaType,
    width: readDisplayNumber(imagePayload.width),
    height: readDisplayNumber(imagePayload.height),
    objectKey,
    overlays: readPreviewImageOverlays(previewPayload?.overlays),
    interaction: readPreviewImageInteraction(previewPayload?.interaction),
  }
}

async function resolveStoragePreviewImageSrc(
  previewRun: WorkflowPreviewRun,
  objectKey: string | null,
  registerObjectUrl: (objectUrl: string) => void,
): Promise<string | null> {
  if (!objectKey) return null
  try {
    const blob = await readPreviewImageBlob(previewRun, objectKey)
    if (!blob) return null
    const objectUrl = URL.createObjectURL(blob)
    registerObjectUrl(objectUrl)
    return objectUrl
  } catch (error) {
    console.warn('读取 Preview 图片失败', error)
    return null
  }
}

async function readPreviewImageBlob(previewRun: WorkflowPreviewRun, objectKey: string): Promise<Blob | null> {
  if (objectKey.startsWith(`workflows/runtime/preview-runs/${previewRun.preview_run_id}/artifacts/`)) {
    return readWorkflowPreviewRunArtifactBlob(previewRun.preview_run_id, objectKey)
  }
  if (objectKey.startsWith(`projects/${previewRun.project_id}/`)) {
    return readProjectObjectContentBlob(previewRun.project_id, objectKey)
  }
  return null
}

function buildPreviewImageStatusText(transportKind: string, objectKey: string | null): string {
  if (transportKind === 'storage-ref' && objectKey) return '预览图引用暂不可读取'
  return '本次 Preview 未返回可展示图片'
}

function readPreviewImageOverlays(value: unknown): PreviewImageOverlay[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((rawOverlay) => {
    if (!isPreviewJsonObject(rawOverlay)) return []
    const overlay = buildPreviewImageOverlay(rawOverlay)
    return overlay ? [overlay] : []
  })
}

function buildPreviewImageOverlay(rawOverlay: WorkflowJsonObject): PreviewImageOverlay | null {
  const kind = readDisplayText(rawOverlay.kind) || 'shape'
  const pointsXy = readPointPairs(rawOverlay.points_xy)
  const bboxXyxy = readNumberTuple4(rawOverlay.bbox_xyxy)
  const lineXyxy = readNumberTuple4(rawOverlay.line_xyxy)
  const circle = readCircleOverlay(rawOverlay.circle)
  if (pointsXy.length === 0 && bboxXyxy === null && lineXyxy === null && circle === null) return null
  return {
    kind,
    id: readDisplayText(rawOverlay.id) || null,
    label: readDisplayText(rawOverlay.label) || null,
    pointsXy,
    bboxXyxy,
    lineXyxy,
    circle,
    targetParameters: readStringArray(rawOverlay.target_parameters),
    parameters: readPreviewObject(rawOverlay.parameters),
  }
}

function readPreviewImageInteraction(value: unknown): PreviewImageInteraction | null {
  if (!isPreviewJsonObject(value)) return null
  const tools = readPreviewImageInteractionTools(value.tools)
  const controls = readPreviewImageInteractionControls(value.controls)
  if (tools.length === 0 && controls.length === 0) return null
  return {
    mode: readDisplayText(value.mode) || 'view',
    coordinateSpace: readDisplayText(value.coordinate_space) || 'source-image',
    controls,
    tools,
  }
}

function readPreviewImageInteractionTools(value: unknown): PreviewImageInteractionTool[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((rawTool) => {
    if (!isPreviewJsonObject(rawTool)) return []
    const tool = readDisplayText(rawTool.tool)
    if (!tool) return []
    return [{
      tool,
      label: readDisplayText(rawTool.label) || null,
      targetParameters: readStringArray(rawTool.target_parameters),
      minPoints: readDisplayNumber(rawTool.min_points),
      maxPoints: readDisplayNumber(rawTool.max_points),
      angleToleranceDeg: readDisplayNumber(rawTool.angle_tolerance_deg),
      searchPaddingRatio: readDisplayNumber(rawTool.search_padding_ratio),
      searchPaddingMin: readDisplayNumber(rawTool.search_padding_min),
    }]
  })
}

function readPreviewImageInteractionControls(value: unknown): PreviewImageInteractionControl[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((rawControl) => {
    if (!isPreviewJsonObject(rawControl)) return []
    const parameterName = readDisplayText(rawControl.parameter_name)
    if (!parameterName) return []
    return [{
      parameterName,
      label: readDisplayText(rawControl.label) || parameterName,
      control: readDisplayText(rawControl.control) || 'slider',
      min: readDisplayNumber(rawControl.min),
      max: readDisplayNumber(rawControl.max),
      step: readDisplayNumber(rawControl.step),
      value: rawControl.value,
      defaultValue: rawControl.default_value,
    }]
  })
}

function readPointPairs(value: unknown): Array<[number, number]> {
  if (!Array.isArray(value)) return []
  return value.flatMap((point) => {
    if (!Array.isArray(point) || point.length < 2) return []
    const pointX = readDisplayNumber(point[0])
    const pointY = readDisplayNumber(point[1])
    return pointX === null || pointY === null ? [] : [[pointX, pointY] as [number, number]]
  })
}

function readNumberTuple4(value: unknown): [number, number, number, number] | null {
  if (!Array.isArray(value) || value.length < 4) return null
  const [x1, y1, x2, y2] = value.slice(0, 4).map((item) => readDisplayNumber(item))
  if (x1 === null || y1 === null || x2 === null || y2 === null) return null
  return [x1, y1, x2, y2]
}

function readCircleOverlay(value: unknown): PreviewImageCircleOverlay | null {
  if (!isPreviewJsonObject(value)) return null
  const centerX = readDisplayNumber(value.center_x)
  const centerY = readDisplayNumber(value.center_y)
  const radius = readDisplayNumber(value.radius)
  if (centerX === null || centerY === null || radius === null || radius <= 0) return null
  return { centerX, centerY, radius }
}

function readStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    const text = readDisplayText(item)
    return text ? [text] : []
  })
}

function readPreviewObject(value: unknown): Record<string, unknown> {
  return isPreviewJsonObject(value) ? value : {}
}

function formatPreviewJson(value: unknown): string {
  if (value === undefined) return ''
  return JSON.stringify(value, null, 2)
}

function isPreviewJsonObject(value: unknown): value is WorkflowJsonObject {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function readDisplayText(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function readDisplayNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}
