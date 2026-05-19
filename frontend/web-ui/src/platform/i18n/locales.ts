export type SupportedLocale = 'zh-CN' | 'en-US' | 'ja-JP' | 'ko-KR'

export interface LocaleOption {
  locale: SupportedLocale
  label: string
}

export const defaultLocale: SupportedLocale = 'zh-CN'

export const supportedLocaleOptions: LocaleOption[] = [
  { locale: 'zh-CN', label: '中文' },
  { locale: 'en-US', label: 'English' },
  { locale: 'ja-JP', label: '日本語' },
  { locale: 'ko-KR', label: '한국어' },
]

const supportedLocales = new Set<SupportedLocale>(supportedLocaleOptions.map((item) => item.locale))

export function isSupportedLocale(value: string | null): value is SupportedLocale {
  return value !== null && supportedLocales.has(value as SupportedLocale)
}