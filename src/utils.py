"""
DataGuard — Utility functions for logging, scoring, and reporting.
"""

import json
import os
import csv
from datetime import datetime
from typing import Dict, List, Optional, Any


class QualityReport:
    """Collects and aggregates results from all quality checkers."""

    def __init__(self, dataset_name: str, thresholds: dict):
        self.dataset_name = dataset_name
        self.thresholds = thresholds
        self.timestamp = datetime.now()
        self.checks: List[dict] = []
        self.dimension_scores: Dict[str, float] = {}
        self.overall_score: float = 0.0
        self.status: str = "unknown"

    def add_check(self, check_result: dict):
        """Add a single check result."""
        self.checks.append(check_result)

    def compute_scores(self):
        """Compute dimension-level and overall quality scores.

        Excludes "overall_*" checks from dimension averaging to avoid
        double-counting (the overall check is the average of individual
        checks within the same dimension).
        """
        if not self.checks:
            return

        # Group checks by dimension
        dimensions: Dict[str, List[dict]] = {}
        for check in self.checks:
            dim = check.get("dimension", "unknown")
            dimensions.setdefault(dim, []).append(check)

        # Score each dimension (average of individual check scores, excluding overall_*)
        for dim, dim_checks in dimensions.items():
            individual_scores = [
                c.get("score", 0) for c in dim_checks
                if "score" in c and not c.get("check", "").startswith("overall_")
            ]
            self.dimension_scores[dim] = (
                sum(individual_scores) / len(individual_scores)
                if individual_scores else 0.0
            )

        # Compute weighted overall score
        weights = self.thresholds.get("scoring", {}).get("dimension_weights", {})
        total_weight = 0
        weighted_sum = 0
        for dim, score in self.dimension_scores.items():
            w = weights.get(dim, 0.2)  # default equal weight
            weighted_sum += score * w
            total_weight += w

        self.overall_score = weighted_sum / total_weight if total_weight > 0 else 0

        # Determine status
        severity = self.thresholds.get("scoring", {}).get("severity", {})
        if self.overall_score < severity.get("critical", 0.50):
            self.status = "critical"
        elif self.overall_score < severity.get("warning", 0.75):
            self.status = "warning"
        else:
            self.status = "pass"

    def to_dict(self) -> dict:
        """Serialize report to a dictionary."""
        return {
            "dataset": self.dataset_name,
            "timestamp": self.timestamp.isoformat(),
            "overall_score": round(self.overall_score, 4),
            "status": self.status,
            "dimension_scores": {k: round(v, 4) for k, v in self.dimension_scores.items()},
            "num_checks": len(self.checks),
            "num_passed": sum(1 for c in self.checks if c.get("passed", False)),
            "num_failed": sum(1 for c in self.checks if not c.get("passed", True)),
            "checks": self.checks,
        }

    def summary_table(self) -> str:
        """Return a text summary table."""
        lines = []
        lines.append(f"{'='*60}")
        lines.append(f"  Quality Report: {self.dataset_name}")
        lines.append(f"  Timestamp:      {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"{'='*60}")
        lines.append(f"  Overall Score:  {self.overall_score:.1%}  [{self.status.upper()}]")
        lines.append(f"{'='*60}")
        lines.append(f"  {'Dimension':25s} {'Score':>8s} {'Status':>10s}")
        lines.append(f"  {'-'*45}")
        for dim, score in sorted(self.dimension_scores.items()):
            status = "PASS" if score >= 0.75 else ("WARN" if score >= 0.50 else "FAIL")
            lines.append(f"  {dim:25s} {score:7.1%}  {status:>10s}")
        lines.append(f"  {'-'*45}")
        lines.append(f"  Checks: {len(self.checks)} total, "
                      f"{sum(1 for c in self.checks if c.get('passed', False))} passed, "
                      f"{sum(1 for c in self.checks if not c.get('passed', True))} failed")
        lines.append(f"{'='*60}")
        return "\n".join(lines)


def save_report(report: QualityReport, output_dir: str):
    """Save the quality report to JSON and text files."""
    os.makedirs(output_dir, exist_ok=True)

    # JSON
    json_path = os.path.join(output_dir, f"quality_report_{report.timestamp.strftime('%Y%m%d_%H%M%S')}.json")
    with open(json_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2, default=str)
    print(f"  > Report (JSON): {json_path}")

    # Text summary
    txt_path = os.path.join(output_dir, "quality_report_latest.txt")
    with open(txt_path, "w") as f:
        f.write(report.summary_table())
    print(f"  > Report (TXT):  {txt_path}")

    return {"json": json_path, "txt": txt_path}


def check_result(
    dimension: str,
    check_name: str,
    passed: bool,
    score: float,
    details: dict,
    threshold: Optional[float] = None,
) -> dict:
    """Create a standardized check result dict."""
    return {
        "dimension": dimension,
        "check": check_name,
        "passed": passed,
        "score": score,
        "threshold": threshold,
        "details": details,
        "timestamp": datetime.now().isoformat(),
    }


def load_thresholds(path: str) -> dict:
    """Load YAML thresholds file, falling back to defaults."""
    try:
        import yaml
        if os.path.exists(path):
            with open(path, "r") as f:
                return yaml.safe_load(f)
    except Exception as e:
        print(f"  Warning: Could not load thresholds from {path}: {e}")

    # Return built-in defaults from config
    from config import DEFAULT_THRESHOLDS
    return DEFAULT_THRESHOLDS
