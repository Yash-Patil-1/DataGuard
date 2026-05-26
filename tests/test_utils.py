"""
Unit tests for DataGuard utilities and alerting modules.
"""

import os
import sys
import json
import tempfile

import pytest
import numpy as np
import pandas as pd

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from utils import check_result, QualityReport, save_report


# ═══════════════════════════════════════════════════════════
# CHECK RESULT TESTS
# ═══════════════════════════════════════════════════════════

class TestCheckResult:
    def test_basic_check(self):
        result = check_result(
            dimension="test",
            check_name="test_check",
            passed=True,
            score=0.95,
            threshold=0.80,
            details={"key": "value"},
        )
        assert result["dimension"] == "test"
        assert result["check"] == "test_check"
        assert result["passed"] is True
        assert result["score"] == 0.95
        assert result["details"]["key"] == "value"

    def test_failed_check(self):
        result = check_result(
            dimension="test",
            check_name="fail_check",
            passed=False,
            score=0.30,
            threshold=0.80,
            details={"reason": "failure"},
        )
        assert result["passed"] is False
        assert result["score"] == 0.30


# ═══════════════════════════════════════════════════════════
# QUALITY REPORT TESTS
# ═══════════════════════════════════════════════════════════

class TestQualityReport:
    @pytest.fixture
    def thresholds(self):
        return {
            "scoring": {
                "dimension_weights": {
                    "completeness": 0.40,
                    "uniqueness": 0.30,
                    "validity": 0.30,
                },
                "severity": {"critical": 0.50, "warning": 0.75, "pass": 1.0},
            }
        }

    def test_empty_report(self, thresholds):
        report = QualityReport("test", thresholds)
        report.compute_scores()
        assert report.overall_score == 0.0
        assert report.status == "unknown"

    def test_single_check(self, thresholds):
        report = QualityReport("test", thresholds)
        report.add_check(check_result(
            dimension="completeness", check_name="c1",
            passed=True, score=0.90, threshold=0.80,
            details={"value": 0.90},
        ))
        report.compute_scores()
        assert report.overall_score > 0
        assert report.dimension_scores.get("completeness") == 0.90

    def test_multiple_dimensions(self, thresholds):
        report = QualityReport("test", thresholds)
        report.add_check(check_result(
            dimension="completeness", check_name="c1",
            passed=True, score=0.90, threshold=0.80,
            details={"value": 0.90},
        ))
        report.add_check(check_result(
            dimension="uniqueness", check_name="u1",
            passed=False, score=0.40, threshold=0.80,
            details={"value": 0.40},
        ))
        report.add_check(check_result(
            dimension="validity", check_name="v1",
            passed=True, score=0.95, threshold=0.80,
            details={"value": 0.95},
        ))
        report.compute_scores()

        assert report.dimension_scores["completeness"] == 0.90
        assert report.dimension_scores["uniqueness"] == 0.40
        assert report.dimension_scores["validity"] == 0.95

        # Weighted: 0.40*0.90 + 0.30*0.40 + 0.30*0.95 = 0.36 + 0.12 + 0.285 = 0.765
        expected = 0.40 * 0.90 + 0.30 * 0.40 + 0.30 * 0.95
        assert abs(report.overall_score - expected) < 0.01

    def test_to_dict(self, thresholds):
        report = QualityReport("test", thresholds)
        report.add_check(check_result(
            dimension="test", check_name="t1",
            passed=True, score=1.0, threshold=0.8,
            details={"value": 1.0},
        ))
        report.compute_scores()
        d = report.to_dict()
        assert d["dataset"] == "test"
        assert "overall_score" in d
        assert "checks" in d

    def test_summary_table(self, thresholds):
        report = QualityReport("test", thresholds)
        report.add_check(check_result(
            dimension="test", check_name="t1",
            passed=True, score=1.0, threshold=0.8,
            details={"value": 1.0},
        ))
        report.compute_scores()
        table = report.summary_table()
        assert "test" in table
        assert "PASS" in table or "FAIL" in table


