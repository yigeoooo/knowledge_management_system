import { expect, test } from '@playwright/test'

test('角色权限分组保留必选授权，并按当前角色保存修改', async ({ page }) => {
  const resources = [
    { id:'home', code:'dashboard', name:'工作台', route_path:'/dashboard', status:'active' },
    { id:'docs', code:'documents', name:'文档管理', route_path:'/documents', status:'disabled' },
    { id:'custom', code:'custom', name:'自定义页面', route_path:'/custom', status:'active' },
  ].map((item,i) => ({ ...item, sort_order:i, page_type:'menu' }))
  const grants: Record<string,string[]> = { admin:['home','docs','custom'], reader:['home'] }
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path.endsWith('/auth/refresh')) data = {
      user:{ id:'fixture', display_name:'测试' }, access_token:'fixture',
      pages:[{ component_key:'RolePermissions', route_path:'/role-permissions', name:'角色页面权限', code:'permissions', page_type:'menu', is_visible:true }],
    }
    else if (path.endsWith('/roles')) data = { items:[
      { id:'admin', name:'超级管理员', code:'super_admin', status:'active' },
      { id:'reader', name:'普通用户', code:'user', status:'active' },
    ], total:2 }
    else if (path === '/api/v1/pages') data = { items:resources, total:resources.length }
    else {
      const id = path.split('/').at(-2)!
      if (route.request().method() === 'PUT') grants[id] = route.request().postDataJSON().page_ids
      data = { page_ids:grants[id] }
    }
    return route.fulfill({ json:{code:0,data} })
  })
  await page.setViewportSize({width:320,height:680})
  await page.goto('/#/role-permissions')
  const save = page.getByRole('button',{name:'保存',exact:true})
  const home = page.getByRole('checkbox',{name:/工作台/})
  await expect(home).toBeDisabled()
  await page.getByRole('button',{name:'清空'}).click()
  await expect(home).toBeChecked()
  await save.click()
  await expect.poll(() => grants.admin.slice().sort()).toEqual(['custom','home'])
  await page.getByRole('button',{name:'选择角色，超级管理员'}).click()
  await page.getByRole('button',{name:'普通用户',exact:true}).click()
  await expect(home).toBeEnabled()
  await page.locator('summary').filter({hasText:'其他页面'}).click()
  await page.getByRole('checkbox',{name:/自定义页面/}).click()
  await save.click()
  await expect.poll(() => grants.reader.slice().sort()).toEqual(['custom','home'])
  await expect(save).toBeDisabled()
  expect(await page.locator('.phone-content').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
})
