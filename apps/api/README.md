# InvestingLab API

API REST (FastAPI) que expone el núcleo de InvestingLab a la web: datos de mercado, análisis de
carteras, Monte Carlo, optimización y planes de ahorro. No contiene lógica de negocio: valida la
petición, llama a un caso de uso del núcleo y traduce el resultado ([ADR-0027](../../docs/adr/0027-stateless-analytics-api.md)).

```bash
uv run investinglab-api            # http://127.0.0.1:8000/docs (Swagger) y /redoc
uv run investinglab-api --reload   # recarga al cambiar el código
uv run investinglab-api --openapi apps/web/openapi.json   # contrato para el cliente web
```

| Variable | Por defecto | Qué controla |
|----------|-------------|--------------|
| `INVESTINGLAB_API_HOST` / `INVESTINGLAB_API_PORT` | `127.0.0.1` / `8000` | Dónde escucha |
| `INVESTINGLAB_API_CORS_ORIGINS` | `["http://localhost:3000", "http://127.0.0.1:3000"]` | Orígenes del navegador permitidos |
| `INVESTINGLAB_API_MAX_SYMBOLS` | `25` | Instrumentos por petición |
| `INVESTINGLAB_API_MAX_PATHS` | `20000` | Trayectorias de Monte Carlo |
| `INVESTINGLAB_API_MAX_HORIZON` | `2520` | Periodos de horizonte |

Las fuentes de datos, la caché y el modo sin red se configuran con las variables del núcleo
(`INVESTINGLAB_*`, ver `.env.example`). Guía completa: [docs/guide/api.md](../../docs/guide/api.md).
