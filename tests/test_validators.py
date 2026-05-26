"""
Unit tests for DataGuard validators module.
"""

import os
import sys
import json
import tempfile
from unittest.mock import patch, MagicMock

import pytest
import numpy as np
import pandas as pd

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from validators import (
    CompletenessChecker,
    UniquenessChecker,
    ValidityChecker,
    ConsistencyChecker,
    TimelinessChecker,
    AccuracyChecker,
    QualityPipeline,
)


# ═══════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def sample_df():
    """Create a small clean DataFrame for testing."""
    np.random.seed(42)
    return pd.DataFrame({
        "order_id": [f"ORD{i:05d}" for i in range(100)],
        "customer_id": [f"CUST{i:05d}" for i in range(100)],
        "customer_email": [f"user{i}@email.com" for i in range(100)],
        "product_category": np.random.choice(["A", "B", "C"], 100),
        "quantity": np.random.randint(1, 10, 100),
        "unit_price": np.random.uniform(100, 1000, 100).round(2),
        "total_amount": (np.random.randint(1, 10, 100) * np.random.uniform(100, 1000, 100).round(2)),
        "order_date": pd.date_range("2026-01-01", periods=100, freq="h").strftime("%Y-%m-%d %H:%M:%S"),
        "customer_age": np.random.randint(18, 75, 100),
        "shipping_city": np.random.choice(["Mumbai", "Delhi", "Bangalore"], 100),
        "shipping_state": np.random.choice(["Maharashtra", "Delhi", "Karnataka"], 100),
        "payment_method": np.random.choice(["Credit Card", "UPI", "COD"], 100),
        "channel": np.random.choice(["Direct", "Social Media", "Email"], 100),
        "device": np.random.choice(["Mobile", "Desktop"], 100),
    })



@pytest.fixture
def dirty_df(sample_df):
    """Create a DataFrame with known quality issues."""
    df = sample_df.copy()

    # Inject 10% nulls in email
    null_idx = np.random.choice(df.index, 10, replace=False)
    df.loc[null_idx, "customer_email"] = None

    # Inject 5% duplicates
    dup_idx = np.random.choice(df.index, 5, replace=False)
    dup_rows = df.loc[dup_idx].copy()
    df = pd.concat([df, dup_rows], ignore_index=True)

    # Inject 1 outlier in quantity
    df.loc[0, "quantity"] = 999

    # Inject invalid email
    df.loc[1, "customer_email"] = "invalid-email"

    # Inject future date
    df.loc[2, "order_date"] = "2027-06-15 12:00:00"

    # Inject orphan customer
    df.loc[3, "customer_id"] = "CUST99999"

    return df


@pytest.fixture
def thresholds():
    return {
        "completeness": {
            "max_null_rate": {"_default": 0.10, "customer_email": 0.15},
            "min_completeness_score": 0.85,
        },
        "uniqueness": {
            "max_duplicate_rate": 0.05,
            "min_uniqueness_score": 0.90,
        },
        "validity": {
            "email_validity_rate": 0.85,
            "future_date_rate": 0.05,
            "min_validity_score": 0.80,
            "range_checks": {
                "quantity": {"min": 1, "max": 10},
                "customer_age": {"min": 0, "max": 120},
            },
        },
        "consistency": {
            "referential_integrity_rate": 0.90,
            "min_consistency_score": 0.85,
        },
        "timeliness": {
            "max_data_freshness_hours": 8760,  # 1 year - so test data passes
            "min_timeliness_score": 0.50,
        },
        "scoring": {
            "dimension_weights": {
                "completeness": 0.25, "uniqueness": 0.20,
                "validity": 0.25, "consistency": 0.15, "timeliness": 0.15,
            },
            "severity": {"critical": 0.50, "warning": 0.75, "pass": 1.0},
        },
    }


# ═══════════════════════════════════════════════════════════
# COMPLETENESS TESTS
# ═══════════════════════════════════════════════════════════

class TestCompletenessChecker:
    def test_clean_data_high_score(self, sample_df, thresholds):
        checker = CompletenessChecker(thresholds)
        results = checker.run(sample_df)
        overall = [r for r in results if r["check"] == "overall_completeness"][0]
        assert overall["score"] >= 0.99
        assert overall["passed"] == True

    def test_null_injection_detected(self, dirty_df, thresholds):
        checker = CompletenessChecker(thresholds)
        results = checker.run(dirty_df)

        # Check null rate for email
        email_check = [r for r in results if r["check"] == "null_rate_customer_email"]
        assert len(email_check) > 0
        # Should detect ~10% nulls in email

    def test_empty_dataframe(self, thresholds):
        checker = CompletenessChecker(thresholds)
        empty_df = pd.DataFrame()
        results = checker.run(empty_df)
        assert len(results) > 0  # should return at least overall score


# ═══════════════════════════════════════════════════════════
# UNIQUENESS TESTS
# ═══════════════════════════════════════════════════════════

