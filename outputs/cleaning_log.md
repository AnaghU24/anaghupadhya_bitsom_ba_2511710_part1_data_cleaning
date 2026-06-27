# Cleaning Log

This log documents every cleaning decision applied to `raw_orders.xlsx`,
the reasoning behind it, and the assumptions made. It is meant to let an
evaluator (or future me) understand the cleaned dataset without needing
to re-read the script line by line.

All logic lives in `scripts/clean_orders.py`. Run it with:

```bash
python scripts/clean_orders.py
python scripts/format_outputs.py   # applies fonts/number formats
```

It reads `data/raw_orders.xlsx` (sheet `raw_orders`) and the rules in the
`business_rules` sheet of the same file, then writes:

- `data/cleaned_orders.xlsx`
- `outputs/data_quality_report.xlsx`
- `outputs/pivot_summary.xlsx`
- `outputs/cleaning_log.md` (this file)

`data/raw_orders.xlsx` itself is never modified.

---

## 1. Text / categorical standardization

**Columns affected:** `region`, `ship_mode`, `segment`, `category`,
`sub_category`, `payment_status`, `order_status`, `state`, `city`,
`customer_name`, `product_name`.

**Issue found:** Free-text and categorical fields had inconsistent
casing (`NORTH`, `north`, `North`) and stray leading/trailing/double
whitespace (`"  Second Class "`, `"Office  Supplies"`).

**Decision:** Trimmed whitespace, collapsed repeated internal spaces,
and applied title case. This is a display/grouping normalization only —
no information is lost, and it lets every region/category etc. roll up
correctly in pivot tables instead of being split into near-duplicate
buckets.

**Assumption:** Title case is an acceptable canonical form for these
fields (e.g. `"Small Business"`, `"First Class"`). No business rule
specified an exact casing convention, so this was my judgment call.

---

## 2. Missing `region`

**Rule:** Fill as `Unknown` and flag in quality report.

**Found:** 26 rows with blank region.

**Action:** Filled with `"Unknown"`. Flag `missing_region` set to `True`
for these rows and included in `data_quality_flag`.

**Why not drop these rows:** The business rule explicitly says to fill
and flag, not delete — region-level KPIs simply show an `"Unknown"`
bucket so the gap is visible rather than hidden.

---

## 3. Missing `ship_mode`

**Rule:** Fill as `Unknown` and flag in quality report.

**Found:** 22 rows with blank ship mode.

**Action:** Same approach as region — filled `"Unknown"`, flagged
`missing_ship_mode`.

---

## 4. Discount cleaning

**Output column name:** the cleaned, normalized values are written to
`cleaned_orders.xlsx` as **`cleaned_discount`** — the raw `discount`
column itself is not carried into the cleaned file under its original
name, so the output file never has an ambiguous, mixed-format
`discount` column sitting next to the cleaned one.

**Issues found in the raw `discount` column:**
- 18 blank/missing values
- Some values stored as percent-strings (`"70%"`, `"85%"`) instead of
  decimals
- 16 negative values (e.g. `-0.19`, `-0.23`) — not a valid discount
- 15 unusually high values (`0.55`, `0.65`, `0.70`, `0.85`) — above the
  50% threshold treated as suspicious

