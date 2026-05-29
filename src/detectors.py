"""
DataGuard — Anomaly Detection Module

Statistical and ML-based anomaly detection methods:
- IQR-based outlier detection
- Z-score / Modified Z-score
- Moving average drift detection (time-series)
- Isolation Forest (multivariate unsupervised)

All detectors return standardized results compatible with the
QualityReport system from validators.py.
"""

import os
import sys
from typing import Optional, List

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import check_result, QualityReport, save_report
from sklearn.ensemble import IsolationForest
import config


# ═══════════════════════════════════════════════════════════
# 1. IQR OUTLIER DETECTOR
# ═══════════════════════════════════════════════════════════

class IQROutlierDetector:
    """Detect outliers using the Interquartile Range (1.5*IQR rule)."""

    def __init__(self, iqr_multiplier: float = 1.5):
        self.iqr_multiplier = iqr_multiplier

    def run(self, df: pd.DataFrame) -> List[dict]:
        """Detect outliers in numeric columns using IQR."""
        results = []
        numeric_cols = df.select_dtypes(include=[np.number]).columns

        for col in numeric_cols:
            vals = df[col].dropna()
            if len(vals) < 4:  # need at least 4 values for meaningful IQR
                continue

            q1 = vals.quantile(0.25)
            q3 = vals.quantile(0.75)
            iqr = q3 - q1

            if iqr == 0:
                continue  # no spread, skip

            lower_bound = q1 - self.iqr_multiplier * iqr
            upper_bound = q3 + self.iqr_multiplier * iqr

            outliers = (vals < lower_bound) | (vals > upper_bound)
            n_outliers = int(outliers.sum())
            outlier_rate = n_outliers / len(vals)

            # Score: 0 outliers = 1.0, >5% outliers = 0.0
            score = max(0, 1.0 - (outlier_rate / 0.05))
            passed = outlier_rate <= 0.02  # allow 2% natural outliers

            results.append(check_result(
                dimension="anomaly_iqr",
                check_name=f"iqr_outliers_{col}",
                passed=passed,
                score=score,
                threshold=0.02,
                details={
                    "column": col,
                    "iqr_multiplier": self.iqr_multiplier,
                    "q1": round(float(q1), 4),
                    "q3": round(float(q3), 4),
                    "iqr": round(float(iqr), 4),
                    "lower_bound": round(float(lower_bound), 4),
                    "upper_bound": round(float(upper_bound), 4),
                    "values_checked": int(len(vals)),
                    "outlier_count": n_outliers,
                    "outlier_rate": round(float(outlier_rate), 4),
                    "sample_outliers": vals[outliers].head(10).tolist() if n_outliers > 0 else [],
                }
            ))

        return results


# ═══════════════════════════════════════════════════════════
# 2. Z-SCORE DETECTOR
# ═══════════════════════════════════════════════════════════

class ZScoreDetector:
    """Detect outliers using Z-score (standard deviation) and Modified Z-score (MAD)."""

    def __init__(self, z_threshold: float = 3.0, use_modified: bool = False):
        self.z_threshold = z_threshold
        self.use_modified = use_modified  # True = use modified Z-score (MAD-based)

    def run(self, df: pd.DataFrame) -> List[dict]:
        """Detect outliers using Z-score or Modified Z-score."""
        results = []
        numeric_cols = df.select_dtypes(include=[np.number]).columns

        for col in numeric_cols:
            vals = df[col].dropna()
            if len(vals) < 4:
                continue

            if self.use_modified:
                # Modified Z-score using MAD (more robust)
                median = vals.median()
                mad = np.median(np.abs(vals - median))
                if mad == 0:
                    continue
                z_scores = 0.6745 * (vals - median) / mad
                method_name = "modified_zscore"
                method_label = "Modified Z-score (MAD)"
            else:
                # Standard Z-score
                mean = vals.mean()
                std = vals.std()
                if std == 0:
                    continue
                z_scores = (vals - mean) / std
                method_name = "zscore"
                method_label = "Standard Z-score"

            outliers = np.abs(z_scores) > self.z_threshold
            n_outliers = int(outliers.sum())
            outlier_rate = n_outliers / len(vals)
            max_abs_z = float(np.abs(z_scores).max())

            score = max(0, 1.0 - (outlier_rate / 0.05))
            passed = outlier_rate <= 0.02

            results.append(check_result(
                dimension="anomaly_zscore",
                check_name=f"{method_name}_{col}",
                passed=passed,
                score=score,
                threshold=0.02,
                details={
                    "column": col,
                    "method": method_label,
                    "threshold": self.z_threshold,
                    "values_checked": int(len(vals)),
                    "outlier_count": n_outliers,
                    "outlier_rate": round(float(outlier_rate), 4),
                    "max_abs_z_score": round(max_abs_z, 4),
                    "sample_outliers": vals[outliers].head(10).tolist() if n_outliers > 0 else [],
                }
            ))

        return results


