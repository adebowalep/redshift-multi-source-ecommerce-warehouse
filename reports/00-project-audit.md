> **HISTORICAL DOCUMENT (written 2026-11-12, before and during the build).** It records what the original Udacity starter files looked like and
> the defects found in them. Statements such as "NOT IMPLEMENTED", "NOT VERIFIED" and the environment notes describe that moment, not the
> current repository. For the current state see `README.md`, `reports/warehouse_report.md` and `reports/01-engineering-audit.md`.

# Project Audit — Unified Commerce Data Warehouse

Audit date: 2026-11-12. Nothing in the starter files has been modified yet.

## Files found

| Item | Location | Status |
|---|---|---|
| `starter.ipynb` (47 cells; the original course starter, since replaced by the revised notebook of the same name, see `evidence/`) | project root (identical to `~/Downloads/starter.ipynb`) | Present, unmodified (at audit time) |
| `project-ddl-long.md` | project root (identical to Downloads copy) | Present, unmodified |
| `project-mermaid-diagram.md` | project root | Present, unmodified |
| `data/*.csv` (3 files) | project root, identical in `selected_folders_backup (3).zip` | Present, readable |

Note: the project folder name ends with a trailing space. Quote the path in shell commands.

## Source data (actual, profiled with pandas)

| File | Rows | Cols | Unique key | Full-row duplicates | Columns with NULLs |
|---|---:|---:|---|---:|---|
| ecom_orders_postgres.csv | 2,500 | 26 | order_id (2,500 unique) | 0 | campaign (409) |
| ecom_events_cassandra.csv | 2,500 | 24 | event_id (2,500 unique) | 0 | state (2,210), payment_outcome (2,127), product_id (1,118), category (1,118) |
| ecom_graph_edges_neo4j.csv | 2,500 | 23 | edge_id (2,500 unique) | 0 | order_id (1,527), region (652), campaign (352) |

Row counts match the brief. No negative amounts, no ship-before-order dates, no padded strings.
Date range for all three sources: 2024-01-01 to 2025-06-29.

### Findings that shape the design

1. **Customer overlap between sources is tiny.** Distinct customers: orders 2,460, events 2,461, graph 2,340, union 7,057. Orders∩events = 72, orders∩graph = 72, events∩graph = 62. A conformed `dim_customer` is correct, but cross-source "customer behaviour" queries (orders joined to events) will only cover about 72 customers. Report this honestly and do not claim full-funnel attribution.
2. **Graph node semantics.** Edge shapes: Customer→Product (PURCHASED 469, VIEWED 830, ADDED_TO_CART 441, RETURNS 111), Customer→Customer (REFERRED_FRIEND 256), Product→Product (ALSO_BOUGHT_WITH 393). `from_node_id`/`to_node_id` must be routed to customer or product surrogate keys by `*_node_type`. For Customer→Product edges `product_id` equals `to_node_id`, and for Product→Product edges it equals `from_node_id` (verified, 0 mismatches).
3. **Edge `order_id`.** 973 edges carry an order_id; all of them exist in the orders file (0 orphans). 796 distinct orders are referenced.
4. **Product IDs.** Events reference 1,276 products, edges 2,175, with 344 in common. `dim_product` must be the union.
5. **Categorical values are already clean and consistent** (10 categories identical across the three sources, 5 channels, 6 campaigns, 2 A/B variants, 6 referrers). Cleaning work is therefore NULL handling and type conversion rather than heavy recoding. `promo_code` uses the literal string `NONE` for no promo, which is a legitimate value, not a missing one.
6. **Max string lengths fit the staging VARCHARs** (e.g. referrer 14 of 32, event_type 16 of 32). Numeric ranges fit the DECIMAL precisions (tax_rate max 0.096, fraud_score max 0.694, unit_price max 992.28).

## Task status

| Project Task | Existing Status | Problems Found | Required Action |
|---|---|---|---|
| 1 Data exploration | PARTIALLY IMPLEMENTED (shapes printed; every deeper TODO empty) | No profiling, no key/FK analysis, no field mapping | Implement profiling cells; write field mapping |
| 2 Schema design | PARTIALLY IMPLEMENTED (DDL complete on paper, never run) | Issues D1–D8 below; cells 18–19 are TODO | Fix DDL, document, render diagram |
| 3 Extraction | NOT IMPLEMENTED (all 9 source functions are `pass`) | Cell 26 prints "All source systems loaded!" with nothing loaded; cell 28 prints "Task 3 Complete" with all code commented out | Implement all; add real checks |
| 3 Transformation | NOT IMPLEMENTED | `trim_df` turns NaN to the string `'nan'` then back, which is correct, but it casts non-strings; no type coercion exists | Implement typed conforming to COLSPECs |
| 4 Redshift loading | NOT IMPLEMENTED | `rs_exec`/`rs_batch_insert` are `pass`; cells 33–39 are comments; cell 35, 37, 39 print false success messages | Implement everything |
| 5 Optimization | NOT IMPLEMENTED | No MV or ANALYZE actually runs, yet "Task 5 Complete" prints | Implement, measure |
| 6 Validation and reporting | NOT IMPLEMENTED | Report template is placeholders; prints "ALL TASKS COMPLETED" | Implement checks, queries, report |
| Setup cell 5 | DEFECT | Hard-codes placeholder AWS creds into `os.environ`, overwriting any real ones | Replace with env-based config |

