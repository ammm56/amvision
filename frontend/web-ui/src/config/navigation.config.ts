export interface NavigationItem {
  labelKey: string
  path: string
  icon: 'FolderKanban' | 'ListChecks' | 'Database' | 'Cpu' | 'Rocket' | 'Activity' | 'Workflow' | 'Cable' | 'Blocks' | 'Settings'
  requiredScopes: string[]
}

export const navigationItems: NavigationItem[] = [
  { labelKey: 'navigation.projects', path: '/projects', icon: 'FolderKanban', requiredScopes: ['workflows:read', 'models:read'] },
  { labelKey: 'navigation.tasks', path: '/tasks', icon: 'ListChecks', requiredScopes: ['tasks:read'] },
  { labelKey: 'navigation.datasets', path: '/datasets', icon: 'Database', requiredScopes: ['datasets:read'] },
  { labelKey: 'navigation.models', path: '/models', icon: 'Cpu', requiredScopes: ['models:read'] },
  { labelKey: 'navigation.deployments', path: '/deployments', icon: 'Rocket', requiredScopes: ['models:read'] },
  { labelKey: 'navigation.inference', path: '/inference', icon: 'Activity', requiredScopes: ['models:read'] },
  { labelKey: 'navigation.workflows', path: '/workflows/templates', icon: 'Workflow', requiredScopes: ['workflows:read'] },
  { labelKey: 'navigation.integrations', path: '/integrations/trigger-sources', icon: 'Cable', requiredScopes: ['workflows:read'] },
  { labelKey: 'navigation.nodes', path: '/custom-nodes', icon: 'Blocks', requiredScopes: ['workflows:read'] },
  { labelKey: 'navigation.settings', path: '/settings', icon: 'Settings', requiredScopes: ['auth:read'] },
]