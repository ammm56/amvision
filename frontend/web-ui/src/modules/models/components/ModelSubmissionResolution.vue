<template>
  <aside v-if="warningOnly" class="submission-resolution submission-resolution--warning" role="status">
    <CircleAlert :size="22" aria-hidden="true" />
    <div><strong>{{ zh ? '正在确认提交结果' : 'Confirming submission' }}</strong><p>{{ warning }}</p></div>
  </aside>
  <section v-else class="submission-resolution submission-resolution--result" :class="{ 'is-confirmed': status === 'accepted' || status === 'not_created' }" :aria-label="zh ? '提交结果' : 'Submission result'">
    <h3><Info :size="18" aria-hidden="true" />{{ zh ? (sectionNumber ? `${sectionNumber}. 提交结果` : '提交结果') : (sectionNumber ? `${sectionNumber}. Submission result` : 'Submission result') }}</h3>
    <dl aria-live="polite">
      <div><dt>{{ zh ? '当前结果' : 'Current result' }}</dt><dd>{{ result }}</dd></div>
      <div><dt>{{ zh ? '最后查询时间' : 'Last checked' }}</dt><dd>{{ checkedAt ? formatSystemDateTime(checkedAt.toISOString()) : '—' }}</dd></div>
    </dl>
    <p>{{ explanation }}</p>
    <div v-if="available || showList" class="submission-resolution__actions">
      <Button v-if="available" size="sm" type="button" variant="secondary" :disabled="checking || !canCheck" :loading="checking" @click="emit('check')">
        {{ status === 'accepted' ? (zh ? '打开任务' : 'Open task') : (zh ? '查询提交结果' : 'Check submission') }}
      </Button>
      <Button v-if="showList" size="sm" type="button" variant="secondary" @click="emit('view-list')">{{ zh ? '查看任务列表' : 'View task list' }}</Button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { CircleAlert, Info } from '@lucide/vue'
import { computed } from 'vue'
import Button from '@/shared/ui/components/Button.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import type { useModelSubmissionReceipt } from '../composables/useModelSubmissionReceipt'

const props = defineProps<{ receipt: ReturnType<typeof useModelSubmissionReceipt>; zh: boolean; warningOnly?: boolean; canCheck?: boolean; showList?: boolean; sectionNumber?: number }>()
const emit = defineEmits<{ check: []; 'view-list': [] }>()
const { status, available, checkedAt, checking } = props.receipt
const warning = computed(() => props.zh ? '提交响应中断，任务可能已经创建。确认前请勿重复提交。' : 'The response was interrupted. The task may already exist. Check before submitting again.')
const result = computed(() => ({
  unknown: props.zh ? '尚未确认' : 'Unconfirmed',
  failed: props.zh ? '查询失败' : 'Could not check',
  not_created: props.zh ? '未创建' : 'Not created',
  accepted: props.zh ? '任务已创建' : 'Task created',
})[status.value])
const explanation = computed(() => {
  if (status.value === 'not_created') return props.zh ? '服务端已确认未创建任务，可以重新提交。' : 'The server confirmed no task was created. You can submit again.'
  if (status.value === 'accepted') return props.zh ? '已找到本次提交的任务，可打开详情。' : 'The task for this submission is ready to open.'
  if (!available.value) return props.zh ? '这次提交没有查询编号，请在任务列表中查找。' : 'This submission has no receipt number. Look for it in the task list.'
  if (status.value === 'failed') return props.zh ? '暂时无法确认，请恢复连接后再查询。' : 'Check again when the connection is restored.'
  return props.zh ? '查询到任务后打开详情；确认未创建后才可重新提交。' : 'If a task exists, its details open. You can submit again after the server confirms none was created.'
})
</script>

<style scoped>
.submission-resolution {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 20px;
  padding: 12px 16px;
  margin: 0 0 12px;
  border: 1px solid var(--am-warning-border);
  border-radius: 8px;
  background: color-mix(in srgb, var(--am-warning-surface) 64%, var(--am-surface));
  min-width: 0;
}
.submission-resolution.is-confirmed {
  border-color: var(--am-success-border);
  background: var(--am-success-surface);
}
.submission-resolution--warning { color: var(--am-warning-text); gap: 12px; }
.submission-resolution--warning > svg { color: var(--am-warning-icon); flex: none; }
.submission-resolution--warning > div { flex: 1 1 180px; min-width: 0; }
.submission-resolution h3 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 1rem; }
.submission-resolution dl { display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 0; }
.submission-resolution dl div { padding-inline-end: 12px; }
.submission-resolution dd { margin: 2px 0 0; font-weight: 600; }
.submission-resolution dt, .submission-resolution p { font-size: .875rem; margin: 0; }
.submission-resolution--result p { flex: 1 1 176px; }
.submission-resolution__actions { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
