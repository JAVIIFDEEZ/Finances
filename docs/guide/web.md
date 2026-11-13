# Cómo ver la web

La web de InvestingLab es la interfaz de la plataforma: mercados, carteras, simulación,
optimización y planificación, en español e inglés y con tema oscuro o claro. Habla con la API
REST, que a su vez usa el núcleo de Python ([ADR-0028](../adr/0028-institutional-web-app.md)).

## Requisitos

* [uv](https://docs.astral.sh/uv/) (ya lo usas para el núcleo).
* Node.js 22 o superior y [pnpm](https://pnpm.io/) 10. Con Node 22 basta con
  `corepack enable pnpm`. En Windows, si Node.js está en `C:\Program Files`, ejecútalo en
  una terminal de administrador o instala pnpm con `npm install -g pnpm@10`. Después, abre
  una terminal nueva y comprueba que `pnpm --version` responde.

Los comandos son los mismos en Linux, macOS y Windows: `just` usa bash en los dos primeros y
PowerShell en Windows.

## Arrancarlo todo con un comando

```bash
uv sync --all-groups        # una vez: dependencias de Python (núcleo y API)
uv run just web-install     # una vez: dependencias de la web
uv run just dev             # API en :8000 y web en :3000; Ctrl+C para ambas
```

Abre <http://localhost:3000>. La primera visita a cada instrumento descarga sus datos de Yahoo
Finance o del BCE y tarda unos segundos (el portal del BCE a veces más); después salen de la
caché local (`data/cache`).

La documentación interactiva de la API está en <http://127.0.0.1:8000/docs>.

## Qué hay en cada pantalla

| Pantalla | Qué puedes hacer |
|----------|------------------|
| **Visión general** | IBEX 35, DAX, S&P 500, EUR/USD y Bitcoin del último año; tu cartera; el €STR conocido cada día; el índice cripto de miedo y codicia (con su banda: miedo extremo… codicia extrema); fuentes de datos y progreso del máster |
| **Mercados** | Buscar cualquier símbolo (⌘K o Ctrl+K: `SAN.MC`, `AAPL`, `^GSPC`, `EURUSD=X`, `BTC/USDT`), ver velas y volumen, estadísticos, Sharpe con su error estándar, VaR, caídas, calidad de datos y el flujo por vela (CVD si la fuente dice quién agredió; si no, el volumen; o por qué no hay). Para un par cripto, también el funding de su perpetuo. En «Comparar», varios activos en base 100 con su correlación |
| **Cartera** | Componer la cartera (pesos con validación en vivo, divisa base, rebalanceo, fecha de inicio) y analizarla: KPIs, valor, caídas, contribución al riesgo, correlación, peores caídas e informe Markdown en español o inglés |
| **Simulación** | Monte Carlo de la cartera (browniano, t de Student o *bootstrap*): abanico de percentiles, distribución final con VaR y CVaR marcados y tabla de riesgo con intervalos de confianza |
| **Optimización** | Máximo Sharpe, mínima varianza, paridad de riesgo, HRP o inversa de la volatilidad con un peso máximo: frontera eficiente, pesos actuales frente a óptimos y un botón para aplicarlos a la cartera |
| **Planificación** | Plan de ahorro con aportaciones mensuales, inflación y objetivo en dinero de hoy: probabilidad de éxito y aportación necesaria. Por defecto supone un 5 % anual, una hipótesis prudente |
| **Módulos del máster** | Trazabilidad requisito → código → test del bloque B1 |

La cartera de trabajo se guarda en tu navegador y la comparten todas las pantallas de análisis.

## Verla desde el móvil

La web se adapta a la pantalla del teléfono: menú desplegable, botones del tamaño de un dedo y
ninguna pantalla con desplazamiento lateral.

Por defecto solo responde en tu ordenador. Para abrirla desde un móvil conectado a la **misma
Wi-Fi**:

```bash
uv run just mobile          # compila la web y la sirve también a tu red local
```

El comando imprime la dirección que hay que abrir en el navegador del móvil, del tipo
`http://192.168.1.74:3000`. La API sigue respondiendo solo en tu ordenador; el móvil habla
con la web y la web con la API.

* **Windows** pregunta la primera vez si permites a Node.js aceptar conexiones: acepta para
  redes privadas. Si el móvil no carga la página, revisa esa regla del cortafuegos y que el
  móvil no esté en la red de invitados del router.
* **Como una app**: en iPhone (Safari), Compartir → «Añadir a pantalla de inicio»; en Android
  (Chrome), menú → «Añadir a pantalla de inicio». Se abre a pantalla completa con su icono.
* **Seguridad**: todavía no hay acceso con usuario, así que cualquiera conectado a esa red
  puede abrirla y ver tus carteras guardadas. Úsalo solo en tu red de casa y para el
  comando (Ctrl+C) cuando termines.
* **Fuera de casa**: hasta que llegue el acceso con usuario (fase G0c) no la expongas a
  Internet. Una red privada como Tailscale entre tu ordenador y tu móvil sí es segura: con
  ella instalada en ambos, `just mobile` y la dirección de Tailscale de tu ordenador bastan.

## Sin red

Con `INVESTINGLAB_OFFLINE=true` la API solo usa tus ficheros locales
(`INVESTINGLAB_LOCAL_DATA_DIR`) y la caché. Para probar la web con datos **sintéticos**:

```bash
cd apps/web
uv run python e2e/synthetic_data.py .e2e/data
INVESTINGLAB_OFFLINE=true INVESTINGLAB_LOCAL_DATA_DIR=.e2e/data uv run investinglab-api &
pnpm dev
```

## Comandos de desarrollo

| Comando | Qué hace |
|---------|----------|
| `uv run just web` | Solo la web con recarga (necesita la API en marcha) |
| `uv run just preview` | API y *build* de producción de la web: páginas más rápidas, sin recarga |
| `uv run just mobile` | Como `preview`, y además accesible desde el móvil en la misma Wi-Fi |
| `uv run just web-check` | `lint`, `typecheck`, tests unitarios (Vitest) y *build* |
| `uv run just web-e2e` | Tests de extremo a extremo (Playwright) con datos sintéticos |
| `uv run just openapi` | Regenera el contrato de la API y los tipos del cliente web |

## Problemas frecuentes

* **«API sin conexión»** (un aviso arriba en todas las pantallas): la API no está en marcha
  u **otro programa ocupa su puerto** (8000). `uv run just dev` comprueba los puertos antes de
  arrancar y dice cuál está ocupado. Para saber qué programa es:
  `Get-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess` en
  PowerShell o `lsof -i :8000` en Linux y macOS. Ciérralo o usa otro puerto con
  `INVESTINGLAB_API_PORT=8010`: con `just dev`, la web lo sigue sola. En cuanto la API
  responde, la web se recupera sin recargar la página.
* **`uv` no se reconoce** en una terminal: no está en el PATH de esa terminal. Abre una nueva
  después de instalarlo, o mira dónde está en una terminal donde sí funcione
  (`(Get-Command uv).Source` en PowerShell) y añade esa carpeta al PATH. Con el entorno del
  proyecto activado, `investinglab-api --reload` arranca la API sin pasar por uv.
* **La página se queda en «Cargando…»** con `just dev`: ábrela en <http://localhost:3000>
  o <http://127.0.0.1:3000>. En desarrollo, Next.js no sirve sus recursos internos a otros
  *hosts*; usa `uv run just preview` o añade el *host* a `allowedDevOrigins` en
  `apps/web/next.config.ts`.
* **Un símbolo no aparece**: Yahoo usa sufijos por mercado (`.MC` Madrid, `.DE` Xetra,
  `.L` Londres, `.PA` París). Algunos índices no publican su divisa (`^STOXX50E`) y la
  plataforma no la adivina.
* **Va lento la primera vez**: es la descarga inicial; el resto sale de la caché.
* **En Windows, `pnpm` no se encuentra** (o salen rutas `/mnt/c/...`, señal de que se usó
  el bash de WSL): actualiza el repositorio, instala pnpm como se indica en los requisitos
  y abre una terminal nueva.
