"""
clean_orders.py
----------------
Part 1: Data Cleaning - Retail Orders Dataset

Reads data/raw_orders.xlsx, applies cleaning rules defined in the
business_rules sheet (and explained in outputs/cleaning_log.md), and
writes:
  - data/cleaned_orders.xlsx          (cleaned dataset + calculated fields)
  - outputs/data_quality_report.xlsx  (summary of issues found/fixed, by category)
  - outputs/pivot_summary.xlsx        (KPI pivot tables for business insights)

Run from the repo root:
    python scripts/clean_orders.py
"""

import re
import pandas as pd
import numpy as np

RAW_PATH = "data/raw_orders.xlsx"
CLEANED_PATH = "data/cleaned_orders.xlsx"
QUALITY_REPORT_PATH = "outputs/data_quality_report.xlsx"
PIVOT_PATH = "outputs/pivot_summary.xlsx"

DATE_FORMATS = ("%d %b %Y", "%m/%d/%Y", "%d-%m-%Y", "%Y-%m-%d")


def parse_date_flex(value):
    """Try each known date format until one parses. Returns NaT if none match."""
    s = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return pd.to_datetime(s, format=fmt)
        except ValueError:
            continue
    return pd.NaT


def clean_text(value):
    """Trim whitespace, collapse internal double-spaces, title-case for consistency."""
    if pd.isna(value):
        return value
    s = re.sub(r"\s+", " ", str(value).strip())
    return s.title() if s else s


