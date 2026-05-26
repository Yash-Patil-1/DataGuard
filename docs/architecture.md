# 🏗️ Architecture

This document describes the internal architecture of DataGuard — how the components interact, the data flow, and key design decisions.

## Overview

DataGuard follows a **modular pipeline architecture** with clear separation of concerns:

```
┌──────────────────────────────────────────────────────────────────┐
│                        Data Layer                                 │
│  customers.csv │ daily_orders_*.csv │ all_orders_combined.csv    │
│  ground_truth_orders.csv │ quality_issues_log.json               │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Pipeline Layer                               │
│                                                                  │
│  config/thresholds.yaml ──► QualityPipeline                      │
│                                ├── CompletenessChecker           │
│                                ├── UniquenessChecker             │
│                                ├── ValidityChecker               │
│                                ├── ConsistencyChecker            │
│                                ├── TimelinessChecker             │
│                                └── AccuracyChecker                │
│                                                                  │
│  data/daily_*.csv ──► AnomalyPipeline                            │
│                          ├── IQROutlierDetector                  │
│                          ├── ZScoreDetector                      │
│                          ├── DriftDetector                       │
│                          └── IsolationForestDetector             │
│                                                                  │
│  QualityReport ◄────── Both pipelines produce checks             │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Alert Layer                                  │
│  evaluate_and_alert() ──► send_slack_alert()                     │
│                        ──► send_email_alert()                    │
│                        ──► console logging                       │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                   Presentation Layer                              │
│  Streamlit Dashboard (6 pages)                                   │
│  ├── Overview         ── KPI cards, dimension chart              │
│  ├── Data Quality     ── Checks table, pass/fail breakdown       │
│  ├── Anomaly Detection ── Method comparison, top anomalies       │
│  ├── Drift Analysis   ── Quality trends over 30 days             │
│  ├── Data Explorer    ── Raw data, comparison, profiles          │
│  └── Data Catalog     ── Schema, column stats, cross-table       │
└──────────────────────────────────────────────────────────────────┘
```

## Module Details

### `src/config.py`
Central configuration module containing:
- **Project constants**: paths, seed, date ranges, scale parameters
- **Product catalog**: 6 categories × 20 products each = 120 products
- **City/state mapping**: 20 Indian cities with their states
- **Quality issue definitions**: base rates and drift factors for each issue type
- **Helper functions**: `get_daily_issue_rate()`, `get_daily_category_weights()`

### `src/data_generator.py`
Synthetic data generator that creates realistic e-commerce data:
- Generates 8,000 customers with Indian names, cities, and states
- Creates 30 daily snapshots (~1,667 orders/day each)
- Injects escalating quality issues (nulls, duplicates, outliers, bad formats)
- Saves ground truth (clean) version for accuracy comparison
- Logs every injected issue with type, rate, and day

### `src/validators.py`
6 modular checker classes, each inheriting a common pattern:
- **`run(df)`** method returns a list of standardized check result dicts
- Each check produces: `score` (0.0–1.0), `passed` (bool), `details` (dict)
- **`QualityPipeline`** orchestrates all 6 checkers and returns a `QualityReport`

### `src/detectors.py`
4 anomaly detection methods:
- **IQR**: 1.5×IQR rule with per-column bounds
- **Z-score**: Standard σ-based and Modified MAD-based
- **Drift**: Rolling window z-score on daily quality metrics
- **Isolation Forest**: sklearn implementation for multivariate anomalies

### `src/data_catalog.py`
Auto-profiling module:
- `profile_column()` — deep analysis of a single column (stats, flags)
- `profile_table()` — aggregates column profiles into table summary
- `generate_catalog()` — profiles all datasets and includes cross-table comparison

### `src/alerts.py`
Alert dispatcher with graceful degradation:
- **Slack**: Incoming webhooks via urllib
- **Email**: SMTP with optional TLS
- **Console**: Always logs to Python logger
- `evaluate_and_alert()` evaluates report against alert thresholds

### `src/utils.py`
Shared utilities:
- `QualityReport` — collects checks, computes dimension scores, serializes to dict
- `check_result()` — standardized result factory function
- `save_report()` — writes JSON + TXT report files

## Key Design Decisions

### 1. Standardized Check Result Format
Every check — whether from validators or detectors — returns the same dict format:
```python
{
    "dimension": "completeness",
    "check": "null_rate_customer_email",
    "passed": True/False,
    "score": 0.0–1.0,
    "threshold": 0.10,
    "details": { ... },  # check-specific data
    "timestamp": "2026-05-26T..."
}
```
This allows the `QualityReport` class to aggregate checks from any source.

### 2. Configurable Thresholds via YAML
All thresholds are externalized in `config/thresholds.yaml`, allowing users to tune without modifying code. The system falls back to built-in defaults if the file is missing.

### 3. Modular Checkers
Each quality dimension is an independent class. Adding a new checker requires:
1. Create a new class with a `run()` method returning check results
2. Add it to `QualityPipeline.run_all()`
3. Define thresholds in `config/thresholds.yaml`

### 4. Graceful Degradation
- Missing data files return None instead of crashing
- Missing sklearn → Isolation Forest is skipped
- Missing YAML file → defaults are used
- Empty DataFrames → informative check result instead of crash

### 5. Caching
The dashboard uses Streamlit's `@st.cache_data` decorator to avoid recomputing:
- Data loading (CSV files, ~50K rows)
- Quality reports (JSON parsing)
- Daily quality timelines (30-day aggregation)
- Data catalog generation (column profiling)

## Data Flow Example

```
1. python run_pipeline.py
2.   ├── PipelineRunner ensures directories exist
3.   ├── run_generate() checks if data exists, generates if not
4.   ├── run_validate()
5.   │   ├── Loads thresholds from config/thresholds.yaml
6.   │   ├── Loads all_orders_combined.csv
7.   │   ├── QualityPipeline.run_all()
8.   │   │   ├── CompletenessChecker.run()
9.   │   │   ├── UniquenessChecker.run()
10.  │   │   ├── ...
11.  │   │   └── Returns QualityReport
12.  │   └── save_report() writes JSON + TXT
13.  ├── run_detect()
14.  │   ├── AnomalyPipeline.run_all()
15.  │   │   ├── IQROutlierDetector.run()
16.  │   │   ├── IsolationForestDetector.run()
17.  │   │   └── Returns QualityReport
18.  │   └── Merges anomaly checks into main report
19.  └── run_alerts() (if --alert flag)
20.      ├── evaluate_and_alert() checks thresholds
21.      └── dispatch_alerts() sends Slack/Email
```

## Extending DataGuard

### Adding a new quality checker:
```python
class MyNewChecker:
    def __init__(self, thresholds):
        self.thresholds = thresholds.get("my_dimension", {})

    def run(self, df):
        results = []
        # ... your logic ...
        results.append(check_result(
            dimension="my_dimension",
            check_name="my_check",
            passed=passed,
            score=score,
            threshold=0.05,
            details={...}
        ))
        return results
```

### Adding a new anomaly detector:
```python
class MyDetector:
    def run(self, df):
        results = []
        # ... your logic ...
        return results

# In AnomalyPipeline.run_all():
# detector = MyDetector()
# for r in detector.run(df):
#     report.add_check(r)
```