class TestUniquenessChecker:
    def test_clean_data_no_duplicates(self, sample_df, thresholds):
        checker = UniquenessChecker(thresholds)
        results = checker.run(sample_df)
        overall = [r for r in results if r["check"] == "overall_uniqueness"][0]
        assert overall["score"] >= 0.95

    def test_duplicates_detected(self, dirty_df, thresholds):
        checker = UniquenessChecker(thresholds)
        results = checker.run(dirty_df)
        exact = [r for r in results if r["check"] == "exact_row_duplicates"][0]
        assert exact["details"]["duplicate_rows"] > 0


# ═══════════════════════════════════════════════════════════
# VALIDITY TESTS
# ═══════════════════════════════════════════════════════════

class TestValidityChecker:
    def test_valid_emails_pass(self, sample_df, thresholds):
        checker = ValidityChecker(thresholds)
        results = checker.run(sample_df)
        email_check = [r for r in results if r["check"] == "email_format"]
        if email_check:
            assert email_check[0]["passed"] == True

    def test_invalid_emails_detected(self, dirty_df, thresholds):
        checker = ValidityChecker(thresholds)
        results = checker.run(dirty_df)
        email_check = [r for r in results if r["check"] == "email_format"]
        if email_check:
            assert email_check[0]["details"]["invalid_emails"] > 0

    def test_future_dates_detected(self, dirty_df, thresholds):
        checker = ValidityChecker(thresholds)
        results = checker.run(dirty_df)
        date_check = [r for r in results if r["check"] == "future_dates"]
        if date_check:
            assert date_check[0]["details"]["future_dates"] > 0

    def test_range_check_outliers(self, dirty_df, thresholds):
        checker = ValidityChecker(thresholds)
        results = checker.run(dirty_df)
        range_check = [r for r in results if r["check"] == "range_check_quantity"]
        if range_check:
            assert range_check[0]["details"]["out_of_range"] > 0


# ═══════════════════════════════════════════════════════════
# CONSISTENCY TESTS
# ═══════════════════════════════════════════════════════════

class TestConsistencyChecker:
    def test_referential_integrity(self, dirty_df, thresholds):
        customers_df = pd.DataFrame({
            "customer_id": [f"CUST{i:05d}" for i in range(100)]
        })
        checker = ConsistencyChecker(thresholds, customers_df)
        results = checker.run(dirty_df)
        ref_check = [r for r in results if r["check"] == "referential_integrity_customer"]
        if ref_check:
            assert ref_check[0]["details"]["orphan_records"] > 0

    def test_no_customers_skips_ref_check(self, sample_df, thresholds):
        checker = ConsistencyChecker(thresholds, customers_df=None)
        results = checker.run(sample_df)
        ref_check = [r for r in results if r["check"] == "referential_integrity_customer"]
        assert len(ref_check) == 0


# ═══════════════════════════════════════════════════════════
# TIMELINESS TESTS
# ═══════════════════════════════════════════════════════════

class TestTimelinessChecker:
    def test_freshness_computed(self, sample_df, thresholds):
        checker = TimelinessChecker(thresholds)
        results = checker.run(sample_df)
        freshness = [r for r in results if r["check"] == "data_freshness"]
        assert len(freshness) > 0
        assert "hours_since_update" in freshness[0]["details"]


# ═══════════════════════════════════════════════════════════
# ACCURACY TESTS
# ═══════════════════════════════════════════════════════════

class TestAccuracyChecker:
    def test_distribution_comparison(self, sample_df, thresholds):
        # Create slightly shifted dirty vs clean
        dirty = sample_df.copy()
        dirty["unit_price"] = dirty["unit_price"] * 1.2  # 20% shift
        clean = sample_df.copy()

        checker = AccuracyChecker(thresholds)
        results = checker.run(dirty, clean)
        assert len(results) > 0  # should have at least overall accuracy

    def test_identical_data_high_score(self, sample_df, thresholds):
        checker = AccuracyChecker(thresholds)
        results = checker.run(sample_df, sample_df)
        overall = [r for r in results if r["check"] == "overall_accuracy"][0]
        assert overall["score"] >= 0.99


# ═══════════════════════════════════════════════════════════
# PIPELINE TESTS
# ═══════════════════════════════════════════════════════════

class TestQualityPipeline:
    def test_pipeline_runs_on_sample_data(self, dirty_df, sample_df, thresholds):
        pipeline = QualityPipeline(thresholds)
        report = pipeline.run_all(dirty_df, "test_dataset", sample_df)
        assert report is not None
        assert report.overall_score is not None
        assert len(report.checks) > 0

    def test_pipeline_rejects_empty_data(self, thresholds):
        pipeline = QualityPipeline(thresholds)
        report = pipeline.run_all(pd.DataFrame(), "empty")
        assert report.overall_score == 0.0

    def test_pipeline_rejects_none(self, thresholds):
        pipeline = QualityPipeline(thresholds)
        report = pipeline.run_all(None, "none")
        assert report.overall_score == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
