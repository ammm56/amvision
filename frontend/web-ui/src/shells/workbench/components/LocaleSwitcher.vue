<script setup lang="ts">
import { Languages } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { usePreferencesStore } from '@/app/stores/preferences.store'
import { supportedLocaleOptions, type SupportedLocale } from '@/platform/i18n'

const { t } = useI18n()
const preferencesStore = usePreferencesStore()

function updateLocale(event: Event): void {
  preferencesStore.setLocale((event.target as HTMLSelectElement).value as SupportedLocale)
}
</script>

<template>
  <label class="locale-switcher">
    <Languages :size="15" />
    <span>{{ t('preferences.language') }}</span>
    <select :aria-label="t('preferences.language')" :value="preferencesStore.locale" @change="updateLocale">
      <option v-for="item in supportedLocaleOptions" :key="item.locale" :value="item.locale">
        {{ item.label }}
      </option>
    </select>
  </label>
</template>