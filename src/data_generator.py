"""  DataGuard - Data Generator
 with Intentional Quality Issues

Generates:
1. customers.csv — Clean reference customer table
2. daily_orders_{day:02d}.csv — 30 daily snapshots with injected quality issues
3. ground_truth_orders.csv — Clean version (no issues) for comparison
4. all_orders_combined.csv — All 30 days concatenated (for analysis)

Quality issues injected (rates escalate over 30 days):
- Missing values (nulls)
- Duplicate records
- Outliers
- Invalid email formats
- Future dates
- Referential integrity breaks
- Distribution drift
"""

import os
import sys
import csv
import random
import json
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

# Ensure src is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

random.seed(config.RANDOM_SEED)
np.random.seed(config.RANDOM_SEED)


# ═══════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════

def _generate_customers():
    """Generate a clean customer reference table."""
    customers = []
    cities_list = list(config.CITIES.items())
    first_names = ["Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Ravi", "Ananya",
                   "Priya", "Ishita", "Neha", "Kavya", "Rohan", "Amit", "Deepika", "Sneha",
                   "Raj", "Pooja", "Vikas", "Meera", "Akash", "Divya", "Karan", "Nisha",
                   "Manish", "Shruti", "Siddharth", "Anjali", "Harsh", "Ritu", "Gaurav",
                   "Swati", "Nitin", "Yash", "Tanvi", "Kunal", "Shreya", "Mohan", "Rekha",
                   "Suresh"]
    last_names = ["Patel", "Sharma", "Singh", "Verma", "Gupta", "Kumar", "Reddy", "Joshi",
                  "Desai", "Nair", "Pillai", "Rao", "Menon", "Iyer", "Mishra", "Agarwal",
                  "Chopra", "Malhotra", "Khanna", "Saxena"]

    for i in range(config.UNIQUE_CUSTOMERS):
        cid = f"CUST{i+1:05d}"
        first = random.choice(first_names)
        last = random.choice(last_names)
        name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}{random.randint(1,999)}@email.com"
        city, state = random.choice(cities_list)
        signup_date = config.START_DATE - timedelta(days=random.randint(1, 365))
        customers.append({
            "customer_id": cid,
            "customer_name": name,
            "customer_email": email,
            "signup_date": signup_date.strftime("%Y-%m-%d"),
            "city": city,
            "state": state,
        })
    return pd.DataFrame(customers)


def _generate_clean_orders_for_day(day_index, customers_df, orders_per_day):
    """Generate clean orders for a specific day (no quality issues)."""
    date = config.START_DATE + timedelta(days=day_index)
    orders = []

    # Get daily category weights (for drift simulation)
    cat_weights = config.get_daily_category_weights(day_index)
    categories = list(cat_weights.keys())
    cat_probs = [cat_weights[c] for c in categories]
    cat_probs = np.array(cat_probs) / sum(cat_probs)

    for _ in range(orders_per_day):
        # Pick a random customer
        customer = customers_df.sample(1).iloc[0]
        category = np.random.choice(categories, p=cat_probs)
        product = random.choice(config.CATEGORIES[category])
        price_min, price_max = config.CATEGORY_PRICES[category]
        unit_price = round(random.uniform(price_min, price_max), 2)
        quantity = random.randint(config.QUANTITY_MIN, config.QUANTITY_MAX)
        total_amount = round(unit_price * quantity, 2)

        # Random time during the day with more weight during business hours
        hour = int(np.random.beta(2, 2) * 24)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        order_datetime = date.replace(hour=hour, minute=minute, second=second)

        channel = random.choices(config.CHANNELS, weights=config.CHANNEL_WEIGHTS, k=1)[0]
        device = random.choices(config.DEVICES, weights=config.DEVICE_WEIGHTS, k=1)[0]
        status = random.choices(config.ORDER_STATUSES, weights=config.ORDER_STATUS_WEIGHTS, k=1)[0]
        payment = random.choice(config.PAYMENT_METHODS)
        age = random.randint(config.AGE_MIN, config.AGE_MAX)

        orders.append({
            "order_id": None,  # assigned later
            "customer_id": customer["customer_id"],
            "customer_name": customer["customer_name"],
            "customer_email": customer["customer_email"],
            "product_category": category,
            "product_name": product,
            "quantity": quantity,
            "unit_price": unit_price,
            "total_amount": total_amount,
            "order_date": order_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            "order_status": status,
            "payment_method": payment,
            "channel": channel,
            "device": device,
            "shipping_city": customer["city"],
            "shipping_state": customer["state"],
            "customer_age": age,
            "is_new_customer": random.random() < 0.15,
        })

    df = pd.DataFrame(orders)
    # Assign clean order IDs
    df["order_id"] = [f"ORD{day_index+1:02d}-{i+1:05d}" for i in range(len(df))]
    return df


