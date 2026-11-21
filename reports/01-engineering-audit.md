# Engineering audit (post-submission review)

Scope: the repository as it stood after the Udacity submission (commit `ddb9a26`), reviewed for documentation accuracy, safe re-runs, source
corrections, deterministic dimension values, testability, and publication readiness. The recorded Redshift results were **not** changed.

**How findings were established.** *Confirmed* = reproduced by running the original code (evidence below) or visible in saved evidence files.
*Suspected / analysed* = derived from reading the code or driver semantics, not executed here (the reason is given). Reproductions run on a
throw-away **PostgreSQL 17 emulation** of the warehouse SQL, not on Amazon Redshift. No AWS account, credential or cloud resource was used.

## 1. What the recorded run supports (verified from the files)

| Claim | Where it is supported |
|---|---|
| Whole notebook executed in the Udacity workspace on 2026-11-12 | `evidence/starter.executed-2026-11-12.ipynb`: 36 of 36 code cells executed, 112 outputs, 0 error outputs (`tests/test_schema_artifacts.py`) |
| 2,500 rows from each of 3 sources, 7,500 fact rows | `reports/validation-results.md` row counts; reconciliation table in the report |
| 12 dimensions (11,009 rows), 3 facts | `reports/pipeline_log.csv` (`populate dimensions` = 11009) |
| 27 of 27 data-quality checks | notebook output, `reports/validation-results.md` |
| Materialized view, 542 rows, 0 differing rows vs a fresh aggregation | notebook output, report section 8 |
| `ANALYZE` on 6 tables, `DS_DIST_NONE` on all 3 joins | notebook output, report section 8 |
| MV speed-up **1.14x** (final run) | notebook output and report. Earlier runs gave 1.10x (rubric checklist) and 1.15x (screenshot 05b): same experiment, run-to-run noise on 2,500 rows |
| Lab naming `public.stg_*` / `public.dw_*` | notebook output (`public_fallback`), report "Naming note", `validation-results.md` |

## 2. Findings

| # | Issue | Evidence | Status | Severity | Fix | Verification |
|---|---|---|---|---|---|---|
| D1 | README said the notebook has no outputs, the reports do not exist and nothing Redshift-specific is verified | `README.md` before commit `1c17858` vs. the files above | Confirmed | High (credibility) | README rewritten around the recorded run | `tests/test_schema_artifacts.py` evidence tests |
| D2 | Three different speed-up figures in three artefacts (1.10x / 1.14x / 1.15x) | checklist, notebook/report, screenshot 05b | Confirmed | Low | kept, labelled as run-to-run noise; README quotes 1.14x (final run) | evidence test asserts 1.14x in report and notebook |
| D3 | `00-project-audit.md` and `rubric-checklist.md` describe earlier stages ("NOT VERIFIED") | the files | Confirmed | Medium | banner marks them HISTORICAL; text untouched | test `historical_documents_are_labelled` |
| D4 | Screenshots come from an earlier run of the same code, not from the final run | 05b shows 1.15x, notebook 1.14x | Confirmed | Low | README says so | - |
| D5 | Notebook text "Larger data would widen the gap" extrapolates the 2,500-row experiment | cell *Performance evidence* | Confirmed | Low | sentence replaced by "says nothing about larger data" | notebook diff |
| D6 | Diagram check only compared table names and column *presence* (extra columns, types, relationships unchecked) while its output read "MATCH (all 15 dw tables and all their columns present)" | cell *Schema diagram*, original source | Confirmed | Medium | `check_diagram()` also checks extra columns, type families and fact-to-dimension relationships; docstring and message state what is NOT checked | 10 negative tests in `test_schema_artifacts.py` |
| E1 | Re-running the notebook **drops and re-creates every populated project table** (`DROP TABLE IF EXISTS` in the DDL cell) | `scripts/repro/output.txt` R1: 2 fact rows before, 0 after | Confirmed | **High** | `PIPELINE_MODE` INITIALIZE (default, never drops) / LOAD / REBUILD (allow-listed database **and** exact confirmation string) | `tests/test_ddl_modes.py` |
| E2 | A corrected order never reaches `fact_orders` (`INSERT ... WHERE NOT EXISTS`) | output.txt R2: staging 92.2, fact stays 102.2 | Confirmed | **High** | `UPDATE ... FROM <same select>` for changed rows (NULL-safe comparison), then insert of new keys | `test_warehouse_semantics.py` |
| E3 | A corrected order never reaches the PostgreSQL source (`ON CONFLICT DO NOTHING`) | output.txt R3: 102.2 after the CSV said 92.2 | Confirmed | High | `ON CONFLICT DO UPDATE ... WHERE <any column differs>` (unchanged rows are not rewritten) | `tests/test_sources.py` |
| E4 | Dimension attributes of an existing customer/product are never updated | same insert-only pattern (`NOT IN`) | Confirmed by code and by the new tests | Medium | Type 1 overwrite in place; surrogate keys unchanged; no history (documented) | `test_corrected_dimension_attribute...` |
| E5 | `ROW_NUMBER()` ties are not deterministic: same data, different staging row order, different `dim_customer` / `dim_product` values | `scripts/repro/output.txt` T1: (US,CA)/(low,10) vs (DE,BE)/(high,99) | Confirmed on PostgreSQL (Redshift not tested) | Medium | added the record id (`order_id` / `event_id` / `edge_id`, higher wins) as last sort key; country and state always from ONE record | parametrised tests with reversed insertion order |
| E6 | Source record removed: facts keep the stale row; the run only failed on a later count assertion | code reading | Confirmed (behaviour), unsupported by design | Medium | explicit `check_no_stale_facts()` with a clear message; no delete logic (out of scope, documented) | `test_removed_source_record...` |
| E7 | Interrupted staging load: the fact cell had no guard of its own | code reading | Suspected, low likelihood (the staging cell asserts counts) | Low | `check_staging_complete()` before any fact/dimension write | `test_interrupted_staging_load...` |
| E8 | One row larger than the 100 KB Data API limit would fail inside AWS with an opaque error | code reading + new test | Confirmed gap | Low | `rs_batch_insert` raises a clear `ValueError` before sending | `test_a_single_row_that_cannot_fit...` |
| E9 | Cassandra loads NULL as `UNSET_VALUE` and Neo4j uses `SET e += props` without NULLs: a correction **to NULL** does not clear the old value. A correction that changes a Cassandra primary-key column, or a Neo4j edge's endpoints/type, creates a second record with the same `edge_id`/`event_id`, which `conform()` then rejects as a duplicate | driver semantics, code | **Suspected, not executed** (no Cassandra/Neo4j service here; Docker daemon not running) | Medium | documented as limitation, loud failure (duplicate key) rather than silent corruption | README "Known limitations" |
| E10 | Redshift-specific SQL added by this review (`UPDATE ... FROM`, `WITH ... UPDATE`) is only parsed (sqlglot, Redshift dialect) and run on PostgreSQL | - | **Not verified on Redshift** | Medium | NULL-safe comparison written without `IS DISTINCT FROM`; to be run once in a disposable lab database | README "Not verified" |

