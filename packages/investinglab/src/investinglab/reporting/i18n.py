"""Bilingual texts (Spanish and English) and locale-aware formatting for reports and charts.

Every message is defined once as a ``(spanish, english)`` pair, so a translation can never
be missing; a test checks that both versions use the same placeholders. Numbers follow
each language's conventions (``1.234,5`` and ``12,3 %`` in Spanish; ``1,234.5`` and
``12.3%`` in English). Missing values are shown as an em dash and dates use ISO 8601.
"""

from __future__ import annotations

import math
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date, datetime

__all__ = ["MISSING", "Language", "Translator"]

MISSING: Final = "—"
"""Placeholder for undefined or unavailable values."""


class Language(StrEnum):
    """Report language."""

    ES = "es"
    """Spanish (default)."""
    EN = "en"
    """English."""


_SEPARATORS: Final = {Language.ES: (".", ","), Language.EN: (",", ".")}
_PERCENT_SUFFIX: Final = {Language.ES: "\u00a0%", Language.EN: "%"}

# ──────────────────────────────────────────────────────────────────────
# Catalogue: key -> (es, en)
# ──────────────────────────────────────────────────────────────────────

_CATALOGUE: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        # ── Generic labels ───────────────────────────────────────────
        "common.yes": ("sí", "yes"),
        "common.no": ("no", "no"),
        "common.portfolio": ("Cartera", "Portfolio"),
        "common.others": ("Otros ({count})", "Others ({count})"),
        "count.assets.one": ("{count} activo", "{count} asset"),
        "count.assets.other": ("{count} activos", "{count} assets"),
        "count.periods.one": ("{count} periodo", "{count} period"),
        "count.periods.other": ("{count} periodos", "{count} periods"),
        "common.interval": ("{low} a {high}", "{low} to {high}"),
        "common.period": ("{start} → {end}", "{start} → {end}"),
        "common.field": ("Campo", "Field"),
        "common.value": ("Valor", "Value"),
        "common.asset": ("Activo", "Asset"),
        "severity.info": ("Información", "Info"),
        "severity.warning": ("Advertencia", "Warning"),
        "severity.critical": ("Crítico", "Critical"),
        # ── Frequencies (always used after «frecuencia» / as an adjective) ──
        "frequency.1m": ("1 minuto", "1-minute"),
        "frequency.5m": ("5 minutos", "5-minute"),
        "frequency.15m": ("15 minutos", "15-minute"),
        "frequency.30m": ("30 minutos", "30-minute"),
        "frequency.1h": ("1 hora", "hourly"),
        "frequency.4h": ("4 horas", "4-hour"),
        "frequency.1d": ("diaria", "daily"),
        "frequency.1w": ("semanal", "weekly"),
        "frequency.1mo": ("mensual", "monthly"),
        "frequency.1q": ("trimestral", "quarterly"),
        "frequency.1y": ("anual", "yearly"),
        # ── Instruments and prices ───────────────────────────────────
        "asset_class.equity": ("Acción", "Equity"),
        "asset_class.etf": ("ETF", "ETF"),
        "asset_class.fund": ("Fondo", "Fund"),
        "asset_class.index": ("Índice", "Index"),
        "asset_class.bond": ("Bono", "Bond"),
        "asset_class.fx": ("Divisa", "FX"),
        "asset_class.crypto": ("Criptoactivo", "Crypto asset"),
        "asset_class.commodity": ("Materia prima", "Commodity"),
        "asset_class.future": ("Futuro", "Future"),
        "adjustment.raw": ("sin ajustar", "unadjusted"),
        "adjustment.splits": ("ajustados por splits", "split-adjusted"),
        "adjustment.splits_and_dividends": (
            "ajustados por splits y dividendos",
            "adjusted for splits and dividends",
        ),
        "price_field.close": ("cierre", "close"),
        "price_field.adj_close": (
            "cierre ajustado por splits y dividendos",
            "close adjusted for splits and dividends",
        ),
        "var_method.historical": ("Histórico", "Historical"),
        "var_method.gaussian": ("Normal", "Gaussian"),
        "var_method.cornish_fisher": ("Cornish-Fisher", "Cornish-Fisher"),
        "rebalance.buy_and_hold": (
            "comprar y mantener (sin rebalanceo)",
            "buy and hold (no rebalancing)",
        ),
        "rebalance.periodic": ("periódico, con frecuencia {frequency}", "periodic ({frequency})"),
        "rebalance.threshold": ("por bandas (±{band})", "threshold (±{band})"),
        # ── Simulation labels ────────────────────────────────────────
        "model.gbm": (
            "movimiento browniano geométrico multivariante",
            "multivariate geometric Brownian motion",
        ),
        "model.student_t": (
            "t de Student multivariante (colas gruesas)",
            "multivariate Student-t (fat tails)",
        ),
        "model.bootstrap": ("bootstrap estacionario por bloques", "stationary block bootstrap"),
        "model_short.gbm": ("GBM", "GBM"),
        "model_short.student_t": ("t de Student", "Student-t"),
        "model_short.bootstrap": ("bootstrap", "bootstrap"),
        "drift.historical": ("media histórica", "historical mean"),
        "drift.zero": ("cero (martingala)", "zero (martingale)"),
        "drift.risk_free": (
            "tipo libre de riesgo ({rate} anual)",
            "risk-free rate ({rate} a year)",
        ),
        "drift.assumed": ("rentabilidades supuestas", "assumed returns"),
        "volatility.historical": ("histórica", "historical"),
        "volatility.assumed": (
            "supuesta (con las correlaciones históricas)",
            "assumed (with historical correlations)",
        ),
        "covariance.sample": ("muestral por pares", "pairwise sample"),
        "covariance.ledoit_wolf": (
            "Ledoit-Wolf (contracción {shrinkage})",
            "Ledoit-Wolf (shrinkage {shrinkage})",
        ),
        # ── Sections ─────────────────────────────────────────────────
        "section.data": ("Datos y procedencia", "Data and provenance"),
        "section.performance": ("Rentabilidad y riesgo", "Return and risk"),
        "section.tail": ("Riesgo de cola por periodo", "Tail risk per period"),
        "section.drawdowns": ("Caídas desde máximos", "Drawdowns"),
        "section.quality": ("Calidad de los datos", "Data quality"),
        "section.diagnostics": ("Diagnósticos y advertencias", "Diagnostics and warnings"),
        "section.methodology": ("Metodología", "Methodology"),
        "section.simulation": ("Simulación de Monte Carlo", "Monte Carlo simulation"),
        "section.composition": ("Composición", "Composition"),
        "section.comparison": ("Rendimiento comparado", "Performance comparison"),
        "section.correlation": ("Correlaciones", "Correlations"),
        "section.risk_contribution": ("Contribución al riesgo", "Risk contribution"),
        "section.rebalancing": ("Rebalanceo y rotación", "Rebalancing and turnover"),
        "section.valuation": ("Calendarios y valoración", "Calendars and valuation"),
        # ── Summary ──────────────────────────────────────────────────
        "series.title": ("Informe de {symbol} · {name}", "{symbol} · {name} report"),
        "series.summary": (
            (
                "Entre el {start} y el {end} ({years} años, {observations} observaciones con "
                "frecuencia {frequency}), {symbol} obtuvo una rentabilidad total del "
                "{total_return}, un {cagr} anualizado, con una volatilidad anualizada del "
                "{volatility}. Su peor caída desde máximos fue del {max_drawdown}."
            ),
            (
                "Between {start} and {end} ({years} years, {observations} observations, "
                "{frequency}), {symbol} returned {total_return} in total, {cagr} a year, with an "
                "annualised volatility of {volatility}. Its worst drawdown was {max_drawdown}."
            ),
        ),
        "portfolio.title": ("Informe de la cartera {name}", "{name} portfolio report"),
        "portfolio.summary": (
            (
                "La cartera {name} invierte en {holdings} con divisa base {currency}; "
                "política de rebalanceo: {policy}. Entre el {start} y el {end} ({years} años) "
                "obtuvo una rentabilidad total del {total_return}, un {cagr} anualizado, con una "
                "volatilidad anualizada del {volatility}, un ratio de Sharpe de {sharpe} y una "
                "máxima caída del {max_drawdown}."
            ),
            (
                "The {name} portfolio holds {holdings} in {currency}; rebalancing policy: "
                "{policy}. Between {start} and {end} ({years} years) it returned {total_return} "
                "in total, {cagr} a year, with an annualised volatility of {volatility}, a Sharpe "
                "ratio of {sharpe} and a maximum drawdown of {max_drawdown}."
            ),
        ),
        "summary.diagnostics": (
            (
                "Diagnóstico · críticos: {critical} · advertencias: {warning} · informativos: "
                "{info} (detalle en «Diagnósticos y advertencias»)."
            ),
            (
                "Diagnostics · critical: {critical} · warnings: {warning} · informational: {info} "
                "(details under “Diagnostics and warnings”)."
            ),
        ),
        "summary.clean": (
            "Diagnóstico: sin advertencias en los datos ni en las métricas.",
            "Diagnostics: no warnings in the data or the metrics.",
        ),
        # ── Data and provenance ──────────────────────────────────────
        "field.symbol": ("Símbolo", "Symbol"),
        "field.name": ("Nombre", "Name"),
        "field.asset_class": ("Clase de activo", "Asset class"),
        "field.exchange": ("Mercado", "Venue"),
        "field.currency": ("Divisa", "Currency"),
        "field.identifiers": ("Identificadores", "Identifiers"),
        "field.frequency": ("Frecuencia", "Frequency"),
        "field.prices": ("Precios", "Prices"),
        "field.price_field": ("Precio analizado", "Price analysed"),
        "field.period": ("Periodo", "Period"),
        "field.observations": ("Observaciones", "Observations"),
        "field.periods_per_year": ("Periodos por año (anualización)", "Periods per year"),
        "field.source": ("Fuente", "Source"),
        "field.retrieved": ("Descargado", "Retrieved"),
        # ── Metrics ──────────────────────────────────────────────────
        "metric.metric": ("Indicador", "Metric"),
        "metric.total_return": ("Rentabilidad total", "Total return"),
        "metric.cagr": ("Rentabilidad anualizada (compuesta)", "Annualised return (CAGR)"),
        "metric.volatility": ("Volatilidad anualizada", "Annualised volatility"),
        "metric.sharpe": ("Ratio de Sharpe", "Sharpe ratio"),
        "metric.sharpe_interval": (
            "Ratio de Sharpe: intervalo de confianza al 95\u00a0%",
            "Sharpe ratio: 95% confidence interval",
        ),
        "metric.sortino": ("Ratio de Sortino", "Sortino ratio"),
        "metric.calmar": ("Ratio de Calmar", "Calmar ratio"),
        "metric.max_drawdown": ("Máxima caída desde máximos", "Maximum drawdown"),
        "metric.best_period": ("Mejor periodo", "Best period"),
        "metric.worst_period": ("Peor periodo", "Worst period"),
        "metric.positive_ratio": ("Periodos con rentabilidad positiva", "Positive periods"),
        "metric.skewness": ("Asimetría", "Skewness"),
        "metric.excess_kurtosis": ("Curtosis (exceso sobre la normal)", "Excess kurtosis"),
        "metric.normality": (
            "Normalidad (p-valor de Jarque-Bera)",
            "Normality (Jarque-Bera p-value)",
        ),
        "metric.risk_free": (
            "Tipo libre de riesgo medio (TAE)",
            "Average risk-free rate (effective annual)",
        ),
        # ── Tail risk ────────────────────────────────────────────────
        "tail.level": ("Confianza", "Confidence"),
        "tail.method": ("Método", "Method"),
        "tail.var": ("VaR", "VaR"),
        "tail.cvar": ("CVaR (pérdida media en la cola)", "CVaR (expected shortfall)"),
        "tail.note": (
            (
                "Pérdidas en un periodo (frecuencia {frequency}) como fracción del valor: un VaR "
                "del 2\u00a0% al 95\u00a0% significa que solo en el 5\u00a0% de los periodos se "
                "pierde más de un 2\u00a0%."
            ),
            (
                "Losses over one period ({frequency}) as a fraction of value: a 2% VaR at 95% "
                "means that only 5% of periods lose more than 2%."
            ),
        ),
        # ── Drawdowns ────────────────────────────────────────────────
        "drawdown.rank": ("#", "#"),
        "drawdown.peak": ("Máximo previo", "Peak"),
        "drawdown.trough": ("Mínimo", "Trough"),
        "drawdown.recovery": ("Recuperación", "Recovery"),
        "drawdown.depth": ("Caída", "Depth"),
        "drawdown.decline": ("Periodos de caída", "Decline (periods)"),
        "drawdown.duration": ("Duración total (periodos)", "Duration (periods)"),
        "drawdown.open": ("en curso", "ongoing"),
        "drawdown.none": (
            "No hubo caídas desde máximos en el periodo.",
            "There were no drawdowns in the period.",
        ),
        # ── Data quality ─────────────────────────────────────────────
        "quality.none": ("Sin incidencias detectadas.", "No issues detected."),
        "quality.calendar": (
            (
                "Se compararon los datos con las sesiones oficiales del mercado ({expected} "
                "sesiones esperadas)."
            ),
            "Data was checked against the official market sessions ({expected} expected sessions).",
        ),
        "quality.no_calendar": (
            "No se comprobaron los huecos frente al calendario oficial del mercado.",
            "Gaps were not checked against the official market calendar.",
        ),
        "quality.policy": (
            "Las incidencias se detectan y se informan; los datos nunca se borran ni se modifican.",
            "Issues are detected and reported; data is never removed or altered.",
        ),
        "quality.severity": ("Gravedad", "Severity"),
        "quality.issue": ("Incidencia", "Issue"),
        "quality.count": ("Fechas afectadas", "Affected dates"),
        "quality.first": ("Primera", "First"),
        "quality.detail": ("Detalle", "Detail"),
        "quality.worst": ("Peor gravedad", "Worst severity"),
        "quality.issues": ("Incidencias", "Issues"),
        "quality.ok": ("Correcto", "OK"),
        "issue.missing_sessions": ("Sesiones sin datos", "Missing sessions"),
        "issue.missing_sessions.message": (
            "Sesiones de mercado sin datos: {count} ({ratio} de las esperadas).",
            "Market sessions without data: {count} ({ratio} of the expected ones).",
        ),
        "issue.unexpected_sessions": ("Datos en días sin sesión", "Data on non-trading days"),
        "issue.unexpected_sessions.message": (
            (
                "Observaciones en días sin sesión oficial: {count} (calendario erróneo o datos "
                "defectuosos)."
            ),
            (
                "Observations on days without an official session: {count} (wrong calendar or bad "
                "data)."
            ),
        ),
        "issue.outlier_returns": ("Retornos atípicos", "Outlier returns"),
        "issue.outlier_returns.message": (
            (
                "Retornos a más de {threshold} desviaciones robustas de la mediana: {count} "
                "(errores o movimientos reales: revisar; no se eliminan)."
            ),
            (
                "Returns beyond {threshold} robust standard deviations: {count} (bad ticks or "
                "genuine shocks: review them; they are not removed)."
            ),
        ),
        "issue.suspected_split": ("Posible split", "Suspected split"),
        "issue.suspected_split.message": (
            "Saltos de precio con ratios típicos de un split: {count} ({ratios}); {status}.",
            "Price jumps with split-like ratios: {count} ({ratios}); {status}.",
        ),
        "issue.suspected_split.unadjusted": (
            "los precios no están ajustados",
            "prices are not adjusted",
        ),
        "issue.suspected_split.adjusted": ("revisa el ajuste", "check the adjustment"),
        "issue.stale_prices": ("Precios congelados", "Frozen prices"),
        "issue.stale_prices.message": (
            "Rachas de precios idénticos: {runs} (la más larga, de {longest} observaciones).",
            "Runs of identical prices: {runs} (longest: {longest} observations).",
        ),
        "issue.ohlc_inconsistent": ("OHLC incoherente", "Inconsistent OHLC"),
        "issue.ohlc_inconsistent.message": (
            "Barras cuyo máximo o mínimo contradice la apertura o el cierre: {count}.",
            "Bars whose high or low contradicts the open or close: {count}.",
        ),
        "issue.zero_volume": ("Volumen cero", "Zero volume"),
        "issue.zero_volume.message": (
            "Observaciones con volumen cero: {count}.",
            "Observations with zero volume: {count}.",
        ),
        "issue.short_history": ("Histórico corto", "Short history"),
        "issue.short_history.message": (
            "Solo {years} años de histórico: las cifras anualizadas no son fiables.",
            "Only {years} years of history: annualised figures are unreliable.",
        ),
        # ── Diagnostics ──────────────────────────────────────────────
        "diag.severity": ("Gravedad", "Severity"),
        "diag.subject": ("Ámbito", "Scope"),
        "diag.message": ("Diagnóstico", "Diagnostic"),
        "diag.advice": ("Recomendación", "Recommendation"),
        "diag.none": ("Sin advertencias.", "No warnings."),
        "diag.missing_sessions": (
            "Comprueba la fuente o combínala con otro proveedor; los huecos nunca se rellenan.",
            "Check the source or combine it with another provider; gaps are never filled.",
        ),
        "diag.unexpected_sessions": (
            "Revisa el mercado asignado al instrumento o la fuente.",
            "Check the venue assigned to the instrument, or the source.",
        ),
        "diag.outlier_returns": (
            "Contrasta esas fechas con otra fuente; si son errores, corrígelos en origen.",
            "Cross-check those dates with another source; fix any errors at the source.",
        ),
        "diag.suspected_split": (
            "Usa precios ajustados (adj_close) o ajusta los splits antes de analizar.",
            "Use adjusted prices (adj_close) or adjust for splits before analysing.",
        ),
        "diag.stale_prices": (
            "Comprueba si hubo una suspensión de cotización o si la fuente dejó de actualizarse.",
            "Check for a trading halt or a source that stopped updating.",
        ),
        "diag.ohlc_inconsistent": (
            "Revisa la fuente: las barras incoherentes distorsionan los indicadores intradía.",
            "Check the source: inconsistent bars distort intraday indicators.",
        ),
        "diag.zero_volume": (
            "Es habitual en activos poco líquidos; vigila la liquidez antes de operar.",
            "Common in illiquid assets; watch liquidity before trading.",
        ),
        "diag.short_history": (
            "Amplía el histórico antes de sacar conclusiones de las cifras anualizadas.",
            "Extend the history before drawing conclusions from annualised figures.",
        ),
        "diag.sharpe_uncertain": (
            (
                "El intervalo de confianza al 95\u00a0% del ratio de Sharpe ({low} a {high}) "
                "incluye el cero: con este histórico, la rentabilidad ajustada al riesgo no es "
                "estadísticamente distinta de cero."
            ),
            (
                "The 95% confidence interval of the Sharpe ratio ({low} to {high}) includes zero: "
                "over this history the risk-adjusted return is not statistically different from "
                "zero."
            ),
        ),
        "diag.sharpe_uncertain.advice": (
            "Trata el Sharpe como orientativo o amplía el histórico.",
            "Treat the Sharpe ratio as indicative or extend the history.",
        ),
        "diag.non_normal": (
            (
                "Los retornos no siguen una distribución normal (p-valor de Jarque-Bera {p_value}; "
                "asimetría {skewness}, curtosis en exceso {kurtosis})."
            ),
            (
                "Returns are not normally distributed (Jarque-Bera p-value {p_value}; skewness "
                "{skewness}, excess kurtosis {kurtosis})."
            ),
        ),
        "diag.non_normal.advice": (
            "El VaR normal infravalora las colas: usa el histórico o el de Cornish-Fisher.",
            "Gaussian VaR understates the tails: use the historical or Cornish-Fisher figures.",
        ),
        "diag.thin_tail": (
            "El VaR al {level} se apoya en pocas observaciones de la cola: {count}.",
            "The {level} VaR rests on few tail observations: {count}.",
        ),
        "diag.thin_tail.advice": (
            "Amplía el histórico o usa un nivel de confianza menor.",
            "Extend the history or use a lower confidence level.",
        ),
        "diag.partial_risk_free": (
            (
                "El tipo libre de riesgo solo se conoce en {known} de {periods} periodos: "
                "Sharpe y Sortino se calculan con esos {known}."
            ),
            (
                "The risk-free rate is known for only {known} of {periods} periods: Sharpe and "
                "Sortino use those {known}."
            ),
        ),
        "diag.partial_risk_free.advice": (
            (
                "Añade una serie de tipos que cubra el principio del histórico o empieza el "
                "análisis cuando ya se publicaba el tipo."
            ),
            (
                "Add a rate series that covers the start of the history, or start the analysis "
                "once the rate was being published."
            ),
        ),
        "diag.zero_risk_free": (
            "Sharpe y Sortino se calculan con un tipo libre de riesgo del 0\u00a0%.",
            "Sharpe and Sortino use a 0% risk-free rate.",
        ),
        "diag.zero_risk_free.advice": (
            (
                "Indica risk_free_rate: una constante anual o, mejor, la serie point-in-time de "
                "tu divisa."
            ),
            (
                "Pass risk_free_rate: an annual constant or, better, the point-in-time series of "
                "your currency."
            ),
        ),
        "diag.unadjusted": (
            (
                "Los precios no están ajustados por dividendos ni por splits: la rentabilidad no "
                "incluye dividendos."
            ),
            "Prices are not adjusted for dividends or splits: returns exclude dividends.",
        ),
        "diag.split_only": (
            (
                "Los precios están ajustados por splits pero no por dividendos: la rentabilidad "
                "no incluye dividendos."
            ),
            "Prices are split-adjusted but not dividend-adjusted: returns exclude dividends.",
        ),
        "diag.unadjusted.advice": (
            "Usa precios ajustados (adj_close) para medir la rentabilidad total.",
            "Use adjusted prices (adj_close) to measure the total return.",
        ),
        "diag.data_lag": (
            "La serie termina el {end}, {days} días antes de su descarga ({retrieved}).",
            "The series ends on {end}, {days} days before it was retrieved ({retrieved}).",
        ),
        "diag.data_lag.advice": (
            "Comprueba si el instrumento dejó de cotizar o si la fuente va con retraso.",
            "Check whether the instrument stopped trading or the source is lagging.",
        ),
        "diag.history_truncated": (
            (
                "El análisis empieza el {start}, cuando {symbol} empieza a cotizar; otros activos "
                "tienen datos desde el {earliest}."
            ),
            (
                "The analysis starts on {start}, when {symbol} starts trading; other holdings "
                "have data since {earliest}."
            ),
        ),
        "diag.history_truncated.advice": (
            "Las métricas de la cartera solo cubren el periodo común a todos los activos.",
            "Portfolio metrics only cover the period common to every holding.",
        ),
        "diag.risk_concentration": (
            "{symbol} aporta el {share} del riesgo de la cartera con un peso del {weight}.",
            "{symbol} contributes {share} of the portfolio risk with a {weight} weight.",
        ),
        "diag.risk_concentration.advice": (
            "Reduce su peso o reparte el riesgo si buscas diversificación.",
            "Reduce its weight or spread the risk if you seek diversification.",
        ),
        "diag.hedge": (
            "{symbol} reduce el riesgo total de la cartera (contribución del {share}).",
            "{symbol} lowers the total portfolio risk (contribution of {share}).",
        ),
        "diag.hedge.advice": (
            "Actúa como cobertura: valora si compensa su rentabilidad esperada.",
            "It acts as a hedge: weigh it against its expected return.",
        ),
        "diag.high_correlation": (
            (
                "{first} y {second} tienen una correlación de {correlation}: apenas se "
                "diversifican entre sí."
            ),
            (
                "{first} and {second} have a correlation of {correlation}: they barely diversify "
                "each other."
            ),
        ),
        "diag.high_correlation.advice": (
            "Valora si necesitas ambos activos.",
            "Consider whether you need both holdings.",
        ),
        "diag.nonsynchronous": (
            (
                "Los activos cotizan con horarios o calendarios distintos: correlaciones y "
                "contribución al riesgo usan retornos semanales para evitar el sesgo de los "
                "cierres no sincrónicos."
            ),
            (
                "Holdings trade on different hours or calendars: correlations and risk "
                "contributions use weekly returns to avoid the bias of non-synchronous closes."
            ),
        ),
        "diag.nonsynchronous.advice": (
            "Es el tratamiento recomendado; no requiere acción.",
            "This is the recommended treatment; no action needed.",
        ),
        "diag.weekly_unavailable": (
            (
                "Los activos cotizan con horarios distintos, pero no hay histórico suficiente "
                "para usar retornos semanales: las correlaciones con frecuencia {frequency} "
                "pueden estar infravaloradas."
            ),
            (
                "Holdings trade on different hours, but the history is too short for weekly "
                "returns: {frequency} correlations may be understated."
            ),
        ),
        "diag.weekly_unavailable.advice": (
            "Amplía el histórico para obtener correlaciones fiables.",
            "Extend the history to get reliable correlations.",
        ),
        "diag.stale_marks": (
            (
                "{symbol} se valoró con precios de hasta {age} periodos de antigüedad (en el "
                "{share} de las fechas no tenía precio observado)."
            ),
            (
                "{symbol} was valued with prices up to {age} periods old (no observed price on "
                "{share} of the dates)."
            ),
        ),
        "diag.stale_marks.advice": (
            "Es normal en los festivos de su mercado; si es frecuente, revisa la fuente.",
            "Normal on its market's holidays; if frequent, check the source.",
        ),
        "diag.high_turnover": (
            (
                "La rotación media es del {turnover} anual y no se modelan costes de transacción "
                "ni impuestos."
            ),
            (
                "Average turnover is {turnover} a year and transaction costs and taxes are not "
                "modelled."
            ),
        ),
        "diag.high_turnover.advice": (
            "Considera un rebalanceo menos frecuente o por bandas.",
            "Consider less frequent or threshold rebalancing.",
        ),
        "diag.leverage": (
            "La exposición bruta es del {exposure} (posiciones cortas o apalancadas).",
            "Gross exposure is {exposure} (short or leveraged positions).",
        ),
        "diag.leverage.advice": (
            "Vigila el riesgo de perder más que el capital y los costes de financiación.",
            "Watch the risk of losing more than the capital, and financing costs.",
        ),
        "diag.historical_drift": (
            (
                "La simulación usa la media histórica como rentabilidad esperada, cuyo error "
                "estándar es de ±{error} anual."
            ),
            (
                "The simulation uses the historical mean as expected return, whose standard "
                "error is ±{error} a year."
            ),
        ),
        "diag.historical_drift.advice": (
            "Para medir riesgo, usa drift zero o risk_free, o rentabilidades supuestas.",
            "To measure risk, use the zero or risk_free drift, or assumed returns.",
        ),
        "diag.wide_var_interval": (
            "El VaR simulado al {level} tiene un intervalo de confianza amplio ({low} a {high}).",
            "The simulated {level} VaR has a wide confidence interval ({low} to {high}).",
        ),
        "diag.wide_var_interval.advice": (
            "Aumenta n_paths para estrecharlo.",
            "Increase n_paths to narrow it.",
        ),
        # ── Portfolio sections ───────────────────────────────────────
        "composition.class": ("Clase", "Class"),
        "composition.weight": ("Peso objetivo", "Target weight"),
        "composition.start": ("Desde", "From"),
        "composition.end": ("Hasta", "To"),
        "composition.observations": ("Obs.", "Obs."),
        "composition.concentration": (
            (
                "Concentración de los pesos: índice de Herfindahl {hhi}, equivalente a "
                "{effective} activos con igual peso; exposición bruta del {gross}."
            ),
            (
                "Weight concentration: Herfindahl index {hhi}, equivalent to {effective} equally "
                "weighted assets; gross exposure {gross}."
            ),
        ),
        "comparison.note": (
            "Todas las cifras cubren el periodo común ({start} → {end}) para que sean comparables.",
            "Every figure covers the common period ({start} → {end}) so they are comparable.",
        ),
        "comparison.total": ("Rentab. total", "Total return"),
        "comparison.cagr": ("Anualizada", "Annualised"),
        "comparison.volatility": ("Volatilidad", "Volatility"),
        "comparison.sharpe": ("Sharpe", "Sharpe"),
        "comparison.max_drawdown": ("Máx. caída", "Max drawdown"),
        "correlation.note": (
            (
                "Correlaciones de los retornos con frecuencia {frequency}, calculadas con las "
                "observaciones comunes de cada par."
            ),
            (
                "Correlations of {frequency} returns, computed on the common observations of each "
                "pair."
            ),
        ),
        "correlation.single": (
            "Con un único activo no hay correlaciones que mostrar.",
            "A single holding has no correlations to show.",
        ),
        "risk.weight": ("Peso", "Weight"),
        "risk.volatility": ("Volatilidad anualizada", "Annualised volatility"),
        "risk.contribution": ("Contribución anualizada", "Annualised contribution"),
        "risk.share": ("% del riesgo", "Share of risk"),
        "risk.note": (
            (
                "Descomposición de Euler de la volatilidad ex ante (retornos con frecuencia "
                "{frequency}): las contribuciones suman la volatilidad de la cartera, "
                "{volatility}. Ratio de diversificación: {ratio} (1 = sin diversificación)."
            ),
            (
                "Euler decomposition of the ex-ante volatility ({frequency} returns): "
                "contributions add up to the portfolio volatility, {volatility}. Diversification "
                "ratio: {ratio} (1 = no diversification)."
            ),
        ),
        "rebalancing.policy": ("Política", "Policy"),
        "rebalancing.count": ("Rebalanceos", "Rebalances"),
        "rebalancing.turnover": ("Rotación total (un sentido)", "Total one-way turnover"),
        "rebalancing.annual_turnover": ("Rotación media anual", "Average annual turnover"),
        "rebalancing.note": (
            "No se modelan costes de transacción ni impuestos.",
            "Transaction costs and taxes are not modelled.",
        ),
        "valuation.timezone": ("Zona horaria", "Time zone"),
        "valuation.observations": ("Observaciones", "Observations"),
        "valuation.stale_share": ("Fechas sin precio observado", "Dates without a price"),
        "valuation.max_age": ("Antigüedad máxima (periodos)", "Maximum age (periods)"),
        "valuation.note": (
            (
                "Cuando un mercado no cotiza (festivos, fines de semana), el activo se valora con "
                "su último precio observado y se informa de su antigüedad; nunca se inventan "
                "precios."
            ),
            (
                "When a market is closed (holidays, weekends) the holding is valued at its last "
                "observed price and its age is reported; prices are never invented."
            ),
        ),
        # ── Monte Carlo ──────────────────────────────────────────────
        "simulation.model": ("Modelo", "Model"),
        "simulation.paths": ("Trayectorias", "Paths"),
        "simulation.horizon": ("Horizonte", "Horizon"),
        "simulation.horizon_value": (
            "{periods} (frecuencia {frequency})",
            "{periods} ({frequency})",
        ),
        "simulation.drift": ("Rentabilidad esperada", "Expected return"),
        "simulation.volatility": ("Volatilidad", "Volatility"),
        "simulation.covariance": ("Covarianza", "Covariance"),
        "simulation.calibration": ("Periodos de calibración", "Calibration periods"),
        "simulation.seed": ("Semilla", "Seed"),
        "simulation.initial_value": ("Valor inicial", "Initial value"),
        "simulation.expected": ("Valor esperado (± error estándar)", "Expected value (± SE)"),
        "simulation.median": ("Valor mediano", "Median value"),
        "simulation.loss_probability": ("Probabilidad de pérdida", "Probability of loss"),
        "simulation.var": ("VaR al {level} (IC 95\u00a0%)", "{level} VaR (95% CI)"),
        "simulation.cvar": ("CVaR al {level}", "{level} CVaR"),
        "simulation.drawdown_at_risk": (
            "Caída máxima al {level} (drawdown at risk)",
            "{level} drawdown at risk",
        ),
        "simulation.expected_drawdown": (
            "Caída máxima media en el horizonte",
            "Average maximum drawdown",
        ),
        "simulation.note": (
            (
                "VaR y CVaR son pérdidas sobre el horizonte completo, como fracción del valor "
                "inicial; la política de rebalanceo se aplica dentro de cada trayectoria."
            ),
            (
                "VaR and CVaR are losses over the whole horizon as a fraction of the initial "
                "value; the rebalancing policy runs inside every path."
            ),
        ),
        # ── Methodology ──────────────────────────────────────────────
        "method.returns": (
            (
                "Retornos simples entre observaciones consecutivas, en el calendario de cada "
                "activo: un festivo es un hueco, nunca un retorno del 0\u00a0%, y no se interpola "
                "ningún dato."
            ),
            (
                "Simple returns between consecutive observations on each asset's own calendar: a "
                "holiday is a gap, never a 0% return, and no data is interpolated."
            ),
        ),
        "method.annualisation": (
            (
                "Anualización con {periods} periodos por año según el mercado y la frecuencia; la "
                "rentabilidad anualizada es compuesta (geométrica)."
            ),
            (
                "Annualised with {periods} periods per year for the market and frequency; the "
                "annualised return is compound (geometric)."
            ),
        ),
        "method.sharpe": (
            (
                "Sharpe y Sortino miden el exceso de rentabilidad sobre el tipo libre de riesgo "
                "conocido en cada fecha, en TAE según la convención de cada serie (ACT/360 en el "
                "mercado monetario); el intervalo del Sharpe usa el error estándar de Mertens "
                "(2002), que tiene en cuenta la asimetría y la curtosis."
            ),
            (
                "Sharpe and Sortino measure the excess return over the risk-free rate known at "
                "each date, as an effective annual rate under each series' convention (ACT/360 "
                "in money markets); the Sharpe interval uses the Mertens (2002) standard error, "
                "which accounts for skewness and kurtosis."
            ),
        ),
        "method.var": (
            (
                "VaR y CVaR por periodo, como pérdidas positivas: histórico (cuantil empírico), "
                "normal y Cornish-Fisher (corregido por asimetría y curtosis)."
            ),
            (
                "VaR and CVaR per period, as positive losses: historical (empirical quantile), "
                "Gaussian and Cornish-Fisher (corrected for skewness and kurtosis)."
            ),
        ),
        "method.quality": (
            (
                "Las incidencias de calidad se detectan y se informan; los datos nunca se borran "
                "ni se modifican."
            ),
            "Data-quality issues are detected and reported; data is never removed or altered.",
        ),
        "method.portfolio": (
            (
                "La cartera se valora con el último precio observado de cada activo y con su "
                "política de rebalanceo; las métricas cubren el periodo común a todos los activos "
                "y no incluyen costes de transacción ni impuestos."
            ),
            (
                "The portfolio is valued at each holding's last observed price under its "
                "rebalancing policy; metrics cover the period common to every holding and exclude "
                "transaction costs and taxes."
            ),
        ),
        "method.footer": (
            "Informe generado con InvestingLab {version}.",
            "Report generated with InvestingLab {version}.",
        ),
        # ── Charts ───────────────────────────────────────────────────
        "chart.price": ("Precio de {symbol} ({currency})", "{symbol} price ({currency})"),
        "chart.drawdown": ("Caída desde máximos de {subject}", "{subject} drawdown"),
        "chart.drawdown_portfolio": (
            "Caída desde máximos de la cartera",
            "Portfolio drawdown",
        ),
        "chart.returns": (
            "Distribución de los retornos (frecuencia {frequency})",
            "Return distribution ({frequency})",
        ),
        "chart.volatility": (
            "Volatilidad anualizada móvil ({window} periodos)",
            "Rolling annualised volatility ({window} periods)",
        ),
        "chart.growth": (
            "Evolución y rendimiento comparado (base 100)",
            "Growth and performance comparison (base 100)",
        ),
        "chart.correlation": (
            "Correlaciones (frecuencia {frequency})",
            "Correlations ({frequency})",
        ),
        "chart.risk_contribution": (
            "Peso frente a contribución al riesgo",
            "Weight versus risk contribution",
        ),
        "chart.weights": ("Pesos efectivos de la cartera", "Effective portfolio weights"),
        "chart.axis.price": ("Precio", "Price"),
        "chart.axis.drawdown": ("Caída", "Drawdown"),
        "chart.axis.periods": ("Periodos", "Periods"),
        "chart.axis.return": ("Retorno", "Return"),
        "chart.axis.volatility": ("Volatilidad", "Volatility"),
        "chart.axis.index": ("Índice (base 100)", "Index (base 100)"),
        "chart.axis.weight": ("Peso", "Weight"),
        "chart.legend.normal": ("Normal ajustada", "Fitted normal"),
        "chart.legend.var": ("VaR histórico {level}", "Historical VaR {level}"),
        "chart.legend.average": ("Media del periodo ({value})", "Period average ({value})"),
        "chart.legend.weight": ("Peso objetivo", "Target weight"),
        "chart.legend.risk": ("Contribución al riesgo", "Risk contribution"),
        "chart.label.trough": ("{value} ({date})", "{value} ({date})"),
        "chart.colorbar": ("Correlación", "Correlation"),
        "chart.simulation.paths": ("Trayectorias simuladas del valor", "Simulated value paths"),
        "chart.simulation.terminal": ("Valor al horizonte", "Value at the horizon"),
        "chart.simulation.outer": ("Percentiles 5-95", "5-95 percentiles"),
        "chart.simulation.inner": ("Percentiles 25-75", "25-75 percentiles"),
        "chart.simulation.median": ("Mediana", "Median"),
        "chart.simulation.initial": ("Valor inicial", "Initial value"),
        "chart.simulation.ahead": ("Periodos simulados", "Periods ahead"),
        "chart.simulation.value": ("Valor", "Value"),
        "chart.simulation.count": ("Trayectorias", "Paths"),
        "chart.simulation.var": ("VaR {level}", "VaR {level}"),
        "chart.simulation.cvar": ("CVaR {level}", "CVaR {level}"),
        "chart.simulation.title": (
            "Monte Carlo · {model} · {paths} trayectorias · {horizon} · P(pérdida) {loss}",
            "Monte Carlo · {model} · {paths} paths · {horizon} · P(loss) {loss}",
        ),
    }
)