def inject_quality_issues(df, day_index):
    """
    Inject quality issues into the clean DataFrame based on day_index.
    Returns the dirty DataFrame and a quality issues log.
    """
    df = df.copy()
    issues_log = []

    # ── 1. Inject Missing Values ──────────────────────────
    for col, issue_cfg in config.QUALITY_ISSUES["null_rates"].items():
        rate = config.get_daily_issue_rate(issue_cfg, day_index)
        if col in df.columns and rate > 0:
            n_null = int(len(df) * rate)
            if n_null > 0:
                null_indices = np.random.choice(df.index, n_null, replace=False)
                df.loc[null_indices, col] = None
                issues_log.append({
                    "type": "missing_value", "column": col,
                    "rate": round(rate, 4), "count": n_null,
                    "day": day_index + 1
                })

    # ── 2. Inject Duplicates ──────────────────────────────
    dup_cfg = config.QUALITY_ISSUES["duplicate_rate"]
    dup_rate = config.get_daily_issue_rate(dup_cfg, day_index)
    n_dup = int(len(df) * dup_rate)
    if n_dup > 0:
        dup_indices = np.random.choice(df.index, n_dup, replace=True)
        dup_rows = df.loc[dup_indices].copy()
        df = pd.concat([df, dup_rows], ignore_index=True)
        issues_log.append({
            "type": "duplicate", "column": "all",
            "rate": round(dup_rate, 4), "count": n_dup,
            "day": day_index + 1, "detail": "exact_row_duplicates"
        })

    # ── 3. Inject Outliers ────────────────────────────────
    for col, issue_cfg in config.QUALITY_ISSUES["outliers"].items():
        rate = config.get_daily_issue_rate(issue_cfg, day_index)
        outlier_val = config.get_daily_outlier_value(issue_cfg, day_index)
        n_outliers = int(len(df) * rate)
        if col in df.columns and n_outliers > 0:
            outlier_indices = np.random.choice(df.index, n_outliers, replace=False)
            df.loc[outlier_indices, col] = outlier_val
            issues_log.append({
                "type": "outlier", "column": col,
                "rate": round(rate, 4), "count": n_outliers,
                "value": outlier_val, "day": day_index + 1
            })

    # ── 4. Inject Invalid Emails ──────────────────────────
    email_cfg = config.QUALITY_ISSUES["invalid_email_rate"]
    email_rate = config.get_daily_issue_rate(email_cfg, day_index)
    n_invalid = int(len(df) * email_rate)
    if n_invalid > 0 and "customer_email" in df.columns:
        invalid_indices = np.random.choice(df.index, n_invalid, replace=False)
        invalid_formats = [
            lambda: f"user{random.randint(1,999)}",           # no @
            lambda: f"user{random.randint(1,999)}@",          # no domain
            lambda: f"user{random.randint(1,999)}@.com",      # no domain name
            lambda: f"user{random.randint(1,999)}@domain",    # no TLD
            lambda: f"user name{random.randint(1,999)}@email.com",  # space in local part
        ]
        for idx in invalid_indices:
            df.at[idx, "customer_email"] = random.choice(invalid_formats)()
        issues_log.append({
            "type": "invalid_format", "column": "customer_email",
            "rate": round(email_rate, 4), "count": n_invalid,
            "day": day_index + 1
        })

    # ── 5. Inject Future Dates ────────────────────────────
    future_cfg = config.QUALITY_ISSUES["future_date_rate"]
    future_rate = config.get_daily_issue_rate(future_cfg, day_index)
    n_future = int(len(df) * future_rate)
    if n_future > 0 and "order_date" in df.columns:
        future_indices = np.random.choice(df.index, n_future, replace=False)
        for idx in future_indices:
            future_date = datetime(2027, random.randint(1, 12),
                                   random.randint(1, 28),
                                   random.randint(0, 23),
                                   random.randint(0, 59))
            df.at[idx, "order_date"] = future_date.strftime("%Y-%m-%d %H:%M:%S")
        issues_log.append({
            "type": "future_date", "column": "order_date",
            "rate": round(future_rate, 4), "count": n_future,
            "day": day_index + 1
        })

    # ── 6. Inject Orphan Customer IDs ─────────────────────
    orphan_cfg = config.QUALITY_ISSUES["orphan_customer_rate"]
    orphan_rate = config.get_daily_issue_rate(orphan_cfg, day_index)
    n_orphan = int(len(df) * orphan_rate)
    if n_orphan > 0 and "customer_id" in df.columns:
        orphan_indices = np.random.choice(df.index, n_orphan, replace=False)
        # Use customer IDs that don't exist in reference table
        max_cust = config.UNIQUE_CUSTOMERS
        for idx in orphan_indices:
            fake_id = f"CUST{max_cust + random.randint(1, 1000):05d}"
            df.at[idx, "customer_id"] = fake_id
        issues_log.append({
            "type": "referential_integrity", "column": "customer_id",
            "rate": round(orphan_rate, 4), "count": n_orphan,
            "day": day_index + 1
        })

    return df, issues_log


