import { expect, test } from "@playwright/test";

test("loads the compiled GLB with stable IDs and a finite camera", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#status")).toHaveAttribute("data-state", "ready");
  const result = await page.evaluate(() => window.__WORLDSPEC_PREVIEW__);
  expect(result.ready).toBe(true);
  expect(result.stableIds).toContain("entity://cube/body");
  for (const extent of result.bounds.size) expect(extent).toBeCloseTo(1, 9);
  expect(result.renderer).toContain("WebGL");
  await page.screenshot({
    path: "test-results/worldspec-threejs-preview.png",
    fullPage: true,
  });
});
