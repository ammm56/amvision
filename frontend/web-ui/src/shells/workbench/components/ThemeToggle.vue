<script setup lang="ts">
import { Moon, Sun } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { usePreferencesStore, type ThemeMode } from '@/app/stores/preferences.store'

const { t } = useI18n()
const preferencesStore = usePreferencesStore()

function setTheme(theme: ThemeMode): void {
  preferencesStore.setTheme(theme)
}
</script>

<template>
  <div class="theme-toggle" :aria-label="t('preferences.theme')">
    <button
      type="button"
      :aria-pressed="preferencesStore.theme === 'light'"
      :title="t('preferences.light')"
      :class="{ 'is-active': preferencesStore.theme === 'light' }"
      @click="setTheme('light')"
    >
      <Sun :size="15" />
      <span>{{ t('preferences.light') }}</span>
    </button>
    <button
      type="button"
      :aria-pressed="preferencesStore.theme === 'dark'"
      :title="t('preferences.dark')"
      :class="{ 'is-active': preferencesStore.theme === 'dark' }"
      @click="setTheme('dark')"
    >
      <Moon :size="15" />
      <span>{{ t('preferences.dark') }}</span>
    </button>
  </div>
</template>