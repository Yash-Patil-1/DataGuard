<div align="center">
  <h1>🛡️ DataGuard</h1>
  <p><strong>Automated Data Quality & Anomaly Detection Framework</strong></p>
  <p>
    <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
    <img src="https://img.shields.io/badge/status-production%20ready-brightgreen" alt="Production Ready">
    <img src="https://img.shields.io/badge/coverage-72%20tests-passing-brightgreen" alt="72 tests passing">
    <img src="https://img.shields.io/github/actions/workflow/status/Yash-Patil-1/dataguard/dataguard-ci.yml?branch=main&label=CI&logo=github" alt="CI">
  </p>
</div>

---

**DataGuard** is an end-to-end data quality monitoring framework that automatically detects, measures, and alerts on data quality issues. It combines statistical checks, machine learning-based anomaly detection, time-series drift monitoring, and an interactive dashboard — all in a single, extensible Python package.

### ✨ Features

| Feature | Description |
|---------|-------------|
| **🧪 6 Quality Dimensions** | Completeness, Uniqueness, Validity, Consistency, Timeliness, Accuracy |
| **🔍 4 Anomaly Methods** | IQR, Z-score, Modified Z-score (MAD), Isolation Forest |
| **📈 Drift Detection** | Rolling window analysis across 30-day time series |
| **🖥️ Interactive Dashboard** | 6-page Streamlit dashboard with drill-downs and live charts |
| **📚 Data Catalog** | Auto-generated schema documentation with column profiles & quality flags |
| **🔔 Alerting** | Slack webhook + SMTP email + console alerts with configurable thresholds |
| **⏰ Scheduling** | Built-in continuous loop + cron-style for CI/CD integration |
| **✅ 72+ Unit Tests** | Comprehensive test coverage across all modules |

---

## 📦 Quick Start

```bash
# Clone
git clone https://github.com/Yash-Patil-1/dataguard.git
cd dataguard

# Install
pip install -r requirements.txt

# Generate sample data with intentionally injected quality issues
python src/data_generator.py

# Run quality checks
python src/validators.py

# Run anomaly detection
python src/detectors.py

# Launch the dashboard
streamlit run dashboard.py
```

Or use the all-in-one runner:

```bash
python run_pipeline.py
python run_pipeline.py --alert          # with Slack/Email alerts
python run_pipeline.py --schedule       # every hour
```

---

## 🏗️ Architecture

```
DataGuard/
├── src/
│   ├── config.py          # Configuration & data quality issue definitions
│   ├── data_generator.py  # Synthetic data generator with quality issues
│   ├── validators.py      # 6 modular quality checkers + pipeline
│   ├── detectors.py       # 4 anomaly/drift detection methods + pipeline
│   ├── data_catalog.py    # Auto-column profiling & data catalog
│   ├── alerts.py          # Slack/Email/Console alert dispatcher
│   └── utils.py           # QualityReport, scoring, reporting utilities
├── tests/
│   ├── test_validators.py # 14 tests — completeness, uniqueness, validity, etc.
│   ├── test_detectors.py  # 9 tests — IQR, Z-score, IForest, drift
│   └── test_utils.py      # 8 tests — report, alerts, formatting
├── config/
│   ├── thresholds.yaml    # Configurable pass/fail thresholds
│   └── alerts.yaml        # Alert channel configuration
├── data/                  # Generated datasets (auto-created)
├── reports/               # Quality reports (auto-created)
├── dashboard.py           # Streamlit interactive dashboard
├── run_pipeline.py        # CLI pipeline orchestrator
└── README.md              # You are here
```

### Data Flow

```
Data Generation ──► Quality Checks ──► Anomaly Detection ──► Alerts
       │                    │                   │                │
       ▼                    ▼                   ▼                ▼
  CSV Files          QualityReport        Anomaly Scores     Slack/Email
  (30 days)          (JSON + TXT)         (per method)       + Console
       │                    │                   │
       ▼                    ▼                   ▼
  ┌─────────────────────────────────────────────────────┐
  │            Streamlit Dashboard (6 pages)            │
  │  Overview │ Data Quality │ Anomalies │ Drift │      │
  │  Data Explorer │ Data Catalog                        │
  └─────────────────────────────────────────────────────┘
```

---

## 🧪 Quality Dimensions

Each dimension is implemented as a **modular checker class** in `src/validators.py`:

| Dimension | Checker | What It Detects |
|-----------|---------|-----------------|
| **Completeness** | `CompletenessChecker` | Null rates per column, empty strings |
| **Uniqueness** | `UniquenessChecker` | Exact row duplicates, key column duplicates |
| **Validity** | `ValidityChecker` | Email format (regex), future dates, numeric range violations |
| **Consistency** | `ConsistencyChecker` | Referential integrity (orphan IDs), amount calculation accuracy, city-state mapping |
| **Timeliness** | `TimelinessChecker` | Data freshness (hours since last update), recent data ratio |
| **Accuracy** | `AccuracyChecker` | Distribution shift vs ground truth (mean/std comparison) |

