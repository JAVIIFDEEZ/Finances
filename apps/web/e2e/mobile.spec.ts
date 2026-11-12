import { devices, expect, test } from "@playwright/test";

/** The same screens on a phone: nothing overflows, the menu navigates, controls fit a finger. */
// Only the phone's screen and touch: the engine stays the one the project installs.
const { viewport, deviceScaleFactor, isMobile, hasTouch, userAgent } = devices["iPhone 14"];
test.use({ viewport, deviceScaleFactor, isMobile, hasTouch, userAgent });

const SCREENS = ["/", "/markets", "/portfolio", "/simulation", "/optimization", "/planning", "/modules"];

test.beforeEach(async ({ context }) => {
  await context.addCookies([{ name: "investinglab.locale", value: "es", url: "http://127.0.0.1:3000" }]);
});

for (const screen of SCREENS) {
  test(`${screen} fits a phone without sideways scrolling`, async ({ page }) => {
    await page.goto(screen);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".animate-pulse")).toHaveCount(0, { timeout: 60_000 });

    const { content, screenWidth } = await page.evaluate(() => ({
      content: document.documentElement.scrollWidth,
      screenWidth: document.documentElement.clientWidth,
    }));

    expect(content).toBeLessThanOrEqual(screenWidth);
  });
}

test("the menu opens, navigates and closes", async ({ page }) => {
  await page.goto("/");
  const menu = page.getByRole("navigation").getByRole("link", { name: "Cartera", exact: true });
  await expect(menu).toBeHidden();

  await page.getByRole("button", { name: "Menú" }).tap();
  await menu.tap();

  await expect(page).toHaveURL(/\/portfolio$/);
  await expect(page.getByRole("heading", { level: 1, name: "Cartera" })).toBeVisible();
  await expect(menu).toBeHidden();
});

test("buttons and fields are big enough for a finger", async ({ page }) => {
  await page.goto("/portfolio");
  const analyse = page.getByRole("button", { name: "Analizar cartera" });
  const name = page.getByLabel("Nombre de la cartera");

  expect((await analyse.boundingBox())?.height).toBeGreaterThanOrEqual(40);
  expect((await name.boundingBox())?.height).toBeGreaterThanOrEqual(40);
  // iOS zooms the page when a field's text is under 16 px.
  expect(await name.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(16);
});

test("the phone can add the app to its home screen", async ({ page, request }) => {
  await page.goto("/");
  const href = await page.locator('link[rel="manifest"]').getAttribute("href");
  const manifest = await (await request.get(href ?? "")).json();

  expect(manifest.display).toBe("standalone");
  expect(manifest.icons.length).toBeGreaterThan(0);
  expect((await request.get("/apple-icon")).headers()["content-type"]).toBe("image/png");
});
