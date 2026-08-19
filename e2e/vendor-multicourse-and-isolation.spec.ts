import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

type MailpitMessage = {
  ID: string
  Subject: string
  To: Array<{ Address: string }>
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required; run bootstrap_e2e_owner first.`)
  return value
}

async function waitForMail(
  request: APIRequestContext,
  mailpitURL: string,
  recipient: string,
  subject: string,
): Promise<MailpitMessage> {
  let matches: MailpitMessage[] = []
  const searchURL = new URL('/api/v1/search', mailpitURL)
  searchURL.searchParams.set('query', `to:${recipient}`)

  await expect.poll(async () => {
    const response = await request.get(searchURL.toString())
    expect(response.ok()).toBeTruthy()
    const payload = await response.json() as { messages?: MailpitMessage[] }
    matches = (payload.messages ?? []).filter((message) =>
      message.Subject === subject
      && message.To.length === 1
      && message.To[0]?.Address.toLowerCase() === recipient.toLowerCase(),
    )
    return matches.length
  }, { message: `waiting for one email "${subject}" to ${recipient}`, timeout: 30_000 }).toBe(1)

  return matches[0]
}

async function mailURL(request: APIRequestContext, mailpitURL: string, message: MailpitMessage): Promise<URL> {
  const detail = await request.get(new URL(`/api/v1/message/${encodeURIComponent(message.ID)}`, mailpitURL).toString())
  expect(detail.ok()).toBeTruthy()
  const body = await detail.json() as { Text?: string }
  const match = body.Text?.match(/https?:\/\/[^\s]+\/app\/[^\s]*/)?.[0]
  expect(match).toBeTruthy()
  return new URL(match as string)
}

async function loginVendor(page: Page, ownerEmail: string, ownerPassword: string, vendorName: string): Promise<void> {
  await page.goto('/vendor/')
  await page.getByLabel('Email').fill(ownerEmail)
  await page.getByLabel('Пароль').fill(ownerPassword)
  await page.getByRole('button', { name: /^Войти/ }).click()
  await expect(page.getByRole('heading', { name: vendorName })).toBeVisible()
}

async function createPublishedCourse(
  page: Page,
  names: { course: string; module: string; lesson: string; content: string },
): Promise<void> {
  await page.getByRole('button', { name: /Новый курс/ }).click()
  await page.getByLabel('Название').fill(names.course)
  await page.getByLabel('Slug').fill(`e2e-${names.course.replace(/\W+/g, '-').toLowerCase()}`)
  await page.getByLabel('Описание Markdown').fill(`Description ${names.course}`)
  const [courseResponse] = await Promise.all([
    page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && response.url().includes('/api/v1/vendor/courses?vendor_id='),
    ),
    page.getByRole('button', { name: 'Сохранить курс' }).click(),
  ])
  expect(courseResponse.ok()).toBeTruthy()

  const courseRow = page.getByRole('button', { name: new RegExp(names.course) })
  await expect(courseRow).toBeVisible()
  await courseRow.click()

  await page.getByPlaceholder('Новый модуль').fill(names.module)
  const [moduleResponse] = await Promise.all([
    page.waitForResponse((response) =>
      response.request().method() === 'POST' && response.url().endsWith('/structure'),
    ),
    page.getByRole('button', { name: 'Добавить модуль' }).click(),
  ])
  expect(moduleResponse.ok()).toBeTruthy()

  await page.getByLabel(`Новый урок в ${names.module}`).fill(names.lesson)
  const lessonResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/structure'),
  )
  await page.getByRole('button', { name: 'Добавить урок' }).click()
  expect((await lessonResponsePromise).ok()).toBeTruthy()
  const lessonRow = page.locator('.tree-child').filter({ hasText: names.lesson })
  await expect(lessonRow).toBeVisible()
  await lessonRow.getByRole('button', { name: 'Редактировать' }).click()

  const newContent = lessonRow.getByRole('heading', { name: 'Новый контент-блок' }).locator('..')
  await newContent.getByLabel('Название').fill(names.content)
  await newContent.getByLabel('Markdown').fill(`# ${names.content}`)
  const contentResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/structure'),
  )
  await newContent.getByRole('button', { name: 'Добавить блок' }).click()
  expect((await contentResponsePromise).ok()).toBeTruthy()

  const lessonPublishResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/structure'),
  )
  await lessonRow.getByRole('button', { name: 'Опубликовать урок' }).click()
  expect((await lessonPublishResponsePromise).ok()).toBeTruthy()
  await expect(lessonRow.getByText('Опубликован в следующей ревизии')).toBeVisible()

  const publishResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/publish'),
  )
  await page.getByRole('button', { name: /Опубликовать ревизию/ }).click()
  expect((await publishResponsePromise).ok()).toBeTruthy()
  await page.getByRole('button', { name: 'Закрыть' }).click()
  await expect(page.getByRole('button', { name: new RegExp(`${names.course}.*published`) })).toBeVisible()
}

