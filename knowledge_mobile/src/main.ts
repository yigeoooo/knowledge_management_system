import { createApp } from 'vue'
import { ActionSheet, Button, Cell, CellGroup, Checkbox, CheckboxGroup, Empty, Field, Form, Icon, Pagination, Popup, Search, Tabbar, TabbarItem, Tag, Locale } from 'vant'
import zhCN from 'vant/es/locale/lang/zh-CN'
import 'vant/lib/index.css'
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
Locale.use('zh-CN', zhCN)
const app = createApp(App)
for (const component of [ActionSheet, Button, Cell, CellGroup, Checkbox, CheckboxGroup, Empty, Field, Form, Icon, Pagination, Popup, Search, Tabbar, TabbarItem, Tag]) app.use(component)
app.provide('sourceMediaPreview', false).use(ElementPlus, { locale: zhCn }).use(router).mount('#app')
