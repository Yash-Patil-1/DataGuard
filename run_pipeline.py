"""
DataGuard — Automated Pipeline Runner

Orchestrates the full data quality pipeline:
1. Data generation (if needed)
2. Quality checks (validators)
3. Anomaly detection (detectors)
4. Alert dispatch (Slack/Email)

Usage:
    # Run once
    python run_pipeline.py

    # Run with alerting
    python run_pipeline.py --alert

    # Scheduled run (every N seconds)
    python run_pipeline.py --schedule --interval 3600

    # Run only specific stages
    python run_pipeline.py --stages validate,detect
"""

import os
import sys
import time
import json
import argparse
import logging
from datetime import datetime
from typing import Optional, List

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dataguard.runner")

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


# ═══════════════════════════════════════════════════════════
# PIPELINE RUNNER
# ═══════════════════════════════════════════════════════════

class PipelineRunner:
    """Orchestrates the full DataGuard pipeline."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self.src_dir = os.path.join(self.base_dir, "src")
        self.data_dir = os.path.join(self.base_dir, "data")
        self.report_dir = os.path.join(self.base_dir, "reports")
        self.config_dir = os.path.join(self.base_dir, "config")
        self.latest_report = None

    def ensure_directories(self):
        """Create required directories if they don't exist."""
        for d in [self.data_dir, self.report_dir, self.config_dir]:
            os.makedirs(d, exist_ok=True)

    def run_generate(self) -> bool:
        """Generate data if not already present."""
        orders_path = os.path.join(self.data_dir, "all_orders_combined.csv")
        if os.path.exists(orders_path):
            logger.info(f"Data already exists at {orders_path}, skipping generation")
            return True

        logger.info("Generating data...")
        try:
            from src.data_generator import generate_dataset
            generate_dataset()
            logger.info("Data generation complete")
            return True
        except Exception as e:
            logger.error(f"Data generation failed: {e}")
            return False

    def run_validate(self) -> Optional[dict]:
        """Run quality checks and return the report dict."""
        logger.info("Running quality checks...")
        try:
            from src.validators import run_pipeline
            report, paths = run_pipeline()
            self.latest_report = report.to_dict() if hasattr(report, 'to_dict') else report
            logger.info(f"Quality checks complete. Report saved.")
            return self.latest_report
        except Exception as e:
            logger.error(f"Quality checks failed: {e}")
            return None

    def run_detect(self) -> Optional[dict]:
        """Run anomaly detection and return the report dict."""
        logger.info("Running anomaly detection...")
        try:
            from src.detectors import run_anomaly_pipeline
            report, paths = run_anomaly_pipeline()
            logger.info(f"Anomaly detection complete.")
            # Update latest_report with anomaly results
            if hasattr(report, 'to_dict'):
                anomaly_dict = report.to_dict()
                if self.latest_report:
                    # Merge anomaly checks into the main report
                    existing_checks = self.latest_report.get("checks", [])
                    anomaly_checks = anomaly_dict.get("checks", [])
                    self.latest_report["checks"] = existing_checks + anomaly_checks
                    self.latest_report["dimension_scores"].update(
                        anomaly_dict.get("dimension_scores", {})
                    )
                    # Recompute overall if needed
                    all_scores = self.latest_report.get("dimension_scores", {}).values()
                    if all_scores:
                        self.latest_report["overall_score"] = sum(all_scores) / len(all_scores)
                else:
                    self.latest_report = anomaly_dict
            return self.latest_report
        except Exception as e:
            logger.error(f"Anomaly detection failed: {e}")
            return None

    def run_alerts(self):
        """Dispatch alerts based on the latest report."""
        if not self.latest_report:
            logger.warning("No report available for alerting")
            return

        logger.info("Evaluating and dispatching alerts...")
        try:
            from src.alerts import load_alert_config, evaluate_and_alert

            # Load alert config
            alert_config_path = os.path.join(self.config_dir, "alerts.yaml")
            alert_config = load_alert_config(alert_config_path)

            # Evaluate and send alerts
            results = evaluate_and_alert(self.latest_report, alert_config)

            for r in results:
                channels = r.get("channels", {})
                sent_to = [k for k, v in channels.items() if v]
                logger.info(
                    f"Alert '{r['type']}' sent via: {', '.join(sent_to) if sent_to else 'none'}"
                )
        except Exception as e:
            logger.error(f"Alert dispatch failed: {e}")

    def run_save_history(self):
        """Save the latest report to historical tracking database."""
        if not self.latest_report:
            logger.warning("No report to save to history")
            return

        try:
            from src.history import save_to_history, get_score_summary
            save_to_history(self.latest_report)
            summary = get_score_summary(days=7)
            if summary.get("count", 0) > 1:
                logger.info(
                    f"History saved — {summary['count']} entries | "
                    f"Current: {summary['current']}% | "
                    f"Trend: {summary['trend']}"
                )
            else:
                logger.info("History saved — first entry")
        except Exception as e:
            logger.warning(f"Could not save to history: {e}")

    def run_full(self, stages: List[str] = None, enable_alerts: bool = False):
        """
        Run the complete pipeline.

        Args:
            stages: List of stages to run ('generate', 'validate', 'detect', 'alerts').
                    Default: all stages
            enable_alerts: Whether to dispatch alerts
        """
        if stages is None:
            stages = ["generate", "validate", "detect", "alerts"]

        self.ensure_directories()
        logger.info(f"Starting pipeline run (stages: {', '.join(stages)})")

        start_time = time.time()

        if "generate" in stages:
            self.run_generate()

        if "validate" in stages:
            self.run_validate()

        if "detect" in stages:
            self.run_detect()

        if enable_alerts and "alerts" in stages:
            self.run_alerts()

        # Always save to history if we have a report
        self.run_save_history()

        elapsed = time.time() - start_time
        logger.info(f"Pipeline run complete in {elapsed:.1f}s")

        return self.latest_report


