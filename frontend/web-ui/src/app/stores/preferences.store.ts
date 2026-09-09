import { defineStore } from 'pinia'

import { defaultLocale, isSupportedLocale, setI18nLocale, type SupportedLocale } from '@/platform/i18n'
import { readStorageValue, writeStorageValue } from '@/platform/storage/browser-storage'
import { canAccessPage } from '@/platform/auth/page-access'
import type { CurrentUser } from '@/shared/contracts'
import { STARTUP_PAGE_STORAGE_KEY, startupStorageKey } from '../startup/startup-page-preference'
import type { BrowserStorageKind } from '@/shared/contracts'
import {
  createDefaultStartupPagePreference,
  readStartupPagePreference,
  type StartupPagePreference,
  writeStartupPagePreference,
} from '../startup/startup-page-preference'

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
    startupPage: createDefaultStartupPagePreference(),
    startupPrincipalId: null as string | null,
  }),
  actions: {
    initializePreferences(): void {
      const storedLocale = readStoredValue(LOCALE_STORAGE_KEY)
      const storedTheme = readStoredValue(THEME_STORAGE_KEY)
      this.locale = isSupportedLocale(storedLocale) ? storedLocale : defaultLocale
      this.theme = isThemeMode(storedTheme) ? storedTheme : 'light'
      this.startupPage = createDefaultStartupPagePreference()
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
    setStartupPrincipal(user: CurrentUser | null): void {
      if (this.startupPrincipalId === (user?.principal_id ?? null)) return
      this.startupPrincipalId = user?.principal_id ?? null
      this.startupPage = createDefaultStartupPagePreference()
      if (!user) return
      this.startupPage = readStartupPagePreference(user.principal_id)
      const key = startupStorageKey(user.principal_id)
      // 只在第一次遇到该账号时迁移合法旧配置；标记避免恢复默认后重复迁移。
      if (!readStorageValue(`${key}.migrated`, 'localStorage')) {
        if (!readStorageValue(key, 'localStorage') && readStorageValue(STARTUP_PAGE_STORAGE_KEY, 'localStorage')) {
          const old = readStartupPagePreference()
          if (old.mode === 'projects' && canAccessPage(user, 'projects') || old.mode === 'workflow-runtime-app-mode' && canAccessPage(user, 'workflow-app-mode') && (!user.project_ids.length || user.project_ids.includes(old.projectId))) {
            this.startupPage = old
            writeStartupPagePreference(old, user.principal_id)
          }
        }
        writeStorageValue(`${key}.migrated`, 'true', 'localStorage')
      }
    },
    setStartupPage(preference: StartupPagePreference): void {
      this.startupPage = preference
      if (this.startupPrincipalId) writeStartupPagePreference(preference, this.startupPrincipalId)
    },
    resetStartupPage(): void {
      this.setStartupPage(createDefaultStartupPagePreference())
    },
  },
})
