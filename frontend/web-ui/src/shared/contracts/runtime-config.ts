export type BrowserStorageKind = 'localStorage' | 'sessionStorage' | 'memory'

export interface RuntimeAuthConfig {
  autoLoginEnabled: boolean
  defaultUsername: string
  defaultUserToken: string | null
  manualLoginRequiredKey: string
}

export interface RuntimeStorageConfig {
  sessionTokenStorage: BrowserStorageKind
  manualLoginStorage: BrowserStorageKind
}

export interface RuntimeFeatureFlags {
  workflowEditor: boolean
  customNodeManagement: boolean
}

export interface RuntimeConfig {
  apiBaseUrl: string
  wsBaseUrl: string
  defaultProjectId: string
  auth: RuntimeAuthConfig
  storage: RuntimeStorageConfig
  features: RuntimeFeatureFlags
}