<template>
  <header class="app-topbar">
    <ProjectSwitcher />
    <UserMenu class="app-topbar__account-fallback" compact />
  </header>
</template>

<script setup lang="ts">
import ProjectSwitcher from './ProjectSwitcher.vue'
import UserMenu from './UserMenu.vue'
</script>