# ═══════════════════════════════════════════════════════════
# SCHEDULED RUNNER
# ═══════════════════════════════════════════════════════════

class ScheduledRunner:
    """Runs the pipeline on a schedule."""

    def __init__(self, interval_seconds: int = 3600, enable_alerts: bool = True):
        self.interval = interval_seconds
        self.enable_alerts = enable_alerts
        self.runner = PipelineRunner()
        self.run_count = 0

    def run_once(self):
        """Execute a single pipeline run."""
        self.run_count += 1
        logger.info(f"=== Scheduled Run #{self.run_count} ===")
        self.runner.run_full(enable_alerts=self.enable_alerts)
        logger.info(f"=== Run #{self.run_count} Complete ===")

    def run_loop(self):
        """Run the pipeline on a continuous schedule."""
        logger.info(
            f"Starting scheduled runner (interval={self.interval}s, "
            f"alerts={'on' if self.enable_alerts else 'off'})"
        )

        # Run immediately on start
        self.run_once()

        while True:
            logger.info(f"Next run in {self.interval}s...")
            time.sleep(self.interval)
            self.run_once()

    def run_cron_style(self):
        """
        Run once and exit (for cron-based scheduling).
        Use with system cron, Task Scheduler, or Kubernetes CronJob:
            # Run every hour
            0 * * * * cd /path/to/DataGuard && python run_pipeline.py --alert
        """
        self.run_once()


# ═══════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="DataGuard — Automated Data Quality Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_pipeline.py                     # Run once (generate + validate + detect)
  python run_pipeline.py --alert             # Run with alerting
  python run_pipeline.py --schedule          # Run continuously
  python run_pipeline.py --schedule --interval 86400  # Run daily
  python run_pipeline.py --stages validate   # Only run quality checks
  python run_pipeline.py --stages detect     # Only run anomaly detection
        """,
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        help="Enable alert dispatch after pipeline run",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run on a schedule (continuous loop)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=3600,
        help="Schedule interval in seconds (default: 3600 = 1 hour)",
    )
    parser.add_argument(
        "--stages",
        type=str,
        default="generate,validate,detect",
        help="Comma-separated stages: generate,validate,detect,alerts",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Database source URI (e.g., postgresql://user:pass@host/db or snowflake://...)",
    )
    parser.add_argument(
        "--table",
        type=str,
        default=None,
        help="Table name to read from the database source (used with --db)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]

    # Database override: load data from external source instead of CSV
    if args.db:
        logger.info(f"Using database source: {args.db}")
        try:
            from src.connectors import load_dataframe
            table_name = args.table or "orders"
            df = load_dataframe(args.db, table_name)

            # Save to local CSV for the rest of the pipeline to consume
            data_dir = os.path.join(os.path.dirname(__file__), "data")
            os.makedirs(data_dir, exist_ok=True)
            out_path = os.path.join(data_dir, "all_orders_combined.csv")
            df.to_csv(out_path, index=False)
            logger.info(f"Loaded {len(df):,} rows from {table_name} → {out_path}")
        except ImportError as e:
            logger.error(f"Database connector not available: {e}")
            logger.error("Install extra: pip install dataguard[postgresql] or dataguard[snowflake]")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to load from database: {e}")
            sys.exit(1)

    if args.schedule:
        # Scheduled mode (continuous loop)
        runner = ScheduledRunner(
            interval_seconds=args.interval,
            enable_alerts=args.alert,
        )
        try:
            runner.run_loop()
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
    else:
        # One-shot mode
        runner = PipelineRunner()
        runner.run_full(stages=stages, enable_alerts=args.alert)


if __name__ == "__main__":
    main()
