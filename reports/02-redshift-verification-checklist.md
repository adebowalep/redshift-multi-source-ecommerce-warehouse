# Manual verification checklist for a disposable Amazon Redshift database

**Status: NOT EXECUTED.** The revised `starter.ipynb` has never run on Amazon Redshift. This is a procedure for the repository owner; nothing here was
run, no AWS resource was created and no credentials were used while writing it. Until the steps below are done and their evidence is saved,
the README keeps saying "not verified on Redshift".

## Safety rules (read first)

* Use a **disposable lab database that nobody else uses** (a throw-away Redshift Serverless workgroup or a database created only for this test).
  Do not use a shared database, a production database or one whose contents you cannot lose.
* `REBUILD` drops every project table (`stg.*`, `dw.*`, or `public.stg_*` / `public.dw_*`). Run it only in that disposable database.
* Work in a **copy** of the repository: the last notebook cell writes `reports/warehouse_report.md`, `validation-results.md`, `field-mapping.md`
  and `pipeline_log.csv`, which would overwrite the committed historical reports. Example:
  `cp -R <repo> /tmp/redshift-check && cd /tmp/redshift-check` and run the notebook from there with `PROJECT_BASE_DIR=/tmp/redshift-check`.
* The notebook needs the three source databases (PostgreSQL, Cassandra, Neo4j) for its extraction cells. In the Udacity lab they exist. Outside
  it, tell the notebook which Redshift database to use with `REDSHIFT_DATABASE`, `REDSHIFT_WORKGROUP` (or cluster variables), and credentials from
  your own session. Never paste keys into the notebook or commit them.
* Stop at the first failure, save the error text, and do not "fix" the result by editing the saved evidence.
* Cost: Redshift Serverless bills while queries run. The data set is 7,500 rows; delete the workgroup afterwards (step 12).

## Evidence to save for every step
The notebook cell output (copy the cell or export the notebook), the query result tables, and the Redshift query-history page if available.
Store them in a folder outside `evidence/` first (`evidence/` holds the historical run and must stay unchanged); add a new, dated file only after review.

## Steps

| # | Step | Execute | Expected | Failure means | Save |
|---|---|---|---|---|---|
| 1 | **Initial schema creation** | `PIPELINE_MODE=INITIALIZE` on an empty database; run Task 4.2 | 40 DDL statements checked ("only touch stg and dw"); 18 project tables created (3 staging, 12 dimensions, 3 facts); naming mode printed (schemas, or the public fallback if `CREATE SCHEMA` is denied); `pg_tables` query in `execute_warehouse_ddl` returns rows without error | an error from the `pg_tables` query (the AWS pages read for this review do not document it; the recorded run used `pg_class`), a missing table, mixed naming | cell output; `SELECT schemaname, tablename FROM pg_tables WHERE schemaname IN ('stg','dw','public')` |
| 2 | **Initial source loading** | Task 3 (load and extract the three sources), Task 4.3 | 2,500 rows per source; staging counts equal the transformed frames (`check_staging_complete` passes) | a count mismatch, an oversize-row `ValueError` | the three counts |
| 3 | **Dimension and fact population** | Tasks 4.4 and 4.5, first run | every statement prints a tick, **in particular** `dim_customer: update changed`, `dim_product: update changed` (`WITH ... UPDATE`) and the three `fact_*: update changed` statements (`UPDATE ... FROM (subquery)`) execute without a syntax error, even though on a first run they change 0 rows | any `Redshift statement FAILED` with a syntax message near `WITH`, `UPDATE` or `FROM`; see "Statements to look at first" below | the statement ids and error text |
| 4 | **Row-count reconciliation** | the assertions at the end of Task 4.5 and `SELECT COUNT(*)` on all 18 tables | facts 2,500 / 2,500 / 2,500 = staging; dimension counts equal the recorded run (11,009 dimension rows in total); one row per natural key | any difference from staging; compare with `reports/warehouse_report.md` of the historical run | the count table |
| 5 | **Data-quality validation** | Task 6 | 27 of 27 checks return 0 | any check above 0 (do not edit the check) | the 27-row result |
| 6 | **Unchanged re-run** | run Tasks 3 to 4.5 again with no source change | no error; row counts and `SUM(order_total_usd)` identical; surrogate keys unchanged (`SELECT MIN(customer_sk), MAX(customer_sk), COUNT(*) FROM dw.dim_customer` before and after); a full-table checksum of each dimension and fact (e.g. `SELECT MD5(LISTAGG(...))` or an `EXCEPT` against a copy made before the re-run) shows no row changed | duplicated rows, changed counts, new surrogate keys | before / after table |
| 7 | **Existing order correction** | in PostgreSQL change one order, e.g. `UPDATE orders SET subtotal_usd = subtotal_usd - 10, order_total_usd = order_total_usd - 10 WHERE order_id = '<id>'`; re-run | exactly that `fact_orders` row changes; same `order_sk`; fact count unchanged; `SUM(order_total_usd)` moves by exactly the difference; DQ still 27 of 27 | the old value stays, a second row appears, the surrogate key changes | the row before and after |
| 8 | **New record** | insert one new order (new `order_id`, existing customer); re-run | `fact_orders` +1; no other row changed; counts reconcile to staging | the row is missing or inserted twice | counts before / after |
| 9 | **Changed dimension attribute** | change a customer's country in the orders source (their latest order) or a product's category on its latest graph edge; re-run | the **same** `customer_sk` / `product_sk` now carries the new value (Type 1 overwrite); `is_current` still TRUE; facts still point to the same key; no second dimension row | a new surrogate key, history rows, or the old value remaining | the dimension row before and after |
| 10 | **Materialized-view refresh** | Task 5.2 (drop and create), then `REFRESH MATERIALIZED VIEW dw.mv_daily_revenue` | the view equals a fresh aggregation of `fact_orders` (0 differing rows) after the correction of step 7; `REFRESH` succeeds | a stale view after the Task 5.2 re-create, or an error from `DROP/CREATE/REFRESH` | the diff query and the view total |
| 11 | **Rebuild safeguards** | (a) `PIPELINE_MODE=REBUILD` with `REBUILD_CONFIRM` unset; (b) with a wrong confirmation; (c) with `REBUILD_ALLOWED_DATABASES` not containing the database; (d) only then, in the disposable database, the exact `REBUILD_CONFIRM="REBUILD <database>"` | (a)(b)(c) raise `PermissionError` before any DDL, tables and data survive; (d) drops and re-creates all 18 tables empty and drops the materialized view | a destructive statement running in (a)(b)(c): **stop immediately** | the three refusals and the (d) output |
| 12 | **Final reconciliation and cleanup** | re-run the full pipeline after (d); run the 27 checks; then delete the lab database / workgroup in the AWS console | counts and DQ as in steps 4 and 5; resources removed | leftover billable resources | final counts, deletion confirmation |

