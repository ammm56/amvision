<template>
  <section class="runtime-body-viewer">
    <div class="runtime-body-viewer__summary">
      <div v-for="item in summaryItems" :key="item.label" class="runtime-body-viewer__summary-card">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </div>
    </div>

    <section v-if="displayImages.length" class="runtime-body-viewer__group">
      <div class="runtime-body-viewer__group-heading">
        <div>
          <p class="runtime-body-viewer__kicker">Images</p>
          <h3>图片结果</h3>
        </div>
        <span>{{ displayImages.length }} item{{ displayImages.length > 1 ? 's' : '' }}</span>
      </div>
      <div class="runtime-body-viewer__image-grid">
        <article v-for="image in displayImages" :key="image.path" class="runtime-body-viewer__image-card">
          <button type="button" class="runtime-body-viewer__image-preview" :disabled="!image.src" @click="openImage(image)">
            <img v-if="image.src" :src="image.src" :alt="image.title" />
            <div v-else class="runtime-body-viewer__image-empty">当前结果只保留脱敏副本，无法直接预览原图。</div>
          </button>
          <div class="runtime-body-viewer__image-meta">
            <strong>{{ image.title }}</strong>
            <span>{{ image.path }}</span>
            <span>{{ image.transportKind }} / {{ image.mediaType || 'unknown' }}</span>
            <span>{{ image.objectKey || 'inline-base64' }}</span>
          </div>
          <div class="table-actions table-actions--wrap">
            <Button size="sm" variant="secondary" type="button" :disabled="!image.src" @click="openImage(image)">
              查看图片
            </Button>
          </div>
        </article>
      </div>
    </section>

    <section v-if="primaryJsonText" class="runtime-body-viewer__group">
      <div class="runtime-body-viewer__group-heading">
        <div>
          <p class="runtime-body-viewer__kicker">Payload</p>
          <h3>{{ primaryJsonTitle }}</h3>
        </div>
      </div>
      <pre class="json-view runtime-body-viewer__json">{{ primaryJsonText }}</pre>
    </section>

    <section v-if="metaJsonText" class="runtime-body-viewer__group">
      <div class="runtime-body-viewer__group-heading">
        <div>
          <p class="runtime-body-viewer__kicker">Meta</p>
          <h3>Meta</h3>
        </div>
      </div>
      <pre class="json-view runtime-body-viewer__json">{{ metaJsonText }}</pre>
    </section>

    <details class="runtime-body-viewer__raw">
      <summary>查看原始 response body JSON</summary>
      <pre class="json-view runtime-body-viewer__json">{{ rawJsonText }}</pre>
    </details>

    <ImageViewer :open="Boolean(activeImage)" :image="activeImage" @close="activeImage = null" />
  </section>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import { createProjectFileObjectUrl } from '@/shared/api/file-url'
import Button from '@/shared/ui/components/Button.vue'
import ImageViewer from '@/shared/ui/components/ImageViewer.vue'
import type { WorkflowJsonObject } from '../types'

interface ResponseImagePayload {
  transport_kind: string
  media_type: string
  image_base64?: string
  object_key?: string
  width?: number
  height?: number
}

interface RuntimeViewerImageSource {
  title: string
  path: string
  transportKind: string
  mediaType: string | null
  width: number | null
  height: number | null
  objectKey: string | null
  imageBase64: string | null
}

interface RuntimeViewerImage extends RuntimeViewerImageSource {
  src: string | null
}

interface SummaryItem {
  label: string
  value: string
}

const props = defineProps<{
  projectId: string
  statusCode: number | null
  body: WorkflowJsonObject | null
}>()

const displayImages = ref<RuntimeViewerImage[]>([])
const activeImage = ref<{
  title: string
  src: string | null
  mediaType?: string | null
  width?: number | null
  height?: number | null
  objectKey?: string | null
} | null>(null)

let latestLoadId = 0
const objectUrls = new Set<string>()

const bodyType = computed(() => {
  const body = props.body
  if (!isRecord(body)) return 'json'
  if (typeof body.type === 'string' && body.type.trim()) return body.type.trim()
  if ('code' in body || 'message' in body || 'data' in body) return 'response-envelope'
  return 'json'
})

