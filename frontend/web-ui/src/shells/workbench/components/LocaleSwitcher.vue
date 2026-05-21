<template>
  <label class="locale-switcher">
    <Languages :size="15" />
    <span>{{ t('preferences.language') }}</span>
    <SelectField :model-value="preferencesStore.locale" :options="localeOptions" :placeholder="t('preferences.language')" @update:model-value="updateLocale" />
  </label>
</template>

<script setup lang="ts">
import { Languages } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { usePreferencesStore } from '@/app/stores/preferences.store'
import SelectField from '@/shared/ui/components/Select.vue'
import { supportedLocaleOptions, type SupportedLocale } from '@/platform/i18n'

type SelectValue = string | number | boolean | null

const { t } = useI18n()
const preferencesStore = usePreferencesStore()
const localeOptions = supportedLocaleOptions.map((item) => ({ label: item.label, value: item.locale }))

function updateLocale(value: SelectValue): void {
  if (typeof value !== 'string') return
  preferencesStore.setLocale(value as SupportedLocale)
}
</script>