# Part 1 — Data Cleaning: Retail Orders Dataset

**Repository name:** `anaghupadhya_bitsom_ba_2511710_part1_data_cleaning`

## Business Problem Summary

The company's order-level sales data (`raw_orders.xlsx`) was collected
from multiple sources and contains the kinds of issues real
transactional data usually has: inconsistent text casing, missing
values, invalid discounts, mixed date formats, duplicate records, and
sales/profit figures that don't always reconcile with the underlying
quantity/price/discount/cost data. Before this data can be trusted for
KPI reporting or experimentation (Parts 2–4 of this assignment), it
needs to be cleaned, validated, and documented so that every number in
a future dashboard can be traced back to a defensible decision.

This part of the assignment cleans the raw dataset, flags every
quality issue found (rather than silently fixing or hiding them), and
produces a reconciled set of calculated fields (`calculated_sales`,
`calculated_profit`, `profit_margin`, etc.) suitable for downstream
analysis.

## Dataset Used

- `data/raw_orders.xlsx` — provided raw dataset, **932 rows**, 21
  columns (order/ship dates, customer, segment, region, location,
  product category, ship mode, quantity, unit price, discount, sales,
  cost, profit, payment status, order status). This file is never
  modified.
- The same workbook includes a `business_rules` sheet, which contains
  the specific cleaning rules this repo implements (missing-value
  handling, duplicate handling, flagging logic, required calculated
  fields).

## Tools Used

- Python 3 (pandas, openpyxl) for all cleaning, calculation, and
  reporting logic
- LibreOffice (headless) to render the screenshots in this repo

The Python scripts in `scripts/` aren't a strict assignment
requirement, but are included to make every output in `data/` and
`outputs/` fully reproducible from the raw file — re-run them any time
with the commands below.

## Steps Performed

1. **Explored** the raw data to find every quality issue: inconsistent
   text casing/whitespace in categorical fields, 4 different date
   formats, missing `region`/`ship_mode`/`discount` values, negative
   and unusually high discounts, percent-string discounts (`"70%"`),
   exact duplicate rows, order_ids with conflicting data, and rows
   where the reported `sales`/`profit` don't match what the other
   columns imply.
2. **Standardized** text fields (trim/whitespace/casing) so categories
   roll up correctly in summaries.
3. **Filled and flagged** missing `region` and `ship_mode` as
   `"Unknown"`.
4. **Cleaned and flagged** the `discount` column: converted
   percent-strings to decimals, filled missing discounts with 0 only
   where every other sales-related field was valid, and flagged (but
   did not alter) negative or unusually high (>50%) discounts. The
   cleaned result is written to `cleaned_orders.xlsx` as
   **`cleaned_discount`** (the raw `discount` column is not carried
   into the output file under its original name).
5. **Parsed dates** across 4 different source formats into a single
   consistent date type, and flagged the 22 rows where `ship_date` was
   before `order_date`.
6. **Recalculated** `calculated_sales`, `calculated_profit`, and
   `profit_margin` independently from `quantity`, `unit_price`,
   `discount`, and `cost` — because the raw `sales`/`profit` columns
   don't always reconcile with these (72 rows mismatch) — and flagged
   every row where the raw and recalculated values disagree.
7. **De-duplicated**: removed 20 exact full-row duplicate pairs, and
   separately flagged 12 order_ids that share an ID but have genuinely
   conflicting data (kept, not deleted, since the correct version can't
   be determined from the data alone).
8. **Filtered** non-completed orders (`Cancelled`, `Returned`) out of
   the completed-sales KPI pivots, while keeping them (flagged) in the
   full cleaned dataset for audit purposes.
9. **Built KPI pivots**, including the assignment-required breakdowns
   by sub-category, profit margin by segment, and non-completed/problem
   orders by region (see Key Outputs below).
10. **Documented** every decision and assumption in
    `outputs/cleaning_log.md`.

Full step-by-step logic is in `scripts/clean_orders.py`, runnable end
to end with:
```bash
pip install pandas openpyxl
python scripts/clean_orders.py
python scripts/format_outputs.py
```

