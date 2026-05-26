"""
DataGuard — Data Catalog Generator

Auto-profiles datasets to produce a rich catalog describing:
- Table-level summary (row count, columns, size estimates)
- Per-column profiles (type, stats, nulls, uniques, cardinality, distributions)
- Quality flags (high null rate, low cardinality, suspicious values)
- Multi-table comparison (dirty vs clean)

Output is a structured dict suitable for the dashboard.
"""

import os
import sys
from datetime import datetime
from typing import Optional, Dict, List, Any
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


# ═══════════════════════════════════════════════════════════
# COLUMN PROFILER
# ═══════════════════════════════════════════════════════════

def profile_column(series: pd.Series, column_name: str) -> dict:
    """
    Profile a single column and return structured metadata.

    Returns:
        dict with keys: name, dtype, is_numeric, is_categorical, is_datetime,
        null_count, null_rate, unique_count, cardinality_ratio,
        sample_values, stats (numeric), top_values (categorical),
        quality_flags
    """
    total = len(series)
    null_count = int(series.isnull().sum())
    null_rate = round(null_count / total, 4) if total > 0 else 0.0
    non_null = series.dropna()
    unique_count = int(non_null.nunique()) if len(non_null) > 0 else 0
    cardinality_ratio = round(unique_count / total, 4) if total > 0 else 0.0
    dtype = str(series.dtype)

    is_numeric = pd.api.types.is_numeric_dtype(series)
    is_datetime = pd.api.types.is_datetime64_any_dtype(series)
    is_categorical = not is_numeric and not is_datetime

    # Sample values (first 5 non-null)
    sample_values = non_null.head(5).tolist() if len(non_null) > 0 else []
    # Convert numpy types to native Python for JSON serialization
    sample_values = [_convert_value(v) for v in sample_values]

    profile = {
        "name": column_name,
        "dtype": dtype,
        "is_numeric": is_numeric,
        "is_categorical": is_categorical,
        "is_datetime": is_datetime,
        "null_count": null_count,
        "null_rate": null_rate,
        "unique_count": unique_count,
        "cardinality_ratio": cardinality_ratio,
        "sample_values": sample_values,
        "stats": {},
        "top_values": [],
        "quality_flags": [],
    }

    # Numeric stats
    if is_numeric and len(non_null) > 0:
        vals = non_null.astype(float)
        profile["stats"] = {
            "min": _convert_value(vals.min()),
            "max": _convert_value(vals.max()),
            "mean": _convert_value(vals.mean()),
            "std": _convert_value(vals.std()),
            "median": _convert_value(vals.median()),
            "p25": _convert_value(vals.quantile(0.25)),
            "p75": _convert_value(vals.quantile(0.75)),
            "iqr": _convert_value(vals.quantile(0.75) - vals.quantile(0.25)),
            "skew": _convert_value(vals.skew()) if len(vals) > 3 else 0,
            "kurtosis": _convert_value(vals.kurtosis()) if len(vals) > 3 else 0,
            "zeros": int((vals == 0).sum()),
            "negatives": int((vals < 0).sum()),
        }
        # Flag extreme skew
        if abs(profile["stats"]["skew"]) > 2:
            profile["quality_flags"].append({
                "severity": "warning",
                "message": f"Highly skewed distribution (skew={profile['stats']['skew']:.2f})",
            })
        # Flag zeros
        zero_pct = profile["stats"]["zeros"] / len(non_null) * 100
        if zero_pct > 50 and unique_count > 2:
            profile["quality_flags"].append({
                "severity": "info",
                "message": f"{zero_pct:.0f}% of values are zero",
            })

    # Categorical stats
    if is_categorical and len(non_null) > 0:
        value_counts = non_null.value_counts()
        top_values = value_counts.head(10)
        total_top = top_values.sum()
        profile["top_values"] = [
            {
                "value": _convert_value(idx),
                "count": int(cnt),
                "percentage": round(float(cnt / len(non_null) * 100), 2),
            }
            for idx, cnt in top_values.items()
        ]
        # Compute entropy for categorical columns
        probs = value_counts / len(non_null)
        entropy = -sum(p * np.log(p + 1e-10) for p in probs)
        max_entropy = np.log(len(value_counts)) if len(value_counts) > 1 else 1
        profile["stats"]["entropy"] = round(float(entropy), 4)
        profile["stats"]["normalized_entropy"] = round(float(entropy / max_entropy), 4) if max_entropy > 0 else 1.0
        profile["stats"]["top_value_share"] = round(float(top_values.iloc[0] / len(non_null) * 100), 2) if len(top_values) > 0 else 0

    # Datetime stats
    if is_datetime and len(non_null) > 0:
        profile["stats"] = {
            "min": str(non_null.min()),
            "max": str(non_null.max()),
            "range_days": (non_null.max() - non_null.min()).days,
            "most_recent": str(non_null.max()),
            "oldest": str(non_null.min()),
        }

    # Quality flags
    if null_rate > 0.10:
        profile["quality_flags"].append({
            "severity": "critical" if null_rate > 0.25 else "warning",
            "message": f"{null_rate:.1%} missing values",
        })
    if cardinality_ratio < 0.01 and is_categorical and unique_count < 5:
        profile["quality_flags"].append({
            "severity": "info",
            "message": f"Low cardinality ({unique_count} unique values across {total} rows)",
        })
    if cardinality_ratio > 0.95 and is_categorical and unique_count > 100:
        profile["quality_flags"].append({
            "severity": "info",
            "message": f"High cardinality — {unique_count} unique values (likely an ID column)",
        })
    if is_numeric and profile["stats"].get("negatives", 0) > 0 and profile["stats"]["negatives"] / len(non_null) > 0.5:
        profile["quality_flags"].append({
            "severity": "info",
            "message": f"Most values are negative ({profile['stats']['negatives']}/{len(non_null)})",
        })

    return profile


