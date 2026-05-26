"""
DataGuard — Configuration & Constants
"""

from datetime import datetime, timedelta
import numpy as np

# ── Project Info ──────────────────────────────────────────
PROJECT_NAME = "DataGuard"
PROJECT_DESC = "Automated Data Quality & Anomaly Detection Framework"

# ── Output Paths ──────────────────────────────────────────
DATA_DIR = "data"
REPORT_DIR = "reports"

# ── Seed for reproducibility ──────────────────────────────
RANDOM_SEED = 42

# ── Date Range ────────────────────────────────────────────
START_DATE = datetime(2026, 1, 1)
END_DATE = datetime(2026, 1, 30)
NUM_DAYS = (END_DATE - START_DATE).days + 1  # 30 days

# ── Scale ─────────────────────────────────────────────────
TOTAL_ORDERS = 50000
UNIQUE_CUSTOMERS = 8000
PRODUCTS_PER_CATEGORY = 20

# ── Categories & Products ─────────────────────────────────
CATEGORIES = {
    "Electronics": ["Smartphone", "Laptop", "Bluetooth Speaker", "Wireless Earbuds",
                    "Tablet", "Smart Watch", "USB-C Hub", "Power Bank",
                    "Monitor", "Mechanical Keyboard", "Wireless Mouse", "Webcam",
                    "External SSD", "Router", "Smart Bulb", "Action Camera",
                    "E-reader", "Fitness Tracker", "Portable Projector", "Drone"],
    "Clothing": ["Men's T-Shirt", "Women's Dress", "Denim Jacket", "Casual Sneakers",
                 "Formal Shirt", "Kurta Set", "Winter Hoodie", "Running Shoes",
                 "Silk Saree", "Leather Belt", "Wrist Watch", "Sunglasses",
                 "Cotton Shorts", "Tracksuit", "Swim Trunks", "Handbag",
                 "Scarf", "Formal Loafers", "Backpack", "Cap"],
    "Home & Kitchen": ["Mixer Grinder", "Non-stick Pan Set", "Induction Cooktop",
                       "Air Purifier", "Coffee Maker", "Electric Kettle",
                       "Vacuum Cleaner", "Cookware Set", "Storage Containers",
                       "Towels Set", "Bedsheet Set", "Pillow Set",
                       "Toaster", "Food Processor", "Water Filter", "Iron",
                       "Sewing Machine", "Chimney", "Spatula Set", "Cutting Board"],
    "Books": ["The Great Gatsby", "Python for Data Analysis", "1984", "To Kill a Mockingbird",
              "Data Science from Scratch", "The Alchemist", "Think Stats", "Sapiens",
              "Deep Learning", "Storytelling with Data", "Atomic Habits", "Rich Dad Poor Dad",
              "The Art of Statistics", "Clean Code", "Designing Data-Intensive Apps",
              "The Psychology of Money", "Naked Statistics", "Freakonomics", "Outliers", "Zero to One"],
    "Sports": ["Yoga Mat", "Dumbbells Set", "Tennis Racket", "Football",
               "Basketball", "Treadmill", "Exercise Bike", "Resistance Bands",
               "Jump Rope", "Boxing Gloves", "Cricket Bat", "Badminton Racket",
               "Swimming Goggles", "Hiking Backpack", "Camping Tent", "Skipping Rope",
               "Push-up Stand", "Kettlebell", "Foam Roller", "Gym Gloves"],
    "Beauty": ["Face Moisturizer", "Lipstick Set", "Shampoo", "Hair Dryer",
               "Perfume", "Eye Shadow Palette", "Foundation", "Sunscreen Lotion",
               "Body Lotion", "Face Wash", "Nail Polish Set", "Makeup Brush Set",
               "Hair Straightener", "Beard Oil", "Serum Vitamin C", "Face Mask Pack",
               "Eye Liner", "Compact Powder", "Toner", "Lip Balm Set"],
}

# ── Payment Methods ───────────────────────────────────────
PAYMENT_METHODS = ["Credit Card", "Debit Card", "UPI", "Net Banking", "COD"]

# ── Order Statuses ────────────────────────────────────────
ORDER_STATUSES = ["Completed", "Pending", "Cancelled", "Refunded"]
ORDER_STATUS_WEIGHTS = [0.75, 0.10, 0.10, 0.05]

# ── Cities (Indian) ───────────────────────────────────────
CITIES = {
    "Mumbai": "Maharashtra", "Delhi": "Delhi", "Bangalore": "Karnataka",
    "Hyderabad": "Telangana", "Ahmedabad": "Gujarat", "Chennai": "Tamil Nadu",
    "Kolkata": "West Bengal", "Pune": "Maharashtra", "Jaipur": "Rajasthan",
    "Lucknow": "Uttar Pradesh", "Surat": "Gujarat", "Thane": "Maharashtra",
    "Indore": "Madhya Pradesh", "Bhopal": "Madhya Pradesh", "Nagpur": "Maharashtra",
    "Visakhapatnam": "Andhra Pradesh", "Patna": "Bihar", "Vadodara": "Gujarat",
    "Coimbatore": "Tamil Nadu", "Guwahati": "Assam",
}

