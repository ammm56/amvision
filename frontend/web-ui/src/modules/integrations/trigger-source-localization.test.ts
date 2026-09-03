import { describe, expect, it } from 'vitest'

import { messages } from '@/platform/i18n/messages'

const localizedFieldKeys = [
  'triggerSourceId',
  'displayName',
  'bindEndpoint',
  'webhookPath',
  'directoryPath',
  'recursive',
  'includeHidden',
  'globPattern',
  'extensions',
  'eventTypes',
  'resultBindings',
  'submitAndAck',
  'directory',
  'fileFilter',
  'intervalAndSamples',
  'submitMode',
  'resultMode',
  'ackPolicy',
  'replyTimeoutSeconds',
  'debounceWindowMs',
  'minTriggerIntervalSeconds',
  'eventSampleLimit',
  'forcePolling',
  'pollDelayMs',
  'ignorePermissionDenied',
  'idempotencyKeyPath',
  'sourcePath',
] as const

const expectedLabels = {
  'zh-CN': {
    triggerSourceId: '触发入口 ID',
    displayName: '显示名称',
    directoryPath: '监控目录',
    minTriggerIntervalSeconds: '最小触发间隔（秒）',
    sourcePath: '来源路径',
  },
  'en-US': {
    triggerSourceId: 'Trigger source ID',
    displayName: 'Display name',
    directoryPath: 'Watched directory',
    minTriggerIntervalSeconds: 'Minimum trigger interval (seconds)',
    sourcePath: 'Source path',
  },
  'ja-JP': {
    triggerSourceId: 'トリガー入口 ID',
    displayName: '表示名',
    directoryPath: '監視ディレクトリ',
    minTriggerIntervalSeconds: '最小トリガー間隔（秒）',
    sourcePath: 'ソースパス',
  },
  'ko-KR': {
    triggerSourceId: '트리거 진입점 ID',
    displayName: '표시 이름',
    directoryPath: '감시 디렉터리',
    minTriggerIntervalSeconds: '최소 트리거 간격(초)',
    sourcePath: '소스 경로',
  },
} as const

describe('TriggerSource 页面字段本地化', () => {
  it.each(Object.entries(expectedLabels))('%s 提供对应语言的配置字段名称', (locale, expected) => {
    const localeMessages = messages[locale] as Record<string, unknown>
    const triggerSources = localeMessages.triggerSources as Record<string, unknown>
    const fields = triggerSources.fields as Record<string, unknown>

    expect(fields).toMatchObject(expected)
    expect(Object.keys(fields)).toEqual(expect.arrayContaining([...localizedFieldKeys]))
    for (const fieldKey of localizedFieldKeys) {
      expect(fields[fieldKey]).toEqual(expect.any(String))
      expect((fields[fieldKey] as string).trim()).not.toBe('')
    }
  })
})
