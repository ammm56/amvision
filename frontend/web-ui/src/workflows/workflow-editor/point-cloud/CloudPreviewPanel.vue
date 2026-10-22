<template>
  <div class="cloud-summary">
    <span>{{ spatial.length_unit || t('unknown') }} · {{ spatial.frame_id || '-' }}</span>
    <span>{{ payload.display_point_count ?? '-' }} / {{ payload.source_point_count ?? '-' }}</span>
    <span v-if="payload.state === 'unavailable'" role="status">{{ payload.reason }}</span>
    <button type="button" :title="t('open')" @click.stop="open = true"><Box :size="16" />{{ t('open') }}</button>
  </div>
  <Teleport to="body">
    <ConfirmDialog v-if="open" :title="t('title')" :cancel-label="t('close')" confirm-label="" :show-confirm="false" size="wide" @cancel="open = false">
      <CloudViewer :payload="payload" :project-id="projectId" />
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { Box } from '@lucide/vue'
import { useI18n } from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
const CloudViewer = defineAsyncComponent(() => import('./CloudViewer.vue'))
const props = defineProps<{ payload: Record<string, unknown>; projectId: string; runId?: string }>()
const open = ref(false)
const spatial = computed(() => (props.payload.spatial || {}) as Record<string, unknown>)
watch(() => [props.payload, props.projectId, props.runId], () => { open.value = false })
const { t } = useI18n({ useScope: 'local', messages: {
  'zh-CN': { title: '3D 点云', open: '查看点云', close: '关闭', unknown: '单位未确认' },
  'en-US': { title: '3D Point Cloud', open: 'View cloud', close: 'Close', unknown: 'Unit unconfirmed' },
} })
</script>
<style scoped>
.cloud-summary { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; padding: 8px; font-size: 12px; min-width: 0; overflow-wrap: anywhere; }
.cloud-summary button { display: flex; align-items: center; gap: 6px; border: 1px solid var(--am-border); background: var(--am-surface); color: var(--am-text); padding: 6px 8px; border-radius: 4px; }
</style>
