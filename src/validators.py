"""
DataGuard — Data Quality Validators

Modular checkers for each quality dimension:
- Completeness: null rates, empty values
- Uniqueness: duplicate detection
- Validity: data types, formats, ranges
- Consistency: cross-column & cross-table integrity
- Timeliness: data freshness & recency
- Accuracy: statistical profile comparisons
"""

import os
import sys
import re
from datetime import datetime, timedelta
from typing import Optional, List

import yaml
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import check_result, QualityReport, save_report
import config


# ═══════════════════════════════════════════════════════════
# 1. COMPLETENESS CHECKER
# ═══════════════════════════════════════════════════════════

class CompletenessChecker:
    """Checks for missing values (nulls, NaNs, empty strings) in each column."""

    def __init__(self, thresholds: dict, dataset_name: str = "unknown"):
        self.thresholds = thresholds.get("completeness", {})
        self.dataset_name = dataset_name

    def run(self, df: pd.DataFrame) -> List[dict]:
        """Check null rates for all columns and return list of check results."""
        results = []
        max_null_rates = self.thresholds.get("max_null_rate", {})
        default_max = max_null_rates.get("_default", 0.10)
        min_score = self.thresholds.get("min_completeness_score", 0.85)

        col_results = {}
        for col in df.columns:
            # Count nulls + empty strings
            null_count = df[col].isnull().sum()
            if df[col].dtype == "object":
                empty_count = (df[col] == "").sum()
            else:
                empty_count = 0
            total_missing = null_count + empty_count
            null_rate = total_missing / len(df) if len(df) > 0 else 0

            # Threshold for this column
            threshold = max_null_rates.get(col, default_max)
            passed = null_rate <= threshold

            # Score: 1.0 if no nulls, 0.0 if at threshold, negative if over
            score = max(0, 1.0 - (null_rate / threshold)) if threshold > 0 else 1.0

            results.append(check_result(
                dimension="completeness",
                check_name=f"null_rate_{col}",
                passed=passed,
                score=score,
                threshold=threshold,
                details={
                    "column": col,
                    "total_rows": len(df),
                    "null_count": int(null_count),
                    "empty_string_count": int(empty_count),
                    "total_missing": int(total_missing),
                    "null_rate": round(null_rate, 4),
                }
            ))
            col_results[col] = null_rate

        # Overall completeness score
        avg_null_rate = np.mean(list(col_results.values())) if col_results else 0
        overall_score = max(0, 1.0 - avg_null_rate)
        results.append(check_result(
            dimension="completeness",
            check_name="overall_completeness",
            passed=overall_score >= min_score,
            score=overall_score,
            threshold=min_score,
            details={
                "columns_checked": len(col_results),
                "average_null_rate": round(float(avg_null_rate), 4),
            }
        ))
        return results


# ═══════════════════════════════════════════════════════════
# 2. UNIQUENESS CHECKER
# ═══════════════════════════════════════════════════════════

