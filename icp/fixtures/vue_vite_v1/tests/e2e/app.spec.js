import { expect, test } from '@playwright/test'

test('renders and captures the ICP fixture', async ({ page }, testInfo) => {
  await page.goto('/')
  await expect(page.locator('[data-icp-node-id="fixture-title"]')).toHaveText('ICP Vue Fixture')
  await page.screenshot({ path: testInfo.outputPath('actual.png') })
})