async function grantAccess(page: Page, learnerEmail: string, courseTitles: string[]): Promise<void> {
  const accessPanel = page.getByRole('heading', { name: 'Ученики' }).locator('..')
  await accessPanel.getByPlaceholder('email ученика').fill(learnerEmail)
  await accessPanel.locator('select').selectOption(courseTitles.map((title) => ({ label: title })))
  const grantResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/api/v1/vendor/access/grant'),
  )
  await accessPanel.getByRole('button', { name: 'Выдать доступ' }).click()
  expect((await grantResponsePromise).ok()).toBeTruthy()
  await expect(accessPanel.getByText(learnerEmail, { exact: true })).toHaveCount(courseTitles.length)
}

async function learnerCourses(page: Page): Promise<Array<{ id: string; title: string }>> {
  return page.evaluate(async () => {
    const response = await fetch('/api/v1/learner/courses', { credentials: 'include' })
    if (response.status !== 200) throw new Error(`courses list status ${response.status}`)
    return await response.json() as Array<{ id: string; title: string }>
  })
}

async function statusOf(page: Page, path: string): Promise<number> {
  return page.evaluate(async (url) => {
    const response = await fetch(url, { credentials: 'include' })
    return response.status
  }, path)
}

test('one access link opens every granted course of the vendor and tenants stay isolated', async ({
  browser,
  request,
}) => {
  test.setTimeout(240_000)
  const ownerEmail = requiredEnvironment('E2E_OWNER_EMAIL')
  const ownerPassword = requiredEnvironment('E2E_OWNER_PASSWORD')
  const vendorName = requiredEnvironment('E2E_VENDOR_NAME')
  const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
  const mailpitURL = process.env.E2E_MAILPIT_URL ?? 'http://localhost:8025'
  const unique = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  const learnerEmail = `learner-multi-${unique}@example.com`
  const expectedSubject = `Доступ к курсам: ${vendorName}`

  const courseA1 = {
    course: `E2E multi A1 ${unique}`,
    module: `E2E module A1 ${unique}`,
    lesson: `E2E lesson A1 ${unique}`,
    content: `E2E content A1 ${unique}`,
  }
  const courseA2 = {
    course: `E2E multi A2 ${unique}`,
    module: `E2E module A2 ${unique}`,
    lesson: `E2E lesson A2 ${unique}`,
    content: `E2E content A2 ${unique}`,
  }

  const vendorContext = await browser.newContext({ baseURL })
  const vendor = await vendorContext.newPage()
  await loginVendor(vendor, ownerEmail, ownerPassword, vendorName)

  await createPublishedCourse(vendor, courseA1)
  await createPublishedCourse(vendor, courseA2)

  await grantAccess(vendor, learnerEmail, [courseA1.course, courseA2.course])

  const accessMessage = await waitForMail(request, mailpitURL, learnerEmail, expectedSubject)
  const emailedURL = await mailURL(request, mailpitURL, accessMessage)
  // The backend composes access links from PUBLIC_APP_URL (production in .env);
  // the E2E app always runs at the local baseURL.
  const accessURL = new URL(`${baseURL}/app/#${emailedURL.hash.replace(/^#/, '')}`)
  await vendorContext.close()

  // Criterion: one access link shows several granted courses of its vendor.
  const learnerContext = await browser.newContext({ baseURL })
  const learnerPage = await learnerContext.newPage()
  await learnerPage.goto(accessURL.toString())
  await expect(learnerPage.getByRole('heading', { name: 'Все курсы' })).toBeVisible()
  await expect(learnerPage.getByRole('button', { name: new RegExp(courseA1.course) })).toBeVisible()
  await expect(learnerPage.getByRole('button', { name: new RegExp(courseA2.course) })).toBeVisible()
  await learnerPage.getByRole('button', { name: new RegExp(courseA2.course) }).click()
  await expect(learnerPage.getByRole('heading', { name: courseA2.course })).toBeVisible()
  await expect(learnerPage.getByText(courseA2.content, { exact: true })).toBeVisible()

  const vendorACourses = await learnerCourses(learnerPage)
  const courseA1Row = vendorACourses.find((course) => course.title === courseA1.course)
  const courseA2Row = vendorACourses.find((course) => course.title === courseA2.course)
  expect(courseA1Row).toBeTruthy()
  expect(courseA2Row).toBeTruthy()
  expect(vendorACourses.length).toBe(2)

  // Tenant isolation: a learner of another vendor must not see or access this content.
  const vendorBLink = process.env.E2E_VENDOR_B_ACCESS_LINK
  const vendorBCourseTitle = process.env.E2E_VENDOR_B_COURSE_TITLE
  test.skip(
    !vendorBLink || !vendorBCourseTitle,
    'E2E_VENDOR_B_ACCESS_LINK and E2E_VENDOR_B_COURSE_TITLE are required; run bootstrap_e2e_vendor first.',
  )
  const token = new URL(vendorBLink as string).hash.replace(/^#access=/, '')
  const vendorBURL = `${baseURL}/app/#access=${token}`

  const vendorBContext = await browser.newContext({ baseURL })
  const vendorBPage = await vendorBContext.newPage()
  await vendorBPage.goto(vendorBURL)
  await expect(
    vendorBPage.locator('h1').filter({ hasText: /Все курсы|Перенос входа/ }).first(),
  ).toBeVisible({ timeout: 15_000 })
  const transferB = vendorBPage.getByRole('heading', { name: 'Перенос входа' })
  if (await transferB.isVisible().catch(() => false)) {
    await vendorBPage.getByRole('button', { name: 'Перенести вход на это устройство' }).click()
  }
  await expect(vendorBPage.getByRole('heading', { name: 'Все курсы' })).toBeVisible()
  await expect(vendorBPage.getByRole('button', { name: new RegExp(vendorBCourseTitle as string) })).toBeVisible()
  await expect(vendorBPage.getByRole('button', { name: new RegExp(courseA1.course) })).toHaveCount(0)
  await expect(vendorBPage.getByRole('button', { name: new RegExp(courseA2.course) })).toHaveCount(0)

  const vendorBCourses = await learnerCourses(vendorBPage)
  const vendorBCourse = vendorBCourses.find((course) => course.title === vendorBCourseTitle)
  expect(vendorBCourse).toBeTruthy()
  expect(vendorBCourses.map((course) => course.id)).not.toContain(courseA1Row?.id)
  expect(vendorBCourses.map((course) => course.id)).not.toContain(courseA2Row?.id)

  for (const foreignCourseId of [courseA1Row?.id, courseA2Row?.id]) {
    expect(await statusOf(vendorBPage, `/api/v1/learner/courses/${foreignCourseId}`)).toBe(404)
    expect(await statusOf(vendorBPage, `/api/v1/learner/courses/${foreignCourseId}/offline-manifest`)).toBe(404)
    expect(await statusOf(vendorBPage, `/api/v1/learner/courses/${foreignCourseId}/progress`)).toBe(404)
    expect(await statusOf(
      vendorBPage,
      `/api/v1/learner/courses/${foreignCourseId}/media/00000000-0000-0000-0000-000000000001/stream-url`,
    )).toBe(404)
    expect(await statusOf(
      vendorBPage,
      `/api/v1/learner/courses/${foreignCourseId}/offline-media/00000000-0000-0000-0000-000000000002/00000000-0000-0000-0000-000000000003`,
    )).toBe(404)
  }

  const vendorAIds = vendorACourses.map((course) => course.id)
  expect(vendorBCourses.map((course) => course.id)).not.toContain(
    ...vendorAIds,
  )
  for (const foreignCourseId of [vendorBCourse?.id]) {
    expect(await statusOf(learnerPage, `/api/v1/learner/courses/${foreignCourseId}`)).toBe(404)
    expect(await statusOf(learnerPage, `/api/v1/learner/courses/${foreignCourseId}/offline-manifest`)).toBe(404)
    expect(await statusOf(learnerPage, `/api/v1/learner/courses/${foreignCourseId}/progress`)).toBe(404)
  }
  const vendorAList = await learnerCourses(learnerPage)
  expect(vendorAList.map((course) => course.id)).not.toContain(vendorBCourse?.id)

  await learnerContext.close()
  await vendorBContext.close()
})
