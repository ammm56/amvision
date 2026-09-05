<template>
  <SideDrawer
    :open="open"
    :title="t('workflowEditor.appDetail.fields.requestExamples')"
    :close-label="t('common.close')"
    @close="emit('close')"
  >
    <div v-if="examples" class="workflow-request-examples">
      <section class="workflow-request-examples__endpoints">
        <h3>{{ t('workflowEditor.appDetail.fields.endpoint') }}</h3>
        <pre class="json-view">{{ endpoints.join('\n') }}</pre>
      </section>
      <details open>
        <summary>JSON</summary>
        <pre class="json-view">{{ examples.json }}</pre>
      </details>
      <details>
        <summary>multipart / curl</summary>
        <pre class="json-view">{{ examples.multipartCurl }}</pre>
      </details>
      <details>
        <summary>.NET SDK</summary>
        <pre class="json-view">{{ examples.dotnet }}</pre>
      </details>
    </div>
  </SideDrawer>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import type { WorkflowAppRequestExamples } from '../workflow-app-request-examples'

defineProps<{
  open: boolean
  examples: WorkflowAppRequestExamples | null
  endpoints: string[]
}>()

const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
</script>

<style scoped>
.workflow-request-examples {
  display: grid;
  gap: var(--am-space-md);
}

.workflow-request-examples__endpoints,
.workflow-request-examples details {
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  padding: var(--am-space-md);
  background: var(--am-surface-soft);
}

.workflow-request-examples__endpoints h3 {
  margin: 0 0 var(--am-space-md);
  color: var(--am-text-strong);
  font-size: 14px;
}

.workflow-request-examples summary {
  cursor: pointer;
  font-weight: 700;
}

.workflow-request-examples details .json-view {
  margin-top: var(--am-space-md);
}

.workflow-request-examples .json-view {
  margin-bottom: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