def catalogue() -> Mapping[str, tuple[str, str]]:
    """Every message as ``key -> (spanish, english)`` (read-only)."""
    return _CATALOGUE


def _grouped(value: float, decimals: int, language: Language) -> str:
    thousands, decimal = _SEPARATORS[language]
    text = f"{abs(value):,.{decimals}f}"
    table: dict[str, str | int | None] = {",": thousands, ".": decimal}
    return text.translate(str.maketrans(table))


class Translator:
    """Texts and number formats in one language.

    Args:
        language: ``es`` (default) or ``en``.

    Raises:
        ValueError: If the language is not supported.
    """

    __slots__ = ("_index", "_language")

    def __init__(self, language: Language | str = Language.ES) -> None:
        self._language = Language(language)
        self._index = 0 if self._language is Language.ES else 1

    @property
    def language(self) -> Language:
        """Language of the texts."""
        return self._language

    def text(self, key: str, /, **params: object) -> str:
        """The message ``key`` with its placeholders filled.

        Raises:
            KeyError: If the key does not exist (a programming error).
        """
        return _CATALOGUE[key][self._index].format(**params)

    def number(self, value: float | None, decimals: int = 2, *, signed: bool = False) -> str:
        """A number with the language's separators (``1.234,57`` / ``1,234.57``)."""
        if value is None or math.isnan(value):
            return MISSING
        if math.isinf(value):
            return "∞" if value > 0 else "-∞"
        text = _grouped(value, decimals, self._language)
        rounded = round(value, decimals)
        if rounded < 0:
            return f"-{text}"
        if signed and rounded > 0:
            return f"+{text}"
        return text

    def percent(self, value: float | None, decimals: int = 1, *, signed: bool = False) -> str:
        """A fraction as a percentage (``0.123`` → ``12,3 %`` / ``12.3%``)."""
        if value is None or math.isnan(value):
            return MISSING
        return self.number(value * 100.0, decimals, signed=signed) + _PERCENT_SUFFIX[self._language]

    def integer(self, value: float | None) -> str:
        """A whole number with thousands separators."""
        return self.number(value, 0)

    def date(self, value: date | datetime | pd.Timestamp | None) -> str:
        """ISO 8601 date (session labels) or date and time (timestamps, shown in UTC)."""
        if value is None or pd.isna(value):
            return MISSING
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC")
            return stamp.strftime("%Y-%m-%d %H:%M UTC")
        if stamp == stamp.normalize():
            return stamp.strftime("%Y-%m-%d")
        return stamp.strftime("%Y-%m-%d %H:%M")

    def plural(self, key: str, count: float) -> str:
        """``count`` with the singular or plural noun of ``key`` (``1 activo``, ``3 activos``)."""
        form = "one" if count == 1 else "other"
        return self.text(f"{key}.{form}", count=self.integer(count))

    def frequency(self, value: str) -> str:
        """Name of a frequency (``1d`` → ``diaria`` / ``daily``)."""
        return self.text(f"frequency.{value}")
