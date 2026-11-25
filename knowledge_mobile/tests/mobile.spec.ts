import { test, expect } from '@playwright/test'

const routes = [
  ['Dashboard','/dashboard','工作台'],['KnowledgeQA','/qa','知识问答'],['RobotQA','/robot-qa','机器人问答'],
  ['RobotManagement','/robots','机器人管理'],['UserManagement','/users','用户管理'],['RoleManagement','/roles','角色管理'],
  ['PageManagement','/pages','页面路由'],['RolePermissions','/role-permissions','角色权限'],['QALogs','/qa-logs','问答日志'],
  ['AuditLogs','/audit-logs','审计日志'],['Profile','/profile','个人信息'],['DocumentManagement','/documents','文档管理'],
  ['DocumentCreate','/create-document','创建文档'],['KnowledgeBaseManagement','/knowledge-bases','知识库管理'],
  ['PromptManagement','/prompts','提示词管理'],['EvaluationManagement','/evaluations','质量测评'],
]
for (const role of ['admin','reader']) {
  test(role + ' uses authorized mobile routes and cannot open excluded pages', async ({ page }, info) => {
    let authenticated = false
    const identity = { user:{id:'fixture',display_name:role === 'admin' ? '林川':'周晨',role_name:role},access_token:'fixture',
      pages: routes.filter(([key]) => role === 'admin' || ['KnowledgeQA','Profile'].includes(key)).map(([key,path,name],i) =>
        ({component_key:key,route_path:path,name,code:key,page_type:'menu',is_visible:true,sort_order:i})) }
    const conversation = {id:'cid',title:'设备启动说明',knowledge_base_id:'kb',knowledge_base_status:'active',turn_count:1,last_turn_no:1}
    const turn = {id:'tid',question:'如何启动？',answer:'请检查电源。',status:'SUCCESS',sources:[],created_at:new Date().toISOString()}
    const errors: string[] = []
    page.on('pageerror',e => errors.push(e.message))
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      let data: unknown = {items:[],total:0}
      if (path.endsWith('/auth/login')) authenticated = true
      if (path.includes('/auth/')) {
        if (!authenticated) return route.fulfill({status:401,json:{code:401,message:'请登录'}})
        data = identity
      } else if (path.endsWith('/dashboard')) data = {user_count:8,robot_count:2}
      else if (path.endsWith('/users')) data = {items:[
        {id:'fixture',display_name:'林川',username:'admin',role_name:'管理员',status:'active'},
        {id:'reader',display_name:'周晨',username:'reader',role_name:'普通用户',status:'active'},
      ],total:2}
      else if (path.endsWith('/admin/qa-users')) data = {items:[{id:'one',name:'周晨',conversation_count:1}],total:1}
      else if (path.endsWith('/knowledge-bases')) data = {items:[{id:'kb',name:'设备资料'}],total:1}
      else if (path.endsWith('/web/suggested-questions')) data = {questions:[]}
      else if (path.endsWith('/turns')) data = {items:[turn],conversation,next_before:null}
      else if (path.endsWith('conversations')) data = {items:[conversation],next_cursor:null}
      if (path.endsWith('/export')) errors.push('Unexpected export')
      return route.fulfill({json:{code:0,data}})
    })
    await page.goto('/')
    await page.getByLabel('用户名').fill(role)
    await page.locator('input[name=password]').fill('fixture')
    await page.screenshot({path:info.outputPath('login.png')})
    await page.getByRole('button',{name:'登录',exact:true}).click()
    if (role === 'admin') {
      await expect(page.getByRole('heading',{name:'林川的工作台'})).toBeVisible()
      await page.screenshot({path:info.outputPath('workbench.png')})
      await page.getByRole('link',{name:/用户管理/}).click()
      const more = page.getByRole('button',{name:'林川的操作'})
      for (const width of [320,390,900]) {
        await page.setViewportSize({width,height:844})
        await expect(more).toBeInViewport()
        expect(await page.locator('.phone-content').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
        await expect(page.locator('.el-table')).toHaveCount(0)
      }
      await page.setViewportSize({width:390,height:844})
      await page.screenshot({path:info.outputPath('users.png')})
      await more.click()
      const sheet = page.locator('.van-action-sheet:visible')
      await expect(sheet.getByRole('button',{name:'删除'})).toHaveClass(/disabled/)
      await expect(sheet.getByRole('button',{name:'停用账号'})).toHaveClass(/disabled/)
      await sheet.getByRole('button',{name:'取消'}).click()
      await page.getByRole('button',{name:'周晨的操作'}).click()
      await expect(sheet.getByRole('button',{name:'停用账号'})).not.toHaveClass(/disabled/)
      await sheet.getByRole('button',{name:'取消'}).click()
      await page.goto('/#/qa-logs')
      await page.locator('.owner-item').click()
      await page.locator('.audit-conversation').click()
      await expect(page.locator('.conversation-answer')).toContainText(turn.answer)
      await expect(page.getByRole('button',{name:/导出/})).toHaveCount(0)
      await page.getByRole('button',{name:'返回会话列表'}).click()
      await expect(page.locator('.audit-conversation')).toBeVisible()
      await page.getByRole('button',{name:'返回用户列表'}).click()
      await expect(page.locator('.owner-item')).toBeVisible()
    } else {
      await page.getByRole('button',{name:'展开历史侧栏'}).click()
      await page.locator('.history-open').click()
      await expect(page.locator('.conversation-answer')).toContainText(turn.answer)
      await page.reload()
      await expect(page.locator('.conversation-answer')).toContainText(turn.answer)
      await expect(page.getByRole('textbox',{name:'你的问题'})).toBeInViewport()
    }
    await page.getByRole('tab',{name:'全部功能'}).click()
    await expect(page.locator('.features a')).toHaveCount(role === 'admin' ? 11 : 2)
    await page.getByRole('button',{name:'关闭菜单'}).click()
    for (const [,path] of routes.slice(11)) {
      await page.goto('/#'+path)
      await expect(page).toHaveURL(/#\/403$/)
    }
    if (role === 'reader') { await page.goto('/#/users'); await expect(page).toHaveURL(/#\/403$/) }
    expect(errors).toEqual([])
  })
}


test('手机筛选回显选中值，长标签与结果在窄屏可见', async ({ page }, info) => {
  const adminPages = routes.slice(3,6).map(([key,path,name]) => ({
    component_key:key,route_path:path,name,code:key,page_type:'menu',is_visible:true,sort_order:0,
  }))
  const kb = '设备安装与维护知识库'
  const requests: URL[] = []
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    requests.push(url)
    let data: unknown = {items:[],total:0}
    if (url.pathname.includes('/auth/')) data = {user:{id:'fixture',display_name:'测试'},pages:adminPages,access_token:'fixture'}
    if (url.pathname.endsWith('/knowledge-base-options')) data = {items:[{id:'base-1',name:kb}]}
    return route.fulfill({json:{code:0,data}})
  })
  for (const width of [320,375,430]) {
    await page.setViewportSize({width,height:812})
    await page.goto('/#/robots')
    await page.getByRole('button',{name:'知识库，全部知识库'}).click()
    await page.getByRole('button',{name:kb,exact:true}).click()
    await page.getByRole('button',{name:'状态，全部状态'}).click()
    await page.getByRole('button',{name:'停用',exact:true}).click()
    for (const value of [kb,'停用']) {
      const label = page.locator('.choice-trigger span').filter({hasText:value})
      await expect(label).toBeInViewport()
      expect(await label.evaluate(el => el.clientWidth > 24 && el.scrollWidth <= el.clientWidth)).toBe(true)
    }
    const lastQuery = () => requests.filter(u=>u.pathname.endsWith('/robots')).at(-1)?.searchParams
    await expect.poll(() => [lastQuery()?.get('knowledge_base_id'),lastQuery()?.get('status')]).toEqual(['base-1','disabled'])
    if (width === 375) await page.screenshot({path:info.outputPath('robot-filters.png')})
    await page.getByRole('button',{name:'重置',exact:true}).click()
    await expect(page.getByRole('button',{name:'知识库，全部知识库'})).toBeVisible()
    await expect.poll(() => lastQuery()?.has('status') || lastQuery()?.has('knowledge_base_id')).toBe(false)
    for (const [path,label,status] of [['users','显示名称','账号状态'],['roles','角色名称或编码','角色状态']]) {
      await page.goto('/#/'+path)
      const input = page.getByPlaceholder('搜索'+label)
      await expect(input).toBeVisible()
      expect(await input.evaluate(el => el.clientWidth)).toBeGreaterThan(150)
      await input.fill('甲')
      await page.getByRole('button',{name:'查询',exact:true}).click()
      await page.getByRole('button',{name:status+'，全部状态'}).click()
      await page.getByRole('button',{name:'启用',exact:true}).click()
      await expect(page.getByRole('button',{name:status+'，启用'})).toBeInViewport()
      await expect.poll(() => requests.some(u=>u.pathname.endsWith('/'+path) && u.searchParams.get('q') === '甲' && u.searchParams.get('status') === 'active')).toBe(true)
      expect(await page.locator('.phone-content').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    }
  }
})
