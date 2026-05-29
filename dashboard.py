"""
DataGuard — Interactive Quality & Anomaly Dashboard

Run with: streamlit run dashboard.py
"""

import os
import sys
import json
from datetime import datetime, timedelta
from glob import glob

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Add src to path so we can import project modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Import project modules
from src.data_catalog import generate_catalog
from src.history import load_history, get_score_summary

# ── Page Config ──────────────────────────────────────────
st.set_page_config(
    page_title="DataGuard — Data Quality Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
REPORT_DIR = os.path.join(PROJECT_DIR, "reports")

# ═══════════════════════════════════════════════════════════
# DATA LOADING (cached)
# ═══════════════════════════════════════════════════════════

@st.cache_data
def load_data():
    """Load all datasets."""
    data = {}

    # Dirty orders
    path = os.path.join(DATA_DIR, "all_orders_combined.csv")
    if os.path.exists(path):
        df = pd.read_csv(path)
        df["order_date_parsed"] = pd.to_datetime(df["order_date"], errors="coerce")
        df["day"] = df["order_date_parsed"].dt.day
        data["orders"] = df

    # Ground truth
    path = os.path.join(DATA_DIR, "ground_truth_orders.csv")
    if os.path.exists(path):
        data["ground_truth"] = pd.read_csv(path)

    # Customers
    path = os.path.join(DATA_DIR, "customers.csv")
    if os.path.exists(path):
        data["customers"] = pd.read_csv(path)

    # Daily snapshots (for drift)
    daily_files = sorted(glob(os.path.join(DATA_DIR, "daily_orders_*.csv")))
    if daily_files:
        data["daily"] = [pd.read_csv(f) for f in daily_files]

    return data


@st.cache_data
def load_latest_report():
    """Load the latest quality report JSON."""
    report_files = sorted(glob(os.path.join(REPORT_DIR, "quality_report_*.json")))
    if report_files:
        with open(report_files[-1], "r") as f:
            return json.load(f)
    return None


# ═══════════════════════════════════════════════════════════
# COMPUTATIONS (cached)
# ═══════════════════════════════════════════════════════════

@st.cache_data
def compute_daily_quality_timeline(daily_dfs):
    """Compute day-by-day quality metrics for the drift timeline."""
    rows = []
    for i, df in enumerate(daily_dfs, 1):
        row = {"day": i, "order_count": len(df)}
        row["null_email"] = df["customer_email"].isnull().mean()
        row["null_price"] = df["unit_price"].isnull().mean()
        row["null_age"] = df["customer_age"].isnull().mean()
        row["duplicate_rate"] = df.duplicated(subset=["order_id"]).mean()
        row["future_date_rate"] = (
            pd.to_datetime(df["order_date"], errors="coerce") > datetime.now()
        ).mean()
        if "quantity" in df.columns:
            row["outlier_qty"] = (df["quantity"] == 999).mean()
        if "unit_price" in df.columns:
            row["outlier_price"] = (df["unit_price"] == 999999).mean()
        if "total_amount" in df.columns:
            row["avg_order_value"] = df["total_amount"].mean()
        if "customer_age" in df.columns:
            row["invalid_age"] = ((df["customer_age"] < 0) | (df["customer_age"] > 120)).mean()
        rows.append(row)

    return pd.DataFrame(rows).set_index("day")


@st.cache_data
def compute_category_drift(daily_dfs, categories):
    """Track category distribution over days."""
    rows = []
    for i, df in enumerate(daily_dfs, 1):
        dist = df["product_category"].value_counts(normalize=True)
        row = {"day": i}
        for cat in categories:
            row[cat] = dist.get(cat, 0)
        rows.append(row)
    return pd.DataFrame(rows).set_index("day")


# ═══════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════

def render_sidebar(data, report):
    """Render sidebar with navigation and filters."""
    st.sidebar.markdown("# 🛡️ DataGuard")
    st.sidebar.caption("Data Quality & Anomaly Dashboard")

    st.sidebar.divider()

    # Navigation
    page = st.sidebar.radio(
        "Navigation",
        ["Overview", "Data Quality", "Anomaly Detection", "Drift Analysis",        "Data Explorer",
        "Data Catalog"
    ],
    index=0,
    )

    st.sidebar.divider()

    # Filters (global context)
    df = data.get("orders")
    if df is not None:
        st.sidebar.markdown("### Filters")
        # Only filter if order_date_parsed is valid
        valid_dates = df["order_date_parsed"].dropna()
        if len(valid_dates) > 0:
            date_range = st.sidebar.date_input(
                "Date range",
                value=(valid_dates.min().date(), valid_dates.max().date()),
                min_value=valid_dates.min().date(),
                max_value=valid_dates.max().date(),
            )

        channels = st.sidebar.multiselect(
            "Channel",
            options=sorted(df["channel"].dropna().unique()) if "channel" in df.columns else [],
            default=[],
        )

        # Quality score gauge in sidebar
        if report:
            overall = report.get("overall_score", 0)
            status = report.get("status", "unknown")
            st.sidebar.markdown("### Latest Score")
            # Color based on status
            color = {"pass": "#2ecc71", "warning": "#f39c12", "critical": "#e74c3c"}.get(status, "#95a5a6")
            st.sidebar.markdown(
                f"<h1 style='text-align: center; color: {color};'>{overall*100:.0f}%</h1>"
                f"<p style='text-align: center;'>{status.upper()}</p>",
                unsafe_allow_html=True,
            )

    return page


# ═══════════════════════════════════════════════════════════
# PAGE: OVERVIEW
# ═══════════════════════════════════════════════════════════

def render_overview(data, report):
    st.markdown("# 📊 Quality Overview")

    # Load history for trend display
    history = load_history(days=30)
    score_summary = get_score_summary(days=30) if history else {}

    # Metrics row
    df = data.get("orders")
    gt = data.get("ground_truth")
    customers = data.get("customers")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Total Orders", f"{len(df):,}" if df is not None else "N/A",
                  delta=f"+{len(df) - len(gt):,}" if df is not None and gt is not None else None)

    with col2:
        st.metric("Customers", f"{len(customers):,}" if customers is not None else "N/A")

    with col3:
        qscore = report.get("overall_score", 0) * 100 if report else 0
        status = report.get("status", "N/A") if report else "N/A"
        st.metric("Quality Score", f"{qscore:.0f}%", delta=status.upper())

    with col4:
        n_checks = report.get("num_checks", 0) if report else 0
        n_passed = report.get("num_passed", 0) if report else 0
        st.metric("Checks Passed", f"{n_passed}/{n_checks}",
                  delta=f"{n_passed/n_checks*100:.0f}%" if n_checks > 0 else None)

    with col5:
        if df is not None and "unit_price" in df.columns:
            total_revenue = df["total_amount"].sum()
            st.metric("Total Revenue", f"₹{total_revenue:,.0f}")

    st.divider()

    # Two-column layout
    left_col, right_col = st.columns([3, 2])

    with left_col:
        st.subheader("Quality Dimensions")

        if report and report.get("dimension_scores"):
            dims = report["dimension_scores"]
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

            # Filter to known dimensions
            known = {k: v for k, v in dims.items() if k in dim_labels}
            if known:
                fig = go.Figure()
                colors = []
                for dim, score in sorted(known.items()):
                    if score >= 0.75:
                        colors.append("#2ecc71")
                    elif score >= 0.50:
                        colors.append("#f39c12")
                    else:
                        colors.append("#e74c3c")

                fig.add_trace(go.Bar(
                    x=[dim_labels.get(d, d) for d in sorted(known.keys())],
                    y=[known[d] * 100 for d in sorted(known.keys())],
                    marker_color=colors,
                    text=[f"{known[d]*100:.1f}%" for d in sorted(known.keys())],
                    textposition="outside",
                    hovertemplate="%{x}<br>Score: %{y:.1f}%<extra></extra>",
                ))
                fig.update_layout(
                    height=400,
                    yaxis_range=[0, 110],
                    yaxis_title="Score (%)",
                    xaxis_title="",
                    margin=dict(l=20, r=20, t=20, b=40),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(size=12),
                )
                fig.add_hline(y=75, line_dash="dash", line_color="#2ecc71", opacity=0.5,
                              annotation_text="Pass (75%)")
                fig.add_hline(y=50, line_dash="dash", line_color="#f39c12", opacity=0.5,
                              annotation_text="Warn (50%)")
                st.plotly_chart(fig, use_container_width=True)

    with right_col:
        st.subheader("Data Profile")

        if df is not None:
            total = len(df)
            null_info = {}
            for col in ["customer_email", "unit_price", "shipping_city", "customer_age"]:
                if col in df.columns:
                    null_info[col] = df[col].isnull().mean() * 100

            if null_info:
                fig = go.Figure(data=[
                    go.Pie(
                        labels=list(null_info.keys()),
                        values=list(null_info.values()),
                        hole=0.4,
                        textinfo="label+percent",
                        marker=dict(colors=px.colors.qualitative.Set2),
                    )
                ])
                fig.update_layout(
                    title="Missing Value Rates",
                    height=300,
                    margin=dict(l=20, r=20, t=40, b=20),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig, use_container_width=True)

            # Quick stats row
            st.caption(f"Dataset: {len(df):,} rows × {len(df.columns)} columns")
            if gt is not None:
                st.caption(f"Ground truth: {len(gt):,} rows (reference clean data)")

    st.divider()

    # ── Quality Score Trend ──
    st.subheader("📈 Quality Score History")

    if history:
        trend_fig = go.Figure()

        # Overall score line
        dates = [h["timestamp"][:10] for h in history]
        scores = [h["overall_score"] * 100 for h in history]

        trend_fig.add_trace(go.Scatter(
            x=dates,
            y=scores,
            mode="lines+markers",
            name="Overall Quality Score",
            line=dict(width=3, color="#3498db"),
            marker=dict(size=8),
            hovertemplate="%{x}<br>Score: %{y:.1f}%<extra></extra>",
        ))

        # Threshold lines
        trend_fig.add_hline(y=75, line_dash="dash", line_color="#2ecc71", opacity=0.4,
                          annotation_text="Pass (75%)")
        trend_fig.add_hline(y=50, line_dash="dash", line_color="#f39c12", opacity=0.4,
                          annotation_text="Warn (50%)")

        trend_fig.update_layout(
            height=350,
            xaxis_title="Date",
            yaxis_title="Score (%)",
            yaxis_range=[0, 100],
            hovermode="x unified",
            margin=dict(l=20, r=20, t=20, b=40),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(trend_fig, use_container_width=True)

        # Trend summary metrics
        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("Current", f"{score_summary.get('current', 0):.1f}%")
        s2.metric("Average", f"{score_summary.get('avg', 0):.1f}%")
        s3.metric("Best", f"{score_summary.get('max', 0):.1f}%")
        s4.metric("Worst", f"{score_summary.get('min', 0):.1f}%")
        trend_icon = {"improving": "↑", "degrading": "↓", "stable": "→", "unknown": "?"}.get(
            score_summary.get("trend", "unknown"), ""
        )
        s5.metric("Trend", f"{trend_icon} {score_summary.get('trend', 'N/A').title()}")

        st.caption(f"Based on {score_summary.get('count', len(history))} historical snapshots")
    else:
        st.info("No historical data yet. Run `python run_pipeline.py` to start collecting quality score history.")


# ═══════════════════════════════════════════════════════════
# PAGE: DATA QUALITY
# ═══════════════════════════════════════════════════════════

def render_data_quality(data, report):
    st.markdown("# 🧪 Data Quality Checks")

    if not report:
        st.warning("No quality report found. Run the pipeline first.")
        return

    # ── Check results table ──
    st.subheader("All Checks")
    checks = report.get("checks", [])

    if checks:
        check_data = []
        for c in checks:
            check_data.append({
                "Dimension": c.get("dimension", "").title(),
                "Check": c.get("check", ""),
                "Status": "✅ PASS" if c.get("passed") else "❌ FAIL",
                "Score": f"{c.get('score', 0)*100:.1f}%",
                "Threshold": f"{c.get('threshold', 0)*100:.1f}%" if c.get("threshold") is not None else "-",
            })

        check_df = pd.DataFrame(check_data)
        # Color rows by status
        st.dataframe(
            check_df,
            use_container_width=True,
            column_config={
                "Status": st.column_config.Column(
                    "Status",
                    help="PASS or FAIL",
                ),
                "Score": st.column_config.ProgressColumn(
                    "Score",
                    help="Check score",
                    format="%s",
                    min_value=0,
                    max_value=100,
                ),
            },
            hide_index=True,
        )

        # Pass rate pie
        passed = sum(1 for c in checks if c.get("passed", False))
        failed = sum(1 for c in checks if not c.get("passed", True))

        col1, col2 = st.columns(2)
        with col1:
            fig = go.Figure(data=[
                go.Pie(
                    labels=["Passed", "Failed"],
                    values=[passed, failed],
                    hole=0.4,
                    marker=dict(colors=["#2ecc71", "#e74c3c"]),
                    textinfo="label+percent",
                )
            ])
            fig.update_layout(
                title=f"Check Results ({passed+failed} total)",
                height=300,
                margin=dict(l=20, r=20, t=40, b=20),
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            # Show failed checks breakdown by dimension
            failed_by_dim = {}
            for c in checks:
                if not c.get("passed", True):
                    dim = c.get("dimension", "unknown")
                    failed_by_dim[dim] = failed_by_dim.get(dim, 0) + 1

            if failed_by_dim:
                fig = go.Figure(data=[
                    go.Bar(
                        x=list(failed_by_dim.keys()),
                        y=list(failed_by_dim.values()),
                        marker_color="#e74c3c",
                        text=list(failed_by_dim.values()),
                        textposition="outside",
                    )
                ])
                fig.update_layout(
                    title="Failures by Dimension",
                    height=300,
                    margin=dict(l=20, r=20, t=40, b=40),
                    xaxis_title="",
                    yaxis_title="Failed Checks",
                )
                st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# PAGE: ANOMALY DETECTION
# ═══════════════════════════════════════════════════════════

def render_anomaly_detection(data, report):
    st.markdown("# 🔍 Anomaly Detection")

    if not report:
        st.warning("No report found.")
        return

    checks = report.get("checks", [])

    # ── Anomaly method comparison ──
    st.subheader("Anomaly Detection Methods")

    anomaly_dims = ["anomaly_iqr", "anomaly_zscore", "anomaly_iforest", "anomaly_drift"]
    dim_scores = report.get("dimension_scores", {})

    adims = {k: v for k, v in dim_scores.items() if k in anomaly_dims}
    if adims:
        dim_labels = {
            "anomaly_iqr": "IQR Outliers",
            "anomaly_zscore": "Z-score",
            "anomaly_iforest": "Isolation Forest",
            "anomaly_drift": "Drift Detection",
        }
        fig = go.Figure()
        colors = ["#3498db", "#9b59b6", "#e74c3c", "#2ecc71"]
        for i, (dim, score) in enumerate(sorted(adims.items())):
            fig.add_trace(go.Bar(
                name=dim_labels.get(dim, dim),
                x=[dim_labels.get(dim, dim)],
                y=[score * 100],
                marker_color=colors[i % len(colors)],
                text=[f"{score*100:.1f}%"],
                textposition="outside",
            ))
        fig.update_layout(
            height=300,
            yaxis_range=[0, 110],
            yaxis_title="Score (%)",
            showlegend=False,
            margin=dict(l=20, r=20, t=20, b=40),
        )
        fig.add_hline(y=75, line_dash="dash", line_color="#2ecc71", opacity=0.5)
        fig.add_hline(y=50, line_dash="dash", line_color="#f39c12", opacity=0.5)
        st.plotly_chart(fig, use_container_width=True)

    # ── Top Isolation Forest Anomalies ──
    st.subheader("Top Anomalies (Isolation Forest)")

    iforest_checks = [c for c in checks if c.get("check") == "isolation_forest"]
    if iforest_checks:
        top_anomalies = iforest_checks[0].get("details", {}).get("top_anomalies", [])
        if top_anomalies:
            anomaly_rows = []
            for a in top_anomalies:
                features = a.get("features", {})
                features_str = ", ".join(f"{k}={v}" for k, v in features.items())
                anomaly_rows.append({
                    "Row": a["row_index"],
                    "Order ID": a.get("order_id", ""),
                    "Customer": a.get("customer_id", ""),
                    "Anomaly Score": f"{a['anomaly_score']:.3f}",
                    "Key Features": features_str,
                })
            st.dataframe(pd.DataFrame(anomaly_rows), use_container_width=True, hide_index=True)

            # Score distribution hint
            score_range = iforest_checks[0].get("details", {}).get("anomaly_score_range", {})
            if score_range:
                st.caption(
                    f"Anomaly score range: [{score_range.get('min', 0):.3f}, "
                    f"{score_range.get('max', 0):.3f}] | "
                    f"Mean: {score_range.get('mean', 0):.3f} | "
                    f"Lower = more anomalous"
                )

    # ── Outlier counts by column ──
    st.subheader("Outlier Detection by Column")

    iqr_checks = [c for c in checks if c.get("dimension") == "anomaly_iqr"]
    if iqr_checks:
        outlier_data = []
        for c in iqr_checks:
            d = c.get("details", {})
            outlier_data.append({
                "Column": d.get("column", ""),
                "Method": "IQR",
                "Outliers": d.get("outlier_count", 0),
                "Rate": f"{d.get('outlier_rate', 0)*100:.2f}%",
                "Pass": "✅" if c.get("passed") else "❌",
            })

        # Add Z-score results
        zscore_checks = [c for c in checks
                         if c.get("dimension") == "anomaly_zscore"
                         and not c.get("check", "").startswith("overall")]
        for c in zscore_checks:
            d = c.get("details", {})
            outlier_data.append({
                "Column": d.get("column", "") + f" ({d.get('method', 'z')})",
                "Method": d.get("method", "Z-score"),
                "Outliers": d.get("outlier_count", 0),
                "Rate": f"{d.get('outlier_rate', 0)*100:.2f}%",
                "Pass": "✅" if c.get("passed") else "❌",
            })

        if outlier_data:
            st.dataframe(pd.DataFrame(outlier_data), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════
# PAGE: DRIFT ANALYSIS
# ═══════════════════════════════════════════════════════════

def render_drift_analysis(data, report_with_drift):
    st.markdown("# 📈 Drift Analysis")

    daily = data.get("daily")
    df = data.get("orders")

    if not daily or len(daily) < 3:
        st.warning("Need at least 3 daily snapshots for drift analysis.")
        return

    # ── Quality metric trends over 30 days ──
    st.subheader("Quality Metrics Over Time")

    timeline = compute_daily_quality_timeline(daily)

    metrics_to_plot = {
        "null_email": "Null Email Rate",
        "null_price": "Null Price Rate",
        "duplicate_rate": "Duplicate Rate",
        "outlier_qty": "Quantity=999 Rate",
        "outlier_price": "Price=999999 Rate",
        "avg_order_value": "Avg Order Value",
        "future_date_rate": "Future Date Rate",
    }

    selected_metrics = st.multiselect(
        "Select metrics to display",
        options=list(metrics_to_plot.keys()),
        default=["null_email", "duplicate_rate", "outlier_qty"],
        format_func=lambda x: metrics_to_plot.get(x, x),
    )

    if selected_metrics:
        fig = go.Figure()
        for metric in selected_metrics:
            if metric in timeline.columns:
                fig.add_trace(go.Scatter(
                    x=timeline.index,
                    y=timeline[metric],
                    mode="lines+markers",
                    name=metrics_to_plot.get(metric, metric),
                    line=dict(width=2),
                    hovertemplate="Day %{x}<br>%{y:.4f}<extra></extra>",
                ))

        fig.update_layout(
            height=450,
            xaxis_title="Day",
            yaxis_title="Rate / Value",
            hovermode="x unified",
            margin=dict(l=20, r=20, t=20, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Category drift ──
    st.subheader("Category Distribution Drift")

    if df is not None and "product_category" in df.columns:
        categories = sorted(df["product_category"].dropna().unique())
        cat_drift = compute_category_drift(daily, categories)

        fig = go.Figure()
        colors = px.colors.qualitative.Set2
        for i, cat in enumerate(categories):
            fig.add_trace(go.Scatter(
                x=cat_drift.index,
                y=cat_drift[cat] * 100,
                mode="lines+markers",
                name=cat,
                line=dict(width=2, color=colors[i % len(colors)]),
                hovertemplate="Day %{x}<br>%{y:.1f}%<extra></extra>",
            ))

        fig.update_layout(
            height=400,
            xaxis_title="Day",
            yaxis_title="Share (%)",
            hovermode="x unified",
            margin=dict(l=20, r=20, t=20, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Drift alerts ──
    st.subheader("Drift Alerts")

    if report_with_drift:
        drift_checks = [c for c in report_with_drift.get("checks", [])
                        if c.get("dimension") == "anomaly_drift"]
        if drift_checks:
            tab_labels = [c.get("check", "unknown") for c in drift_checks]
            tabs = st.tabs(tab_labels)
            for tab, check in zip(tabs, drift_checks):
                with tab:
                    details = check.get("details", {})
                    alerts = details.get("alerts", [])
                    metric = details.get("metric", "unknown")
                    st.caption(f"Metric: {metric} | "
                               f"Window: {details.get('window_size', '?')} days | "
                               f"Threshold: {details.get('drift_threshold_sigma', '?')}σ")

                    if alerts:
                        st.dataframe(pd.DataFrame(alerts), use_container_width=True, hide_index=True)
                    else:
                        st.success("No drift alerts for this metric.")


# ═══════════════════════════════════════════════════════════
# PAGE: DATA EXPLORER
# ═══════════════════════════════════════════════════════════

def render_data_explorer(data, report_for_explorer):
    st.markdown("# 🔎 Data Explorer")

    df = data.get("orders")
    gt = data.get("ground_truth")

    tab1, tab2, tab3 = st.tabs(["Preview Data", "Compare with Ground Truth", "Column Profiles"])

    # ── Tab 1: Preview ──
    with tab1:
        if df is not None:
            st.subheader("Dirty Orders Preview")

            display_cols = [c for c in df.columns if c != "order_date_parsed"]
            n_rows = st.slider("Rows to display", 10, 500, 50)

            # Highlight nulls
            styled = df[display_cols].head(n_rows).style.map(
                lambda v: "background-color: #ffcccc" if pd.isna(v) else ""
            )
            st.dataframe(styled, use_container_width=True)

            st.caption(f"Showing {n_rows} of {len(df):,} rows")

    # ── Tab 2: Compare with Ground Truth ──
    with tab2:
        if df is not None and gt is not None:
            st.subheader("Dirty vs Clean Comparison")

            col1, col2 = st.columns(2)

            with col1:
                # Null rate comparison
                dirty_nulls = df.isnull().mean() * 100
                clean_nulls = gt.isnull().mean() * 100

                compare_df = pd.DataFrame({
                    "Dirty (%)": dirty_nulls,
                    "Clean (%)": clean_nulls,
                }).dropna(how="all")

                compare_df = compare_df[compare_df["Dirty (%)"] > 0]

                if len(compare_df) > 0:
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        name="Dirty Data",
                        x=compare_df.index,
                        y=compare_df["Dirty (%)"],
                        marker_color="#e74c3c",
                    ))
                    fig.add_trace(go.Bar(
                        name="Clean (Ground Truth)",
                        x=compare_df.index,
                        y=compare_df["Clean (%)"],
                        marker_color="#2ecc71",
                    ))
                    fig.update_layout(
                        title="Null Rate Comparison",
                        height=350,
                        barmode="group",
                        yaxis_title="Null Rate (%)",
                        margin=dict(l=20, r=20, t=40, b=40),
                    )
                    st.plotly_chart(fig, use_container_width=True)

            with col2:
                # Row count comparison
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=["Dirty Data", "Clean (Ground Truth)"],
                    y=[len(df), len(gt)],
                    marker_color=["#e74c3c", "#2ecc71"],
                    text=[f"{len(df):,}", f"{len(gt):,}"],
                    textposition="outside",
                ))
                fig.update_layout(
                    title="Dataset Size",
                    height=350,
                    yaxis_title="Row Count",
                    margin=dict(l=20, r=20, t=40, b=40),
                )
                st.plotly_chart(fig, use_container_width=True)

    # ── Tab 3: Column Profiles ──
    with tab3:
        if df is not None:
            st.subheader("Column Profiles")

            col = st.selectbox("Select column to analyze", df.columns)

            if col in df.columns:
                col1, col2 = st.columns(2)

                with col1:
                    dtype = df[col].dtype
                    nulls = df[col].isnull().sum()
                    null_pct = nulls / len(df) * 100
                    uniques = df[col].nunique()

                    st.markdown("**Stats**")
                    st.markdown(f"- **Type:** `{dtype}`")
                    st.markdown(f"- **Missing:** {nulls:,} / {null_pct:.1f}%")
                    st.markdown(f"- **Unique:** {uniques:,}")

                    if pd.api.types.is_numeric_dtype(df[col]):
                        st.markdown(f"- **Mean:** {df[col].mean():.2f}")
                        st.markdown(f"- **Std:** {df[col].std():.2f}")
                        st.markdown(f"- **Min:** {df[col].min():.2f}")
                        st.markdown(f"- **Max:** {df[col].max():.2f}")

                with col2:
                    if pd.api.types.is_numeric_dtype(df[col]):
                        valid = df[col].dropna()
                        if len(valid) > 0:
                            fig = px.histogram(
                                valid, x=col,
                                nbins=min(50, int(valid.nunique())),
                                title=f"Distribution of {col}",
                                color_discrete_sequence=["#3498db"],
                            )
                            fig.update_layout(
                                height=300,
                                margin=dict(l=20, r=20, t=40, b=20),
                                showlegend=False,
                            )
                            st.plotly_chart(fig, use_container_width=True)
                    else:
                        value_counts = df[col].value_counts().head(20)
                        fig = go.Figure(data=[
                            go.Bar(
                                x=value_counts.values,
                                y=value_counts.index,
                                orientation="h",
                                marker_color="#3498db",
                                text=value_counts.values,
                                textposition="outside",
                            )
                        ])
                        fig.update_layout(
                            title=f"Top 20 values in {col}",
                            height=max(300, len(value_counts) * 20),
                            margin=dict(l=20, r=20, t=40, b=20),
                            xaxis_title="Count",
                            yaxis_title="",
                        )
                        st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# PAGE: DATA CATALOG
# ═══════════════════════════════════════════════════════════

@st.cache_data
def load_catalog():
    """Load and cache the data catalog."""
    catalog = generate_catalog()
    return catalog


def render_data_catalog(data, report):
    st.markdown("# 📚 Data Catalog")
    st.caption("Automated column profiling & schema overview — powered by `src/data_catalog.py`")

    with st.spinner("Generating data catalog..."):
        catalog = load_catalog()

    if not catalog or "tables" not in catalog:
        st.warning("No data found to catalog. Run the data generator first.")
        return

    # ── Table Selector ──
    tables = catalog["tables"]
    table_names = list(tables.keys())
    selected_table = st.selectbox(
        "Select dataset",
        options=table_names,
        format_func=lambda x: tables[x].get("table_name", x),
    )

    table = tables[selected_table]

    # ── Table Summary KPIs ──
    st.subheader("Dataset Summary")
    health = table.get("overall_health", "unknown")
    health_icon = {"good": "✅", "warning": "🟡", "critical": "🔴", "empty": "⚪"}.get(health, "❓")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Rows", f"{table['row_count']:,}")
    col2.metric("Columns", str(table["column_count"]))
    col3.metric("Estimated Size", table["estimated_size"])
    col4.metric("Health", f"{health_icon} {health.title()}")
    col5.metric("Flags", f"🔴{table.get('critical_flags', 0)} 🟡{table.get('warning_flags', 0)}")

    # Column type distribution
    type_dist = table.get("column_types_summary", {})
    if type_dist:
        fig = go.Figure(data=[
            go.Pie(
                labels=list(type_dist.keys()),
                values=list(type_dist.values()),
                hole=0.4,
                textinfo="label+percent",
                marker=dict(colors=px.colors.qualitative.Pastel),
            )
        ])
        fig.update_layout(
            title="Column Type Distribution",
            height=300,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Schema Overview Table ──
    st.subheader("Schema Overview")

    schema_rows = []
    for col in table["columns"]:
        flags_str = ", ".join(f["message"] for f in col.get("quality_flags", []))
        # Severity icons
        severity_icons = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}
        flag_icons = "".join(
            severity_icons.get(f["severity"], "⚪") for f in col.get("quality_flags", [])
        )
        schema_rows.append({
            "Column": col["name"],
            "Type": col["dtype"],
            "Nulls": f"{col['null_count']:,} ({col['null_rate']:.1%})",
            "Unique": f"{col['unique_count']:,}",
            "Cardinality": f"{col['cardinality_ratio']:.2%}",
            "Flags": flag_icons,
            "Flags Detail": flags_str,
        })

    if schema_rows:
        df_schema = pd.DataFrame(schema_rows)
        st.dataframe(
            df_schema,
            use_container_width=True,
            column_config={
                "Flags": st.column_config.Column(
                    "Flags",
                    width="small",
                    help="Quality flags: 🔴 critical, 🟡 warning, ℹ️ info",
                ),
            },
            hide_index=True,
        )

    st.divider()

    # ── Column Deep Dive ──
    st.subheader("Column Deep Dive")

    col_names = [c["name"] for c in table["columns"]]
    selected_col_name = st.selectbox("Select a column to inspect", options=col_names, key="cat_col_select")

    # Find the column profile
    col_profile = next((c for c in table["columns"] if c["name"] == selected_col_name), None)

    if col_profile:
        c1, c2 = st.columns([1, 1])

        with c1:
            st.markdown("**Basic Info**")
            st.markdown(f"- **Dtype:** `{col_profile['dtype']}`")
            st.markdown(f"- **Nulls:** {col_profile['null_count']:,} / {col_profile['null_rate']:.2%}")
            st.markdown(f"- **Uniques:** {col_profile['unique_count']:,}")
            st.markdown(f"- **Cardinality:** {col_profile['cardinality_ratio']:.2%}")

            if col_profile.get("sample_values"):
                samples = col_profile["sample_values"][:5]
                samples_str = ", ".join(str(s) for s in samples)
                st.markdown(f"- **Samples:** `{samples_str}`")

            # Quality flags
            if col_profile.get("quality_flags"):
                st.markdown("**Quality Flags**")
                for flag in col_profile["quality_flags"]:
                    icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(flag["severity"], "⚪")
                    st.markdown(f"{icon} {flag['message']}")

        with c2:
            # Numeric stats
            if col_profile["is_numeric"] and col_profile.get("stats"):
                stats = col_profile["stats"]
                st.markdown("**Numeric Statistics**")
                st.markdown(f"- **Min:** {stats.get('min', 'N/A')}")
                st.markdown(f"- **Max:** {stats.get('max', 'N/A')}")
                st.markdown(f"- **Mean:** {stats.get('mean', 'N/A')}")
                st.markdown(f"- **Median:** {stats.get('median', 'N/A')}")
                st.markdown(f"- **Std:** {stats.get('std', 'N/A')}")
                st.markdown(f"- **IQR:** {stats.get('iqr', 'N/A')}")
                st.markdown(f"- **Skew:** {stats.get('skew', 'N/A')}")
                st.markdown(f"- **Zeros:** {stats.get('zeros', 'N/A')}")

            # Categorical stats
            if col_profile["is_categorical"] and col_profile.get("stats"):
                stats = col_profile["stats"]
                st.markdown("**Categorical Statistics**")
                st.markdown(f"- **Entropy:** {stats.get('entropy', 'N/A')}")
                st.markdown(f"- **Norm. Entropy:** {stats.get('normalized_entropy', 'N/A')}")
                st.markdown(f"- **Top Value Share:** {stats.get('top_value_share', 'N/A')}%")

            # Datetime stats
            if col_profile["is_datetime"] and col_profile.get("stats"):
                stats = col_profile["stats"]
                st.markdown("**Temporal Statistics**")
                st.markdown(f"- **Min:** {stats.get('min', 'N/A')}")
                st.markdown(f"- **Max:** {stats.get('max', 'N/A')}")
                st.markdown(f"- **Range:** {stats.get('range_days', 'N/A')} days")

        # ── Distribution Chart ──
        st.divider()
        st.markdown("**Distribution**")

        df_data = data.get("orders")
        if df_data is not None and selected_col_name in df_data.columns:
            vals = df_data[selected_col_name].dropna()
            if len(vals) > 0:
                if col_profile["is_numeric"]:
                    fig = px.histogram(
                        vals,
                        x=selected_col_name,
                        nbins=min(50, int(vals.nunique())),
                        title=f"Distribution of {selected_col_name}",
                        color_discrete_sequence=["#3498db"],
                        marginal="box",
                    )
                    # Add vertical lines for mean and median
                    mean_val = vals.mean()
                    median_val = vals.median()
                    fig.add_vline(x=mean_val, line_dash="dash", line_color="red",
                                  annotation_text=f"Mean={mean_val:.1f}")
                    fig.add_vline(x=median_val, line_dash="dot", line_color="green",
                                  annotation_text=f"Median={median_val:.1f}")
                    fig.update_layout(
                        height=400,
                        margin=dict(l=20, r=20, t=40, b=20),
                        showlegend=False,
                    )
                    st.plotly_chart(fig, use_container_width=True)

                elif col_profile["is_categorical"] and col_profile.get("top_values"):
                    top_vals = col_profile["top_values"]
                    fig = go.Figure(data=[
                        go.Bar(
                            x=[t["count"] for t in top_vals],
                            y=[str(t["value"]) for t in top_vals],
                            orientation="h",
                            marker_color="#3498db",
                            text=[f"{t['percentage']:.1f}%" for t in top_vals],
                            textposition="outside",
                            hovertemplate="%{y}<br>Count: %{x}<br>Share: %{text}<extra></extra>",
                        )
                    ])
                    fig.update_layout(
                        title=f"Top 10 values in {selected_col_name}",
                        height=max(300, len(top_vals) * 28),
                        margin=dict(l=20, r=20, t=40, b=20),
                        xaxis_title="Count",
                        yaxis_title="",
                    )
                    st.plotly_chart(fig, use_container_width=True)

    # ── Cross-Table Comparison ──
    if catalog.get("cross_table"):
        st.divider()
        st.subheader("🔄 Cross-Table Comparison")

        ct = catalog["cross_table"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Shared Columns", len(ct["shared_columns"]))
        c2.metric("Row Count Difference", f"{ct['row_count_diff']:+d}")
        c3.metric("Difference %", f"{ct['row_count_diff_pct']:+.1f}%")

        # Null rate comparison chart (dirty vs clean)
        if "orders" in tables and "ground_truth" in tables:
            orders_table = tables["orders"]
            gt_table = tables["ground_truth"]

            # Build comparison data for shared columns
            compare_data = []
            for col in orders_table["columns"]:
                if col["name"] in ct["shared_columns"]:
                    gt_col = next(
                        (c for c in gt_table["columns"] if c["name"] == col["name"]),
                        None
                    )
                    if gt_col:
                        compare_data.append({
                            "column": col["name"],
                            "dirty_nulls": col["null_rate"] * 100,
                            "clean_nulls": gt_col["null_rate"] * 100,
                        })

            if compare_data:
                compare_df = pd.DataFrame(compare_data)
                compare_df = compare_df[compare_df["dirty_nulls"] > 0]

                if len(compare_df) > 0:
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        name="Dirty Data",
                        x=compare_df["column"],
                        y=compare_df["dirty_nulls"],
                        marker_color="#e74c3c",
                    ))
                    fig.add_trace(go.Bar(
                        name="Clean (Ground Truth)",
                        x=compare_df["column"],
                        y=compare_df["clean_nulls"],
                        marker_color="#2ecc71",
                    ))
                    fig.update_layout(
                        title="Null Rate: Dirty vs Clean",
                        barmode="group",
                        height=350,
                        yaxis_title="Null Rate (%)",
                        margin=dict(l=20, r=20, t=40, b=40),
                    )
                    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════


def main():
    # Load data
    with st.spinner("Loading data..."):
        data = load_data()
        report = load_latest_report()

    if data.get("orders") is None:
        st.error("No data found. Run the data generator first: `python src/data_generator.py`")
        st.stop()

    # Render sidebar
    page = render_sidebar(data, report)

    st.divider()

    # Render selected page
    if page == "Overview":
        render_overview(data, report)
    elif page == "Data Quality":
        render_data_quality(data, report)
    elif page == "Anomaly Detection":
        render_anomaly_detection(data, report)
    elif page == "Drift Analysis":
        render_drift_analysis(data, report)
    elif page == "Data Explorer":
        render_data_explorer(data, report)
    elif page == "Data Catalog":
        render_data_catalog(data, report)

    # Footer
    st.divider()
    st.caption(
        f"DataGuard v1.0 | "
        f"Orders: {len(data.get('orders', [])):,} | "
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


if __name__ == "__main__":
    main()
