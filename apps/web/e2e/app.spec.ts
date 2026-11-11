import { expect, test, type Page } from "@playwright/test";

/** Uncaught errors fail the test; failed requests (an offline source) are allowed. */
function trackErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test.beforeEach(async ({ context }) => {
  await context.addCookies([{ name: "investinglab.locale", value: "es", url: "http://127.0.0.1:3000" }]);
});

test("the overview shows the markets, the portfolio and the platform", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: "Visión general" })).toBeVisible();
  await expect(page.getByRole("link", { name: /IBEX 35/ })).toBeVisible();
  await expect(page.getByText("Rentabilidad anualizada").first()).toBeVisible();
  const header = page.getByRole("banner");
  await expect(header.getByText("API conectada").or(header.getByText("Modo sin red"))).toBeVisible();
  expect(errors).toEqual([]);
});

test("an instrument is found with the search and explored", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/markets");
  await page.getByRole("button", { name: /Buscar instrumento/ }).click();
  await page.getByRole("combobox").fill("ITX.MC");
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/symbol=ITX\.MC/);
  await expect(page.getByRole("main").getByText("ITX.MC", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("img", { name: "Precio ITX.MC" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Calidad de datos" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("instruments are compared", async ({ page }) => {
  await page.goto("/markets?view=compare");

  await expect(page.getByRole("img", { name: "Rendimiento (base 100)" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Correlación de rentabilidades" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "BBVA.MC" })).toBeVisible();
});

test("the portfolio is validated live and analysed", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/portfolio");

  await expect(page.getByText("Composición válida")).toBeVisible();
  await page.getByLabel("Peso SAN.MC").fill("10");
  await expect(page.getByText("Revisa la composición")).toBeVisible();
  await expect(page.getByRole("button", { name: "Analizar cartera" })).toBeDisabled();
  await page.getByRole("button", { name: "Normalizar a 100 %" }).click();
  await expect(page.getByText("Composición válida")).toBeVisible();

  await page.getByRole("button", { name: "Analizar cartera" }).click();
  await expect(page.getByRole("img", { name: "Valor de la cartera (base 100)" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Peso frente a contribución al riesgo" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Informe en español/ })).toBeVisible();
  expect(errors).toEqual([]);
});

test("Monte Carlo, optimisation and savings plans run", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/simulation");
  await expect(page.getByRole("img", { name: "Abanico de percentiles" })).toBeVisible();
  await expect(page.getByText("Probabilidad de pérdida")).toBeVisible();

  await page.goto("/optimization");
  await expect(page.getByRole("img", { name: "Frontera eficiente" })).toBeVisible();
  await page.getByRole("button", { name: "Usar estos pesos en la cartera" }).click();
  await expect(page.getByText("Pesos aplicados a la cartera")).toBeVisible();

  await page.goto("/planning");
  await expect(page.getByRole("img", { name: "Patrimonio en dinero de hoy" })).toBeVisible();
  await expect(page.getByText("Probabilidad de éxito")).toBeVisible();
  expect(errors).toEqual([]);
});

test("language and theme are switched and remembered", async ({ page }) => {
  await page.goto("/modules");
  await expect(page.getByRole("heading", { level: 1, name: "Módulos del máster" })).toBeVisible();

  await page.getByRole("radio", { name: "EN" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Master's modules" })).toBeVisible();
  const theme = await page.locator("html").getAttribute("data-theme");
  await page.getByRole("button", { name: theme === "dark" ? "Light theme" : "Dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme === "dark" ? "light" : "dark");

  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Master's modules" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme === "dark" ? "light" : "dark");
});
