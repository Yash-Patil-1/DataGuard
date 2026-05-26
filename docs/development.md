# 💻 Development Guide

## Setup for Development

```bash
# Clone the repository
git clone https://github.com/yourusername/dataguard.git
cd dataguard

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install development dependencies
pip install -r requirements.txt
pip install pytest pytest-cov  # Testing tools
```

## Project Structure

```
DataGuard/
├── src/                  # Source code
│   ├── __init__.py       # (optional) Package init
│   ├── config.py         # Configuration & constants
│   ├── data_generator.py # Synthetic data with quality issues
│   ├── validators.py     # 6 quality checkers + pipeline
│   ├── detectors.py      # 4 anomaly methods + pipeline
│   ├── data_catalog.py   # Auto-column profiling
│   ├── alerts.py         # Slack/Email/Console alerts
│   └── utils.py          # Report, scoring, utilities
├── tests/                # Unit tests
│   ├── test_validators.py
│   ├── test_detectors.py
│   └── test_utils.py
├── config/               # Configuration files
│   ├── thresholds.yaml
│   └── alerts.yaml
├── data/                 # Generated data (gitignored)
├── reports/              # Generated reports (gitignored)
├── docs/                 # Documentation
│   ├── getting_started.md
│   ├── usage.md
│   ├── architecture.md
│   └── development.md
├── dashboard.py          # Streamlit dashboard
├── run_pipeline.py       # Pipeline orchestrator
├── Dockerfile            # Docker build
├── docker-compose.yml    # Docker orchestration
└── requirements.txt      # Python dependencies
```

## Coding Standards

### Style
- Follow **PEP 8** for Python code
- Use **type hints** for all function signatures
- Write **docstrings** for all classes and public methods (Google style)
- Keep lines under **100 characters**

### Naming Conventions
- **Classes**: `PascalCase` (e.g., `CompletenessChecker`, `AnomalyPipeline`)
- **Functions/Methods**: `snake_case` (e.g., `run_pipeline()`, `check_result()`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `DATA_DIR`, `RANDOM_SEED`)
- **Private methods**: `_leading_underscore` (e.g., `_check_emails()`)

### Checker Pattern
Every checker class should follow this pattern:

```python
class MyChecker:
    """Description of what this checker validates."""

    def __init__(self, thresholds: dict):
        self.thresholds = thresholds.get("my_dimension", {})

    def run(self, df: pd.DataFrame) -> List[dict]:
        """Run checks and return list of standardized result dicts."""
        results = []
        # ... detection logic ...
        results.append(check_result(
            dimension="my_dimension",
            check_name="my_specific_check",
            passed=bool,
            score=float,      # 0.0–1.0
            threshold=float,   # expected threshold value
            details={          # check-specific metadata
                "column": "name",
                "metric": value,
            }
        ))
        return results
```

## Testing

### Running Tests
```bash
# All tests
pytest tests/ -v

# By module
pytest tests/test_validators.py -v
pytest tests/test_detectors.py -v
pytest tests/test_utils.py -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing

# Single test
pytest tests/test_validators.py::test_completeness_normal -v
```

### Writing Tests
```python
# tests/test_my_module.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import pandas as pd
import numpy as np
from my_checker import MyChecker

class TestMyChecker:
    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame({
            "col_a": [1, 2, 3, None, 5],
            "col_b": ["a", "b", "c", "d", "e"],
        })

    def test_normal_data(self, sample_df):
        checker = MyChecker({"my_dimension": {"threshold": 0.10}})
        results = checker.run(sample_df)
        assert len(results) > 0
        assert all("check" in r for r in results)
        assert all("score" in r for r in results)

    def test_empty_dataframe(self):
        checker = MyChecker({"my_dimension": {}})
        results = checker.run(pd.DataFrame())
        assert len(results) >= 0  # Should not crash
```

### Test Fixtures
Common fixtures are defined within each test file. Key patterns:
- **`sample_df`**: Small clean DataFrame (~100 rows) for basic testing
- **`dirty_df`**: DataFrame with injected issues for failure path testing
- **`normal_df`**: Clean numeric data for detector testing
- **`outlier_df`**: Data with known outliers for detector validation

## Extending DataGuard

### Adding a New Quality Checker

1. **Create the checker class** in `src/validators.py`:
   ```python
   class MyNewChecker:
       def __init__(self, thresholds):
           self.thresholds = thresholds.get("my_dimension", {})
       def run(self, df):
           results = []
           # ... implementation ...
           return results
   ```

2. **Register it in `QualityPipeline.run_all()`**:
   ```python
   # Inside run_all()
   print("  > Running my new checks...")
   my_checker = MyNewChecker(self.thresholds)
   for r in my_checker.run(df):
       report.add_check(r)
   ```

3. **Add thresholds** in `config/thresholds.yaml`:
   ```yaml
   my_dimension:
     my_threshold: 0.10
     another_param: 42
   ```

4. **Write tests** in `tests/test_validators.py`:
   ```python
   def test_my_new_checker_normal(self, sample_df):
       checker = MyNewChecker(THRESHOLDS)
       results = checker.run(sample_df)
       assert len(results) > 0
       assert results[0]["passed"]
   ```

5. **Rerun tests**: `pytest tests/ -v`

### Adding a New Anomaly Detector

Same pattern in `src/detectors.py`:
1. Create a detector class with a `run(df)` method
2. Add it to `AnomalyPipeline.run_all()`
3. Write tests in `tests/test_detectors.py`

### Adding a Dashboard Page

1. Create a `render_new_page(data, report)` function in `dashboard.py`
2. Add the page name to the sidebar radio options
3. Add the routing in the `main()` function

## Git Workflow

```bash
# Create a branch
git checkout -b feature/your-feature

# Make changes and commit
git add .
git commit -m "feat: add my new quality checker"

# Run tests before pushing
pytest tests/ -v

# Push and create PR
git push origin feature/your-feature
```

## Release Process

1. Update version in `dashboard.py` and `README.md`
2. Run full test suite: `pytest tests/ -v`
3. Build Docker image: `docker build -t dataguard:latest .`
4. Tag release: `git tag v1.0.0 && git push --tags`