## 3. Decisions

* **The notebook outputs were cleared** in the revised `starter.ipynb`, because its code is no longer the code that produced them. The executed
  original is preserved unchanged as `evidence/starter.executed-2026-11-12.ipynb` and is also in Git history (commit `ddb9a26`).
* The reports in `reports/` still describe the recorded run and were not regenerated.
* Type 1 (overwrite) was chosen for changed dimension attributes; Type 2 history is not implemented and not claimed.
* No CDC, streaming, S3 `COPY` or orchestrator was added.

## 4. Review of the recorded performance and schema evidence

Checked against the **saved outputs of the recorded Redshift run** (not re-measured):

| Item | Finding |
|---|---|
| Distribution and sort keys | The catalog output (`pg_class` / `pg_attribute`) lists, for all 15 `dw` tables, exactly the keys in the DDL and in report section 8. Now enforced by a test. |
| Column encodings | Fact tables: 1 `none` (= `ENCODE raw` on the leading sort-key column), 1 `az64` (the `IDENTITY` surrogate key, which has no `ENCODE` clause so Redshift applied its default), rest `zstd` (23 / 20 / 20). Consistent with "zstd on most columns, raw on leading sort-key columns". Now enforced by a test. |
| Staging tables | The catalog shows `reldiststyle` **9** for the three staging tables, a value that the notebook's own mapping table does not contain, so it printed as "9". The DDL gives no distribution clause (the report says `AUTO/EVEN`). Not interpreted further; no claim is made about it. |
| Materialized view | 542 rows, 0 differing rows, `REFRESH` succeeded. `stv_mv_info` was not readable by the lab user (permission denied), as the checklist already says. |
| Speed-up | 1.14x (median of 6 runs, result cache bypassed by a unique predicate per run). Both queries take ~50 ms on 2,500 rows, so the figure is direction only; the earlier "larger data would widen the gap" sentence was removed (D5). No larger benchmark exists and none was invented. |
| `EXPLAIN` | `DS_DIST_NONE` on all three fact-to-dimension joins, as designed. |
| Batch loading | Multi-row `INSERT` through the Data API is documented as a small-data choice; S3 `COPY` is the normal approach for large loads and was not implemented (no demonstrated need). |
| Diagram check | See D6: strengthened and documented; `project-mermaid-diagram.md` now states what the check covers and the logical/physical naming. |

## 5. Open items that need the owner

1. **Run the revised notebook once in a disposable Redshift lab database** (modes, `UPDATE ... FROM`, `WITH ... UPDATE`). Until then these are *not verified on Redshift* (E10). After that run, `starter.ipynb` can carry outputs again and the reports can be regenerated.
2. **Push and let GitHub Actions run.** The workflow has been executed only in a local simulation of CI (clean virtual environment from `requirements-dev.txt`, external PostgreSQL via `TEST_PG_DSN`); no remote run exists.
3. **Publication rights** of the course-supplied files: see `PROVENANCE.md`. The repository is public today and has no license.
4. Cassandra / Neo4j correction semantics (E9) were analysed, not executed; a one-off local check with Docker would settle them.
