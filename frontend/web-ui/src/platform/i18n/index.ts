import type { App } from 'vue'
import { createI18n } from 'vue-i18n'

import { defaultLocale, type SupportedLocale } from './locales'
import { messages, type MessageSchema } from './messages'

export const i18n = createI18n({
  legacy: false,
  locale: defaultLocale,
  fallbackLocale: defaultLocale,
  messages: messages as Record<string, MessageSchema>,
})

export function installI18n(app: App): void {
  app.use(i18n)
}

export function setI18nLocale(locale: SupportedLocale): void {
  const globalScope = i18n.global as unknown as { locale: SupportedLocale | { value: SupportedLocale } }
  if (typeof globalScope.locale === 'string') {
    globalScope.locale = locale
    return
  }
  globalScope.locale.value = locale
}

export function translate(key: string, params?: Record<string, string | number>): string {
  return params ? i18n.global.t(key, params) : i18n.global.t(key)
}

export function useTranslation(): {
  t: (key: string, params?: Record<string, string | number>) => string
} {
  return {
    t(key, params) {
      void i18n.global.locale.value
      return translate(key, params)
    },
  }
}

export { defaultLocale, isSupportedLocale, supportedLocaleOptions, type SupportedLocale } from './locales'