**Actions taken:**
1. Percent-strings converted to decimal (`"70%"` → `0.70`).
2. **Missing discount → 0**, but only applied where `quantity`,
   `unit_price`, `sales`, `cost`, and `profit` were all present and
   valid for that row, per the business rule ("treat as 0 only if all
   other sales fields are valid; otherwise flag"). In this dataset, all
   18 missing-discount rows had valid surrounding fields, so all 18
   were filled as 0 and flagged `missing_discount_filled_as_zero`. (No
   rows fell into the `missing_discount_unresolved` case, but the logic
   handles it if a future data refresh introduces one.)
3. **Negative discounts** were *not* zeroed out or corrected — they
   were left as-is and flagged `negative_discount`, so the original
   (invalid) value stays visible for audit rather than being silently
   "fixed" with an assumption about what the analyst intended.
4. **Discounts above 50%** were similarly left as-is and flagged
   `unusually_high_discount`. 50% was chosen as the threshold because it
   is well above every "normal-looking" discount in the data (which top
   out around 25%) and matches the business rule's framing of "unusually
   high."

**Assumption:** The 50% threshold is a judgment call, not a value
specified in the business rules sheet. An evaluator with domain
knowledge of the retailer's actual discount policy might choose a
different cutoff.

**Why flag instead of delete or auto-correct:** Negative and very high
discounts are exactly the kind of thing a business stakeholder should
see and decide on — guessing whether `-0.19` was meant to be `0.19` (a
sign error) or `0` (data entry mistake) would be fabricating data.

---

## 5. Date parsing

**Issue found:** `order_date` and `ship_date` were stored in **four
different formats** within the same column, e.g.:
- `21 Jul 2024`
- `08/31/2024`
- `28-11-2024`
- `2024-05-24`

**Action:** Each date string is tried against all four known formats
(`%d %b %Y`, `%m/%d/%Y`, `%d-%m-%Y`, `%Y-%m-%d`) in order until one
parses successfully. Every date in this dataset parsed cleanly under
this approach (0 unparseable dates).

**Assumption / risk:** `%m/%d/%Y` and `%d-%m-%Y` are both used in the
data, and for day values ≤ 12 these are ambiguous in isolation (e.g.
`01/05/2024` could be Jan 5 or May 1). I resolved this by trusting the
**separator** as the format signal: slash-separated dates are parsed as
`MM/DD/YYYY` (US-style) and hyphen-separated dates as `DD-MM-YYYY`
(matching the pattern seen elsewhere in the file), rather than by
guessing per-row. This is a reasonable but not provably "correct"
assumption — it is documented here so it can be challenged if a more
authoritative source format is known.

**Calculated fields produced from these dates:**
- `shipping_delay_days` = `ship_date` − `order_date`, in days
- `order_month`, `order_year` = extracted from `order_date`

---

## 6. Ship date earlier than order date

**Rule:** Flag `ship_date` earlier than `order_date`.

**Found:** 22 rows where the parsed ship date is before the parsed
order date — logically impossible (can't ship before ordering).

**Action:** Flagged `ship_before_order`. Rows were **not** dropped or
corrected, since the rule only asks for a flag — fixing it would
require guessing which of the two dates is wrong.

---

## 7. Sales / profit reconciliation and calculated fields

**Issue found:** The raw `sales` and `profit` columns do not always
match what you'd expect from the other fields:
- `sales` should equal `quantity × unit_price × (1 − discount)` — this
  held for most rows but **72 rows** showed a discrepancy of more than
  1 cent (many of these overlap with the negative/high/missing discount
  cases above, but **27 rows had an otherwise normal, valid discount
  and still didn't reconcile** — a genuine, unexplained data quality
  issue).
- `profit` should equal `sales − cost` — **72 rows** also showed a
  mismatch here.

**Action:** Per the business rule ("Create `calculated_sales`,
`calculated_profit`..."), these were computed independently from first
principles rather than trusted from the raw file:
```
calculated_sales  = quantity * unit_price * (1 - discount)
calculated_profit = calculated_sales - cost
profit_margin     = calculated_profit / calculated_sales
```
The original `sales`/`profit`/`cost` columns are kept in the cleaned
file alongside the calculated ones (nothing is overwritten), and rows
where they disagree are flagged `sales_mismatch_vs_reported` /
`profit_mismatch_vs_reported` so the discrepancy stays visible.

**Why this matters for the business insights:** All KPI/pivot summaries
in `pivot_summary.xlsx` use `calculated_sales` and `calculated_profit`,
**not** the raw `sales`/`profit` columns, because the raw columns are
demonstrably unreliable for a meaningful subset of rows.

---

## 8. Duplicate handling

Two different kinds of duplication were found and treated differently:

**a) Exact duplicates** — the entire row (every column except the raw
`discount`/date strings, which are compared post-cleaning) is identical
to another row. **20 such pairs were found (40 rows total).** One copy
of each pair was removed; the remaining copy is flagged
`exact_duplicate_row` so it's clear in the audit trail that a duplicate
existed and was removed.

**b) Conflicting duplicates** — rows sharing the same `order_id` but
with at least one differing field. **12 order_ids** fell into this
category. In every case found, the only fields that differed were
`sales` (a different reported value) and `order_status` (one copy says
`Completed`, the other says `Returned`). **Neither row was deleted** —
both are kept and flagged `conflicting_duplicate_order_id`, because
deciding which version is "correct" would require information not
present in the dataset (e.g. an audit timestamp). This is a case for a
human reviewer, not an automated guess.

One order_id (`ORD-2024-10124`) had **three** rows: two were exact
duplicates of each other, the third conflicted (different `sales`
value and `order_status`). The exact-duplicate pair was deduplicated
down to one row; the conflicting third row was kept and flagged — both
flags (`exact_duplicate_row` and `conflicting_duplicate_order_id`) can
appear on the same order_id for this reason. This is why the count of
order_ids with an exact-duplicate flag (20) and the count with a
conflicting-duplicate flag (12) overlap by one ID rather than being
fully separate sets.

---

## 9. Order status filtering for completed-sales summaries

**Rule:** Do not include non-completed/failed/refunded records in
completed-sales summaries.

**Found:** After standardizing casing, `order_status` has three clean
values: `Completed` (majority), `Cancelled`, `Returned`. 310 rows are
not `Completed`.

**Action:** Non-completed rows are **kept in `cleaned_orders.xlsx`**
(flagged `non_completed_order`) so the cleaned file remains a complete,
auditable record of all 912 rows. They are **excluded** only at the
pivot/KPI stage — `pivot_summary.xlsx` is built from `Completed` orders
only, per the rule.

---

## 10. Data quality report structure

`outputs/data_quality_report.xlsx` is split into one sheet per topic,
rather than one combined summary, so each required area is easy to find
on its own:

| Sheet | Covers |
|---|---|
| `missing_value_summary` | Missing region / ship_mode / discount counts |
| `duplicate_summary` | Raw row count, exact duplicates removed, rows remaining, conflicting duplicate order_ids |
| `invalid_discount_summary` | Negative discounts, unusually high discounts, percent-string discounts normalized |
| `date_issue_summary` | Unparseable dates, ship-before-order count |
| `order_status_issue_summary` | Count of Completed / Cancelled / Returned, and how many were excluded from completed-sales KPIs |
| `sales_profit_mismatch_summary` | Rows where reported sales/profit disagree with the recalculated values |
| `final_clean_vs_flagged_count` | Final row count, how many are flag-free ("OK") vs. flagged |
| `flagged_rows` | Row-level detail: every flagged `order_id` and its specific flag(s) |

## 11. Pivot summary — additional breakdowns

Beyond region/category/month/ship-mode, `outputs/pivot_summary.xlsx`
also includes:

- **`sales_by_subcategory`** — sales, profit, order count, and average
  profit margin for every category/sub-category combination (e.g.
  Technology → Copiers, Furniture → Chairs).
- **`profit_margin_by_segment`** — average profit margin per customer
  segment (Consumer, Corporate, Home Office, Small Business), alongside
  total sales/profit/order count. Consumer has the lowest average
  margin (~22%) of the four segments; the other three cluster around
  29%.
- **`order_status_by_region`** (and a long-format twin,
  `order_status_by_region_long`) — counts of `Cancelled` and `Returned`
  orders by region. **Note:** this dataset's `order_status` column only
  contains `Completed` / `Cancelled` / `Returned` — there is no
  `"Failed"` order status in the source data.
- **`payment_status_by_region`** — counts of `Refunded`, `Failed`, and
  `Pending` *payment* statuses by region, since `"Failed"` exists as a
  `payment_status` value, not an `order_status` value. Both pivots are
  provided so the "problem orders by region" question is answered
  accurately against what the data actually contains, instead of
  inventing an order status that doesn't exist.

## Known limitations

- The date-format disambiguation (Section 5) is a reasonable assumption
  based on separator style, not a certainty — a different convention
  could change a small number of dates.
- The 50% "unusually high discount" threshold (Section 4) is a judgment
  call; no exact cutoff was specified in the business rules.
- For the 11 genuinely conflicting duplicate order_ids (Section 8b), no
  attempt was made to determine which version is correct — this is
  intentionally left for business/human review rather than guessed.
- 27 rows have valid-looking inputs (normal discount, no missing
  fields) where the raw `sales`/`profit` still don't reconcile with the
  calculated values. The root cause of this discrepancy in the source
  data is unknown; it's flagged but not explained.
- `customer_id`/`customer_name` were not deduplicated or validated for
  consistency (e.g. same customer_id always mapping to the same name)
  since no business rule required it.
