import { beforeEach, describe, expect, it } from 'vitest'

import { messages, type MessageSchema } from '@/platform/i18n/messages'
import { supportedLocaleOptions } from '@/platform/i18n/locales'

import {
  parseStartupPagePreference,
  readStartupPagePreference,
  STARTUP_PAGE_PREFERENCE_FORMAT_ID,
  STARTUP_PAGE_STORAGE_KEY,
  writeStartupPagePreference,
} from './startup-page-preference'

describe('startup page preference', () => {
  beforeEach(() => localStorage.clear())

  it('uses projects for missing, damaged, or incomplete values', () => {
    expect(parseStartupPagePreference(null)).toEqual({ mode: 'projects' })
    expect(parseStartupPagePreference('{bad-json')).toEqual({ mode: 'projects' })
    expect(parseStartupPagePreference(JSON.stringify({ mode: 'workflow-runtime-app-mode' })))
      .toEqual({ mode: 'projects' })
    expect(parseStartupPagePreference(JSON.stringify({
      format_id: STARTUP_PAGE_PREFERENCE_FORMAT_ID,
      mode: 'workflow-runtime-app-mode',
      workflowRuntimeId: 'runtime',
    })))
      .toEqual({ mode: 'projects' })
  })

  it('normalizes and restores a complete Runtime App Mode target', () => {
    const preference = parseStartupPagePreference(JSON.stringify({
      format_id: STARTUP_PAGE_PREFERENCE_FORMAT_ID,
      mode: 'workflow-runtime-app-mode',
      projectId: ' project-1 ',
      applicationId: ' workflow-app-1 ',
      workflowRuntimeId: ' workflow-runtime-1 ',
    }))

    expect(preference).toEqual({
      mode: 'workflow-runtime-app-mode',
      projectId: 'project-1',
      applicationId: 'workflow-app-1',
      workflowRuntimeId: 'workflow-runtime-1',
    })
  })

  it('writes one atomic value and removes it when restoring defaults', () => {
    writeStartupPagePreference({
      mode: 'workflow-runtime-app-mode',
      projectId: 'project-1',
      applicationId: 'workflow-app-1',
      workflowRuntimeId: 'workflow-runtime-1',
    })
    expect(JSON.parse(localStorage.getItem(STARTUP_PAGE_STORAGE_KEY) ?? '{}')).toMatchObject({
      format_id: STARTUP_PAGE_PREFERENCE_FORMAT_ID,
    })
    expect(readStartupPagePreference()).toMatchObject({ workflowRuntimeId: 'workflow-runtime-1' })

    writeStartupPagePreference({ mode: 'projects' })
    expect(localStorage.getItem(STARTUP_PAGE_STORAGE_KEY)).toBeNull()
    expect(readStartupPagePreference()).toEqual({ mode: 'projects' })
  })

  it('provides complete startup-page labels for every supported locale', () => {
    const requiredKeys = [
      'title',
      'openMode',
      'projects',
      'appMode',
      'project',
      'runtime',
      'selectRuntime',
      'save',
      'restoreDefault',
      'saved',
      'restored',
      'targetUnavailable',
      'targetReset',
      'appModeRequired',
    ]

    for (const { locale } of supportedLocaleOptions) {
      const section = messages[locale]?.startupPage as MessageSchema | undefined
      expect(section, locale).toBeDefined()
      for (const key of requiredKeys) {
        expect(section?.[key], `${locale}.${key}`).toEqual(expect.any(String))
      }
    }
  })
})
