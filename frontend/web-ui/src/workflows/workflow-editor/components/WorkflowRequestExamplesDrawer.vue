<template>
  <SideDrawer
    :open="open"
    title="请求示例"
    :close-label="t('common.close')"
    plain
    size="compact"
    @close="emit('close')"
  >
    <div v-if="examples" class="workflow-request-examples">
      <div v-if="runtimeName || versionLabel" class="workflow-request-examples__meta">
        <div v-if="runtimeName" class="workflow-request-examples__meta-item">
          <span>目标实例</span>
          <strong>{{ runtimeName }}</strong>
        </div>
        <div v-if="versionLabel" class="workflow-request-examples__meta-item">
          <span>版本</span>
          <strong>{{ versionLabel }}</strong>
        </div>
      </div>

      <section class="workflow-request-examples__endpoints">
        <h3>接口</h3>
        <pre class="workflow-request-examples__code">{{ endpoints.join('\n') }}</pre>
      </section>

      <TabList
        :model-value="activeTab"
        :tabs="exampleTabs"
        label="请求示例格式"
        variant="underline"
        @update:model-value="(val) => (activeTab = val as ExampleTabId)"
      />

      <pre class="workflow-request-examples__code workflow-request-examples__code--tall">{{ activeExampleText }}</pre>
    </div>

    <template v-if="examples" #footer>
      <Button variant="secondary" @click="emit('close')">关闭</Button>
      <Button variant="primary" data-request-example-copy @click="copyActiveExample">
        <Check v-if="copied" :size="14" />
        <Copy v-else :size="14" />
        {{ copied ? '已复制' : '复制示例' }}
      </Button>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { Check, Copy } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import Button from '@/shared/ui/components/Button.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import TabList, { type TabListItem } from '@/shared/ui/navigation/TabList.vue'
import type { WorkflowAppRequestExamples } from '../workflow-app-request-examples'

type ExampleTabId = 'json' | 'curl' | 'dotnet'

const props = defineProps<{
  open: boolean
  examples: WorkflowAppRequestExamples | null
  endpoints: string[]
  runtimeName?: string
  versionLabel?: string
}>()

const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()

const activeTab = ref<ExampleTabId>('json')
const copied = ref(false)
let copyTimer: ReturnType<typeof setTimeout> | null = null

const exampleTabs: readonly TabListItem[] = [
  { id: 'json', label: 'JSON' },
  { id: 'curl', label: 'multipart / curl' },
  { id: 'dotnet', label: '.NET SDK' },
]

const activeExampleText = computed(() => {
  if (!props.examples) return ''
  if (activeTab.value === 'curl') return props.examples.multipartCurl
  if (activeTab.value === 'dotnet') return props.examples.dotnet
  return props.examples.json
})

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      copied.value = false
    } else if (copyTimer) {
      clearTimeout(copyTimer)
      copyTimer = null
    }
  },
)

async function copyActiveExample(): Promise<void> {
  const text = activeExampleText.value
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copied.value = false
    }, 1800)
  } catch {
    copied.value = false
  }
}
</script>

<style scoped>
.workflow-request-examples {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
  min-width: 0;
}

.workflow-request-examples__meta {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px 20px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--am-border);
}

.workflow-request-examples__meta-item {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.workflow-request-examples__meta-item span {
  font-size: 12px;
  color: var(--am-text-muted);
}

.workflow-request-examples__meta-item strong {
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-request-examples__endpoints {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
}

.workflow-request-examples__endpoints h3 {
  margin: 0;
  color: var(--am-text-strong);
  font-size: 13px;
  font-weight: 600;
}

.workflow-request-examples__code {
  min-width: 0;
  max-width: 100%;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
  color: var(--am-text-strong);
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-size: 12px;
  line-height: 1.55;
  overflow: auto;
  white-space: pre;
}

.workflow-request-examples__code--tall {
  max-height: 440px;
}
</style>