# ═══════════════════════════════════════════════════════════
# 3. TIME-SERIES DRIFT DETECTOR
# ═══════════════════════════════════════════════════════════

class DriftDetector:
    """
    Detect distribution drift over time by analyzing daily snapshots.
    
    Tracks key quality metrics (null rates, outlier rates, category mix)
    across consecutive days and flags significant deviations from the
    rolling average (moving window).
    """

    def __init__(self, window_size: int = 5, drift_threshold: float = 2.0):
        self.window_size = window_size
        self.drift_threshold = drift_threshold  # standard deviations from rolling mean

    def run(self, daily_dir: str) -> List[dict]:
        """
        Analyze daily CSV snapshots to detect drift in quality metrics.
        
        Args:
            daily_dir: Directory containing daily_orders_XX.csv files
            
        Returns:
            List of check results
        """
        results = []

        # Load daily files in order
        daily_files = sorted([
            os.path.join(daily_dir, f)
            for f in os.listdir(daily_dir)
            if f.startswith("daily_orders_") and f.endswith(".csv")
        ])

        if len(daily_files) < self.window_size + 1:
            return results  # not enough data for drift detection

        print(f"  > Loading {len(daily_files)} daily snapshots for drift analysis...")

        # Compute per-day quality metrics
        daily_metrics = []
        for filepath in daily_files:
            df = pd.read_csv(filepath)
            metrics = self._compute_daily_metrics(df)
            metrics["day"] = len(daily_metrics) + 1
            daily_metrics.append(metrics)

        metrics_df = pd.DataFrame(daily_metrics)

        # Check each metric for drift
        metric_cols = [c for c in metrics_df.columns if c != "day"]

        for metric in metric_cols:
            values = metrics_df[metric].values
            if len(values) < self.window_size + 1:
                continue

            drift_alerts = []
            for i in range(self.window_size, len(values)):
                window = values[i - self.window_size:i]
                rolling_mean = np.mean(window)
                rolling_std = max(np.std(window), 1e-10)
                z = (values[i] - rolling_mean) / rolling_std

                if abs(z) > self.drift_threshold:
                    drift_alerts.append({
                        "day": int(metrics_df.iloc[i]["day"]),
                        "value": round(float(values[i]), 4),
                        "rolling_mean": round(float(rolling_mean), 4),
                        "z_score": round(float(z), 4),
                    })

            n_drifts = len(drift_alerts)
            drift_rate = n_drifts / (len(values) - self.window_size)

            # Score: fewer drifts = better
            score = max(0, 1.0 - drift_rate * 10)  # 10% drift rate = 0.0
            passed = drift_rate <= 0.05  # allow 5% drift events

            results.append(check_result(
                dimension="anomaly_drift",
                check_name=f"drift_{metric}",
                passed=passed,
                score=score,
                threshold=0.05,
                details={
                    "metric": metric,
                    "window_size": self.window_size,
                    "drift_threshold_sigma": self.drift_threshold,
                    "days_analyzed": len(values),
                    "drift_events": n_drifts,
                    "drift_rate": round(float(drift_rate), 4),
                    "alerts": drift_alerts[:20],  # limit to 20 alerts
                    "metric_timeline": [
                        {"day": int(metrics_df.iloc[i]["day"]),
                         "value": round(float(values[i]), 4)}
                        for i in range(0, len(values), max(1, len(values) // 10))
                    ],
                }
            ))

        return results

    def _compute_daily_metrics(self, df: pd.DataFrame) -> dict:
        """Compute quality metrics for a single day's data."""
        metrics = {}

        # Null rates
        for col in ["customer_email", "unit_price", "customer_age"]:
            if col in df.columns:
                metrics[f"null_rate_{col}"] = df[col].isnull().mean()

        # Outlier counts
        if "quantity" in df.columns:
            metrics["outlier_quantity_999"] = (df["quantity"] == 999).mean()
        if "unit_price" in df.columns:
            metrics["outlier_unit_price_999999"] = (df["unit_price"] == 999999).mean()

        # Category distribution (entropy as a measure of diversity)
        if "product_category" in df.columns:
            cat_dist = df["product_category"].value_counts(normalize=True)
            # Shannon entropy: higher = more diverse
            entropy = -sum(p * np.log(p + 1e-10) for p in cat_dist)
            metrics["category_entropy"] = entropy

        # Order count
        metrics["order_count"] = len(df)

        # Average order value
        if "total_amount" in df.columns:
            metrics["avg_order_value"] = df["total_amount"].mean()

        return metrics


# ═══════════════════════════════════════════════════════════
# 4. ISOLATION FOREST DETECTOR
# ═══════════════════════════════════════════════════════════

class IsolationForestDetector:
    """
    Unsupervised anomaly detection using Isolation Forest.
    
    Works well for multivariate anomaly detection - finds rows where
    the combination of values is unusual, even if individual values
    look normal.
    """

    def __init__(self, contamination: float = 0.05, n_estimators: int = 100):
        self.contamination = contamination  # expected % of anomalies
        self.n_estimators = n_estimators

    def run(self, df: pd.DataFrame) -> List[dict]:
        """Run Isolation Forest anomaly detection."""
        results = []
        # Select numeric columns for modeling
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if len(numeric_cols) < 2:
            results.append(check_result(
                dimension="anomaly_iforest",
                check_name="iforest_insufficient_features",
                passed=True,
                score=1.0,
                threshold=0.0,
                details={"error": "Need at least 2 numeric columns for Isolation Forest"}
            ))
            return results

        print(f"  > Isolation Forest: {len(numeric_cols)} features, {self.contamination:.0%} contamination")

        # Prepare data
        model_data = df[numeric_cols].copy()

        # Handle nulls by filling with median
        null_counts = model_data.isnull().sum()
        for col in numeric_cols:
            if null_counts[col] > 0:
                model_data[col] = model_data[col].fillna(model_data[col].median())

        if len(model_data) < 10:
            return results

        # Sample if very large
        sample_size = min(10000, len(model_data))
        if len(model_data) > sample_size:
            sample_indices = np.random.choice(len(model_data), sample_size, replace=False)
            sample_data = model_data.iloc[sample_indices]
        else:
            sample_indices = slice(None)
            sample_data = model_data

        # Fit Isolation Forest
        model = IsolationForest(
            contamination=self.contamination,
            n_estimators=self.n_estimators,
            random_state=config.RANDOM_SEED,
            n_jobs=-1,
        )
        model.fit(sample_data)

        # Predict on same data
        scores = model.decision_function(sample_data)  # higher = more normal
        predictions = model.predict(sample_data)  # -1 = anomaly, 1 = normal

        n_anomalies = int((predictions == -1).sum())
        anomaly_rate = n_anomalies / len(predictions)

        # Get the most anomalous rows
        anomaly_indices = np.where(predictions == -1)[0]
        anomaly_scores = scores[anomaly_indices]

        # Sort anomalies by severity (most negative score = most anomalous)
        severe_idx = np.argsort(anomaly_scores)[:20]

        top_anomalies = []
        for idx in severe_idx:
            actual_idx = sample_indices[idx] if isinstance(sample_indices, np.ndarray) else idx
            row = df.iloc[actual_idx]
            top_anomalies.append({
                "row_index": int(actual_idx),
                "anomaly_score": round(float(anomaly_scores[idx]), 4),
                "order_id": str(row.get("order_id", "")),
                "customer_id": str(row.get("customer_id", "")),
                "features": {
                    col: round(float(row[col]), 2) if pd.notna(row.get(col)) else None
                    for col in numeric_cols[:5]  # limit to 5 features in display
                }
            })

        # Score: anomaly rate close to contamination = good model fit
        rate_diff = abs(anomaly_rate - self.contamination)
        score = max(0, 1.0 - rate_diff * 5)  # 20% deviation = score 0
        passed = anomaly_rate <= self.contamination * 1.5  # allow 1.5x contamination

        results.append(check_result(
            dimension="anomaly_iforest",
            check_name="isolation_forest",
            passed=passed,
            score=score,
            threshold=self.contamination,
            details={
                "contamination": self.contamination,
                "n_estimators": self.n_estimators,
                "features_used": numeric_cols,
                "rows_analyzed": int(len(sample_data)),
                "anomalies_detected": n_anomalies,
                "anomaly_rate": round(float(anomaly_rate), 4),
                "anomaly_score_range": {
                    "min": round(float(scores.min()), 4),
                    "max": round(float(scores.max()), 4),
                    "mean": round(float(scores.mean()), 4),
                },
                "top_anomalies": top_anomalies,
            }
        ))

        return results


# ═══════════════════════════════════════════════════════════
# 5. ANOMALY PIPELINE (Orchestrator)
# ═══════════════════════════════════════════════════════════

class AnomalyPipeline:
    """Orchestrates all anomaly detectors and produces a consolidated report."""

    def __init__(self, iqr_multiplier: float = 1.5,
                 z_threshold: float = 3.0,
                 drift_window: int = 5,
                 drift_threshold: float = 2.0,
                 iforest_contamination: float = 0.05):
        self.iqr_multiplier = iqr_multiplier
        self.z_threshold = z_threshold
        self.drift_window = drift_window
        self.drift_threshold = drift_threshold
        self.iforest_contamination = iforest_contamination

    def run_all(self, df: pd.DataFrame, dataset_name: str = "unknown",
                daily_dir: Optional[str] = None) -> QualityReport:
        """Run all anomaly detectors and return consolidated report."""
        # Use threshold defaults for report scoring
        thresholds = {
            "scoring": {
                "dimension_weights": {
                    "anomaly_iqr": 0.25,
                    "anomaly_zscore": 0.25,
                    "anomaly_drift": 0.25,
                    "anomaly_iforest": 0.25,
                },
                "severity": {"critical": 0.50, "warning": 0.75, "pass": 1.0},
            }
        }
        report = QualityReport(dataset_name, thresholds)

        # Guard
        if df is None or len(df) == 0:
            report.add_check(check_result(
                dimension="pipeline", check_name="empty_dataset",
                passed=False, score=0.0, threshold=0.0,
                details={"error": "Input DataFrame is empty"}
            ))
            report.compute_scores()
            return report

        # 1. IQR outliers
        print("  > IQR-based outlier detection...")
        iqr = IQROutlierDetector(self.iqr_multiplier)
        for r in iqr.run(df):
            report.add_check(r)

        # 2. Standard Z-score
        print("  > Z-score outlier detection...")
        zscore = ZScoreDetector(self.z_threshold, use_modified=False)
        for r in zscore.run(df):
            report.add_check(r)

        # 3. Modified Z-score (MAD-based, more robust)
        print("  > Modified Z-score (MAD-based) detection...")
        mod_zscore = ZScoreDetector(self.z_threshold, use_modified=True)
        for r in mod_zscore.run(df):
            report.add_check(r)

        # 4. Time-series drift (if daily data available)
        if daily_dir and os.path.isdir(daily_dir):
            print(f"  > Time-series drift detection (window={self.drift_window})...")
            drift = DriftDetector(self.drift_window, self.drift_threshold)
            for r in drift.run(daily_dir):
                report.add_check(r)
        else:
            print("  > Skipping drift detection (no daily data directory)")

        # 5. Isolation Forest
        print(f"  > Isolation Forest (contamination={self.iforest_contamination})...")
        iforest = IsolationForestDetector(self.iforest_contamination)
        for r in iforest.run(df):
            report.add_check(r)

        # Compute scores
        report.compute_scores()
        return report


# ═══════════════════════════════════════════════════════════
# COMMAND-LINE ENTRY POINT
# ═══════════════════════════════════════════════════════════

def run_anomaly_pipeline(data_path: str = None, daily_dir: str = None):
    """Run the anomaly detection pipeline from command line."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if data_path is None:
        data_path = os.path.join(base_dir, config.DATA_DIR, "all_orders_combined.csv")
    if daily_dir is None:
        daily_dir = os.path.join(base_dir, config.DATA_DIR)

    print("=" * 60)
    print("  DataGuard — Anomaly Detection Engine")
    print("=" * 60)

    # Load data
    print("\n[1/4] Loading data...")
    df = pd.read_csv(data_path)
    print(f"       > {len(df):,} rows, {len(df.columns)} columns")

    # Run pipeline
    print("\n[2/4] Running anomaly detection...")
    pipeline = AnomalyPipeline()
    dataset_name = os.path.splitext(os.path.basename(data_path))[0]
    report = pipeline.run_all(df, dataset_name, daily_dir)

    # Output
    print("\n[3/4] Results:")
    print(report.summary_table())

    # Save report
    print("\n[4/4] Saving report...")
    report_dir = os.path.join(base_dir, config.REPORT_DIR)
    paths = save_report(report, report_dir)

    # Print top anomalies
    print("\n  Top Anomalies (Isolation Forest):")
    for check in report.checks:
        if check.get("check") == "isolation_forest":
            anomalies = check.get("details", {}).get("top_anomalies", [])
            for a in anomalies[:5]:
                print(f"    Row {a['row_index']:>6} | score={a['anomaly_score']:.3f} | "
                      f"order={a['order_id']} | cust={a['customer_id']}")
            break

    print("=" * 60)
    return report, paths


if __name__ == "__main__":
    run_anomaly_pipeline()