def _convert_value(v):
    """Convert numpy/pandas types to native Python types for JSON serialization."""
    if isinstance(v, (np.integer,)):
        return int(v)
    elif isinstance(v, (np.floating,)):
        return float(v)
    elif isinstance(v, (np.bool_,)):
        return bool(v)
    elif isinstance(v, pd.Timestamp):
        return str(v)
    elif isinstance(v, (pd.Period, pd.Timedelta)):
        return str(v)
    elif isinstance(v, (np.datetime64,)):
        return str(v)
    return v


# ═══════════════════════════════════════════════════════════
# TABLE PROFILER
# ═══════════════════════════════════════════════════════════

def profile_table(df: pd.DataFrame, table_name: str = "unknown") -> dict:
    """
    Profile an entire DataFrame and return a structured catalog entry.

    Returns:
        dict with keys: table_name, row_count, column_count, estimated_size,
        created_at, columns (list of column profiles), column_types_summary,
        overall_health
    """
    if df is None or len(df) == 0:
        return {
            "table_name": table_name,
            "row_count": 0,
            "column_count": 0,
            "estimated_size": "0 B",
            "created_at": datetime.now().isoformat(),
            "columns": [],
            "column_types_summary": {},
            "overall_health": "empty",
        }

    columns = [profile_column(df[col], col) for col in df.columns]

    # Column type summary
    type_summary = Counter(p["dtype"].split("[")[0].split("(")[0] for p in columns)  # e.g. "int64", "object"
    type_summary = {k: v for k, v in sorted(type_summary.items())}

    # Quality health
    critical_flags = sum(1 for c in columns for f in c.get("quality_flags", []) if f["severity"] == "critical")
    warning_flags = sum(1 for c in columns for f in c.get("quality_flags", []) if f["severity"] == "warning")

    if critical_flags > 0:
        overall_health = "critical"
    elif warning_flags > 3:
        overall_health = "warning"
    else:
        overall_health = "good"

    # Estimate size
    size_bytes = df.memory_usage(deep=True).sum()
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024**2:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / 1024**2:.1f} MB"

    return {
        "table_name": table_name,
        "row_count": len(df),
        "column_count": len(df.columns),
        "estimated_size": size_str,
        "created_at": datetime.now().isoformat(),
        "columns": columns,
        "column_types_summary": type_summary,
        "overall_health": overall_health,
        "critical_flags": critical_flags,
        "warning_flags": warning_flags,
    }