class UniquenessChecker:
    """Checks for duplicate rows and duplicate key columns."""

    def __init__(self, thresholds: dict, key_columns: Optional[List[str]] = None):
        self.thresholds = thresholds.get("uniqueness", {})
        self.key_columns = key_columns or ["order_id"]

    def run(self, df: pd.DataFrame) -> List[dict]:
        """Check duplicate rates."""
        results = []
        max_dup_rate = self.thresholds.get("max_duplicate_rate", 0.03)
        min_score = self.thresholds.get("min_uniqueness_score", 0.95)

        # ── Exact row duplicates ──
        exact_dups = df.duplicated(keep="first").sum()
        exact_rate = exact_dups / len(df) if len(df) > 0 else 0
        exact_passed = exact_rate <= max_dup_rate
        exact_score = max(0, 1.0 - (exact_rate / max_dup_rate)) if max_dup_rate > 0 else 1.0

        results.append(check_result(
            dimension="uniqueness",
            check_name="exact_row_duplicates",
            passed=exact_passed,
            score=exact_score,
            threshold=max_dup_rate,
            details={
                "total_rows": len(df),
                "duplicate_rows": int(exact_dups),
                "duplicate_rate": round(float(exact_rate), 4),
            }
        ))

        # ── Key column duplicates ──
        for key_col in self.key_columns:
            if key_col in df.columns:
                key_dups = df[key_col].duplicated(keep="first").sum()
                key_rate = key_dups / len(df) if len(df) > 0 else 0
                key_passed = key_rate <= max_dup_rate
                key_score = max(0, 1.0 - (key_rate / max_dup_rate)) if max_dup_rate > 0 else 1.0

                results.append(check_result(
                    dimension="uniqueness",
                    check_name=f"key_duplicates_{key_col}",
                    passed=key_passed,
                    score=key_score,
                    threshold=max_dup_rate,
                    details={
                        "key_column": key_col,
                        "total_rows": len(df),
                        "duplicate_keys": int(key_dups),
                        "duplicate_rate": round(float(key_rate), 4),
                    }
                ))

        # ── Overall uniqueness score (1 - avg duplicate rate) ──
        dup_rates = [r["details"]["duplicate_rate"] for r in results
                     if r["check"] != "overall_uniqueness"]
        avg_dup = np.mean(dup_rates) if dup_rates else 0
        overall_score = max(0.0, 1.0 - avg_dup * 2)  # scale so 5% dup = 0.9

        results.append(check_result(
            dimension="uniqueness",
            check_name="overall_uniqueness",
            passed=overall_score >= min_score,
            score=overall_score,
            threshold=min_score,
            details={
                "checks_performed": len([r for r in results if r["check"] != "overall_uniqueness"]),
                "average_duplicate_rate": round(float(avg_dup), 4),
            }
        ))
        return results


# ═══════════════════════════════════════════════════════════
# 3. VALIDITY CHECKER
# ═══════════════════════════════════════════════════════════

class ValidityChecker:
    """Checks data types, format validity (email, date), and range constraints."""

    EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

    def __init__(self, thresholds: dict):
        self.thresholds = thresholds.get("validity", {})

    def run(self, df: pd.DataFrame) -> List[dict]:
        """Run all validity checks."""
        results = []
        results.extend(self._check_emails(df))
        results.extend(self._check_dates(df))
        results.extend(self._check_ranges(df))
        results.append(self._overall_validity(results))
        return results

    def _check_emails(self, df: pd.DataFrame) -> List[dict]:
        """Validate email format."""
        results = []
        min_valid = self.thresholds.get("email_validity_rate", 0.90)

        if "customer_email" not in df.columns:
            return results

        emails = df["customer_email"].dropna()
        if len(emails) == 0:
            return results

        valid_emails = emails.apply(lambda x: bool(self.EMAIL_REGEX.match(str(x))))
        valid_count = valid_emails.sum()
        valid_rate = valid_count / len(emails)
        passed = valid_rate >= min_valid
        score = min(1.0, valid_rate / min_valid) if min_valid > 0 else 1.0

        results.append(check_result(
            dimension="validity",
            check_name="email_format",
            passed=passed,
            score=score,
            threshold=min_valid,
            details={
                "total_emails_checked": len(emails),
                "valid_emails": int(valid_count),
                "invalid_emails": int(len(emails) - valid_count),
                "validity_rate": round(float(valid_rate), 4),
                "sample_invalid": emails[~valid_emails].head(5).tolist() if not valid_emails.all() else [],
            }
        ))
        return results

    def _check_dates(self, df: pd.DataFrame) -> List[dict]:
        """Check for future dates and parseable date formats."""
        results = []
        max_future = self.thresholds.get("future_date_rate", 0.02)
        now = datetime.now()

        for col in ["order_date"]:
            if col not in df.columns:
                continue

            dates = pd.to_datetime(df[col], errors="coerce")
            parse_failures = dates.isnull().sum()
            future_dates = (dates > now).sum() if len(dates) > 0 else 0
            future_rate = future_dates / len(df) if len(df) > 0 else 0
            parse_rate = 1 - (parse_failures / len(df)) if len(df) > 0 else 1

            passed = future_rate <= max_future
            score = min(1.0, 1.0 - (future_rate / max_future)) if max_future > 0 else 1.0

            results.append(check_result(
                dimension="validity",
                check_name="future_dates",
                passed=passed,
                score=score,
                threshold=max_future,
                details={
                    "column": col,
                    "total_rows": len(df),
                    "future_dates": int(future_dates),
                    "future_date_rate": round(float(future_rate), 4),
                    "parse_failures": int(parse_failures),
                    "parse_success_rate": round(float(parse_rate), 4),
                }
            ))
        return results

    def _check_ranges(self, df: pd.DataFrame) -> List[dict]:
        """Check numeric columns against valid range constraints."""
        results = []
        range_checks = self.thresholds.get("range_checks", {})

        for field, bounds in range_checks.items():
            if field not in df.columns:
                continue

            col_min = bounds.get("min", float("-inf"))
            col_max = bounds.get("max", float("inf"))

            # Exclude nulls for range checks
            valid = df[field].dropna()
            if len(valid) == 0:
                continue

            out_of_range = ((valid < col_min) | (valid > col_max)).sum()
            oob_rate = out_of_range / len(valid)
            passed = oob_rate <= 0.02  # allow 2% out of range
            score = max(0, 1.0 - (oob_rate / 0.05))  # 5% OOB = score 0

            results.append(check_result(
                dimension="validity",
                check_name=f"range_check_{field}",
                passed=passed,
                score=score,
                threshold=0.02,
                details={
                    "column": field,
                    "expected_range": [col_min, col_max],
                    "values_checked": int(len(valid)),
                    "out_of_range": int(out_of_range),
                    "out_of_range_rate": round(float(oob_rate), 4),
                    "actual_min": round(float(valid.min()), 2),
                    "actual_max": round(float(valid.max()), 2),
                }
            ))
        return results

    def _overall_validity(self, all_results: List[dict]) -> dict:
        """Aggregate validity checks into an overall score."""
        scores = [r["score"] for r in all_results if "score" in r]
        avg_score = np.mean(scores) if scores else 1.0
        min_val = self.thresholds.get("min_validity_score", 0.85)
        return check_result(
            dimension="validity",
            check_name="overall_validity",
            passed=avg_score >= min_val,
            score=avg_score,
            threshold=min_val,
            details={"checks_aggregated": len(scores), "average_score": round(float(avg_score), 4)}
        )


