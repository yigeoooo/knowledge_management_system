import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import '@web/style.css'
import './mobile.css'
import { configureClient } from '@web/lib/session'
import { supported } from './pages'
import { send } from './network'
import { router } from './router'
import App from './Shell.vue'

configureClient(send, supported)
createApp(App).provide('sourceMediaPreview', false).use(ElementPlus, { locale: zhCn }).use(router).mount('#app')
