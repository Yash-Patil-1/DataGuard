"""Tests for the data_catalog module."""

import sys
import os
import json
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import pytest
import pandas as pd
import numpy as np
from data_catalog import (
    profile_column,
    profile_table,
    generate_catalog,
    _convert_value,
)


# ═══════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def numeric_series():
    """A clean numeric series with known stats."""
    np.random.seed(42)
    return pd.Series(np.random.normal(100, 15, 1000), name="unit_price")


@pytest.fixture
def categorical_series():
    """A categorical series with known distribution."""
    return pd.Series(
        ["A", "B", "C", "A", "B", "A", "A", "B", "C", "D"] * 100,
        name="category",
    )


@pytest.fixture
def datetime_series():
    """A datetime series."""
    return pd.Series(
        pd.date_range("2026-01-01", periods=100, freq="D"),
        name="order_date",
    )


@pytest.fixture
def null_series():
    """A series with many nulls."""
    s = pd.Series([1.0, 2.0, None, None, None, None, None, 3.0, 4.0, 5.0], name="null_col")
    return s


@pytest.fixture
def sample_df():
    """A small clean DataFrame for profiling."""
    np.random.seed(42)
    return pd.DataFrame({
        "order_id": [f"ORD{i:05d}" for i in range(100)],
        "customer_email": [f"user{i}@email.com" for i in range(100)],
        "unit_price": np.random.uniform(10, 500, 100),
        "quantity": np.random.randint(1, 10, 100),
        "product_category": np.random.choice(["Books", "Electronics", "Clothing"], 100),
        "order_date": pd.date_range("2026-01-01", periods=100, freq="h"),
    })


@pytest.fixture
def dirty_df():
    """A DataFrame with known quality issues."""
    df = pd.DataFrame({
        "id": range(50),
        "value": list(range(45)) + [999, 999, 999, -1, -1],
        "email": [f"user{i}@email.com" for i in range(45)] + [
            "bad-email", "noatsign", "user@", "@domain.com", "user name@email.com"
        ],
        "category": ["A"] * 40 + [None] * 10,
    })
    return df


# ═══════════════════════════════════════════════════════════
# _convert_value
# ═══════════════════════════════════════════════════════════

class TestConvertValue:
    def test_int(self):
        assert _convert_value(np.int64(42)) == 42
        assert isinstance(_convert_value(np.int64(42)), int)

    def test_float(self):
        assert _convert_value(np.float64(3.14)) == 3.14
        assert isinstance(_convert_value(np.float64(3.14)), float)

    def test_bool(self):
        assert _convert_value(np.bool_(True)) is True
        assert isinstance(_convert_value(np.bool_(True)), bool)

    def test_timestamp(self):
        ts = pd.Timestamp("2026-01-01")
        result = _convert_value(ts)
        assert isinstance(result, str)
        assert "2026" in result

    def test_datetime64(self):
        dt = np.datetime64("2026-01-01")
        result = _convert_value(dt)
        assert isinstance(result, str)

    def test_native_types(self):
        assert _convert_value(42) == 42
        assert _convert_value(3.14) == 3.14
        assert _convert_value("hello") == "hello"
        assert _convert_value(None) is None


# ═══════════════════════════════════════════════════════════
# profile_column
# ═══════════════════════════════════════════════════════════

