# Modelo de dominio

El dominio (`investinglab.domain`) contiene los objetos con los que trabaja todo el sistema.
Todos son `@dataclass(frozen=True, slots=True)`, se validan al construirse (ver
[ADR-0006](../adr/0006-strict-input-validation.md)) y no hacen I/O. Sus cálculos se delegan en
el núcleo numérico `investinglab.analytics`.

## Diagrama de clases

```mermaid
classDiagram
    direction LR

    class Currency {
        +str code
        +kind CurrencyKind
    }
    class CurrencyPair {
        +Currency base
        +Currency quote
        +symbol str
        +inverse() CurrencyPair
    }
    class MarketSchedule {
        +float sessions_per_year
        +float session_hours
        +periods_per_year(frequency) float
    }
    class Exchange {
        +str code
        +str name
        +str timezone
        +MarketSchedule schedule
    }
    class Identifiers {
        +str isin
        +str figi
        +str cik
        +str lei
    }
    class Instrument {
        +str symbol
        +str name
        +AssetClass asset_class
        +Currency currency
        +Exchange exchange
        +Identifiers identifiers
        +schedule MarketSchedule
        +timezone str
    }
    class DataSource {
        +str provider
        +datetime retrieved_at
        +str dataset
    }
    class SeriesStats {
        +int n_observations
        +float mean_return
        +float std_return
        +float mean_log_return
        +float std_log_return
        +float total_return
        +float annualized_return
        +float annualized_volatility
        +float max_drawdown
        +float skewness
        +float excess_kurtosis
        +from_prices(prices, periods_per_year)$ SeriesStats
    }
    class PriceSeries {
        +Instrument instrument
        +Frequency frequency
        +DataSource source
        +PriceAdjustment adjustment
        +SeriesStats stats
        +bars DataFrame
        +prices Series
        +returns(kind) Series
        +log_returns() Series
        +cumulative_returns() Series
        +annualized_volatility() float
        +drawdown() Series
        +max_drawdown() float
        +between(start, end) PriceSeries
        +resample(frequency) PriceSeries
        +metrics(risk_free_rate, levels) RiskMetrics
        +beta(benchmark) float
    }
    class EconomicSeries {
        +str series_id
        +str title
        +str units
        +Frequency frequency
        +DataSource source
        +first_release() Series
        +latest() Series
        +as_of(date) Series
        +known_values_at(dates) Series
    }
    class AlignedPanel {
        +AlignmentMethod method
        +prices DataFrame
        +returns DataFrame
        +observed DataFrame
        +valuation_prices() DataFrame
        +staleness() DataFrame
        +common_start() Timestamp
    }
    class RebalancePolicy {
        +RebalanceKind kind
        +Frequency frequency
        +float band
        +buy_and_hold()$
        +periodic(frequency)$
        +threshold(band)$
    }
    class Holding {
        +PriceSeries series
        +float weight
    }
    class Portfolio {
        +str name
        +tuple~Holding~ holdings
        +Currency base_currency
        +RebalancePolicy rebalance
        +bool allow_short
        +weights Series
        +from_weights(name, series, weights)$ Portfolio
        +equal_weight(name, series)$ Portfolio
        +aligned(method) AlignedPanel
        +backtest(initial_value) PortfolioBacktest
        +returns() Series
        +value_history(initial_value) Series
        +metrics(risk_free_rate, levels) RiskMetrics
        +correlation(frequency) DataFrame
        +risk_contributions(frequency) DataFrame
    }
    class PortfolioBacktest {
        +returns Series
        +values Series
        +weights DataFrame
        +turnover Series
        +staleness DataFrame
        +rebalance_dates DatetimeIndex
        +drawdown() Series
    }
    class RiskMetrics {
        +float annualized_return
        +float annualized_volatility
        +float sharpe_ratio
        +float sortino_ratio
        +float calmar_ratio
        +float max_drawdown
        +tuple~TailRisk~ tail
        +from_returns(returns, periods_per_year)$ RiskMetrics
        +tail_risk(level, method) TailRisk
    }
    class TailRisk {
        +float level
        +VaRMethod method
        +float value_at_risk
        +float conditional_value_at_risk
    }

    CurrencyPair --> Currency
    Exchange --> MarketSchedule
    Instrument --> Currency
    Instrument --> Exchange
    Instrument --> Identifiers
    PriceSeries --> Instrument
    PriceSeries --> DataSource
    PriceSeries *-- SeriesStats : calculada en __post_init__
    EconomicSeries --> DataSource
    Portfolio "1" *-- "1..*" Holding
    Holding --> PriceSeries
    Portfolio --> RebalancePolicy
    Portfolio --> Currency
    Portfolio ..> AlignedPanel : crea
    Portfolio ..> PortfolioBacktest : crea
    Portfolio ..> RiskMetrics : calcula
    PriceSeries ..> RiskMetrics : calcula
    RiskMetrics *-- TailRisk
```

## Responsabilidades

| Objeto | Responsabilidad |
|--------|-----------------|
| `Currency`, `CurrencyPair`, `QuoteUnit` | Divisas ISO 4217 validadas; `parse_quote_currency` resuelve unidades menores (`GBp` → GBP × 0,01) |
| `Frequency`, `MarketSchedule` | Frecuencias de 1 minuto a 1 año y anualización según el mercado ([ADR-0007](../adr/0007-time-representation.md)) |
| `Exchange`, `Instrument`, `Identifiers` | Metadatos del activo; ISIN y LEI con checksum verificado |
| `PriceSeries` | Serie OHLCV o de cierre ajustado inmutable y validada; estadísticos automáticos al construirse |
| `EconomicSeries` | Serie macro bitemporal *point-in-time* ([ADR-0009](../adr/0009-point-in-time-economic-series.md)) |
| `AlignedPanel` | Alineación multiactivo sin inventar datos ([ADR-0008](../adr/0008-alignment-without-artificial-fill.md)) |
| `Portfolio`, `Holding`, `RebalancePolicy` | Cartera con pesos validados (suma 1, cortos solo explícitos, misma divisa y frecuencia), historia con rebalanceo, métricas, correlaciones y contribución al riesgo ([ADR-0013](../adr/0013-risk-metrics-and-portfolio-engine.md)) |
| `PortfolioBacktest` | Trayectoria histórica: retornos, valor, pesos, rotación y antigüedad de las valoraciones |
| `RiskMetrics`, `TailRisk` | Rentabilidad, volatilidad, Sharpe, Sortino, Calmar, drawdown y VaR/CVaR (histórico, normal y Cornish-Fisher) |

## Inmutabilidad

Las `dataclass` son `frozen`, así que sus atributos no se pueden reasignar. Los datos tabulares
se guardan en un DataFrame privado y cada accesor (`bars`, `prices`, `returns()`…) devuelve un
objeto nuevo. Con pandas 3 (*Copy-on-Write* siempre activo) esos objetos comparten memoria
con la serie, pero cualquier modificación provoca una copia privada. La serie validada no
puede alterarse.
