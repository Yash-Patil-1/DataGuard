# 📖 Usage Guide

## Command Line Reference

### `python src/data_generator.py`

Generates all synthetic datasets. Creates `data/` directory with:
- `customers.csv` — 8,000 clean customer records
- `all_orders_combined.csv` — ~50K dirty orders
- `ground_truth_orders.csv` — ~50K clean orders
- `daily_orders_XX.csv` — 30 daily snapshots
- `quality_issues_log.json` — audit trail

### `python src/validators.py`

Runs the 6 quality checkers on the generated data. Produces:
- Console output with per-dimension scores
- `reports/quality_report_YYYYMMDD_HHMMSS.json`
- `reports/quality_report_latest.txt`

### `python src/detectors.py`

Runs 4 anomaly detection methods. Produces:
- Console output with per-method scores
- JSON and TXT reports (same format as validators)

### `python src/data_catalog.py`

Prints a terminal-optimized catalog summary showing:
- Table-level stats (rows, columns, size, health)
- Per-column profiles (type, nulls, uniques, quality flags)
- Cross-table comparison (dirty vs clean)

### `python run_pipeline.py`

All-in-one runner with CLI arguments:

```bash
# Full pipeline (generate + validate + detect)
python run_pipeline.py

# With alerting
python run_pipeline.py --alert

# Scheduled mode (continuous loop)
python run_pipeline.py --schedule --interval 3600

# Specific stages
python run_pipeline.py --stages generate
python run_pipeline.py --stages validate
python run_pipeline.py --stages detect
python run_pipeline.py --stages validate,detect

# For cron/CI integration (one-shot with alerts)
0 * * * * cd /path/to/dataguard && python run_pipeline.py --alert
```

### `streamlit run dashboard.py`

Launches the interactive dashboard at `http://localhost:8501`.

### `pytest tests/ -v`

Runs all 43 unit tests.

---

## Configuration Reference

### `config/thresholds.yaml`

```yaml
completeness:
  max_null_rate:
    _default: 0.10        # Default max null rate (10%)
    customer_email: 0.15  # Per-column override (15%)
    unit_price: 0.10
    shipping_city: 0.08
    customer_age: 0.05
  min_completeness_score: 0.85

uniqueness:
  max_duplicate_rate: 0.03  # Max 3% duplicates
  min_uniqueness_score: 0.95

validity:
  email_validity_rate: 0.90      # Min 90% valid emails
  future_date_rate: 0.02         # Max 2% future dates
  min_validity_score: 0.85
  range_checks:
    quantity: {min: 1, max: 50}
    unit_price: {min: 1, max: 200000}
    customer_age: {min: 0, max: 120}

consistency:
  referential_integrity_rate: 0.98
  min_consistency_score: 0.90

timeliness:
  max_data_freshness_hours: 48
  min_timeliness_score: 0.90

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

### `config/alerts.yaml`

```yaml
slack:
  enabled: false
  webhook_url: ""           # Or set DATAGUARD_SLACK_WEBHOOK env var
  channel: "#data-quality"
  username: "DataGuard Bot"
  icon_emoji: ":shield:"

email:
  enabled: false
  smtp_host: ""             # Or set DATAGUARD_SMTP_HOST env var
  smtp_port: 587
  use_tls: true
  username: ""              # Or set DATAGUARD_SMTP_USER
  password: ""              # Or set DATAGUARD_SMTP_PASS
  from_addr: "dataguard@example.com"
  to_addrs: []              # Or set DATAGUARD_ALERT_EMAILS (comma-separated)

console:
  enabled: true             # Always logs to Python logger

alert_on:
  critical_score: true      # Alert when overall score < critical threshold
  any_failures: false       # Alert on any check failure
  drift_events: true        # Alert on drift detection events
  daily_summary: true       # Send daily summary even without failures
```

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATAGUARD_SLACK_WEBHOOK` | Slack incoming webhook URL |
| `DATAGUARD_SMTP_HOST` | SMTP server hostname |
| `DATAGUARD_SMTP_PORT` | SMTP port (default: 587) |
| `DATAGUARD_SMTP_USER` | SMTP username |
| `DATAGUARD_SMTP_PASS` | SMTP password |
| `DATAGUARD_FROM_EMAIL` | From address for alert emails |
| `DATAGUARD_ALERT_EMAILS` | Comma-separated recipient email addresses |

---

## Python Library Usage

### Quality Checks
```python
from src.validators import QualityPipeline
from src.utils import load_thresholds

# Load config
thresholds = load_thresholds("config/thresholds.yaml")

# Run pipeline
pipeline = QualityPipeline(thresholds)
report = pipeline.run_all(df, dataset_name="my_data")

# Access results
print(report.overall_score)       # 0.56
print(report.status)              # "warning"
print(report.dimension_scores)    # {"completeness": 0.75, ...}

# Save
from src.utils import save_report
save_report(report, "reports/")
```

### Anomaly Detection
```python
from src.detectors import AnomalyPipeline

pipeline = AnomalyPipeline(
    iqr_multiplier=1.5,
    z_threshold=3.0,
    iforest_contamination=0.05,
)
report = pipeline.run_all(
    df,
    dataset_name="my_data",
    daily_dir="data/daily/",
)

for check in report.checks:
    print(f"{check['check']}: {check['score']:.2f} ({'PASS' if check['passed'] else 'FAIL'})")
```

### Data Catalog
```python
from src.data_catalog import generate_catalog

catalog = generate_catalog()
orders = catalog["tables"]["orders"]
print(f"Rows: {orders['row_count']:,}")
print(f"Columns: {orders['column_count']}")
for col in orders["columns"]:
    print(f"  {col['name']:25s} | {col['dtype']:12s} | null={col['null_rate']:.1%}")
```

### Custom Alerting
```python
from src.alerts import load_alert_config, evaluate_and_alert

config = load_alert_config("config/alerts.yaml")
results = evaluate_and_alert(report.to_dict(), config)

for r in results:
    print(f"Alert '{r['type']}' sent: {r['channels']}")
```

---

## Docker Usage

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f pipeline

# Run single pipeline container
docker compose run --rm pipeline

# Stop
docker compose down

# Rebuild
docker compose build --no-cache
```

Services:
- **pipeline**: Runs generate + validate + detect on start, then exits
- **dashboard**: Streamlit app on port 8501
- **scheduler**: Runs pipeline every hour (configurable via interval env var)