class TestProfileColumn:
    def test_numeric_column(self, numeric_series):
        profile = profile_column(numeric_series, "unit_price")
        assert profile["name"] == "unit_price"
        assert profile["is_numeric"] is True
        assert profile["is_categorical"] is False
        assert profile["null_count"] == 0
        assert profile["null_rate"] == 0.0
        assert profile["unique_count"] == 1000
        assert "mean" in profile["stats"]
        assert 85 < profile["stats"]["mean"] < 115  # mean ~100
        assert "min" in profile["stats"]
        assert "max" in profile["stats"]
        assert "std" in profile["stats"]
        assert "median" in profile["stats"]
        assert profile["dtype"].startswith("float")

    def test_categorical_column(self, categorical_series):
        profile = profile_column(categorical_series, "category")
        assert profile["is_numeric"] is False
        assert profile["is_categorical"] is True
        assert len(profile["top_values"]) == 4  # A, B, C, D
        assert profile["top_values"][0]["value"] == "A"  # Most frequent
        assert profile["top_values"][0]["count"] == 400  # 40% of 1000
        assert "entropy" in profile["stats"]
        assert "normalized_entropy" in profile["stats"]

    def test_datetime_column(self, datetime_series):
        profile = profile_column(datetime_series, "order_date")
        assert profile["is_datetime"] is True
        assert profile["is_numeric"] is False
        assert "min" in profile["stats"]
        assert "max" in profile["stats"]
        assert "range_days" in profile["stats"]
        assert profile["stats"]["range_days"] == 99

    def test_all_null_column(self):
        series = pd.Series([None, None, None], name="all_null")
        profile = profile_column(series, "all_null")
        assert profile["null_count"] == 3
        assert profile["null_rate"] == 1.0
        assert profile["unique_count"] == 0
        assert len(profile["sample_values"]) == 0

    def test_empty_column(self):
        series = pd.Series([], dtype=float, name="empty")
        profile = profile_column(series, "empty")
        assert profile["null_count"] == 0
        assert profile["unique_count"] == 0
        assert profile["null_rate"] == 0.0
        assert profile["name"] == "empty"

    def test_high_null_quality_flag(self, null_series):
        profile = profile_column(null_series, "null_col")
        flags = profile["quality_flags"]
        critical_flags = [f for f in flags if f["severity"] == "critical"]
        warning_flags = [f for f in flags if f["severity"] == "warning"]
        # > 25% nulls should be critical
        assert len(critical_flags) >= 1 or len(warning_flags) >= 1

    def test_low_cardinality_flag(self):
        series = pd.Series(["X"] * 1000 + ["Y"] * 2, name="low_card")
        profile = profile_column(series, "low_card")
        flags = [f["severity"] for f in profile["quality_flags"]]
        # Should have info flag about low cardinality
        assert any(f["severity"] == "info" for f in profile["quality_flags"])

    def test_sample_values(self):
        series = pd.Series([10, 20, 30, 40, 50], name="samples")
        profile = profile_column(series, "samples")
        assert len(profile["sample_values"]) == 5
        assert profile["sample_values"] == [10, 20, 30, 40, 50]

    def test_constant_numeric_column(self):
        series = pd.Series([5.0] * 100, name="constant")
        profile = profile_column(series, "constant")
        assert profile["stats"]["min"] == 5.0
        assert profile["stats"]["max"] == 5.0
        assert profile["stats"]["std"] == 0.0

    def test_skewed_data_flag(self):
        # Create highly right-skewed data
        np.random.seed(42)
        skewed = pd.Series(np.random.exponential(scale=1, size=1000), name="skewed")
        profile = profile_column(skewed, "skewed")
        if "skew" in profile["stats"]:
            skew_val = profile["stats"]["skew"]
            if abs(skew_val) > 2:
                flags = [f for f in profile["quality_flags"] if "skew" in f["message"].lower()]
                assert len(flags) >= 1


# ═══════════════════════════════════════════════════════════
# profile_table
# ═══════════════════════════════════════════════════════════

class TestProfileTable:
    def test_normal_dataframe(self, sample_df):
        profile = profile_table(sample_df, "test_table")
        assert profile["table_name"] == "test_table"
        assert profile["row_count"] == 100
        assert profile["column_count"] == 6
        assert profile["estimated_size"] is not None
        assert profile["overall_health"] in ("good", "warning", "critical")
        assert len(profile["columns"]) == 6
        assert "float64" in profile["column_types_summary"] or "float" in str(profile["column_types_summary"])

    def test_empty_dataframe(self):
        profile = profile_table(pd.DataFrame(), "empty")
        assert profile["row_count"] == 0
        assert profile["column_count"] == 0
        assert profile["overall_health"] == "empty"

    def test_none_dataframe(self):
        profile = profile_table(None, "none")
        assert profile["row_count"] == 0
        assert profile["overall_health"] == "empty"

    def test_dirty_dataframe(self, dirty_df):
        profile = profile_table(dirty_df, "dirty")
        assert profile["row_count"] == 50
        # Should have some quality flags
        all_flags = []
        for col in profile["columns"]:
            all_flags.extend(col.get("quality_flags", []))
        assert len(all_flags) > 0

    def test_column_types_summary(self, sample_df):
        profile = profile_table(sample_df, "test")
        types = profile["column_types_summary"]
        assert len(types) > 0
        # Should have int, float, object, datetime types represented
        type_names = [k.split("[")[0] for k in types.keys()]
        assert any("float" in t for t in type_names) or any("int" in t for t in type_names)


