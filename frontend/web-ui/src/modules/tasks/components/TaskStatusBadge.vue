<template>
  <TaskStateBadge :state="rawState" />
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { TaskRecord } from '@/shared/contracts'
import TaskStateBadge from './TaskStateBadge.vue'

const props = defineProps<{ task: TaskRecord }>()
const rawState = computed(() => String(props.task.state || props.task.status || ''))
</script>
