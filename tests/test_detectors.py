"""
Unit tests for DataGuard anomaly detectors module.
"""

import os
import sys
import tempfile

import pytest
import numpy as np
import pandas as pd

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from detectors import (
    IQROutlierDetector,
    ZScoreDetector,
    IsolationForestDetector,
    AnomalyPipeline,
)


# ═══════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def normal_df():
    """Create a DataFrame with mostly normal data."""
    np.random.seed(42)
    n = 200
    return pd.DataFrame({
        "value_a": np.random.normal(100, 15, n),
        "value_b": np.random.normal(50, 10, n),
        "quantity": np.random.randint(1, 10, n),
        "price": np.random.uniform(100, 500, n).round(2),
        "category": np.random.choice(["X", "Y", "Z"], n),
    })


@pytest.fixture
def outlier_df(normal_df):
    """Create a DataFrame with known outliers."""
    df = normal_df.copy()
    # Inject extreme outliers
    df.loc[0, "value_a"] = 9999
    df.loc[1, "value_b"] = -9999
    df.loc[2, "quantity"] = 999
    df.loc[3, "price"] = 999999
    # Inject a few moderate outliers
    df.loc[4, "value_a"] = 200
    df.loc[5, "value_b"] = 120
    return df


# ═══════════════════════════════════════════════════════════
# IQR DETECTOR TESTS
# ═══════════════════════════════════════════════════════════

class TestIQROutlierDetector:
    def test_detects_outliers(self, outlier_df):
        detector = IQROutlierDetector(iqr_multiplier=1.5)
        results = detector.run(outlier_df)

        # Should have results for numeric columns
        assert len(results) > 0

        # The quantity column should have out-of-range values
        qty_results = [r for r in results if r["details"]["column"] == "quantity"]
        if qty_results:
            assert qty_results[0]["details"]["outlier_count"] > 0

    def test_normal_data_few_outliers(self, normal_df):
        detector = IQROutlierDetector(iqr_multiplier=3.0)  # wider bounds
        results = detector.run(normal_df)

        # Normal data should have few detected outliers
        total_outliers = sum(r["details"]["outlier_count"] for r in results)
        assert total_outliers <= 5  # at most a few natural outliers

    def test_skips_non_numeric(self):
        df = pd.DataFrame({"text": ["a", "b", "c"]})
        detector = IQROutlierDetector()
        results = detector.run(df)
        assert len(results) == 0  # no numeric columns


# ═══════════════════════════════════════════════════════════
# Z-SCORE DETECTOR TESTS
# ═══════════════════════════════════════════════════════════

class TestZScoreDetector:
    def test_standard_zscore(self, outlier_df):
        detector = ZScoreDetector(z_threshold=3.0, use_modified=False)
        results = detector.run(outlier_df)

        # Should detect the extreme outliers
        value_a_results = [r for r in results if "value_a" in r["check"]]
        if value_a_results:
            assert value_a_results[0]["details"]["outlier_count"] > 0

    def test_modified_zscore(self, outlier_df):
        detector = ZScoreDetector(z_threshold=3.0, use_modified=True)
        results = detector.run(outlier_df)
        assert len(results) > 0

    def test_normal_data(self, normal_df):
        detector = ZScoreDetector(z_threshold=3.0)
        results = detector.run(normal_df)

        # Normal data with z=3 should have very few outliers
        # (less than 1% naturally in a normal distribution)
        total_outliers = sum(r["details"]["outlier_count"] for r in results)
        assert total_outliers < len(normal_df) * 0.02


# ═══════════════════════════════════════════════════════════
# ISOLATION FOREST TESTS
# ═══════════════════════════════════════════════════════════

class TestIsolationForestDetector:
    def test_detects_anomalies(self, outlier_df):
        detector = IsolationForestDetector(contamination=0.05)
        results = detector.run(outlier_df)
        iforest = [r for r in results if r["check"] == "isolation_forest"]
        if iforest:
            assert iforest[0]["details"]["anomalies_detected"] > 0

    def test_requires_multiple_features(self):
        detector = IsolationForestDetector()
        df = pd.DataFrame({"only_one": [1, 2, 3, 4, 5]})
        results = detector.run(df)
        assert len(results) > 0

    def test_handles_nulls(self, outlier_df):
        # Add some nulls
        df = outlier_df.copy()
        df.loc[10:20, "value_a"] = None
        detector = IsolationForestDetector()
        results = detector.run(df)
        # Should not crash
        assert len(results) > 0


# ═══════════════════════════════════════════════════════════
# PIPELINE TESTS
# ═══════════════════════════════════════════════════════════

class TestAnomalyPipeline:
    def test_pipeline_runs(self, outlier_df):
        pipeline = AnomalyPipeline()
        report = pipeline.run_all(outlier_df, "test")
        assert report is not None
        assert len(report.checks) > 0

    def test_pipeline_handles_empty(self):
        pipeline = AnomalyPipeline()
        report = pipeline.run_all(pd.DataFrame(), "empty")
        assert report.overall_score == 0.0

    def test_pipeline_handles_none(self):
        pipeline = AnomalyPipeline()
        report = pipeline.run_all(None, "none")
        assert report.overall_score == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
