# Ingesta de datos de mercado

Flujo de una petición de precios ([ADR-0010](../adr/0010-multi-provider-ingestion.md),
[ADR-0011](../adr/0011-parquet-duckdb-cache.md), [ADR-0012](../adr/0012-resilient-http-client.md)).

## Diagrama de secuencia

```mermaid
sequenceDiagram
    autonumber
    actor U as Notebook / API
    participant S as MarketDataService
    participant C as SeriesStore (Parquet + DuckDB)
    participant R as ProviderRegistry
    participant P1 as Proveedor preferido
    participant P2 as Proveedor alternativo
    participant H as HttpClient

    U->>S: get_many_bars([SAN.MC, ^IBEX, SPY…])
    loop cada símbolo (concurrencia ≤ max_concurrency)
        S->>C: load_bars(request)
        alt entrada fresca que cubre la petición
            C-->>S: CachedBars
            S-->>S: recortar a [start, end]
        else sin caché válida
            S->>R: bars_candidates(request)
            R-->>S: [P1, P2] por preferencia y capacidades
            S->>P1: fetch_bars(request)
            P1->>H: GET (cuota + reintentos + backoff)
            alt éxito
                H-->>P1: respuesta
                P1-->>S: PriceSeries validada
            else fallo (ProviderError)
                P1-->>S: error → FetchAttempt
                S->>P2: fetch_bars(request)
                P2-->>S: PriceSeries validada
            end
            S->>C: save_bars(series, cobertura)
        end
    end
    S-->>U: BatchResult(succeeded, failed)
```

## Componentes

| Componente | Capa | Responsabilidad |
|------------|------|-----------------|
| `BarsRequest`, `EconomicRequest` | `ports` | Qué se pide: símbolo o serie, frecuencia, fechas, modo de *vintage* |
| `ProviderCapabilities`, `RateLimit` | `ports` | Qué puede servir cada proveedor y con qué cuotas |
| `MarketDataProvider`, `EconomicDataProvider` | `ports` | Contrato de los adaptadores: devuelven objetos del dominio |
| `ProviderError` y subclases | `ports` | Errores homogéneos con `retryable` |
| `ProviderRegistry` | `services` | Registro y orden de preferencia |
| `MarketDataService` | `services` | Caché → candidatos → *fallback* → `DataUnavailableError` / `BatchResult` |
| `HttpClient` | `adapters/http` | Reintentos, cuotas, traducción de errores, secretos fuera de los logs |
| `ParquetSeriesStore` | `adapters/storage` | Caché autodescriptiva, escritura atómica, catálogo con DuckDB |

Los adaptadores de cada proveedor (Yahoo, Alpha Vantage, FRED/ALFRED, BCE…) se añaden en la
fase F2b, sin cambiar nada de lo anterior.
