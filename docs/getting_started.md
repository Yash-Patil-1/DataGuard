# 🚀 Getting Started with DataGuard

This guide walks you through your first DataGuard run — from installation to exploring the dashboard.

## Prerequisites

- **Python 3.9+** installed on your system
- **pip** package manager
- Basic familiarity with the command line

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/dataguard.git
cd dataguard

# Install dependencies
pip install -r requirements.txt

# (Optional) Create a virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

## Your First Run

### 1. Generate Sample Data

DataGuard includes a synthetic data generator that creates realistic e-commerce data with intentionally injected quality issues. This lets you see the framework in action immediately.

```bash
python src/data_generator.py
```

This creates:
- `data/customers.csv` — 8,000 clean customer records
- `data/all_orders_combined.csv` — ~50,000 orders with quality issues
- `data/ground_truth_orders.csv` — ~50,000 clean orders for comparison
- `data/daily_orders_01.csv` through `data/daily_orders_30.csv` — 30 daily snapshots
- `data/quality_issues_log.json` — audit trail of all injected issues

### 2. Run Quality Checks

```bash
python src/validators.py
```

You'll see output like:

```
============================================================
  DataGuard — Quality Check Engine
============================================================

[1/4] Loading thresholds...
       > Loaded from ...\config\thresholds.yaml

[2/4] Loading data...
       > 50,000 rows, 18 columns
       > Customers table: 8,000 rows

[3/4] Running quality checks...
  > Running completeness checks...
  > Running uniqueness checks...
  > Running validity checks...
  > Running consistency checks...
  > Running timeliness checks...

[4/4] Results:
============================================================
  Quality Report: all_orders_combined
  ...
  Overall Score:  56.4%  [WARNING]
============================================================
```

### 3. Run Anomaly Detection

```bash
python src/detectors.py
```

### 4. Launch the Dashboard

```bash
streamlit run dashboard.py
```

This opens your browser at `http://localhost:8501` with the full interactive dashboard.

### 5. Use the All-in-One Runner

```bash
python run_pipeline.py
```

This runs generation (if needed), validation, and anomaly detection in a single command.

---

## Next Steps

- [Usage Guide](usage.md) — Detailed CLI reference and configuration
- [Architecture](architecture.md) — Deep dive into the codebase design
- [Development](development.md) — Guide for contributors and extending DataGuard
- [README.md](../README.md) — Project overview and feature summary
