"""
DataGuard — Alerting Module

Sends notifications when quality checks or anomaly detectors
detect critical failures. Supports:

- Slack webhook integration
- SMTP email (with optional TLS)
- Console fallback (always writes to log)

All alert methods are optional; the system degrades gracefully
if no alert channels are configured.
"""

import os
import json
import copy
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional, Dict, List, Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

logger = logging.getLogger("dataguard.alerts")


# ═══════════════════════════════════════════════════════════
# ALERT CONFIG
# ═══════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    "slack": {
        "enabled": False,
        "webhook_url": "",  # Set via env var: DATAGUARD_SLACK_WEBHOOK
        "channel": "#data-quality",
        "username": "DataGuard Bot",
        "icon_emoji": ":shield:",
    },
    "email": {
        "enabled": False,
        "smtp_host": "",  # Set via env var: DATAGUARD_SMTP_HOST
        "smtp_port": 587,
        "use_tls": True,
        "username": "",  # Set via env var: DATAGUARD_SMTP_USER
        "password": "",  # Set via env var: DATAGUARD_SMTP_PASS
        "from_addr": "dataguard@example.com",
        "to_addrs": [],  # Set via env var: DATAGUARD_ALERT_EMAILS (comma-separated)
    },
    "console": {
        "enabled": True,
    },
    "alert_on": {
        "critical_score": True,  # Alert when overall score < critical threshold
        "any_failures": False,   # Alert on any check failure
        "drift_events": True,    # Alert on drift detection events
        "daily_summary": True,   # Send daily summary even without failures
    },
}


def load_alert_config(config_path: Optional[str] = None) -> dict:
    """Load alert configuration from YAML file or env vars, falling back to defaults."""
    config = copy.deepcopy(DEFAULT_CONFIG)

    # Try loading from YAML file
    if config_path and os.path.exists(config_path):
        try:
            import yaml
            with open(config_path, "r") as f:
                file_config = yaml.safe_load(f) or {}
            for section in ["slack", "email", "console", "alert_on"]:
                if section in file_config:
                    config[section].update(file_config[section])
        except Exception as e:
            logger.warning(f"Could not load alert config from {config_path}: {e}")

    # Override with environment variables
    env_overrides = {
        "slack": {
            "webhook_url": os.environ.get("DATAGUARD_SLACK_WEBHOOK", ""),
            "enabled": bool(os.environ.get("DATAGUARD_SLACK_WEBHOOK", "")),
        },
        "email": {
            "smtp_host": os.environ.get("DATAGUARD_SMTP_HOST", ""),
            "smtp_port": int(os.environ.get("DATAGUARD_SMTP_PORT", "587")),
            "username": os.environ.get("DATAGUARD_SMTP_USER", ""),
            "password": os.environ.get("DATAGUARD_SMTP_PASS", ""),
            "from_addr": os.environ.get("DATAGUARD_FROM_EMAIL", config["email"]["from_addr"]),
            "enabled": bool(os.environ.get("DATAGUARD_SMTP_HOST", "")),
        },
    }
    emails_str = os.environ.get("DATAGUARD_ALERT_EMAILS", "")
    if emails_str:
        env_overrides["email"]["to_addrs"] = [e.strip() for e in emails_str.split(",")]

    for section, overrides in env_overrides.items():
        for key, val in overrides.items():
            if val:  # Only override non-empty values
                config[section][key] = val

    return config


# ═══════════════════════════════════════════════════════════
# SLACK ALERT
# ═══════════════════════════════════════════════════════════

def send_slack_alert(webhook_url: str, message: str,
                     username: str = "DataGuard Bot",
                     icon_emoji: str = ":shield:") -> bool:
    """Send a message to Slack via Incoming Webhook."""
    if not webhook_url:
        logger.warning("Slack webhook URL not configured")
        return False

    payload = json.dumps({
        "text": message,
        "username": username,
        "icon_emoji": icon_emoji,
    }).encode("utf-8")

    req = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                logger.info("Slack alert sent successfully")
                return True
            else:
                logger.warning(f"Slack returned status {resp.status}")
                return False
    except (URLError, HTTPError) as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# EMAIL ALERT
# ═══════════════════════════════════════════════════════════

