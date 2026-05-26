<template>
  <Teleport to="body">
    <div v-if="open && viewer" class="workflow-preview-json-viewer" @click.self="emit('close')">
      <div class="workflow-preview-json-viewer__panel" role="dialog" aria-modal="true">
        <div class="workflow-preview-json-viewer__toolbar">
          <div class="workflow-preview-json-viewer__title">
            <strong>{{ viewer.title }}</strong>
            <span>{{ viewer.statusText || 'JSON viewer' }}</span>
          </div>
          <div class="workflow-preview-json-viewer__actions">
            <Button size="sm" variant="secondary" type="button" @click="toggleCompactMode">
              {{ compactMode ? '格式化' : '压缩' }}
            </Button>
            <Button size="sm" variant="secondary" type="button" @click="wrapLines = !wrapLines">
              {{ wrapLines ? '取消换行' : '自动换行' }}
            </Button>
            <Button size="sm" variant="secondary" type="button" @click="copyJsonText">
              {{ copied ? '已复制' : '复制 JSON' }}
            </Button>
            <Button size="sm" variant="secondary" type="button" title="关闭" aria-label="关闭 JSON 查看器" @click="emit('close')">
              <X :size="17" />
            </Button>
          </div>
        </div>
        <div class="workflow-preview-json-viewer__viewport">
          <pre class="json-view workflow-preview-json-viewer__content" :class="{ 'is-wrapped': wrapLines }">{{ displayText }}</pre>
        </div>
        <div class="workflow-preview-json-viewer__status">
          <span>{{ lineCount }} 行</span>
          <span>{{ charCount }} 字符</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { X } from '@lucide/vue'

import Button from '@/shared/ui/components/Button.vue'

interface PreviewJsonViewerState {
  title: string
  value: unknown
  statusText?: string | null
}

const props = defineProps<{
  open: boolean
  viewer: PreviewJsonViewerState | null
}>()

const emit = defineEmits<{
  close: []
}>()

const compactMode = ref(false)
const wrapLines = ref(false)
const copied = ref(false)

const displayText = computed(() => formatJsonValue(props.viewer?.value, compactMode.value))
const lineCount = computed(() => (displayText.value ? displayText.value.split('\n').length : 0))
const charCount = computed(() => displayText.value.length)

watch(() => props.open, (open) => {
  if (!open) return
  compactMode.value = false
  wrapLines.value = false
  copied.value = false
})

function toggleCompactMode(): void {
  compactMode.value = !compactMode.value
}

async function copyJsonText(): Promise<void> {
  const text = displayText.value
  if (!text) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      copied.value = true
      window.setTimeout(() => {
        copied.value = false
      }, 1400)
    }
  } catch {
    copied.value = false
  }
}

function formatJsonValue(value: unknown, compact: boolean): string {
  if (value === undefined) return ''
  if (typeof value === 'string') {
    const parsed = tryParseJson(value)
    if (parsed !== null) {
      return compact ? JSON.stringify(parsed) : JSON.stringify(parsed, null, 2)
    }
    return value
  }
  return compact ? JSON.stringify(value) ?? '' : JSON.stringify(value, null, 2) ?? ''
}

function tryParseJson(value: string): unknown | null {
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}
</script>

<style scoped>
.workflow-preview-json-viewer {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  padding: 24px;
  background: rgb(13 16 18 / 0.92);
}

.workflow-preview-json-viewer__panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-width: 0;
  min-height: 0;
  border: 1px solid rgb(255 255 255 / 0.14);
  border-radius: 12px;
  overflow: hidden;
  color: #eef3f6;
  background: #1d2225;
  box-shadow: 0 18px 40px rgb(0 0 0 / 0.34);
}

.workflow-preview-json-viewer__toolbar,
.workflow-preview-json-viewer__status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  padding: 10px 12px;
  background: #1d2225;
}

.workflow-preview-json-viewer__toolbar {
  border-bottom: 1px solid rgb(255 255 255 / 0.14);
}

.workflow-preview-json-viewer__status {
  border-top: 1px solid rgb(255 255 255 / 0.14);
  color: #b9c6cc;
  font-size: 12px;
}

.workflow-preview-json-viewer__title {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.workflow-preview-json-viewer__title strong,
.workflow-preview-json-viewer__title span,
.workflow-preview-json-viewer__status span {
  overflow-wrap: anywhere;
}

.workflow-preview-json-viewer__title span {
  color: #b9c6cc;
  font-size: 12px;
}

.workflow-preview-json-viewer__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.workflow-preview-json-viewer__viewport {
  min-width: 0;
  min-height: 0;
  padding: 12px;
  overflow: auto;
  background: #161a1d;
}

.workflow-preview-json-viewer__content {
  min-height: 100%;
  margin: 0;
}

.workflow-preview-json-viewer__content.is-wrapped {
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 900px) {
  .workflow-preview-json-viewer {
    padding: 12px;
  }

  .workflow-preview-json-viewer__toolbar,
  .workflow-preview-json-viewer__status,
  .workflow-preview-json-viewer__actions {
    flex-wrap: wrap;
  }
}
</style>