# ═══════════════════════════════════════════════════════════
# 4. CONSISTENCY CHECKER
# ═══════════════════════════════════════════════════════════

class ConsistencyChecker:
    """Checks cross-column consistency and referential integrity."""

    def __init__(self, thresholds: dict, customers_df: Optional[pd.DataFrame] = None):
        self.thresholds = thresholds.get("consistency", {})
        self.customers_df = customers_df

    def run(self, df: pd.DataFrame) -> List[dict]:
        """Run all consistency checks."""
        results = []
        results.extend(self._check_referential_integrity(df))
        results.extend(self._check_cross_column(df))
        results.append(self._overall_consistency(results))
        return results

    def _check_referential_integrity(self, df: pd.DataFrame) -> List[dict]:
        """Check that customer_ids reference valid customers."""
        results = []
        min_rate = self.thresholds.get("referential_integrity_rate", 0.98)

        if self.customers_df is None or "customer_id" not in df.columns:
            return results

        valid_ids = set(self.customers_df["customer_id"])
        total_orders = len(df)
        orphan_count = (~df["customer_id"].isin(valid_ids)).sum()
        orphan_rate = orphan_count / total_orders if total_orders > 0 else 0
        valid_rate = 1 - orphan_rate
        passed = valid_rate >= min_rate
        score = min(1.0, valid_rate / min_rate) if min_rate > 0 else 1.0

        results.append(check_result(
            dimension="consistency",
            check_name="referential_integrity_customer",
            passed=passed,
            score=score,
            threshold=min_rate,
            details={
                "total_orders": total_orders,
                "valid_references": int(total_orders - orphan_count),
                "orphan_records": int(orphan_count),
                "orphan_rate": round(float(orphan_rate), 4),
                "valid_rate": round(float(valid_rate), 4),
            }
        ))
        return results

    def _check_cross_column(self, df: pd.DataFrame) -> List[dict]:
        """Check cross-column consistency (e.g., total_amount = quantity * unit_price)."""
        results = []

        # Check amount consistency
        if all(c in df.columns for c in ["quantity", "unit_price", "total_amount"]):
            valid = df[["quantity", "unit_price", "total_amount"]].dropna()
            if len(valid) > 0:
                expected = valid["quantity"] * valid["unit_price"]
                # Allow 0.5% rounding tolerance
                inconsistent = (abs(valid["total_amount"] - expected) / expected.abs().replace(0, 1) > 0.005).sum()
                inconsistency_rate = inconsistent / len(valid)
                passed = inconsistency_rate <= 0.02
                score = max(0, 1.0 - (inconsistency_rate / 0.05))

                results.append(check_result(
                    dimension="consistency",
                    check_name="amount_calculation",
                    passed=passed,
                    score=score,
                    threshold=0.02,
                    details={
                        "rows_checked": int(len(valid)),
                        "inconsistent_rows": int(inconsistent),
                        "inconsistency_rate": round(float(inconsistency_rate), 4),
                    }
                ))

        # Check city-state mapping consistency
        if all(c in df.columns for c in ["shipping_city", "shipping_state"]):
            known_cities = config.CITIES
            valid_loc = df[["shipping_city", "shipping_state"]].dropna()
            if len(valid_loc) > 0:
                mismatched = 0
                for _, row in valid_loc.iterrows():
                    expected_state = known_cities.get(row["shipping_city"])
                    if expected_state and row["shipping_state"] != expected_state:
                        mismatched += 1
                mismatch_rate = mismatched / len(valid_loc)
                passed = mismatch_rate <= 0.02
                score = max(0, 1.0 - (mismatch_rate / 0.05))

                results.append(check_result(
                    dimension="consistency",
                    check_name="city_state_mapping",
                    passed=passed,
                    score=score,
                    threshold=0.02,
                    details={
                        "rows_checked": int(len(valid_loc)),
                        "mismatched": int(mismatched),
                        "mismatch_rate": round(float(mismatch_rate), 4),
                    }
                ))

        return results

    def _overall_consistency(self, all_results: List[dict]) -> dict:
        scores = [r["score"] for r in all_results if "score" in r]
        avg_score = np.mean(scores) if scores else 1.0
        min_val = self.thresholds.get("min_consistency_score", 0.90)
        return check_result(
            dimension="consistency",
            check_name="overall_consistency",
            passed=avg_score >= min_val,
            score=avg_score,
            threshold=min_val,
            details={"checks_aggregated": len(scores), "average_score": round(float(avg_score), 4)}
        )


