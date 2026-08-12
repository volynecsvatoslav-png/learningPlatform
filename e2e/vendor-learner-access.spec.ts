import { expect, test } from '@playwright/test'

test('vendor grants access and one-device learner session is replaced', async ({ browser, request }) => {
  const vendorContext = await browser.newContext()
  const vendor = await vendorContext.newPage()
  await vendor.goto('/vendor/')
  await vendor.getByLabel('Email').fill(process.env.E2E_VENDOR_EMAIL ?? 'owner.manual@example.com')
  await vendor.getByLabel('Пароль').fill(process.env.E2E_VENDOR_PASSWORD ?? 'correct horse battery staple')
  await vendor.getByRole('button', { name: /войти/i }).click()
  await expect(vendor.getByRole('heading', { name: /manual/i })).toBeVisible()
  await vendorContext.close()

  const messages = await request.get('http://localhost:8025/api/v1/messages')
  expect(messages.ok()).toBeTruthy()
  const payload = await messages.json()
  const message = payload.messages?.[0]
  expect(message).toBeTruthy()
  const detail = await request.get(`http://localhost:8025/api/v1/message/${message.ID}`)
  const body = await detail.json()
  const accessUrl = String(body.Text ?? '').match(/http:\/\/localhost:5173\/app\/access\/\S+/)?.[0]
  expect(accessUrl).toBeTruthy()

  const first = await browser.newContext()
  const second = await browser.newContext()
  const firstPage = await first.newPage()
  const secondPage = await second.newPage()
  await firstPage.goto(accessUrl as string)
  await firstPage.getByRole('button', { name: /открыть курс/i }).click()
  await secondPage.goto(accessUrl as string)
  await secondPage.getByRole('button', { name: /открыть курс/i }).click()
  await firstPage.reload()
  await expect(firstPage.getByRole('heading', { name: /сессия открыта на другом устройстве/i })).toBeVisible()
  await expect(secondPage.getByRole('heading', { name: /ваш учебный маршрут/i })).toBeVisible()
  await first.close()
  await second.close()
})