def generate_dataset():
    """Main function to generate all datasets."""
    base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            config.DATA_DIR)
    os.makedirs(base_dir, exist_ok=True)

    print("=" * 60)
    print("  DataGuard — Data Generator")
    print("=" * 60)

    # ── Step 1: Generate Customers ────────────────────────
    print("\n[1/4] Generating customers table...")
    customers_df = _generate_customers()
    cust_path = os.path.join(base_dir, "customers.csv")
    customers_df.to_csv(cust_path, index=False)
    print(f"       > {len(customers_df)} customers > {cust_path}")

    # ── Step 2: Generate Orders per day ───────────────────
    print(f"\n[2/4] Generating {config.NUM_DAYS} daily order snapshots...")
    orders_per_day = max(100, config.TOTAL_ORDERS // config.NUM_DAYS)

    all_daily_issues = []
    ground_truth_dfs = []
    dirty_order_ids_seen = set()

    for day in range(config.NUM_DAYS):
        # Clean orders for this day
        clean_df = _generate_clean_orders_for_day(day, customers_df, orders_per_day)

        # Dirty version with quality issues
        dirty_df, issues_log = inject_quality_issues(clean_df, day)

        # Save daily dirty CSV
        day_path = os.path.join(base_dir, f"daily_orders_{day+1:02d}.csv")
        dirty_df.to_csv(day_path, index=False)
        all_daily_issues.extend(issues_log)

        # Save clean version for ground truth
        ground_truth_dfs.append(clean_df)

        if (day + 1) % 5 == 0:
            print(f"       > Day {day+1:2d}/{config.NUM_DAYS}: {len(clean_df)} orders, "
                  f"{len(issues_log)} quality issues injected")

    print(f"       > All {config.NUM_DAYS} daily snapshots saved")

    # ── Step 3: Combine all dirty orders ──────────────────
    print("\n[3/4] Combining all daily snapshots...")
    all_dirty_dfs = []
    for day in range(config.NUM_DAYS):
        path = os.path.join(base_dir, f"daily_orders_{day+1:02d}.csv")
        all_dirty_dfs.append(pd.read_csv(path))
    combined_dirty = pd.concat(all_dirty_dfs, ignore_index=True)

    combined_path = os.path.join(base_dir, "all_orders_combined.csv")
    combined_dirty.to_csv(combined_path, index=False)
    print(f"       > {len(combined_dirty)} total dirty orders > {combined_path}")

    # ── Step 4: Save Ground Truth ─────────────────────────
    print("\n[4/4] Saving ground truth (clean) dataset...")
    ground_truth = pd.concat(ground_truth_dfs, ignore_index=True)
    gt_path = os.path.join(base_dir, "ground_truth_orders.csv")
    ground_truth.to_csv(gt_path, index=False)
    print(f"       > {len(ground_truth)} clean orders > {gt_path}")

    # ── Summary Statistics ────────────────────────────────
    print("\n" + "=" * 60)
    print("  Generation Complete — Summary")
    print("=" * 60)
    print(f"  Customers:       {len(customers_df):>8,}")
    print(f"  Daily Orders:    {orders_per_day:>8,} per day × {config.NUM_DAYS} days")
    print(f"  Total Orders:    {len(combined_dirty):>8,} (dirty)")
    print(f"  Ground Truth:    {len(ground_truth):>8,} (clean)")
    print(f"  Total Issues:    {len(all_daily_issues):>8,}")

    # Count by type
    from collections import Counter
    issue_types = Counter(i["type"] for i in all_daily_issues)
    print(f"\n  Issues by type:")
    for itype, count in sorted(issue_types.items()):
        print(f"    - {itype:30s} {count:>6,}")

    # ── Save issues log ───────────────────────────────────
    issues_path = os.path.join(base_dir, "quality_issues_log.json")
    with open(issues_path, "w") as f:
        # Convert to serializable format
        serializable = []
        for issue in all_daily_issues:
            item = {k: v for k, v in issue.items()}
            for k, v in item.items():
                if isinstance(v, (np.integer,)):
                    item[k] = int(v)
                elif isinstance(v, (np.floating,)):
                    item[k] = float(v)
            serializable.append(item)
        json.dump(serializable, f, indent=2)
    print(f"\n  Issues log saved > {issues_path}")
    print("=" * 60)

    return {
        "customers": cust_path,
        "daily_orders": [os.path.join(base_dir, f"daily_orders_{d+1:02d}.csv")
                         for d in range(config.NUM_DAYS)],
        "combined": combined_path,
        "ground_truth": gt_path,
        "issues_log": issues_path,
        "total_orders": len(combined_dirty),
        "total_issues": len(all_daily_issues),
    }


if __name__ == "__main__":
    generate_dataset()
