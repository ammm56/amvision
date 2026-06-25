<template>
  <div v-if="!loading && nodeCount === 0" class="workflow-graph-empty">
    <Workflow :size="42" />
    <strong>{{ t('workflowEditor.editor.canvasPlaceholderTitle') }}</strong>
    <span>{{ description }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Workflow } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  loading: boolean
  nodeCount: number
  isNewApp: boolean
}>()

const { t } = useI18n()

const description = computed(() => props.isNewApp
  ? '右键画布添加节点，至少添加一个节点后可以首次保存应用。'
  : t('workflowEditor.editor.canvasPlaceholderDescription'))
</script>