# ═══════════════════════════════════════════════════════════
# SAVE REPORT TESTS
# ═══════════════════════════════════════════════════════════

class TestSaveReport:
    @pytest.fixture
    def thresholds(self):
        return {
            "scoring": {
                "dimension_weights": {},
                "severity": {"critical": 0.50, "warning": 0.75, "pass": 1.0},
            }
        }

    def test_save_json_and_txt(self, thresholds):
        report = QualityReport("test", thresholds)
        report.add_check(check_result(
            dimension="test", check_name="t1",
            passed=True, score=1.0, threshold=0.8,
            details={"value": 1.0},
        ))
        report.compute_scores()

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = save_report(report, tmpdir)

            # JSON file should exist
            json_path = paths.get("json")
            assert json_path is not None
            assert os.path.exists(json_path)

            # TXT file should exist
            txt_path = paths.get("txt")
            assert txt_path is not None
            assert os.path.exists(txt_path)

            # Verify JSON content
            with open(json_path, "r") as f:
                data = json.load(f)
            assert data["dataset"] == "test"

    def test_save_creates_directory(self, thresholds):
        report = QualityReport("test", thresholds)
        report.add_check(check_result(
            dimension="test", check_name="t1",
            passed=True, score=1.0, threshold=0.8,
            details={"value": 1.0},
        ))
        report.compute_scores()

        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "nested", "dir")
            paths = save_report(report, nested)
            assert os.path.exists(nested)


# ═══════════════════════════════════════════════════════════
# ALERTS TESTS
# ═══════════════════════════════════════════════════════════

class TestAlertsModule:
    def test_load_config_defaults(self):
        from alerts import load_alert_config
        config = load_alert_config()
        assert config["slack"]["enabled"] is False
        assert config["email"]["enabled"] is False
        assert config["console"]["enabled"] is True
        assert "alert_on" in config

    def test_load_config_env_overrides(self, monkeypatch):
        from alerts import load_alert_config
        monkeypatch.setenv("DATAGUARD_SLACK_WEBHOOK", "https://hooks.slack.com/test")
        config = load_alert_config()
        assert config["slack"]["enabled"] is True
        assert config["slack"]["webhook_url"] == "https://hooks.slack.com/test"

    def test_format_slack_message(self):
        from alerts import format_slack_message
        report = {
            "overall_score": 0.45,
            "status": "critical",
            "dimension_scores": {
                "completeness": 0.80,
                "uniqueness": 0.20,
            },
            "checks": [
                {"passed": True, "score": 0.80},
                {"passed": False, "score": 0.20},
            ],
        }
        msg = format_slack_message(report, "critical_score")
        assert "DataGuard" in msg
        assert "45.0%" in msg
        assert "CRITICAL" in msg

    def test_format_email_body(self):
        from alerts import format_email_body
        report = {
            "overall_score": 0.65,
            "status": "warning",
            "dimension_scores": {
                "completeness": 0.90,
                "uniqueness": 0.40,
            },
            "checks": [
                {"passed": True, "score": 0.90},
                {"passed": False, "score": 0.40},
            ],
        }
        text, html = format_email_body(report, "any_failures")
        assert "DataGuard" in text
        assert "65.0%" in text
        assert "<html>" in html
        assert "65.0%" in html

    def test_evaluate_and_alert_critical(self):
        from alerts import load_alert_config, evaluate_and_alert
        report = {
            "overall_score": 0.30,
            "status": "critical",
            "dataset_name": "test",
            "dimension_scores": {},
            "checks": [],
            "scoring": {
                "severity": {"critical": 0.50, "warning": 0.75},
            },
        }
        config = load_alert_config()
        # Set console to true so we get at least a console alert
        config["console"]["enabled"] = True
        config["alert_on"]["daily_summary"] = False

        results = evaluate_and_alert(report, config)
        # Should have at least a critical_score alert via console
        assert len(results) >= 1
        assert any(r["type"] == "critical_score" for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
