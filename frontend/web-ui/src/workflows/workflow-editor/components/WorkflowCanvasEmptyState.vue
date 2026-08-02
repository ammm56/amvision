<template>
  <div v-if="nodeCount === 0" class="workflow-graph-empty">
    <Workflow :size="42" />
    <strong>{{ t('workflowEditor.editor.canvasPlaceholderTitle') }}</strong>
  </div>
</template>

<script setup lang="ts">
import { Workflow } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

defineProps<{
  nodeCount: number
}>()

const { t } = useI18n()
</script>
