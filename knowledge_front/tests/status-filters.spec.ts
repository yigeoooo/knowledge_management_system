import { expect, test } from '@playwright/test'

const baseId = '00000000-0000-4000-8000-000000000001'
const screens = [
  { path: '/knowledge-bases', component: 'KnowledgeBaseManagement', selector: '.knowledge-bases-filters .el-select', other: 'archived', label: '已归档' },
  { path: '/documents', component: 'DocumentManagement', selector: '.table-toolbar .el-select', other: 'archived', label: '已归档' },
  { path: '/users', component: 'UserManagement', selector: '.users-filters .el-select', other: 'disabled', label: '停用' },
  { path: '/roles', component: 'RoleManagement', selector: '.roles-filters .el-select', other: 'disabled', label: '停用' },
  { path: '/robots', component: 'RobotManagement', selector: '.robots-filters .el-select', other: 'disabled', label: '停用' },
  { path: '/pages', component: 'PageManagement', selector: '.table-toolbar .el-select', other: 'disabled', label: '停用' },
]

for (const screen of screens) {
  test(`${screen.path}: clearing status restores all records`, async ({ page }) => {
    const endpoint = screen.path === '/documents'
      ? `/api/v1/knowledge-bases/${baseId}/documents` : `/api/v1${screen.path}`
    const requests: URL[] = []
    const rows = ['active', screen.other].map((status, index) => ({
      id: `record-${index}`, name: `Fixture ${status}`, code: `fixture_${status}`,
      title: `Fixture ${status}`, username: `fixture_${status}`, display_name: `Fixture ${status}`,
      serial_no: `fixture_${status}`, status, description: '', role_name: 'Test role',
      role_id: 'test-role', is_system: false, user_count: 0, sort_order: index,
      current_version: null, current_version_id: null, knowledge_base_id: baseId,
      created_at: '2026-10-23T00:00:00Z', updated_at: '2026-10-23T00:00:00Z',
    }))
    await page.route('**/api/v1/**', async route => {
      const url = new URL(route.request().url())
      let data: unknown
      if (url.pathname === '/api/v1/auth/refresh') {
        data = {
          access_token: 'test-token',
          user: { id: 'admin', username: 'admin', display_name: 'Admin', role: 'super_admin' },
          pages: screens.map((item, index) => ({
            code: item.component, name: item.component, route_path: item.path,
            route_name: item.component, component_key: item.component,
            page_type: 'menu', sort_order: index, is_visible: true,
          })),
        }
      } else if (url.pathname === endpoint) {
        requests.push(url)
        const status = url.searchParams.get('status')
        const items = status ? rows.filter(row => row.status === status) : rows
        data = { items, total: items.length, page: 1, page_size: 20 }
      } else if (url.pathname === '/api/v1/knowledge-bases') {
        data = { items: [{ id: baseId, name: 'Fixture base', code: 'fixture', status: 'active' }] }
      } else {
        throw new Error(`Unexpected API request: ${url.pathname}`)
      }
      await route.fulfill({ json: { code: 0, message: 'ok', data } })
    })

    await page.goto(screen.path)
    const tableRows = page.locator('.el-table__body-wrapper tr')
    await expect(tableRows).toHaveCount(2)
    expect(requests.at(-1)?.searchParams.has('status')).toBe(false)
    const select = page.locator(screen.selector).last()
    await select.click()
    await page.getByRole('option', { name: screen.label, exact: true }).click()
    await expect(tableRows).toHaveCount(1)
    expect(requests.at(-1)?.searchParams.get('status')).toBe(screen.other)

    await select.hover()
    await select.locator('.el-select__clear').click()
    await expect.poll(() => requests.at(-1)?.searchParams.has('status')).toBe(false)
    await expect(tableRows).toHaveCount(2)
    await expect(page.locator('.el-alert--error')).toHaveCount(0)

    const refreshResponse = page.waitForResponse(response => new URL(response.url()).pathname === endpoint)
    await page.getByRole('button', { name: /刷新/ }).click()
    await refreshResponse
    await expect(tableRows).toHaveCount(2)
    expect(requests.at(-1)?.searchParams.has('status')).toBe(false)

    const keyword = page.locator('.resource-card .el-input input').first()
    await keyword.fill('Fixture')
    await keyword.press('Enter')
    await expect.poll(() => requests.at(-1)?.searchParams.get('q')).toBe('Fixture')
    await select.click()
    await page.getByRole('option', { name: screen.path === '/documents' ? '有效' : '启用', exact: true }).click()
    await expect(tableRows).toHaveCount(1)
    expect(requests.at(-1)?.searchParams.get('status')).toBe('active')
    await select.hover()
    await select.locator('.el-select__clear').click()
    await expect(tableRows).toHaveCount(2)
    expect(requests.at(-1)?.searchParams.get('q')).toBe('Fixture')
    expect(requests.at(-1)?.searchParams.has('status')).toBe(false)

    const reset = page.getByRole('button', { name: '重置', exact: true })
    if (await reset.count()) {
      await select.click()
      await page.getByRole('option', { name: screen.label, exact: true }).click()
      await expect(tableRows).toHaveCount(1)
      await reset.click()
      await expect(tableRows).toHaveCount(2)
      expect(requests.at(-1)?.searchParams.has('status')).toBe(false)
      expect(requests.at(-1)?.searchParams.has('q')).toBe(false)
    }
  })
}
