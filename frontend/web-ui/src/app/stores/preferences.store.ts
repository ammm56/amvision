import { defineStore } from 'pinia'

import { defaultLocale, isSupportedLocale, setI18nLocale, type SupportedLocale } from '@/platform/i18n'
import { readStorageValue, writeStorageValue } from '@/platform/storage/browser-storage'
import type { BrowserStorageKind } from '@/shared/contracts'

export type ThemeMode = 'light' | 'dark'

const LOCALE_STORAGE_KEY = 'amvision.web-ui.locale'
const THEME_STORAGE_KEY = 'amvision.web-ui.theme'
const PREFERENCE_STORAGE_KIND: BrowserStorageKind = 'localStorage'

function readStoredValue(key: string): string | null {
  return readStorageValue(key, PREFERENCE_STORAGE_KIND)
}

function writeStoredValue(key: string, value: string): void {
  writeStorageValue(key, value, PREFERENCE_STORAGE_KIND)
}

function isThemeMode(value: string | null): value is ThemeMode {
  return value === 'light' || value === 'dark'
}

function applyDocumentLocale(locale: SupportedLocale): void {
  if (typeof document === 'undefined') return
  document.documentElement.lang = locale
}

function applyDocumentTheme(theme: ThemeMode): void {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
}

export const usePreferencesStore = defineStore('preferences', {
  state: () => ({
    locale: defaultLocale as SupportedLocale,
    theme: 'light' as ThemeMode,
  }),
  actions: {
    initializePreferences(): void {
      const storedLocale = readStoredValue(LOCALE_STORAGE_KEY)
      const storedTheme = readStoredValue(THEME_STORAGE_KEY)
      this.locale = isSupportedLocale(storedLocale) ? storedLocale : defaultLocale
      this.theme = isThemeMode(storedTheme) ? storedTheme : 'light'
      setI18nLocale(this.locale)
      applyDocumentLocale(this.locale)
      applyDocumentTheme(this.theme)
    },
    setLocale(locale: SupportedLocale): void {
      this.locale = locale
      setI18nLocale(locale)
      applyDocumentLocale(locale)
      writeStoredValue(LOCALE_STORAGE_KEY, locale)
    },
    setTheme(theme: ThemeMode): void {
      this.theme = theme
      applyDocumentTheme(theme)
      writeStoredValue(THEME_STORAGE_KEY, theme)
    },
  },
})