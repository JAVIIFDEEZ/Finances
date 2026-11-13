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
  // Offline there is no source of the crypto Fear & Greed Index: the card says so.
  await expect(page.getByRole("heading", { name: "Miedo y codicia cripto" })).toBeVisible();
  await expect(page.getByText("No disponible: el índice viene de alternative.me", { exact: false })).toBeVisible();
  expect(errors).toEqual([]);
});

test("when the API does not answer, one banner says so and the screens recover by themselves", async ({ page }) => {
  const errors = trackErrors(page);
  // Another program on the API's port: it answers, but not with InvestingLab's Problem Details.
  const foreign = (route: Parameters<Parameters<Page["route"]>[1]>[0]) =>
    route.fulfill({ status: 404, contentType: "text/html", body: "<h1>Not Found</h1>" });
  await page.route("**/health/**", foreign);
  await page.route("**/api/v1/**", foreign);
  await page.goto("/");

  const banner = page.getByRole("alert").filter({ hasText: "API sin conexión" });
  await expect(banner).toContainText("ningún otro programa ocupe su puerto");
  await expect(page.getByText("La API no responde.").first()).toBeVisible();
  await expect(page.getByText("Ningún proveedor tiene ese instrumento.")).toHaveCount(0);

  await page.unrouteAll();
  await expect(banner).toBeHidden({ timeout: 20_000 });
  await expect(page.getByText("Rentabilidad anualizada").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("La API no responde.")).toHaveCount(0);
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

test("every instrument shows its flow, or why it has none", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/markets?symbol=ITX.MC");

  await expect(page.getByRole("heading", { name: "Flujo por vela" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Volumen por vela" })).toBeVisible();
  await expect(page.getByText("La fuente no dice quién agredió", { exact: false })).toBeVisible();
  await expect(page.getByText("Volumen total")).toBeVisible();

  await page.goto("/markets?symbol=EURUSD%3DX");
  await expect(page.getByText("Ninguna fuente publica el flujo", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Funding del perpetuo" })).toHaveCount(0);
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

test("a portfolio is saved, changed, reopened and deleted", async ({ page }) => {
  test.skip(!process.env.INVESTINGLAB_E2E_DATABASE_URL, "needs PostgreSQL (INVESTINGLAB_E2E_DATABASE_URL)");
  const errors = trackErrors(page);
  const name = `E2E ${Date.now()}`;
  await page.goto("/portfolio");
  const saved = page.locator("section").filter({ has: page.getByRole("heading", { name: "Carteras guardadas" }) });

  // Save the analysed portfolio under a new name.
  await page.getByLabel("Nombre de la cartera").fill(name);
  await page.getByRole("button", { name: "Analizar cartera" }).click();
  await saved.getByRole("button", { name: /Guardar cartera|Guardar como nueva/ }).click();
  await expect(saved.getByRole("status")).toHaveText("Guardada.");
  const row = saved.getByRole("listitem").filter({ hasText: name });
  await expect(row).toContainText("abierta");

  // A second save with the same name is refused and explained, not an error page.
  await saved.getByRole("button", { name: "Guardar como nueva" }).click();
  await expect(saved.getByRole("alert")).toContainText("Ya tienes una cartera con ese nombre");

  // Change it: the saved record moves to a new version.
  await page.getByLabel("Nombre de la cartera").fill(`${name} v2`);
  await page.getByRole("button", { name: "Analizar cartera" }).click();
  await saved.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(saved.getByRole("listitem").filter({ hasText: `${name} v2` })).toBeVisible();

  // It survives a reload, and opening it restores the definition.
  await page.getByLabel("Nombre de la cartera").fill("Otra");
  await page.getByRole("button", { name: "Analizar cartera" }).click();
  await page.reload();
  await page.getByRole("button", { name: `Abrir ${name} v2` }).click();
  await expect(page.getByLabel("Nombre de la cartera")).toHaveValue(`${name} v2`);

  // Delete it, with a confirmation.
  await page.getByRole("button", { name: `Borrar ${name} v2` }).click();
  await saved.getByRole("button", { name: "¿Borrar?" }).click();
  await expect(saved.getByRole("listitem").filter({ hasText: name })).toHaveCount(0);
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
