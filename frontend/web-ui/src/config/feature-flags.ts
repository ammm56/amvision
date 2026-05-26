import { getRuntimeConfig } from '@/platform/runtime/runtime-config'

export function isFeatureEnabled(featureName: keyof ReturnType<typeof getRuntimeConfig>['features']): boolean {
  return getRuntimeConfig().features[featureName]
}