## Statements to look at first (confirmed gaps in the AWS documentation read for this review)

These are the places where the PostgreSQL emulation and the SQL parser cannot tell you what Redshift does. If one fails, fix only that statement.

1. **`WITH ... UPDATE`** (`SQL_DIM_CUSTOMER_UPDATE`, `SQL_DIM_PRODUCT_UPDATE`). The UPDATE syntax page lists a leading `WITH` clause, but the `WITH` page
   mentions UPDATE only inside a `WHERE` subquery. If it is rejected, move the CTEs into a subquery in the `FROM` clause.
2. **Schema-qualified target columns** (`WHERE dw.dim_customer.customer_id = src.customer_id`, `dw.fact_orders.order_id = s.order_id`). The UPDATE page says the target
   table cannot take an alias there, yet its syntax shows one; the notebook uses no alias and qualifies with `schema.table`. If rejected, qualify with the
   table name only after setting the schema in `search_path`, or alias the target as the page's syntax allows.
3. **`pg_tables`** in `execute_warehouse_ddl`. If it is unavailable use the `pg_class` / `pg_namespace` query already proven in `rs_table_meta`.
4. **Multiple source rows per target row.** PostgreSQL silently picks one; Redshift raises an error when `error_on_nondeterministic_update` is on. The code
   guarantees one source row per key (staging keys are unique, the dimension source CTEs return one row per natural key), so an error here would show a
   real duplicate and must not be "fixed" by turning the setting off.
5. **Statement size.** The code keeps statements under 90,000 characters; the AWS pages give 200 KB and 16 MB. Not a concern at this data size.

Not used in the Redshift SQL, by design: `IS DISTINCT FROM` (replaced by a portable NULL-safe comparison; it is not in the Redshift comparison-condition list),
`ON CONFLICT` (used only in the PostgreSQL *source* loader), `DISTINCT ON`, and outer joins at the top level of an `UPDATE ... FROM`.

## Reporting the outcome
Record the date, the Redshift flavour (Serverless / provisioned), the pass or fail of each step and the evidence file names in a new document
`reports/03-redshift-verification-result.md`. Only then change the README's "Not verified" row and regenerate reports from that run. Until then
the verification is **pending**.