# ═══════════════════════════════════════════════════════════
# FULL CATALOG GENERATOR
# ═══════════════════════════════════════════════════════════

def generate_catalog(data_path: str = None, customers_path: str = None,
                     ground_truth_path: str = None) -> dict:
    """
    Load all datasets and generate a complete data catalog.

    Args:
        data_path: Path to dirty orders CSV
        customers_path: Path to customers CSV
        ground_truth_path: Path to clean ground truth CSV

    Returns:
        dict with catalog entries for each table
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if data_path is None:
        data_path = os.path.join(base_dir, config.DATA_DIR, "all_orders_combined.csv")
    if customers_path is None:
        customers_path = os.path.join(base_dir, config.DATA_DIR, "customers.csv")
    if ground_truth_path is None:
        ground_truth_path = os.path.join(base_dir, config.DATA_DIR, "ground_truth_orders.csv")

    catalog = {
        "generated_at": datetime.now().isoformat(),
        "project": config.PROJECT_NAME,
        "tables": {},
    }

    # Profile dirty orders
    if os.path.exists(data_path):
        df = pd.read_csv(data_path)
        catalog["tables"]["orders"] = profile_table(df, "orders (dirty)")

    # Profile customers
    if os.path.exists(customers_path):
        cdf = pd.read_csv(customers_path)
        catalog["tables"]["customers"] = profile_table(cdf, "customers")

    # Profile ground truth
    if os.path.exists(ground_truth_path):
        gdf = pd.read_csv(ground_truth_path)
        catalog["tables"]["ground_truth"] = profile_table(gdf, "ground_truth (clean)")

    # Cross-table comparison (if both dirty and clean available)
    if "orders" in catalog["tables"] and "ground_truth" in catalog["tables"]:
        orders_cols = {c["name"] for c in catalog["tables"]["orders"]["columns"]}
        gt_cols = {c["name"] for c in catalog["tables"]["ground_truth"]["columns"]}

        catalog["cross_table"] = {
            "shared_columns": sorted(orders_cols & gt_cols),
            "orders_only": sorted(orders_cols - gt_cols),
            "ground_truth_only": sorted(gt_cols - orders_cols),
            "row_count_diff": catalog["tables"]["orders"]["row_count"] - catalog["tables"]["ground_truth"]["row_count"],
            "row_count_diff_pct": round(
                (catalog["tables"]["orders"]["row_count"] - catalog["tables"]["ground_truth"]["row_count"])
                / catalog["tables"]["ground_truth"]["row_count"] * 100, 2
            ) if catalog["tables"]["ground_truth"]["row_count"] > 0 else 0,
        }

    return catalog


# ═══════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════

def main():
    """Print catalog summary to console."""
    print("=" * 60)
    print("  DataGuard — Data Catalog")
    print("=" * 60)

    catalog = generate_catalog()

    for table_name, table_profile in catalog.get("tables", {}).items():
        print(f"\n  📋 {table_profile['table_name']}")
        print(f"     Rows: {table_profile['row_count']:,}  |  "
              f"Columns: {table_profile['column_count']}  |  "
              f"Size: {table_profile['estimated_size']}  |  "
              f"Health: {table_profile['overall_health']}")
        print(f"     Types: {table_profile['column_types_summary']}")

        # Show columns with quality flags
        for col in table_profile.get("columns", []):
            flags = col.get("quality_flags", [])
            flag_str = ""
            for f in flags:
                icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(f["severity"], "⚪")
                flag_str += f" {icon} {f['message']}"
            null_str = f"null={col['null_rate']:.1%}" if col["null_rate"] > 0 else ""
            print(f"       {col['name']:25s} | {col['dtype']:12s} | "
                  f"uniques={col['unique_count']:>6,} | {null_str}{flag_str}")

    if catalog.get("cross_table"):
        ct = catalog["cross_table"]
        print(f"\n  🔄 Cross-Table Comparison")
        print(f"     Shared columns: {len(ct['shared_columns'])}")
        print(f"     Row count diff: {ct['row_count_diff']:+d} ({ct['row_count_diff_pct']:+.1f}%)")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