## Key Outputs

| File | Description |
|---|---|
| `data/raw_orders.xlsx` | Original, untouched source file |
| `data/cleaned_orders.xlsx` | 912 rows, all standardized. The raw `discount` column is replaced with `cleaned_discount` (percent-strings normalized to decimals; invalid values flagged, not deleted — see Discount Cleaning below). `calculated_sales`, `calculated_profit`, `profit_margin`, `shipping_delay_days`, `order_month`, `order_year`, and `data_quality_flag` columns are added |
| `outputs/data_quality_report.xlsx` | Issue counts broken out into separate sheets by topic (see below), plus a row-level list of every flagged `order_id` and why |
| `outputs/pivot_summary.xlsx` | KPI pivot tables for business insights (see below) |
| `outputs/cleaning_log.md` | Full write-up of every cleaning decision and the reasoning/assumptions behind it |

**`outputs/data_quality_report.xlsx` sheets:**

| Sheet | Covers |
|---|---|
| `missing_value_summary` | Missing region / ship_mode / discount |
| `duplicate_summary` | Raw rows, exact duplicates removed, rows remaining, conflicting duplicate order_ids |
| `invalid_discount_summary` | Negative / unusually high / percent-string discounts |
| `date_issue_summary` | Unparseable dates, ship-before-order count |
| `order_status_issue_summary` | Completed / Cancelled / Returned counts |
| `sales_profit_mismatch_summary` | Reported vs. recalculated sales/profit mismatches |
| `final_clean_vs_flagged_count` | Final row count, flag-free vs. flagged |
| `flagged_rows` | Row-level detail: every flagged `order_id` and its flag(s) |

**`outputs/pivot_summary.xlsx` sheets:**

| Sheet | Covers |
|---|---|
| `sales_by_region` | Sales, profit, order count, avg margin by region |
| `sales_by_category` | Same, by category |
| `sales_by_subcategory` | Same, by category + sub-category |
| `profit_margin_by_segment` | Sales, profit, order count, **avg profit margin** by customer segment |
| `sales_by_month` | Sales, profit, order count by year/month |
| `shipping_by_mode` | Avg shipping delay and order count by ship mode |
| `order_status_by_region` | Cancelled/Returned counts by region (pivoted) |
| `order_status_by_region_long` | Same, in long format |
| `payment_status_by_region` | Refunded/Failed/Pending **payment** status counts by region (see note below) |

> **Note on "Failed orders by region":** this dataset's `order_status`
> column only contains `Completed` / `Cancelled` / `Returned` — there
> is no `"Failed"` order status anywhere in the source data. `"Failed"`
> exists as a `payment_status` value instead (alongside `Paid`,
> `Refunded`, `Pending`). Rather than fabricate an order status that
> isn't in the data, both `order_status_by_region` (Cancelled/Returned)
> and `payment_status_by_region` (Refunded/Failed/Pending) are provided
> so the "problem orders by region" question is answered accurately.

## Business Insights

- **Technology** is the top category by total sales (~$2.16M) but has
  the **lowest** average profit margin (23.4%) of the three categories
  — Furniture and Office Supplies are both more profitable per dollar
  of sales (~29–30%), even though they sell less in absolute terms.
  Within Technology, **Machines** (15.2% margin) and **Phones** (19.9%)
  drag the category average down the most at the sub-category level.
- **South and West regions** lead in total sales, but **West has the
  highest profit margin (30.2%)** among the four known regions —
  worth a closer look at why South sells more but converts less of it
  to profit.
- **Consumer is the lowest-margin segment** (22.0% average profit
  margin) versus ~29% for Small Business, Home Office, and Corporate —
  despite Consumer not being the smallest segment by sales, it
  converts noticeably less of each sale into profit.
- Orders missing a region code (~2% of completed orders, now bucketed
  as `Unknown`) actually carry the **highest average profit margin**
  in the whole dataset (33.8%) — small sample size (19 orders), but
  worth investigating whether this is a specific sales channel that
  isn't being region-tagged correctly upstream.
