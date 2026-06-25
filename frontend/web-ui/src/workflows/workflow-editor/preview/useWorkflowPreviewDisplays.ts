import { computed, ref } from 'vue'

import { readProjectObjectContentBlob, readWorkflowPreviewRunArtifactBlob } from '../services/workflow-runtime.service'
import type { WorkflowJsonObject, WorkflowPreviewRun } from '../types'

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

  async function refreshPreviewNodeDisplays(previewRun: WorkflowPreviewRun): Promise<void> {
    revokePreviewImageObjectUrls()
    const nextDisplays: Record<string, PreviewNodeDisplay> = {}
    for (const displayOutput of readPreviewDisplayOutputs(previewRun)) {
      const previewDisplay = await buildPreviewNodeDisplay(previewRun, displayOutput, registerPreviewImageObjectUrl)
      if (previewDisplay) {
        nextDisplays[previewDisplay.nodeId] = previewDisplay
      }
    }
    previewNodeDisplays.value = nextDisplays
  }

  function revokePreviewImageObjectUrls(): void {
    for (const objectUrl of previewImageObjectUrls) {
      URL.revokeObjectURL(objectUrl)
    }
    previewImageObjectUrls = []
    previewNodeDisplays.value = {}
    closeImageViewer()
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
  const image = await buildPreviewViewerImage(previewRun, payload.image, title, displayOutput.nodeId, registerObjectUrl)
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
  const galleryItems: PreviewGalleryItemView[] = []
  for (const [itemIndex, rawItem] of rawItems.entries()) {
    if (!isPreviewJsonObject(rawItem) || !isPreviewJsonObject(rawItem.image)) continue
    const caption = readDisplayText(rawItem.caption) || `Image ${itemIndex + 1}`
    const image = await buildPreviewViewerImage(previewRun, rawItem.image, caption, displayOutput.nodeId, registerObjectUrl)
    galleryItems.push({
      ...image,
      title: caption,
      caption,
      cropIndex: readDisplayNumber(rawItem.crop_index),
    })
  }
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
