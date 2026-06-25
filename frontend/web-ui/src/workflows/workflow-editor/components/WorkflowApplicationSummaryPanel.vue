<template>
  <div class="workflow-graph-inspector-body">
    <div class="workflow-graph-inspector-row">
      <span>应用</span>
      <strong>{{ applicationId }}</strong>
    </div>
    <div class="workflow-graph-inspector-row">
      <span>应用输入</span>
      <strong>{{ templateInputText || emptyText }}</strong>
    </div>
    <div class="workflow-graph-inspector-row">
      <span>应用输出</span>
      <strong>{{ templateOutputText || emptyText }}</strong>
    </div>
    <div v-if="previewRunText" class="workflow-graph-inspector-row">
      <span>Preview run</span>
      <strong>{{ previewRunText }}</strong>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  applicationId: string
  templateInputText: string
  templateOutputText: string
  emptyText: string
  previewRunText: string | null
}>()
</script>
