/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AMVISION_API_BASE_URL?: string
  readonly VITE_AMVISION_WS_BASE_URL?: string
  readonly VITE_AMVISION_DEFAULT_PROJECT_ID?: string
  readonly VITE_AMVISION_DEFAULT_USER_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}