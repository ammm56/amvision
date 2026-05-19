<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'

import AuthShell from '@/shells/auth/AuthShell.vue'
import BlankShell from '@/shells/blank/BlankShell.vue'
import WorkbenchShell from '@/shells/workbench/WorkbenchShell.vue'

const route = useRoute()

const shellComponent = computed(() => {
  if (route.meta.shell === 'auth') {
    return AuthShell
  }
  if (route.meta.shell === 'blank') {
    return BlankShell
  }
  return WorkbenchShell
})
</script>

<template>
  <component :is="shellComponent">
    <RouterView />
  </component>
</template>