def send_email_alert(config: dict, subject: str, body_text: str,
                     body_html: Optional[str] = None) -> bool:
    """Send an email alert via SMTP."""
    email_cfg = config.get("email", {})
    if not email_cfg.get("enabled"):
        logger.debug("Email alerts not enabled")
        return False

    smtp_host = email_cfg.get("smtp_host", "")
    smtp_port = email_cfg.get("smtp_port", 587)
    username = email_cfg.get("username", "")
    password = email_cfg.get("password", "")
    from_addr = email_cfg.get("from_addr", "dataguard@example.com")
    to_addrs = email_cfg.get("to_addrs", [])

    if not smtp_host or not to_addrs:
        logger.warning("Email not configured: missing SMTP host or recipient addresses")
        return False

    # Build message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if email_cfg.get("use_tls", True):
                server.starttls()
            if username and password:
                server.login(username, password)
            server.sendmail(from_addr, to_addrs, msg.as_string())
        logger.info(f"Email alert sent to {to_addrs}")
        return True
    except smtplib.SMTPException as e:
        logger.error(f"Failed to send email alert: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# REPORT FORMATTING
# ═══════════════════════════════════════════════════════════

def format_slack_message(report: dict, alert_type: str = "critical") -> str:
    """Format a quality report into a Slack message."""
    overall = report.get("overall_score", 0) * 100
    status = report.get("status", "unknown").upper()
    dims = report.get("dimension_scores", {})
    checks = report.get("checks", [])

    passed = sum(1 for c in checks if c.get("passed", False))
    failed = sum(1 for c in checks if not c.get("passed", True))
    total = passed + failed

    # Emoji for status
    if status == "CRITICAL":
        status_emoji = ":red_circle:"
    elif status == "WARNING":
        status_emoji = ":warning:"
    else:
        status_emoji = ":white_check_mark:"

    lines = [
        f"{status_emoji} *DataGuard Alert — {alert_type.replace('_', ' ').title()}*",
        f"*Overall Quality:* {overall:.1f}% ({status})",
        f"*Checks:* {passed}/{total} passed ({failed} failed)",
        "",
        "*Dimension Scores:*",
    ]

    dim_labels = {
        "completeness": "Completeness",
        "uniqueness": "Uniqueness",
        "validity": "Validity",
        "consistency": "Consistency",
        "timeliness": "Timeliness",
        "accuracy": "Accuracy",
        "anomaly_iqr": "IQR Anomalies",
        "anomaly_zscore": "Z-score Anomalies",
        "anomaly_drift": "Drift Detection",
        "anomaly_iforest": "Isolation Forest",
    }

    for dim, score in sorted(dims.items()):
        label = dim_labels.get(dim, dim)
        bar = _progress_bar(score)
        lines.append(f"  {label:20s} {bar} {score*100:.1f}%")

    lines.extend([
        "",
        f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
    ])

    return "\n".join(lines)


def format_email_body(report: dict, alert_type: str = "critical") -> tuple:
    """Format report as (text_body, html_body) for email."""
    overall = report.get("overall_score", 0) * 100
    status = report.get("status", "unknown").upper()
    dims = report.get("dimension_scores", {})
    checks = report.get("checks", [])

    passed = sum(1 for c in checks if c.get("passed", False))
    failed = sum(1 for c in checks if not c.get("passed", True))
    total = passed + failed

    # Plain text
    text = f"""DataGuard Alert — {alert_type.replace('_', ' ').title()}
{'=' * 60}

Overall Quality: {overall:.1f}% ({status})
Checks: {passed}/{total} passed ({failed} failed)

Dimension Scores:
"""
    for dim, score in sorted(dims.items()):
        text += f"  {dim:25s} {score*100:5.1f}%\n"

    text += f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

    # HTML
    dim_rows = ""
    for dim, score in sorted(dims.items()):
        color = "#2ecc71" if score >= 0.75 else ("#f39c12" if score >= 0.50 else "#e74c3c")
        bar_pct = score * 100
        dim_rows += f"""
        <tr>
            <td style="padding: 6px 12px; border-bottom: 1px solid #eee;">{dim}</td>
            <td style="padding: 6px 12px; border-bottom: 1px solid #eee;">
                <div style="background: #ecf0f1; border-radius: 8px; height: 20px; width: 100%;">
                    <div style="background: {color}; width: {bar_pct:.0f}%; height: 20px; border-radius: 8px;"></div>
                </div>
            </td>
            <td style="padding: 6px 12px; border-bottom: 1px solid #eee; text-align: right;"><strong>{bar_pct:.1f}%</strong></td>
        </tr>"""

    status_color = "#2ecc71" if status == "PASS" else ("#f39c12" if status == "WARNING" else "#e74c3c")

    html = f"""<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="border: 1px solid #ddd; border-radius: 12px; overflow: hidden;">
        <div style="background: {status_color}; color: white; padding: 20px; text-align: center;">
            <h1 style="margin: 0;">DataGuard Alert</h1>
            <p style="margin: 4px 0 0 0; opacity: 0.9;">{alert_type.replace('_', ' ').title()}</p>
        </div>
        <div style="padding: 20px;">
            <p><strong>Overall Quality Score:</strong> <span style="color: {status_color};">{overall:.1f}% ({status})</span></p>
            <p><strong>Checks:</strong> {passed}/{total} passed ({failed} failed)</p>

            <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
                <thead>
                    <tr style="background: #f8f9fa;">
                        <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #ddd;">Dimension</th>
                        <th style="padding: 8px 12px; text-align: left; border-bottom: 2px solid #ddd;">Score</th>
                        <th style="padding: 8px 12px; text-align: right; border-bottom: 2px solid #ddd;">%</th>
                    </tr>
                </thead>
                <tbody>
                    {dim_rows}
                </tbody>
            </table>

            <p style="color: #999; font-size: 12px; margin-top: 20px;">
                Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </p>
        </div>
    </div>
</body>
</html>"""

    return text, html


def _progress_bar(value: float, width: int = 10) -> str:
    """Render a simple text progress bar."""
    filled = int(round(value * width))
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    return bar


# ═══════════════════════════════════════════════════════════
# ALERT DISPATCHER
# ═══════════════════════════════════════════════════════════

def dispatch_alerts(report_json: dict, config: dict,
                    alert_type: str = "critical_score") -> Dict[str, bool]:
    """
    Send alerts through all configured channels.

    Args:
        report_json: The quality report as a dict (from QualityReport.to_dict())
        config: Alert configuration dict (from load_alert_config())
        alert_type: Type of alert ('critical_score', 'any_failures', 'drift_events', 'daily_summary')

    Returns:
        Dict mapping channel names to success booleans
    """
    results = {}

    # Console fallback (always writes to log)
    if config.get("console", {}).get("enabled", True):
        overall = report_json.get("overall_score", 0) * 100
        status = report_json.get("status", "unknown").upper()
        logger.info(
            f"ALERT [{alert_type}] Overall: {overall:.1f}% ({status}) | "
            f"Dataset: {report_json.get('dataset_name', 'unknown')}"
        )
        results["console"] = True

    # Slack
    slack_cfg = config.get("slack", {})
    if slack_cfg.get("enabled"):
        message = format_slack_message(report_json, alert_type)
        results["slack"] = send_slack_alert(
            slack_cfg["webhook_url"],
            message,
            username=slack_cfg.get("username", "DataGuard Bot"),
            icon_emoji=slack_cfg.get("icon_emoji", ":shield:"),
        )

    # Email
    email_cfg = config.get("email", {})
    if email_cfg.get("enabled"):
        subject = f"DataGuard Alert — {alert_type.replace('_', ' ').title()} — {report_json.get('overall_score', 0)*100:.0f}% Overall"
        text_body, html_body = format_email_body(report_json, alert_type)
        results["email"] = send_email_alert(config, subject, text_body, html_body)

    return results


def evaluate_and_alert(report_json: dict, alert_config: dict) -> List[Dict[str, Any]]:
    """
    Evaluate a quality report against alert thresholds and send alerts as needed.

    Args:
        report_json: Quality report dict
        alert_config: Alert configuration

    Returns:
        List of alert dispatch results
    """
    alert_on = alert_config.get("alert_on", {})
    alerts_sent = []

    overall = report_json.get("overall_score", 1.0)
    severity = report_json.get("scoring", {}).get("severity", {})
    critical_threshold = severity.get("critical", 0.50) if severity else 0.50
    warning_threshold = severity.get("warning", 0.75) if severity else 0.75

    checks = report_json.get("checks", [])
    failed_checks = [c for c in checks if not c.get("passed", True)]

    # 1. Critical score alert
    if alert_on.get("critical_score") and overall < critical_threshold:
        result = dispatch_alerts(report_json, alert_config, "critical_score")
        alerts_sent.append({"type": "critical_score", "channels": result})

    # 2. Any failures alert
    if alert_on.get("any_failures") and failed_checks:
        result = dispatch_alerts(report_json, alert_config, "any_failures")
        alerts_sent.append({"type": "any_failures", "channels": result, "failed_count": len(failed_checks)})

    # 3. Drift events
    if alert_on.get("drift_events"):
        drift_checks = [c for c in checks if c.get("dimension") == "anomaly_drift"]
        for dc in drift_checks:
            drift_alerts = dc.get("details", {}).get("alerts", [])
            if drift_alerts:
                result = dispatch_alerts(report_json, alert_config, "drift_events")
                alerts_sent.append({
                    "type": "drift_events",
                    "metric": dc.get("details", {}).get("metric", "unknown"),
                    "event_count": len(drift_alerts),
                    "channels": result,
                })

    # 4. Daily summary (always, if enabled)
    if alert_on.get("daily_summary") and not alerts_sent:
        result = dispatch_alerts(report_json, alert_config, "daily_summary")
        alerts_sent.append({"type": "daily_summary", "channels": result})

    return alerts_sent
