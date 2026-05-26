import type { SupportedLocale } from '@/platform/i18n'

import type { NodeDefinition, NodeParameterUiField, NodePortDefinition, WorkflowJsonObject } from './types'

type LocalizedTextMap = Record<string, string>

const localeAliases: Record<string, string[]> = {
  'zh-CN': ['zh-CN', 'zh'],
  'en-US': ['en-US', 'en'],
  'ja-JP': ['ja-JP', 'ja'],
  'ko-KR': ['ko-KR', 'ko'],
}

export function resolveNodeDefinitionDisplayName(definition: NodeDefinition, locale: SupportedLocale): string {
  return resolveLocalizedText(readNodeMetadataLocalization(definition.metadata, 'display_name'), definition.display_name, locale)
}

export function resolveNodeDefinitionDescription(definition: NodeDefinition, locale: SupportedLocale): string {
  return resolveLocalizedText(readNodeMetadataLocalization(definition.metadata, 'description'), definition.description, locale)
}

export function resolveNodePortDisplayName(port: NodePortDefinition, locale: SupportedLocale): string {
  return resolveLocalizedText(readNodeMetadataLocalization(port.metadata, 'display_name'), port.display_name, locale) || port.name
}

export function resolveNodePortDescription(port: NodePortDefinition, locale: SupportedLocale): string {
  return resolveLocalizedText(readNodeMetadataLocalization(port.metadata, 'description'), port.description, locale)
}

export function resolveNodeParameterDisplayName(field: NodeParameterUiField, locale: SupportedLocale): string {
  return resolveLocalizedText(readParameterSchemaLocalization(field, 'title'), field.display_name, locale) || field.parameter_name
}

export function resolveNodeParameterDescription(field: NodeParameterUiField, locale: SupportedLocale): string {
  return resolveLocalizedText(readParameterSchemaLocalization(field, 'description'), field.description, locale)
}

function readNodeMetadataLocalization(metadata: WorkflowJsonObject, key: 'display_name' | 'description'): unknown {
  const localizedKey = `localized_${key}`
  if (localizedKey in metadata) return metadata[localizedKey]
  const i18n = metadata.i18n
  if (isWorkflowJsonObject(i18n) && key in i18n) return i18n[key]
  const localizations = metadata.localizations
  if (isWorkflowJsonObject(localizations) && key in localizations) return localizations[key]
  return null
}

function readParameterSchemaLocalization(field: NodeParameterUiField, key: 'title' | 'description'): unknown {
  const localization = field.json_schema['x-amvision-i18n']
  if (!isWorkflowJsonObject(localization) || !(key in localization)) return null
  return localization[key]
}

function resolveLocalizedText(localizedValue: unknown, fallbackValue: unknown, locale: SupportedLocale): string {
  const localizedMap = readLocalizedTextMap(localizedValue)
  for (const candidateLocale of buildLocaleFallbackChain(locale)) {
    const localizedText = normalizeText(localizedMap[candidateLocale])
    if (localizedText) return localizedText
  }
  const fallbackText = normalizeText(fallbackValue)
  if (fallbackText) return fallbackText
  for (const localizedText of Object.values(localizedMap)) {
    const normalizedText = normalizeText(localizedText)
    if (normalizedText) return normalizedText
  }
  return ''
}

function buildLocaleFallbackChain(locale: SupportedLocale): string[] {
  const chain = [locale, ...(localeAliases[locale] ?? [])]
  if (locale !== 'en-US') chain.push('en-US', 'en')
  if (locale !== 'zh-CN') chain.push('zh-CN', 'zh')
  return [...new Set(chain)]
}

function readLocalizedTextMap(value: unknown): LocalizedTextMap {
  if (!isWorkflowJsonObject(value)) return {}
  const localizedTexts: LocalizedTextMap = {}
  for (const [locale, text] of Object.entries(value)) {
    const normalizedText = normalizeText(text)
    if (normalizedText) localizedTexts[locale] = normalizedText
  }
  return localizedTexts
}

function normalizeText(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function isWorkflowJsonObject(value: unknown): value is WorkflowJsonObject {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}