const summaryItems = computed<SummaryItem[]>(() => {
  const items: SummaryItem[] = [
    { label: 'status', value: props.statusCode === null ? '-' : String(props.statusCode) },
    { label: 'body type', value: bodyType.value },
    { label: 'images', value: String(displayImages.value.length) },
  ]
  const body = props.body
  if (isRecord(body) && body.code !== undefined) items.push({ label: 'code', value: String(body.code) })
  if (isRecord(body) && typeof body.message === 'string' && body.message.trim()) {
    items.push({ label: 'message', value: body.message.trim() })
  }
  return items
})

const primaryJsonTitle = computed(() => {
  const body = props.body
  if (isRecord(body) && body.data !== undefined) return 'Data'
  if (bodyType.value === 'image') return 'Body Summary'
  return 'Body'
})

const primaryJsonText = computed(() => {
  const body = props.body
  if (!isRecord(body)) return formatViewerJson(body)
  const candidate = body.data !== undefined ? body.data : buildBodySummary(body)
  if (candidate === null || candidate === undefined) return ''
  return formatViewerJson(candidate)
})

const metaJsonText = computed(() => {
  const body = props.body
  if (!isRecord(body) || body.meta === undefined) return ''
  return formatViewerJson(body.meta)
})

const rawJsonText = computed(() => formatViewerJson(props.body))

watch(
  () => [props.projectId, props.body] as const,
  async () => {
    latestLoadId += 1
    const loadId = latestLoadId
    activeImage.value = null
    revokeObjectUrls()
    const imageSources = collectResponseImages(props.body)
    const nextImages: RuntimeViewerImage[] = []
    for (const imageSource of imageSources) {
      let src = buildInlineImageSrc(imageSource.mediaType, imageSource.imageBase64)
      if (!src && imageSource.objectKey && props.projectId.trim()) {
        try {
          src = await createProjectFileObjectUrl(props.projectId.trim(), imageSource.objectKey)
          objectUrls.add(src)
        } catch {
          src = null
        }
      }
      nextImages.push({ ...imageSource, src })
    }
    if (loadId !== latestLoadId) {
      nextImages.forEach((image) => {
        if (image.src && objectUrls.has(image.src)) {
          URL.revokeObjectURL(image.src)
          objectUrls.delete(image.src)
        }
      })
      return
    }
    displayImages.value = nextImages
  },
  { immediate: true, deep: true },
)

function openImage(image: RuntimeViewerImage): void {
  activeImage.value = {
    title: image.title,
    src: image.src,
    mediaType: image.mediaType,
    width: image.width,
    height: image.height,
    objectKey: image.objectKey,
  }
}

function revokeObjectUrls(): void {
  for (const objectUrl of objectUrls) URL.revokeObjectURL(objectUrl)
  objectUrls.clear()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isResponseImagePayload(value: unknown): value is ResponseImagePayload {
  return isRecord(value) && typeof value.transport_kind === 'string' && typeof value.media_type === 'string'
}

function buildInlineImageSrc(mediaType: string | null, imageBase64: string | null): string | null {
  if (!imageBase64) return null
  return `data:${mediaType || 'image/png'};base64,${imageBase64}`
}

function formatViewerJson(value: unknown): string {
  return JSON.stringify(transformViewerJsonValue(value), null, 2)
}

function transformViewerJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => transformViewerJsonValue(item))
  if (isRecord(value)) {
    const normalized: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(value)) {
      if (key === 'image_base64' && typeof item === 'string') {
        normalized[key] = `[inline-base64 ${item.length} chars]`
        continue
      }
      normalized[key] = transformViewerJsonValue(item)
    }
    return normalized
  }
  if (typeof value === 'string' && value.length > 320) return `${value.slice(0, 160)}... [${value.length} chars]`
  return value
}

function buildBodySummary(body: Record<string, unknown>): Record<string, unknown> | null {
  const summary = { ...body }
  if (typeof summary.type === 'string' && summary.type === 'image') delete summary.image
  if (Object.keys(summary).length === 0) return null
  return summary
}