# ═══════════════════════════════════════════════════════════
# 5. TIMELINESS CHECKER
# ═══════════════════════════════════════════════════════════

class TimelinessChecker:
    """Checks data freshness and recency."""

    def __init__(self, thresholds: dict):
        self.thresholds = thresholds.get("timeliness", {})

    def run(self, df: pd.DataFrame) -> List[dict]:
        """Check timeliness metrics."""
        results = []
        max_hours = self.thresholds.get("max_data_freshness_hours", 48)
        min_score = self.thresholds.get("min_timeliness_score", 0.90)

        if "order_date" in df.columns:
            dates = pd.to_datetime(df["order_date"], errors="coerce")
            dates = dates.dropna()
            now = datetime.now()

            if len(dates) > 0:
                # Most recent order
                most_recent = dates.max()
                hours_old = (now - most_recent).total_seconds() / 3600
                freshness_score = max(0, min(1.0, 1.0 - (hours_old / max_hours)))
                passed = hours_old <= max_hours

                results.append(check_result(
                    dimension="timeliness",
                    check_name="data_freshness",
                    passed=passed,
                    score=freshness_score,
                    threshold=max_hours,
                    details={
                        "most_recent_record": most_recent.isoformat(),
                        "hours_since_update": round(float(hours_old), 2),
                        "max_allowed_hours": max_hours,
                    }
                ))

                # Check recency distribution
                # What % of records are from the last N days?
                cutoff = now - timedelta(days=30)
                recent_records = (dates >= cutoff).sum()
                recent_rate = recent_records / len(dates)

                results.append(check_result(
                    dimension="timeliness",
                    check_name="recent_data_ratio",
                    passed=recent_rate >= 0.50,
                    score=min(1.0, recent_rate / 0.50),
                    threshold=0.50,
                    details={
                        "total_dates": len(dates),
                        "records_last_30_days": int(recent_records),
                        "recent_ratio": round(float(recent_rate), 4),
                        "date_range": {
                            "min": dates.min().isoformat(),
                            "max": dates.max().isoformat(),
                        }
                    }
                ))

        # Overall timeliness
        scores = [r["score"] for r in results if "score" in r]
        avg_score = np.mean(scores) if scores else 1.0
        results.append(check_result(
            dimension="timeliness",
            check_name="overall_timeliness",
            passed=avg_score >= min_score,
            score=avg_score,
            threshold=min_score,
            details={"checks_aggregated": len(scores), "average_score": round(float(avg_score), 4)}
        ))
        return results


