import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.dexforce.knowledge',
  appName: '跨维知识',
  webDir: 'dist',
  loggingBehavior: 'none',
  backgroundColor: '#f7f8fa',
  ios: { contentInset: 'never' },
}
export default config
