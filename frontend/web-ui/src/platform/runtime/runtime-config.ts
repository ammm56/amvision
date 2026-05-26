import type { RuntimeConfig } from '@/shared/contracts'

const defaultRuntimeConfig: RuntimeConfig = {
  apiBaseUrl: import.meta.env.VITE_AMVISION_API_BASE_URL || 'http://127.0.0.1:8000/api/v1',
  wsBaseUrl: import.meta.env.VITE_AMVISION_WS_BASE_URL || 'ws://127.0.0.1:8000/ws/v1',
  defaultProjectId: import.meta.env.VITE_AMVISION_DEFAULT_PROJECT_ID || 'project-1',
  auth: {
    autoLoginEnabled: true,
    defaultUsername: 'amvar',
    defaultUserToken: import.meta.env.VITE_AMVISION_DEFAULT_USER_TOKEN || 'amvision-default-user-token',
    manualLoginRequiredKey: 'amvision.web-ui.manual-login-required',
  },
  storage: {
    sessionTokenStorage: 'sessionStorage',
    manualLoginStorage: 'localStorage',
  },
  features: {
    workflowEditor: true,
    customNodeManagement: false,
  },
}

let runtimeConfig: RuntimeConfig = defaultRuntimeConfig

function normalizeRuntimeConfig(rawConfig: Partial<RuntimeConfig>): RuntimeConfig {
  return {
    ...defaultRuntimeConfig,
    ...rawConfig,
    auth: {
      ...defaultRuntimeConfig.auth,
      ...rawConfig.auth,
    },
    storage: {
      ...defaultRuntimeConfig.storage,
      ...rawConfig.storage,
    },
    features: {
      ...defaultRuntimeConfig.features,
      ...rawConfig.features,
    },
  }
}

async function fetchRuntimeConfig(path: string): Promise<Partial<RuntimeConfig> | null> {
  try {
    const response = await fetch(path, { cache: 'no-store' })
    if (!response.ok) {
      return null
    }
    return (await response.json()) as Partial<RuntimeConfig>
  } catch {
    return null
  }
}

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  const paths = import.meta.env.DEV ? ['/runtime-config.local.json', '/runtime-config.json'] : ['/runtime-config.json']
  for (const path of paths) {
    const rawConfig = await fetchRuntimeConfig(path)
    if (rawConfig) {
      runtimeConfig = normalizeRuntimeConfig(rawConfig)
      return runtimeConfig
    }
  }
  runtimeConfig = defaultRuntimeConfig
  return runtimeConfig
}

export function getRuntimeConfig(): RuntimeConfig {
  return runtimeConfig
}