# ═══════════════════════════════════════════════════════════
# 6. ACCURACY CHECKER (Statistical Profile)
# ═══════════════════════════════════════════════════════════

class AccuracyChecker:
    """Compares data distributions against a reference (ground truth) dataset."""

    def __init__(self, thresholds: dict):
        self.thresholds = thresholds.get("validity", {})  # reuse validity section

    def run(self, dirty_df: pd.DataFrame, ground_truth_df: pd.DataFrame) -> List[dict]:
        """Compare dirty vs clean distributions."""
        results = []
        numeric_cols = dirty_df.select_dtypes(include=[np.number]).columns

        for col in numeric_cols:
            if col not in ground_truth_df.columns:
                continue

            dirty_vals = dirty_df[col].dropna()
            clean_vals = ground_truth_df[col]

            if len(dirty_vals) == 0 or len(clean_vals) == 0:
                continue

            # Compare basic statistics
            dirty_mean = dirty_vals.mean()
            clean_mean = clean_vals.mean()
            # Use epsilon to avoid division by zero when clean_mean == 0
            denom = abs(clean_mean) + 1e-10
            mean_shift = abs(dirty_mean - clean_mean) / denom

            # Score based on mean shift
            score = max(0, 1.0 - mean_shift * 5)  # 20% shift = score 0
            passed = mean_shift <= 0.10  # allow 10% mean shift

            results.append(check_result(
                dimension="accuracy",
                check_name=f"distribution_comparison_{col}",
                passed=passed,
                score=score,
                threshold=0.10,
                details={
                    "column": col,
                    "dirty_mean": round(float(dirty_mean), 2),
                    "clean_mean": round(float(clean_mean), 2),
                    "mean_shift_pct": round(float(mean_shift * 100), 2),
                    "dirty_std": round(float(dirty_vals.std()), 2),
                    "clean_std": round(float(clean_vals.std()), 2),
                    "dirty_count": int(len(dirty_vals)),
                    "clean_count": int(len(clean_vals)),
                }
            ))

        # Overall accuracy
        scores = [r["score"] for r in results if "score" in r]
        avg_score = np.mean(scores) if scores else 1.0
        results.append(check_result(
            dimension="accuracy",
            check_name="overall_accuracy",
            passed=avg_score >= 0.85,
            score=avg_score,
            threshold=0.85,
            details={"checks_aggregated": len(scores), "average_score": round(float(avg_score), 4)}
        ))
        return results


# ═══════════════════════════════════════════════════════════
# QUALITY PIPELINE (Orchestrator)
# ═══════════════════════════════════════════════════════════