**Scoring:** Each check produces a 0.0–1.0 score. Dimension scores are weighted and aggregated into an **Overall Quality Score** with PASS (≥75%), WARNING (50–75%), or CRITICAL (<50%) status.

---

## 🔍 Anomaly Detection

Four detection methods in `src/detectors.py`:

| Method | Type | Best For |
|--------|------|----------|
| **IQR** | Statistical | Univariate outliers, simple threshold-based detection |
| **Z-score** | Statistical | Normally distributed data, standard deviation-based |
| **Modified Z-score** | Robust | Data with outliers already present (MAD-based) |
| **Isolation Forest** | ML-based | Multivariate anomalies — unusual combinations of values |
| **Drift Detection** | Time-series | Distribution shifts over time (rolling window) |

---

## 🖥️ Dashboard

The Streamlit dashboard has **6 interactive pages**:

| Page | Features |
|------|----------|
| **📊 Overview** | KPI cards, quality dimension bar chart, missing value pie chart |
| **🧪 Data Quality** | Full checks table, pass/fail breakdown, failures by dimension |
| **🔍 Anomaly Detection** | Method comparison, top IForest anomalies, outlier counts by column |
| **📈 Drift Analysis** | Multi-metric quality trends over 30 days, category drift, alert detail tabs |
| **🔎 Data Explorer** | Null-highlighted preview, dirty vs clean comparison, per-column profiles |
| **📚 Data Catalog** | Schema overview, column stats & distributions, cross-table comparison |

```bash
streamlit run dashboard.py
```

---

## 🔔 Alerting

Configure alerts in `config/alerts.yaml` or via environment variables:

```bash
# Slack
export DATAGUARD_SLACK_WEBHOOK="https://hooks.slack.com/services/..."

# Email
export DATAGUARD_SMTP_HOST="smtp.gmail.com"
export DATAGUARD_SMTP_USER="your@gmail.com"
export DATAGUARD_SMTP_PASS="app-password"
export DATAGUARD_ALERT_EMAILS="team@company.com"

# Run with alerts
python run_pipeline.py --alert
```

Alert triggers: critical score drop, any check failures, drift events, daily summary.

---

## ⏰ Scheduling

```bash
# Continuous loop (every hour)
python run_pipeline.py --schedule --interval 3600

# One-shot (for cron/CI)
python run_pipeline.py --alert

# Specific stages only
python run_pipeline.py --stages validate,detect
```

---

## 🧪 Testing

```bash
pytest tests/ -v
# 72+ tests passed (all modules, including connectors, data catalog & history)
```

---

## 📁 Generated Data

| File | Description |
|------|-------------|
| `customers.csv` | 8,000 clean customer records |
| `all_orders_combined.csv` | ~50,000 dirty orders with injected issues |
| `ground_truth_orders.csv` | ~50,000 clean orders (no issues) for comparison |
| `daily_orders_01–30.csv` | 30 daily snapshots with escalating quality issue rates |
| `quality_issues_log.json` | Audit trail of all injected quality issues |

Quality issues escalate over the 30-day period: null rates increase from 3–12% to 6–24%, duplicate rates from 3% to 9%, email invalidity from 5% to 11%, and category distributions drift.

---

## 🛠️ Configuration

All thresholds are configurable via YAML:

```yaml
# config/thresholds.yaml
completeness:
  max_null_rate:
    _default: 0.10
    customer_email: 0.15
    unit_price: 0.10
  min_completeness_score: 0.85

scoring:
  dimension_weights:
    completeness: 0.25
    validity: 0.25
    uniqueness: 0.20
    consistency: 0.15
    timeliness: 0.15
  severity:
    critical: 0.50
    warning: 0.75
```

---

## 📊 Sample Output

```
============================================================
  Quality Report: all_orders_combined
  Timestamp:      2026-05-26 11:10:17
============================================================
  Overall Score:  56.4%  [WARNING]
============================================================
   Dimension                  Score     Status
  ---------------------------------------------
   accuracy                  43.3%       FAIL
   anomaly_drift              0.0%       FAIL
   anomaly_iforest          100.0%       PASS
   anomaly_iqr               44.0%       FAIL
   anomaly_zscore            60.7%       WARN
   completeness              74.7%       WARN
   consistency               86.3%       PASS
   timeliness                52.4%       WARN
   uniqueness                 0.0%       FAIL
   validity                  67.6%       WARN
  ---------------------------------------------
  Checks: 35 total, 24 passed, 11 failed
============================================================
```

---

## 📄 License

[MIT License](LICENSE)

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing`)
3. Run tests (`pytest tests/ -v`)
4. Commit your changes (`git commit -m 'Add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing`)
6. Open a Pull Request

---

## 📬 Contact

**Yash Patil**

- 📧 [yashpatil7714@gmail.com](mailto:yashpatil7714@gmail.com)
- 🔗 [LinkedIn](https://www.linkedin.com/in/yash-patil-997357330)
- 🐙 [GitHub](https://github.com/Yash-Patil-1)

---

<div align="center">
  <sub>Built with ❤️ for reliable data pipelines</sub>
</div>