## DDL / schema defects found

| # | Defect | Impact | Planned fix |
|---|---|---|---|
| D1 | `dim_customer` is `DISTKEY(customer_id)` but facts are `DISTKEY(customer_sk)`; `fact_graph_edges` is `DISTKEY(to_product_sk)` but `dim_product` is `DISTKEY(product_id)`. | The documented "collocated joins" are false. The join column is `*_sk` on both sides, so dimension and fact rows land on different slices. | `DISTKEY(customer_sk)` on `dim_customer` and `DISTKEY(product_sk)` on `dim_product` so fact.sk = dim.sk joins are colocated. Keep sort keys. |
| D2 | `DROP TABLE dw.dim_customer` / `dim_product` fail on rerun because `v_lookup_*` views depend on them. | DDL not re-runnable | Add `CASCADE` (or drop the views first). Scope is only the `stg`/`dw` schemas. |
| D3 | `fact_events` has `channel_sk`, but the events CSV has no channel field. | Column would always be NULL and misleads readers. | Drop `channel_sk` from `fact_events` and the diagram (no source field). |
| D4 | `stg.edges_raw` has a column named `timestamp`. | Type-name collision, possible quoting issues in Redshift | Quote as `"timestamp"` in all SQL; verify on Redshift. |
| D5 | Notebook hints rewrite `stg.`→`public.stg_` while the DDL and the brief use `stg`/`dw`. | Mixed naming would break every later query | Use `stg` and `dw` throughout. Fall back to a complete `public.` mapping only if `CREATE SCHEMA` is refused. |
| D6 | The Mermaid diagram uses `dw_dim_shipmethod` / `dw_dim_paymethod` while the DDL has `dim_shipping_method` / `dim_payment_method`, and it still has `fact_events.channel_sk`. | Diagram does not match the DDL (a rubric criterion) | Regenerate diagram from the final DDL, render to PNG/SVG. |
| D7 | The file has no materialized view and no unknown-member rows. | Needed for Task 5; fact lookups would otherwise yield NULL keys silently. | Add MV in Task 5. Insert an "Unknown" member (sk = -1 style via explicit rows) or document NULL-key policy. |
| D8 | `ENCODE zstd` on sort-key leading columns and on BOOLEAN; Redshift generally recommends RAW on the leading sort column. Redshift `PRIMARY KEY`/FK are informational, not enforced. | Possible performance cost; no integrity guarantee | Set leading sort key columns to RAW; add explicit integrity checks. Confirm the DDL executes on the real cluster. |

SCD2: `effective_from/effective_to/is_current` exist but nothing implements change tracking. The final report will say "SCD-Type-2 ready, loaded as a single current version per natural key" and will not claim full Type 2.

## Environment

| Need | State |
|---|---|
| pandas 2.2.3, numpy 1.26.4, SQLAlchemy 2.0.40, tqdm, jupyter/nbconvert | Installed |
| psycopg2-binary, cassandra-driver, neo4j, boto3 | **Not installed** |
| PostgreSQL | A local server is listening on 5432, but the role `temp` from the notebook does not exist. It is the user's own instance, so I have not used it. |
| Cassandra (9042), Neo4j (7687) | **Not running** |
| Docker | CLI present, **daemon not running** |
| AWS / Redshift | **No AWS_* or REDSHIFT_* variables set.** A `~/.aws` folder exists; I have not read or used it. It is presumably a personal account, not the Udacity lab. |

## Blockers for a fully verified submission

1. **Redshift evidence cannot be produced from this machine** without the Udacity lab credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`) plus `REDSHIFT_WORKGROUP`, `REDSHIFT_DATABASE`, `REDSHIFT_SECRET_ARN`. Until they exist, Tasks 4–6 on Redshift stay NOT VERIFIED.
2. **Source databases.** The Udacity workspace supplies PostgreSQL, Cassandra and Neo4j. Locally they would need to be started (Docker) or run in the workspace.

## Status after the build session (same day)

Decision taken with the project owner: build and test here, run the notebook in the Udacity workspace (where PostgreSQL, Cassandra, Neo4j and the Redshift lab credentials live).

| Project Task | Status now |
|---|---|
| 1 Data exploration, field mapping | COMPLETE AND VERIFIED (executed on the real CSVs) |
| 2 Schema design, DDL, diagram | COMPLETE AND VERIFIED offline (DDL corrected D1–D4, D8; diagram generated from DDL); Redshift acceptance of the DDL NOT VERIFIED |
| 3 Extraction | COMPLETE AND VERIFIED against local PostgreSQL 17, Cassandra 4.1 and Neo4j 5 (workspace run still pending) |
| 3 Transformation | COMPLETE AND VERIFIED (real data, pandas 2.2.3 and 3.x) |
| 4 Redshift loading | IMPLEMENTED BUT NOT VERIFIED on Redshift (logic verified on a PostgreSQL emulation) |
| 5 Optimization | IMPLEMENTED BUT NOT VERIFIED on Redshift |
| 6 Validation and reporting | IMPLEMENTED BUT NOT VERIFIED on Redshift; report is generated by the last notebook cell |

See `rubric-checklist.md` for the criterion-level view.
