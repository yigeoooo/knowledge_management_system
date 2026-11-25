import { expect, test } from '@playwright/test'

test('robot list and detail show saved city and timezone', async ({ page }) => {
  const robot = { id: 'r1', serial_no: 'w1-025-177', name: 'W1导览机器人', description: '导览', status: 'active', knowledge_base_id: 'k1', knowledge_base_name: '知识库', binding_version: 1, default_location: '101271101', default_location_name: '四川省 / 宜宾市', timezone: 'Asia/Shanghai', created_at: '2026-11-13T00:00:00Z', updated_at: '2026-11-13T00:00:00Z', last_request_at: null }
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown
    if (path.endsWith('/auth/refresh')) data = { access_token: 'test', user: { display_name: '管理员' }, pages: [{ code: 'robots', name: '机器人管理', route_path: '/robots', route_name: 'RobotManagement', component_key: 'RobotManagement', page_type: 'menu', is_visible: true }] }
    else if (path.endsWith('/robots/knowledge-base-options')) data = { items: [{ id: 'k1', name: '知识库' }] }
    else if (path.endsWith('/robots/r1')) data = robot
    else if (path.endsWith('/robots')) data = { items: [robot], total: 1 }
    else return route.fulfill({ status: 404, json: { message: 'unexpected' } })
    await route.fulfill({ json: { code: 0, data } })
  })
  await page.goto('/robots')
  const row = page.getByRole('row').filter({ hasText: 'W1导览机器人' })
  await expect(row).toContainText('四川省 / 宜宾市')
  await expect(row).toContainText('北京时间（Asia/Shanghai）')
  await row.getByRole('button', { name: '详情' }).click()
  const dialog = page.getByRole('dialog', { name: '机器人详情' })
  await expect(dialog).toContainText('绑定城市')
  await expect(dialog).toContainText('四川省 / 宜宾市')
  await expect(dialog).toContainText('北京时间（Asia/Shanghai）')
})