class QualityPipeline:
    """Orchestrates all quality checkers and produces a consolidated report."""

    def __init__(self, thresholds: dict, customers_df: Optional[pd.DataFrame] = None):
        self.thresholds = thresholds
        self.customers_df = customers_df

    def run_all(self, df: pd.DataFrame, dataset_name: str = "unknown",
                ground_truth: Optional[pd.DataFrame] = None) -> QualityReport:
        """Run all checkers on a DataFrame and return a QualityReport."""
        # Guard against empty DataFrame
        if df is None or len(df) == 0:
            report = QualityReport(dataset_name, self.thresholds)
            report.add_check(check_result(
                dimension="pipeline",
                check_name="empty_dataset",
                passed=False,
                score=0.0,
                threshold=0.0,
                details={"error": "Input DataFrame is empty or None"}
            ))
            report.compute_scores()
            return report

        report = QualityReport(dataset_name, self.thresholds)

        # 1. Completeness
        print("  > Running completeness checks...")
        completeness = CompletenessChecker(self.thresholds, dataset_name)
        for r in completeness.run(df):
            report.add_check(r)

        # 2. Uniqueness
        print("  > Running uniqueness checks...")
        uniqueness = UniquenessChecker(self.thresholds)
        for r in uniqueness.run(df):
            report.add_check(r)

        # 3. Validity
        print("  > Running validity checks...")
        validity = ValidityChecker(self.thresholds)
        for r in validity.run(df):
            report.add_check(r)

        # 4. Consistency
        print("  > Running consistency checks...")
        consistency = ConsistencyChecker(self.thresholds, self.customers_df)
        for r in consistency.run(df):
            report.add_check(r)

        # 5. Timeliness
        print("  > Running timeliness checks...")
        timeliness = TimelinessChecker(self.thresholds)
        for r in timeliness.run(df):
            report.add_check(r)

        # 6. Accuracy (if ground truth provided)
        if ground_truth is not None:
            print("  > Running accuracy checks (comparing vs ground truth)...")
            accuracy = AccuracyChecker(self.thresholds)
            for r in accuracy.run(df, ground_truth):
                report.add_check(r)

        # Compute scores
        report.compute_scores()
        return report


# ═══════════════════════════════════════════════════════════
# COMMAND-LINE ENTRY POINT
# ═══════════════════════════════════════════════════════════

def run_pipeline(data_path: str = None, customers_path: str = None,
                 ground_truth_path: str = None, thresholds_path: str = None):
    """Run the full quality pipeline from the command line."""

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if data_path is None:
        data_path = os.path.join(base_dir, config.DATA_DIR, "all_orders_combined.csv")
    if customers_path is None:
        customers_path = os.path.join(base_dir, config.DATA_DIR, "customers.csv")
    if thresholds_path is None:
        thresholds_path = os.path.join(base_dir, "config", "thresholds.yaml")

    print("=" * 60)
    print("  DataGuard — Quality Check Engine")
    print("=" * 60)

    # Load thresholds
    print("\n[1/4] Loading thresholds...")
    if os.path.exists(thresholds_path):
        with open(thresholds_path, "r") as f:
            thresholds = yaml.safe_load(f)
        print(f"       > Loaded from {thresholds_path}")
    else:
        print(f"       > Using default thresholds (file not found: {thresholds_path})")
        thresholds = config.DEFAULT_THRESHOLDS

    # Load data
    print("\n[2/4] Loading data...")
    df = pd.read_csv(data_path)
    print(f"       > {len(df):,} rows, {len(df.columns)} columns")

    customers_df = None
    if os.path.exists(customers_path):
        customers_df = pd.read_csv(customers_path)
        print(f"       > Customers table: {len(customers_df):,} rows")

    ground_truth = None
    if ground_truth_path and os.path.exists(ground_truth_path):
        ground_truth = pd.read_csv(ground_truth_path)
        print(f"       > Ground truth: {len(ground_truth):,} rows")

    # Run pipeline
    print("\n[3/4] Running quality checks...")
    pipeline = QualityPipeline(thresholds, customers_df)
    dataset_name = os.path.splitext(os.path.basename(data_path))[0]
    report = pipeline.run_all(df, dataset_name, ground_truth)

    # Output
    print("\n[4/4] Results:")
    print(report.summary_table())

    # Save report
    report_dir = os.path.join(base_dir, config.REPORT_DIR)
    paths = save_report(report, report_dir)

    return report, paths


if __name__ == "__main__":
    report, paths = run_pipeline()
