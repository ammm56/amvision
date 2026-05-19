<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { Lock, WifiOff } from '@lucide/vue'

const props = defineProps<{
  kind?: 'forbidden' | 'offline'
}>()
</script>

<template>
  <section class="error-view">
    <Lock v-if="props.kind === 'forbidden'" :size="36" />
    <WifiOff v-else :size="36" />
    <h1>{{ props.kind === 'forbidden' ? '权限不足' : '后端不可用' }}</h1>
    <p>{{ props.kind === 'forbidden' ? '当前主体没有访问该页面所需的 scope。' : '请确认 backend-service 已启动。' }}</p>
    <RouterLink to="/projects">返回工作台</RouterLink>
  </section>
</template>