def clean_discount(value):
    """
    Normalize discount to a decimal fraction.
    Handles: blanks, plain decimals (0.2), and percent-strings ('70%').
    Does NOT clip invalid values -- those are flagged separately so the
    flag and the original value both stay visible in the quality report.
    """
    if pd.isna(value):
        return np.nan
    if isinstance(value, str) and value.strip().endswith("%"):
        try:
            return float(value.strip().rstrip("%")) / 100
        except ValueError:
            return np.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def main():
    raw = pd.read_excel(RAW_PATH, sheet_name="raw_orders")
    df = raw.copy()
    flags = pd.DataFrame(index=df.index)
    flags["order_id"] = df["order_id"]

    # ----------------------------------------------------------------
    # 1. Standardize text/categorical fields (whitespace + casing)
    #    Affects: region, ship_mode, segment, category, sub_category,
    #    payment_status, order_status, state, city, customer_name
    # ----------------------------------------------------------------
    text_cols = [
        "region", "ship_mode", "segment", "category", "sub_category",
        "payment_status", "order_status", "state", "city", "customer_name",
        "product_name",
    ]
    for col in text_cols:
        df[col] = df[col].apply(clean_text)

    # ----------------------------------------------------------------
    # 2. Missing region -> "Unknown" + flag
    # ----------------------------------------------------------------
    flags["missing_region"] = df["region"].isna()
    df["region"] = df["region"].fillna("Unknown")

    # ----------------------------------------------------------------
    # 3. Missing ship_mode -> "Unknown" + flag
    # ----------------------------------------------------------------
    flags["missing_ship_mode"] = df["ship_mode"].isna()
    df["ship_mode"] = df["ship_mode"].fillna("Unknown")

    # ----------------------------------------------------------------
    # 4. Discount cleaning
    #    - Normalize percent-strings to decimals
    #    - Missing discount -> 0 ONLY if quantity, unit_price, sales,
    #      cost, profit are all present and valid; otherwise flag
    #    - Flag negative discounts (invalid)
    #    - Flag unusually high discounts (> 50%) as invalid/suspicious
    # ----------------------------------------------------------------
    df["discount_clean"] = df["discount"].apply(clean_discount)

    other_sales_fields_valid = (
        df["quantity"].notna()
        & df["unit_price"].notna()
        & df["sales"].notna()
        & df["cost"].notna()
        & df["profit"].notna()
    )

    missing_discount_mask = df["discount_clean"].isna()
    flags["missing_discount_filled_as_zero"] = missing_discount_mask & other_sales_fields_valid
    flags["missing_discount_unresolved"] = missing_discount_mask & ~other_sales_fields_valid

    df.loc[flags["missing_discount_filled_as_zero"], "discount_clean"] = 0.0

    flags["negative_discount"] = df["discount_clean"] < 0
    HIGH_DISCOUNT_THRESHOLD = 0.50
    flags["unusually_high_discount"] = df["discount_clean"] > HIGH_DISCOUNT_THRESHOLD

    df["discount_clean"] = df["discount_clean"].round(4)

    # ----------------------------------------------------------------
    # 5. Date parsing (multiple inconsistent formats in source file)
    #    and ship-before-order sequence flag
    # ----------------------------------------------------------------
    df["order_date_clean"] = df["order_date"].apply(parse_date_flex)
    df["ship_date_clean"] = df["ship_date"].apply(parse_date_flex)

    flags["unparseable_order_date"] = df["order_date_clean"].isna()
    flags["unparseable_ship_date"] = df["ship_date_clean"].isna()
    flags["ship_before_order"] = (
        df["ship_date_clean"].notna()
        & df["order_date_clean"].notna()
        & (df["ship_date_clean"] < df["order_date_clean"])
    )

    df["shipping_delay_days"] = (
        df["ship_date_clean"] - df["order_date_clean"]
    ).dt.days
    df["order_month"] = df["order_date_clean"].dt.month
    df["order_year"] = df["order_date_clean"].dt.year

    # ----------------------------------------------------------------
    # 6. Calculated sales / profit fields
    #    The raw sales/profit columns do not always reconcile with
    #    quantity * unit_price * (1-discount) or sales - cost
    #    (see cleaning_log.md). calculated_sales / calculated_profit
    #    are derived independently and used for all summaries.
    # ----------------------------------------------------------------
    df["calculated_sales"] = (
        df["quantity"] * df["unit_price"] * (1 - df["discount_clean"])
    ).round(2)
    df["calculated_profit"] = (df["calculated_sales"] - df["cost"]).round(2)

    flags["sales_mismatch_vs_reported"] = (
        (df["calculated_sales"] - df["sales"]).abs() > 0.01
    )
    flags["profit_mismatch_vs_reported"] = (
        (df["calculated_profit"] - df["profit"]).abs() > 0.01
    )

    df["profit_margin"] = np.where(
        df["calculated_sales"] != 0,
        (df["calculated_profit"] / df["calculated_sales"]).round(4),
        np.nan,
    )

    # ----------------------------------------------------------------
    # 7. order_status / payment_status normalization for filtering
    #    (after clean_text, values like "completed"/"COMPLETED" are
    #    already title-cased to "Completed")
    # ----------------------------------------------------------------
    flags["non_completed_order"] = df["order_status"] != "Completed"

    # ----------------------------------------------------------------
    # 8. Duplicate detection
    #    - Exact full-row duplicates (after cleaning) -> removed, kept once
    #    - Same order_id but conflicting field values -> flagged, both kept
    # ----------------------------------------------------------------
    compare_cols = [
        c for c in df.columns
        if c not in ("discount", "order_date", "ship_date", "data_quality_flag")
    ]
    exact_dup_mask = df.duplicated(subset=compare_cols, keep=False)
    flags["exact_duplicate_row"] = exact_dup_mask

    id_counts = df["order_id"].value_counts()
    dup_ids = id_counts[id_counts > 1].index
    conflicting_ids = []
    for oid in dup_ids:
        subset = df[df["order_id"] == oid]
        if not subset.duplicated(subset=compare_cols, keep=False).all():
            conflicting_ids.append(oid)
    flags["conflicting_duplicate_order_id"] = df["order_id"].isin(conflicting_ids)

    # ----------------------------------------------------------------
    # 9. Build overall data_quality_flag (comma-separated list of issues)
    # ----------------------------------------------------------------
    flag_cols = [c for c in flags.columns if c != "order_id"]
    def build_flag_string(row):
        issues = [c for c in flag_cols if row[c]]
        return "; ".join(issues) if issues else "OK"

    flags["data_quality_flag"] = flags.apply(build_flag_string, axis=1)
    df["data_quality_flag"] = flags["data_quality_flag"]

    # ----------------------------------------------------------------
    # 10. Assemble cleaned dataset
    #     - Drop exact duplicate rows (keep first occurrence)
    #     - Keep conflicting duplicates (both rows) but they are flagged
    #     - Keep non-completed orders in the cleaned file (they are
    #       flagged, not deleted) so the file remains a full audit trail;
    #       completed-sales summaries filter them out at the pivot stage
    # ----------------------------------------------------------------
    cleaned = df.drop(columns=["discount", "order_date", "ship_date"]).rename(
        columns={"discount_clean": "cleaned_discount"}
    )
    cleaned = cleaned.rename(
        columns={"order_date_clean": "order_date", "ship_date_clean": "ship_date"}
    )

    is_repeat_of_earlier_exact_dup = exact_dup_mask & df.duplicated(subset=compare_cols, keep="first")
    keep_mask = ~is_repeat_of_earlier_exact_dup.values
    cleaned_dedup = cleaned[keep_mask].reset_index(drop=True)

    removed_count = len(cleaned) - len(cleaned_dedup)

    # Reorder columns for readability
    col_order = [
        "order_id", "order_date", "ship_date", "shipping_delay_days",
        "order_month", "order_year",
        "customer_id", "customer_name", "segment",
        "region", "state", "city",
        "category", "sub_category", "product_name", "ship_mode",
        "quantity", "unit_price", "cleaned_discount",
        "sales", "cost", "profit",
        "calculated_sales", "calculated_profit", "profit_margin",
        "payment_status", "order_status",
        "data_quality_flag",
    ]
    cleaned_dedup = cleaned_dedup[col_order]

    with pd.ExcelWriter(CLEANED_PATH, engine="openpyxl") as writer:
        cleaned_dedup.to_excel(writer, sheet_name="cleaned_orders", index=False)
        ws = writer.sheets["cleaned_orders"]
        date_cols = {"order_date": None, "ship_date": None}
        for idx, col_name in enumerate(cleaned_dedup.columns, start=1):
            if col_name in date_cols:
                date_cols[col_name] = idx
        for col_idx in date_cols.values():
            if col_idx is None:
                continue
            col_letter = ws.cell(row=1, column=col_idx).column_letter
            for row in range(2, len(cleaned_dedup) + 2):
                ws[f"{col_letter}{row}"].number_format = "yyyy-mm-dd"

    # ----------------------------------------------------------------
    # 11. Data quality report
    #     Split into the required separate sections/sheets:
    #       - missing_value_summary
    #       - duplicate_summary
    #       - invalid_discount_summary
    #       - date_issue_summary
    #       - order_status_issue_summary
    #       - sales_profit_mismatch_summary
    #       - final_clean_vs_flagged_count
    #       - flagged_rows (row-level detail, kept for traceability)
    # ----------------------------------------------------------------
    missing_value_summary = pd.DataFrame(
        [
            ("Missing region (filled as Unknown)", int(flags["missing_region"].sum())),
            ("Missing ship_mode (filled as Unknown)", int(flags["missing_ship_mode"].sum())),
            ("Missing discount filled as 0", int(flags["missing_discount_filled_as_zero"].sum())),
            ("Missing discount unresolved (other fields also invalid)", int(flags["missing_discount_unresolved"].sum())),
        ],
        columns=["Metric", "Count"],
    )

    duplicate_summary = pd.DataFrame(
        [
            ("Total raw rows", len(raw)),
            ("Exact duplicate rows removed", removed_count),
            ("Rows remaining after dedup", len(cleaned_dedup)),
            ("Conflicting duplicate order_ids (same ID, different data)", len(conflicting_ids)),
        ],
        columns=["Metric", "Count"],
    )

    invalid_discount_summary = pd.DataFrame(
        [
            ("Negative discount values flagged", int(flags["negative_discount"].sum())),
            (f"Unusually high discount (>{int(HIGH_DISCOUNT_THRESHOLD*100)}%) flagged", int(flags["unusually_high_discount"].sum())),
            ("Discount stored as percent-string (e.g. '70%') normalized", int(df["discount"].apply(lambda v: isinstance(v, str) and v.strip().endswith("%")).sum())),
        ],
        columns=["Metric", "Count"],
    )

    date_issue_summary = pd.DataFrame(
        [
            ("Unparseable order_date", int(flags["unparseable_order_date"].sum())),
            ("Unparseable ship_date", int(flags["unparseable_ship_date"].sum())),
            ("Ship date earlier than order date (flagged)", int(flags["ship_before_order"].sum())),
        ],
        columns=["Metric", "Count"],
    )

    order_status_issue_summary = pd.DataFrame(
        [
            ("Completed orders", int((df["order_status"] == "Completed").sum())),
            ("Cancelled orders", int((df["order_status"] == "Cancelled").sum())),
            ("Returned orders", int((df["order_status"] == "Returned").sum())),
            ("Non-completed orders excluded from completed-sales KPIs", int(flags["non_completed_order"].sum())),
        ],
        columns=["Metric", "Count"],
    )

    sales_profit_mismatch_summary = pd.DataFrame(
        [
            ("Rows where reported sales != calculated_sales", int(flags["sales_mismatch_vs_reported"].sum())),
            ("Rows where reported profit != calculated_profit", int(flags["profit_mismatch_vs_reported"].sum())),
        ],
        columns=["Metric", "Count"],
    )

    total_flagged_rows = int((flags["data_quality_flag"] != "OK").sum())
    final_clean_vs_flagged_count = pd.DataFrame(
        [
            ("Total rows in cleaned_orders.xlsx", len(cleaned_dedup)),
            ("Rows with no quality flag (OK)", int((flags["data_quality_flag"] == "OK").sum())),
            ("Rows with at least one quality flag", total_flagged_rows),
        ],
        columns=["Metric", "Count"],
    )

    flagged_detail = df.loc[
        flags["data_quality_flag"] != "OK",
        ["order_id"],
    ].copy()
    flagged_detail["data_quality_flag"] = flags.loc[flagged_detail.index, "data_quality_flag"]
    flagged_detail = flagged_detail.drop_duplicates()

    with pd.ExcelWriter(QUALITY_REPORT_PATH, engine="openpyxl") as writer:
        missing_value_summary.to_excel(writer, sheet_name="missing_value_summary", index=False)
        duplicate_summary.to_excel(writer, sheet_name="duplicate_summary", index=False)
        invalid_discount_summary.to_excel(writer, sheet_name="invalid_discount_summary", index=False)
        date_issue_summary.to_excel(writer, sheet_name="date_issue_summary", index=False)
        order_status_issue_summary.to_excel(writer, sheet_name="order_status_issue_summary", index=False)
        sales_profit_mismatch_summary.to_excel(writer, sheet_name="sales_profit_mismatch_summary", index=False)
        final_clean_vs_flagged_count.to_excel(writer, sheet_name="final_clean_vs_flagged_count", index=False)
        flagged_detail.to_excel(writer, sheet_name="flagged_rows", index=False)

    # Combined summary (kept for convenience / backward compatibility with
    # earlier version of this report) is no longer written as its own
    # sheet -- each topic above now has its own clearly labeled sheet.
    summary_df = pd.concat(
        [
            missing_value_summary,
            duplicate_summary,
            invalid_discount_summary,
            date_issue_summary,
            sales_profit_mismatch_summary,
        ],
        ignore_index=True,
    )

    # ----------------------------------------------------------------
    # 12. Pivot summary for business insights
    #     Completed orders only, exact duplicates removed, UNLESS noted.
    # ----------------------------------------------------------------
    completed = cleaned_dedup[cleaned_dedup["order_status"] == "Completed"].copy()

    by_region = (
        completed.groupby("region", as_index=False)
        .agg(
            total_calculated_sales=("calculated_sales", "sum"),
            total_calculated_profit=("calculated_profit", "sum"),
            order_count=("order_id", "count"),
            avg_profit_margin=("profit_margin", "mean"),
        )
        .sort_values("total_calculated_sales", ascending=False)
    )

    by_category = (
        completed.groupby("category", as_index=False)
        .agg(
            total_calculated_sales=("calculated_sales", "sum"),
            total_calculated_profit=("calculated_profit", "sum"),
            order_count=("order_id", "count"),
            avg_profit_margin=("profit_margin", "mean"),
        )
        .sort_values("total_calculated_sales", ascending=False)
    )

    by_subcategory = (
        completed.groupby(["category", "sub_category"], as_index=False)
        .agg(
            total_calculated_sales=("calculated_sales", "sum"),
            total_calculated_profit=("calculated_profit", "sum"),
            order_count=("order_id", "count"),
            avg_profit_margin=("profit_margin", "mean"),
        )
        .sort_values("total_calculated_sales", ascending=False)
    )

    by_segment = (
        completed.groupby("segment", as_index=False)
        .agg(
            total_calculated_sales=("calculated_sales", "sum"),
            total_calculated_profit=("calculated_profit", "sum"),
            order_count=("order_id", "count"),
            avg_profit_margin=("profit_margin", "mean"),
        )
        .sort_values("total_calculated_sales", ascending=False)
    )

    by_month = (
        completed.groupby(["order_year", "order_month"], as_index=False)
        .agg(
            total_calculated_sales=("calculated_sales", "sum"),
            total_calculated_profit=("calculated_profit", "sum"),
            order_count=("order_id", "count"),
        )
        .sort_values(["order_year", "order_month"])
    )

    by_ship_mode = (
        completed.groupby("ship_mode", as_index=False)
        .agg(
            avg_shipping_delay_days=("shipping_delay_days", "mean"),
            order_count=("order_id", "count"),
        )
        .sort_values("order_count", ascending=False)
    )

    # Non-completed orders (Cancelled / Returned) by region -- this pivot
    # intentionally uses the FULL cleaned dataset (not the `completed`
    # filter above) since its entire purpose is to look at the orders
    # that were excluded from the completed-sales KPIs.
    #
    # Note on terminology: this dataset's `order_status` column only
    # takes values Completed / Cancelled / Returned -- there is no
    # "Failed" order status. "Failed" appears instead as a
    # `payment_status` value (alongside Paid / Refunded / Pending). Both
    # dimensions are covered below rather than inventing an order_status
    # value that doesn't exist in the source data.
    non_completed = cleaned_dedup[cleaned_dedup["order_status"] != "Completed"].copy()
    status_by_region = (
        non_completed.groupby(["region", "order_status"], as_index=False)
        .agg(order_count=("order_id", "count"))
        .sort_values(["region", "order_status"])
    )
    status_by_region_pivot = (
        status_by_region.pivot(index="region", columns="order_status", values="order_count")
        .fillna(0)
        .astype(int)
        .reset_index()
    )

    problem_payment_statuses = cleaned_dedup[
        cleaned_dedup["payment_status"].isin(["Refunded", "Failed", "Pending"])
    ].copy()
    payment_status_by_region = (
        problem_payment_statuses.groupby(["region", "payment_status"], as_index=False)
        .agg(order_count=("order_id", "count"))
        .sort_values(["region", "payment_status"])
    )
    payment_status_by_region_pivot = (
        payment_status_by_region.pivot(
            index="region", columns="payment_status", values="order_count"
        )
        .fillna(0)
        .astype(int)
        .reset_index()
    )

    with pd.ExcelWriter(PIVOT_PATH, engine="openpyxl") as writer:
        by_region.to_excel(writer, sheet_name="sales_by_region", index=False)
        by_category.to_excel(writer, sheet_name="sales_by_category", index=False)
        by_subcategory.to_excel(writer, sheet_name="sales_by_subcategory", index=False)
        by_segment.to_excel(writer, sheet_name="profit_margin_by_segment", index=False)
        by_month.to_excel(writer, sheet_name="sales_by_month", index=False)
        by_ship_mode.to_excel(writer, sheet_name="shipping_by_mode", index=False)
        status_by_region_pivot.to_excel(writer, sheet_name="order_status_by_region", index=False)
        status_by_region.to_excel(writer, sheet_name="order_status_by_region_long", index=False)
        payment_status_by_region_pivot.to_excel(
            writer, sheet_name="payment_status_by_region", index=False
        )

    print("Done.")
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