# ── Price Ranges (₹) ─────────────────────────────────────
CATEGORY_PRICES = {
    "Electronics": (500, 150000),
    "Clothing": (299, 15000),
    "Home & Kitchen": (199, 50000),
    "Books": (99, 5000),
    "Sports": (299, 80000),
    "Beauty": (99, 10000),
}

# ── Quantity Range ────────────────────────────────────────
QUANTITY_MIN = 1
QUANTITY_MAX = 10

# ── Customer Age ──────────────────────────────────────────
AGE_MIN = 18
AGE_MAX = 75

# ── Probabilities for Channel / Device ────────────────────
CHANNELS = ["Direct", "Organic Search", "Paid Search", "Social Media", "Email", "Referral"]
CHANNEL_WEIGHTS = [0.20, 0.25, 0.20, 0.15, 0.10, 0.10]

DEVICES = ["Desktop", "Mobile", "Tablet"]
DEVICE_WEIGHTS = [0.35, 0.55, 0.10]

# ═══════════════════════════════════════════════════════════
# QUALITY ISSUE CONFIGURATION
# ═══════════════════════════════════════════════════════════

# Each issue has a base rate and an optional drift factor
# The drift factor increases the issue rate over the 30 days

QUALITY_ISSUES = {
    # ── Missing Values (null rates) ────
    "null_rates": {
        "customer_email":       {"base": 0.12, "drift": 0.004},  # 12% → 24% over 30 days
        "unit_price":           {"base": 0.08, "drift": 0.003},  # 8% → 17%
        "shipping_city":        {"base": 0.05, "drift": 0.002},  # 5% → 11%
        "customer_age":         {"base": 0.03, "drift": 0.001},  # 3% → 6%
        "payment_method":       {"base": 0.02, "drift": 0.001},  # 2% → 5%
    },
    # ── Duplicates ─────────────────────
    "duplicate_rate":            {"base": 0.03, "drift": 0.002},  # 3% → 9% duplicate orders
    # ── Outliers ───────────────────────
    "outliers": {
        "quantity":             {"base": 0.005, "drift": 0.0005, "value": 999},
        "unit_price":           {"base": 0.003, "drift": 0.0003, "value": 999999},
        "customer_age_neg":     {"base": 0.005, "drift": 0.0003, "value": -1},
        "customer_age_extreme": {"base": 0.005, "drift": 0.0003, "value": 999},
    },
    # ── Schema/Format Violations ───────
    "invalid_email_rate":        {"base": 0.05, "drift": 0.002},  # 5% → 11% emails with bad format
    "future_date_rate":          {"base": 0.01, "drift": 0.001},  # 1% → 4% dates in 2027
    "mixed_date_format_rate":    {"base": 0.00, "drift": 0.00},   # Handled separately in raw output
    # ── Referential Integrity ──────────
    "orphan_customer_rate":      {"base": 0.02, "drift": 0.001},  # 2% → 5% orders with no matching customer
    # ── Distribution Drift ─────────────
    "category_drift": {
        "Electronics":           {"shift": 0.00},   # No shift
        "Clothing":              {"shift": -0.05},  # Gradual decline
        "Home & Kitchen":        {"shift": 0.00},
        "Books":                 {"shift": -0.03},
        "Sports":                {"shift": 0.04},   # Gradual increase (sports season)
        "Beauty":                {"shift": 0.04},
    },
}


def get_daily_issue_rate(issue_config, day_index):
    """
    Calculate the effective issue rate for a given day (0-indexed).

    Base rate + drift * day_index
    The drift adds ~0.3% per day on average, so by day 29 (last day),
    the rate is base + drift * 29.
    """
    base = issue_config["base"]
    drift = issue_config.get("drift", 0)
    return min(base + drift * day_index, 0.50)  # Cap at 50%


def get_daily_outlier_value(issue_config, day_index):
    """Return the outlier value for the given day."""
    return issue_config["value"]


def get_daily_category_weights(day_index):
    """Return category weights that drift over time."""
    base_weight = 1.0 / len(CATEGORIES)
    weights = {}
    for cat, drift_info in QUALITY_ISSUES["category_drift"].items():
        shift = drift_info["shift"]
        # Linear shift from 0 to full shift over 30 days
        effective_shift = shift * (day_index / NUM_DAYS) if NUM_DAYS > 0 else 0
        weights[cat] = max(0.01, base_weight + effective_shift)
    return weights


# ── Default Thresholds for Quality Checks ─────────────────
DEFAULT_THRESHOLDS = {
    "max_null_rate": 0.10,
    "max_duplicate_rate": 0.02,
    "max_outlier_rate": 0.02,
    "min_email_validity": 0.95,
    "max_future_date_rate": 0.01,
    "max_orphan_rate": 0.01,
    "min_completeness_score": 0.90,
    "min_uniqueness_score": 0.95,
    "min_validity_score": 0.90,
    "min_consistency_score": 0.95,
    "min_overall_quality_score": 0.85,
}