- **310 of 912 rows (~34%) are not `Completed`** (cancelled or
  returned) — that's a large enough share that completed-sales KPIs
  meaningfully overstate the picture if non-completed rows aren't
  excluded, which is why the pivot summary filters them out. North has
  the most cancellations (48) while East has the most returns (45).
- **72 rows (~8%) have a reported `sales` or `profit` figure that
  doesn't reconcile** with quantity/price/discount/cost — this is a
  data-pipeline issue worth raising with whoever owns the source system,
  since it affects roughly 1 in 12 orders.

## Assumptions Made

- Title case was chosen as the canonical form for categorical text
  fields (no convention was specified).
- A discount above 50% was treated as "unusually high" per the
  business rule's wording — this exact threshold was my judgment call.
- Ambiguous numeric date formats (`MM/DD/YYYY` vs `DD/MM/YYYY`-style)
  were disambiguated by separator character (`/` → US-style,
  `-` → day-first), based on the patterns observed in the file, not a
  stated rule.
- Negative/invalid discounts were flagged, not corrected — I did not
  assume what the "real" intended value was.
- "Failed orders by region" was interpreted using `payment_status`
  (the only column where `"Failed"` actually appears), in addition to
  an `order_status`-by-region pivot for Cancelled/Returned, rather than
  guessing which field the requirement meant.

See `outputs/cleaning_log.md` for full detail on each of these,
including the exact row counts affected.

## Known Limitations

- For the 11 order_ids with genuinely conflicting duplicate data (plus
  one ID with both an exact-duplicate pair and a conflicting third
  row), this repo does **not** decide which record is correct — both
  are retained and flagged for a human reviewer, since nothing in the
  data indicates which is authoritative.
- 27 rows have otherwise-valid inputs but still show a sales/profit
  mismatch with no identifiable cause in the available columns.
- Date disambiguation (see Assumptions) could be wrong for a small
  number of rows if the source system's date convention differs from
  what was inferred here.
- `customer_id`/`customer_name` were not deduplicated or validated for
  consistency (e.g. same customer_id always mapping to the same name)
  since no business rule required it.

## Screenshots

All screenshots are in `screenshots/`:

| File | Shows |
|---|---|
| `raw_data_preview.png` | Sample of the **raw** dataset before cleaning — visible mixed date formats, blank region/ship_mode cells, percent-string discounts |
| `cleaned_data_preview.png` | The **same rows**, after cleaning — standardized dates, filled "Unknown" values, decimal discounts, calculated fields, and quality flags |
| `pivot_summary_1.png` | KPI pivot — sales/profit by sub-category |
| `pivot_summary_2.png` | KPI pivot — profit margin by customer segment |
| `01_cleaned_orders_sample.png` | Additional sample of `cleaned_orders.xlsx` |
| `02_data_quality_report_summary.png` | Final clean-vs-flagged row counts from `data_quality_report.xlsx` |
| `03_pivot_sales_by_region.png` | KPI pivot — sales/profit by region |
| `04_pivot_sales_by_category.png` | KPI pivot — sales/profit by category |
| `05_conflicting_duplicates_evidence.png` | Side-by-side evidence of conflicting duplicate order_ids and how they were flagged |
| `06_order_status_by_region.png` | Cancelled/Returned order counts by region |

## Repository Structure

```
.
├── README.md
├── data/
│   ├── raw_orders.xlsx
│   └── cleaned_orders.xlsx
├── outputs/
│   ├── data_quality_report.xlsx
│   ├── pivot_summary.xlsx
│   └── cleaning_log.md
├── scripts/
│   ├── clean_orders.py
│   └── format_outputs.py
└── screenshots/
    ├── raw_data_preview.png
    ├── cleaned_data_preview.png
    ├── pivot_summary_1.png
    ├── pivot_summary_2.png
    ├── 01_cleaned_orders_sample.png
    ├── 02_data_quality_report_summary.png
    ├── 03_pivot_sales_by_region.png
    ├── 04_pivot_sales_by_category.png
    ├── 05_conflicting_duplicates_evidence.png
    └── 06_order_status_by_region.png
```