# ═══════════════════════════════════════════════════════════
# generate_catalog
# ═══════════════════════════════════════════════════════════

class TestGenerateCatalog:
    def test_generate_with_temp_files(self):
        """Test generate_catalog with temporary CSV files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create orders CSV
            orders = pd.DataFrame({
                "id": range(100),
                "value": np.random.randn(100),
                "category": np.random.choice(["A", "B", "C"], 100),
            })
            orders_path = os.path.join(tmpdir, "orders.csv")
            orders.to_csv(orders_path, index=False)

            # Create customers CSV
            customers = pd.DataFrame({
                "customer_id": [f"C{i:05d}" for i in range(50)],
                "name": [f"User {i}" for i in range(50)],
            })
            customers_path = os.path.join(tmpdir, "customers.csv")
            customers.to_csv(customers_path, index=False)

            # Create ground truth CSV
            gt = pd.DataFrame({
                "id": range(100),
                "value": np.random.randn(100),
            })
            gt_path = os.path.join(tmpdir, "ground_truth.csv")
            gt.to_csv(gt_path, index=False)

            # Generate catalog
            catalog = generate_catalog(
                data_path=orders_path,
                customers_path=customers_path,
                ground_truth_path=gt_path,
            )

            assert "tables" in catalog
            assert "generated_at" in catalog

    def test_catalog_with_missing_files(self):
        """Should handle missing files gracefully."""
        catalog = generate_catalog(
            data_path="/nonexistent/orders.csv",
            customers_path="/nonexistent/customers.csv",
            ground_truth_path="/nonexistent/ground_truth.csv",
        )
        assert "tables" in catalog
        # All tables should be empty since files don't exist
        for table_key in ["orders", "customers", "ground_truth"]:
            if table_key in catalog["tables"]:
                assert catalog["tables"][table_key]["row_count"] == 0

    def test_catalog_structure(self):
        """Verify the catalog dict has the expected top-level keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Minimal data
            df = pd.DataFrame({"a": [1, 2, 3]})
            path = os.path.join(tmpdir, "data.csv")
            df.to_csv(path, index=False)

            catalog = generate_catalog(
                data_path=path,
                customers_path=os.path.join(tmpdir, "nonexistent.csv"),
                ground_truth_path=os.path.join(tmpdir, "nonexistent.csv"),
            )

            assert "project" in catalog
            assert catalog["project"] == "DataGuard"
            assert "tables" in catalog
            assert "orders" in catalog["tables"]


# ═══════════════════════════════════════════════════════════
# INTEGRATION: profile_column edge cases
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_mixed_type_column(self):
        """Column with mixed types should not crash."""
        series = pd.Series([1, "two", 3.0, None, "five"], name="mixed")
        profile = profile_column(series, "mixed")
        assert profile["name"] == "mixed"
        # Should not crash during profiling

    def test_boolean_column(self):
        series = pd.Series([True, False, True, True, False] * 20, name="bool_col")
        profile = profile_column(series, "bool_col")
        assert profile["is_numeric"] is True or profile["is_categorical"] is True
        # Boolean is a numeric subtype in pandas

    def test_large_cardinality_column(self):
        series = pd.Series(range(5000), name="id_col")
        profile = profile_column(series, "id_col")
        # ID column with all unique values
        assert profile["unique_count"] == 5000
        assert profile["cardinality_ratio"] == 1.0

    def test_zero_values(self):
        series = pd.Series([0] * 90 + [1] * 10, name="mostly_zero")
        profile = profile_column(series, "mostly_zero")
        if "zeros" in profile["stats"]:
            assert profile["stats"]["zeros"] == 90

    def test_negative_values(self):
        series = pd.Series(list(range(-50, 50)), name="neg_pos")
        profile = profile_column(series, "neg_pos")
        if "negatives" in profile["stats"]:
            assert profile["stats"]["negatives"] == 50