function collectResponseImages(value: unknown, path = 'body'): RuntimeViewerImageSource[] {
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => collectResponseImages(item, `${path}[${index}]`))
  }
  if (!isRecord(value)) return []

  const wrapperType = typeof value.type === 'string' ? value.type : null
  if ((wrapperType === 'image' || wrapperType === 'image-preview') && isResponseImagePayload(value.image)) {
    return [buildViewerImageSource(path, value, value.image)]
  }
  if (isResponseImagePayload(value)) {
    return [buildViewerImageSource(path, null, value)]
  }

  return Object.entries(value).flatMap(([key, item]) => collectResponseImages(item, `${path}.${key}`))
}

function buildViewerImageSource(
  path: string,
  wrapper: Record<string, unknown> | null,
  image: ResponseImagePayload,
): RuntimeViewerImageSource {
  const pathLabel = path.replace(/^body\.?/, '') || 'body'
  const title =
    (wrapper && typeof wrapper.title === 'string' && wrapper.title.trim()) ||
    pathLabel.split('.').at(-1)?.replace(/\[(\d+)\]/g, ' $1') ||
    'image'
  return {
    title,
    path: pathLabel,
    transportKind: image.transport_kind,
    mediaType: typeof image.media_type === 'string' ? image.media_type : null,
    width: normalizeOptionalNumber(image.width),
    height: normalizeOptionalNumber(image.height),
    objectKey: typeof image.object_key === 'string' && image.object_key.trim() ? image.object_key : null,
    imageBase64: typeof image.image_base64 === 'string' && image.image_base64 ? image.image_base64 : null,
  }
}

function normalizeOptionalNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

onUnmounted(() => {
  revokeObjectUrls()
})
</script>

<style scoped>
.runtime-body-viewer {
  display: grid;
  gap: 16px;
}

.runtime-body-viewer__summary {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
}

.runtime-body-viewer__summary-card,
.runtime-body-viewer__image-card {
  border: 1px solid var(--ui-border-subtle, rgba(148, 163, 184, 0.24));
  border-radius: 16px;
  background: var(--ui-surface-raised, rgba(15, 23, 42, 0.02));
}

.runtime-body-viewer__summary-card {
  display: grid;
  gap: 4px;
  padding: 14px 16px;
}

.runtime-body-viewer__summary-card span,
.runtime-body-viewer__image-meta span,
.runtime-body-viewer__group-heading span,
.runtime-body-viewer__kicker {
  color: var(--ui-text-muted, rgba(71, 85, 105, 0.9));
  font-size: 12px;
}

.runtime-body-viewer__summary-card strong,
.runtime-body-viewer__image-meta strong {
  color: var(--ui-text-strong, inherit);
}

.runtime-body-viewer__group {
  display: grid;
  gap: 12px;
}

.runtime-body-viewer__group-heading {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-end;
}

.runtime-body-viewer__group-heading h3 {
  margin: 0;
}

.runtime-body-viewer__kicker {
  margin: 0 0 4px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.runtime-body-viewer__image-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.runtime-body-viewer__image-card {
  display: grid;
  gap: 12px;
  padding: 12px;
}

.runtime-body-viewer__image-preview {
  display: grid;
  place-items: center;
  min-height: 180px;
  padding: 0;
  border: 0;
  border-radius: 12px;
  overflow: hidden;
  background: linear-gradient(135deg, rgba(148, 163, 184, 0.12), rgba(15, 23, 42, 0.08));
  cursor: pointer;
}

.runtime-body-viewer__image-preview:disabled {
  cursor: not-allowed;
}

.runtime-body-viewer__image-preview img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.runtime-body-viewer__image-empty {
  padding: 20px;
  text-align: center;
  line-height: 1.6;
  color: var(--ui-text-muted, rgba(71, 85, 105, 0.9));
}

.runtime-body-viewer__image-meta {
  display: grid;
  gap: 4px;
}

.runtime-body-viewer__json {
  margin: 0;
  max-height: 360px;
  overflow: auto;
}

.runtime-body-viewer__raw {
  border: 1px solid var(--ui-border-subtle, rgba(148, 163, 184, 0.24));
  border-radius: 14px;
  padding: 12px 14px;
  background: var(--ui-surface-raised, rgba(15, 23, 42, 0.02));
}

.runtime-body-viewer__raw summary {
  cursor: pointer;
  font-weight: 600;
}

.runtime-body-viewer__raw .json-view {
  margin-top: 12px;
}
</style>