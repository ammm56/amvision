<template>
  <InlineMessage tone="success" :title="title">
    <span class="task-submission-notice__id">{{ identifier }}</span>
    <template v-if="detailTo" #actions>
      <ButtonLink :to="detailTo" size="sm" variant="secondary">
        <ArrowRight :size="14" />
        {{ t('tasks.actions.viewTask') }}
      </ButtonLink>
    </template>
  </InlineMessage>
</template>

<script setup lang="ts">
import { ArrowRight } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import ButtonLink from '@/shared/ui/components/ButtonLink.vue'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'

defineProps<{
  title: string
  identifier: string
  detailTo?: string
}>()

const { t } = useI18n()
</script>

<style scoped>
.task-submission-notice__id {
  font-family: var(--am-font-mono);
  font-size: 12px;
  font-weight: 650;
}
</style>
