> **HISTORICAL DOCUMENT (Udacity rubric self-review, 2026-11-12).** The evidence names below (`starter (1).ipynb`, `starter (4).ipynb`) are the
> workspace notebooks of earlier runs. Two notebooks are committed in this repository, and neither is one of those files:
> `evidence/starter.executed-2026-11-12.ipynb` is the **executed notebook of the final recorded Redshift run** (all saved outputs; its report is
> `reports/warehouse_report.md`), and `starter.ipynb` is the **later, revised implementation** (safe re-runs, corrections, deterministic
> dimension selection), committed **without outputs** and not yet run on Redshift. The assessments below describe the recorded run only.
>
> **Known inconsistency between runs (kept, not rewritten):** this checklist and the screenshots quote the materialized-view speed-up of
> earlier runs (1.10x here, 1.15x in `screenshots/05b_performance_explain_plans.png`). The final recorded run, saved in `evidence/starter.executed-2026-11-12.ipynb` and
> `reports/warehouse_report.md`, measured **1.14x**. All three are the same experiment repeated on 2,500 rows, i.e. run-to-run noise.

# Independent rubric review (reviewer mode)

Basis: a complete notebook run in the Udacity workspace against real PostgreSQL, Cassandra, Neo4j and Redshift (saved as `starter (1).ipynb`, all cells executed, no errors).
PASS = evidence exists in the saved outputs. Items marked **TO DO** are submission chores, not code.

## A. Data exploration and schema design
| Criterion | Status | Evidence |
|---|---|---|
| Field mapping table (PostgreSQL, Cassandra, Neo4j -> fact/dimension) | PASS | notebook Task 1 output (73 rows, every source column mapped); `reports/field-mapping.md` |
| Key fields, relationships, ID standardization documented | PASS | Task 1 cells and ID-conformance text |
| Redshift DDL with surrogate keys, DISTKEY, SORTKEY, encodings | PASS | executed on Redshift (39 statements); catalog check shows keys equal the DDL |
| Schema diagram matches the DDL | PASS | programmatic diagram-vs-DDL check; `reports/schema-diagram.svg` (**TO DO**: upload to workspace so the image renders) |

## B. Extraction and transformation
| Criterion | Status | Evidence |
|---|---|---|
| PostgreSQL / Cassandra / Neo4j extraction | PASS | 2,500 rows each; value-for-value match with the CSVs (0 mismatches) |
| IDs conformed, derived fields, cleaned categories | PASS | transformation-evidence cell (type changes, validated IDs, date keys); source text was already clean, so no case changes were needed |
| DataFrames match staging specs | PASS | column-name/order assertion |

## C. Data loading
| Criterion | Status | Evidence |
|---|---|---|
| Staging, dimension and fact tables contain data; counts displayed | PASS | 3 staging (2,500 each), 12 dimensions (11,009 rows), 3 facts (2,500 each) |
| Reconciliation, no unexplained loss | PASS | CSV = source DB = extracted = transformed = staging = fact for all three; revenue/cart/price control totals match |

## D. Performance optimization
| Criterion | Status | Evidence |
|---|---|---|
| DISTKEY/SORTKEY documented with justification | PASS | design table; Redshift catalog confirms |
| Materialized view or summary table executed | PASS | `dw.mv_daily_revenue`: 542 rows, 0 differences from a fresh aggregation, REFRESH succeeded |
| Optimization steps demonstrated | PASS | ANALYZE on 6 tables; EXPLAIN shows DS_DIST_NONE on all three fact-dimension joins; MV vs base timing 1.10x (small data, stated honestly) |

## E. Validation and reporting
| Criterion | Status | Evidence |
|---|---|---|
| Duplicate / NULL / row-count checks | PASS | 27 of 27 checks passed |
| Analytical query with visible results | PASS | 8 queries with results |
| Final report | PASS (**TO DO**: download it) | `reports/warehouse_report.md` is generated in the workspace |

## F. Submission quality
| Criterion | Status | Evidence |
|---|---|---|
| TODOs resolved, no credentials in notebook | PASS | scan of the run found no credential strings |
| Naming consistent | PASS | public.stg_* / public.dw_* applied to every statement; report states it |
| Screenshots | PASS (**TO DO**: upload) | `screenshots/` folder: 9 images rendered from the saved outputs of the clean run (`starter (4).ipynb`) |
| Files for submission | **TO DO** | notebook with outputs, DDL, diagram, report files from the workspace |

Known limits (all disclosed in the report): small dataset so timings differ little; `stv_mv_info` not readable by the lab user; customer overlap across systems is small; SCD Type 2 columns present but one current row per key.
