"""DDL, schema diagram, field mapping, SQL syntax, repository hygiene and consistency of the recorded Redshift evidence."""
import csv
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sqlglot = pytest.importorskip("sqlglot")


# ---------------------------------------------------------------- DDL and SQL
def test_ddl_defines_3_staging_12_dimension_3_fact_tables(ns):
    assert ns["DDL_TABLES"].kind.value_counts().to_dict() == {"dimension": 12, "fact": 3, "staging": 3}


def test_ddl_join_columns_are_colocated(ns):
    t = ns["DDL_TABLES"].set_index("table")
    assert t.loc["fact_orders", "distkey"] == t.loc["fact_events", "distkey"] == t.loc["dim_customer", "distkey"] == "customer_sk"
    assert t.loc["fact_graph_edges", "distkey"] == "to_product_sk" and t.loc["dim_product", "distkey"] == "product_sk"


def parse_redshift(sql):
    return sqlglot.parse(sql, read="redshift")


def test_every_ddl_statement_parses_as_redshift_sql(ns):
    for s in ns["DDL_STATEMENTS"]:
        assert parse_redshift(s)[0] is not None, s[:80]


def test_every_warehouse_statement_parses_as_redshift_sql(ns):
    stmts = [sql for _, sql in ns["dimension_statements"]() + ns["fact_statements"]()] + [sql for _, sql in ns["DQ_CHECKS"]] \
        + [sql for _, sql in ns["STALE_FACT_CHECKS"]]
    assert len(stmts) > 40
    for sql in stmts:
        assert parse_redshift(sql)[0] is not None, sql[:120]


def test_warehouse_sql_uses_only_logical_names_so_the_naming_fallback_is_complete(ns):
    sqls = [sql for _, sql in ns["dimension_statements"]() + ns["fact_statements"]()] + [sql for _, sql in ns["DQ_CHECKS"]]
    for sql in sqls:
        assert not re.search(r"\bpublic\.(stg|dw)_", sql), sql[:100]
        for ref in re.findall(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+(\w+)\.\w+", sql):
            assert ref in ("stg", "dw"), (ref, sql[:100])


def test_the_update_statements_never_target_staging_or_unknown_tables(ns):
    for label, sql in ns["dimension_statements"]() + ns["fact_statements"]():
        for target in re.findall(r"\bUPDATE\s+(\w+\.\w+)", sql):
            assert target.startswith("dw."), label


# ---------------------------------------------------------------- schema diagram
def run_check(ns, mermaid):
    return ns["check_diagram"](ns["DDL_STATEMENTS"], ns["DDL_TABLES"], mermaid)


@pytest.fixture
def mermaid():
    return (ROOT / "project-mermaid-diagram.md").read_text()


def test_committed_diagram_matches_the_ddl(ns, mermaid):
    assert run_check(ns, mermaid) == []


def test_diagram_check_detects_a_missing_table(ns, mermaid):
    broken = re.sub(r"dw_dim_os\s*\{[^}]*\}", "", mermaid)
    assert any("table missing in diagram: dw_dim_os" in p for p in run_check(ns, broken))


def test_diagram_check_detects_a_missing_column(ns, mermaid):
    assert any("fact_orders: column returned" in p for p in run_check(ns, mermaid.replace("BOOLEAN returned\n", "")))


def test_diagram_check_detects_an_extra_column(ns, mermaid):
    broken = mermaid.replace("BOOLEAN returned\n", "BOOLEAN returned\n      VARCHAR surprise\n")
    assert any("surprise is in the diagram but not in the DDL" in p for p in run_check(ns, broken))


def test_diagram_check_detects_a_wrong_data_type(ns, mermaid):
    broken = mermaid.replace("DECIMAL order_total_usd", "VARCHAR order_total_usd")
    assert any("dw_fact_orders.order_total_usd" in p and "type family" in p for p in run_check(ns, broken))


def test_diagram_check_detects_a_missing_relationship(ns, mermaid):
    broken = mermaid.replace('    dw_dim_channel ||--o{ dw_fact_orders : "channel_sk"\n', "")
    assert any("fact_orders.channel_sk: key column without a relationship line" in p for p in run_check(ns, broken))


def test_diagram_check_detects_a_relationship_to_a_non_existing_column(ns, mermaid):
    broken = mermaid.replace('dw_dim_channel ||--o{ dw_fact_orders : "channel_sk"', 'dw_dim_channel ||--o{ dw_fact_orders : "chanel_sk"')
    probs = run_check(ns, broken)
    assert any("'chanel_sk' is not a column" in p for p in probs)


def test_diagram_check_detects_a_relationship_wired_to_the_wrong_dimension(ns, mermaid):
    broken = mermaid.replace('dw_dim_channel ||--o{ dw_fact_orders : "channel_sk"', 'dw_dim_device ||--o{ dw_fact_orders : "channel_sk"')
    assert any("does not end with the dimension key" in p for p in run_check(ns, broken))


def test_diagram_check_detects_a_table_that_is_not_in_the_ddl(ns, mermaid):
    broken = mermaid + "\n    dw_dim_ghost { BIGINT ghost_sk PK }\n"
    assert any("diagram has table not in DDL: dw_dim_ghost" in p for p in run_check(ns, broken))


def test_diagram_check_documents_what_it_does_not_cover(ns):
    assert "NOT checked" in ns["check_diagram"].__doc__ and "DISTKEY" in ns["check_diagram"].__doc__


# ---------------------------------------------------------------- field mapping
@pytest.mark.parametrize("system,csvname", [("PostgreSQL", "ecom_orders_postgres.csv"), ("Cassandra", "ecom_events_cassandra.csv"),
                                            ("Neo4j", "ecom_graph_edges_neo4j.csv")])
def test_every_source_column_appears_in_the_field_mapping(system, csvname):
    header = next(csv.reader(open(ROOT / "data" / csvname)))
    rows = [line for line in (ROOT / "reports" / "field-mapping.md").read_text().splitlines() if line.startswith(f"| {system} |")]
    mapped = " ".join(rows)
    missing = [c for c in header if not re.search(rf"\b{re.escape(c)}\b", mapped)]
    assert not missing, missing


def test_colspecs_match_the_csv_headers(ns):
    for csvname, spec in [("ecom_orders_postgres.csv", "ORDERS_COLSPEC"), ("ecom_events_cassandra.csv", "EVENTS_COLSPEC"),
                          ("ecom_graph_edges_neo4j.csv", "EDGES_COLSPEC")]:
        assert next(csv.reader(open(ROOT / "data" / csvname))) == [c for c, _ in ns[spec]]


def test_real_source_csvs_conform_without_modification(ns):
    import pandas as pd
    for csvname, spec, name in [("ecom_orders_postgres.csv", "ORDERS_COLSPEC", "orders"), ("ecom_events_cassandra.csv", "EVENTS_COLSPEC", "events"),
                                ("ecom_graph_edges_neo4j.csv", "EDGES_COLSPEC", "edges")]:
        df = ns["trim_df"](pd.read_csv(ROOT / "data" / csvname))
        assert len(ns["conform"](df, ns[spec], name)) == 2500


# ---------------------------------------------------------------- notebook and repository hygiene
NOTEBOOK = json.loads((ROOT / "starter.ipynb").read_text())
SECRET_PATTERNS = [r"AKIA[0-9A-Z]{16}", r"ASIA[0-9A-Z]{16}", r"aws_secret_access_key\s*[=:]\s*\S{20,}", r"aws_session_token\s*[=:]\s*\S{20,}",
                   r"arn:aws:secretsmanager:[a-z0-9-]+:\d{12}:", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"]


def test_every_code_cell_compiles():
    for i, c in enumerate(NOTEBOOK["cells"]):
        if c["cell_type"] == "code":
            compile("".join(c["source"]), f"cell {i}", "exec")


def tracked_text_files():
    skip = {".git", "__pycache__", ".pytest_cache", ".venv", "venv"}
    for p in ROOT.rglob("*"):
        if p.is_file() and not (skip & set(p.relative_to(ROOT).parts)) and p.suffix in (".md", ".ipynb", ".csv", ".py", ".yml", ".yaml", ".txt", ".json", ".svg"):
            yield p


def test_no_credentials_in_any_text_file_or_notebook_output():
    hits = [(str(p.relative_to(ROOT)), pat) for p in tracked_text_files() for pat in SECRET_PATTERNS if re.search(pat, p.read_text(errors="ignore"))]
    assert not hits, hits


def test_notebook_has_no_hard_coded_aws_credentials_and_reads_them_from_the_environment():
    code = "\n".join("".join(c["source"]) for c in NOTEBOOK["cells"] if c["cell_type"] == "code")
    assert "os.environ.get(k)" in code and "getpass.getpass" in code
    assert not re.search(r"AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)\s*=\s*['\"][A-Za-z0-9/+=]{8,}", code)


def test_notebook_has_no_false_success_banner_without_the_work(ns):
    code = "\n".join("".join(c["source"]) for c in NOTEBOOK["cells"] if c["cell_type"] == "code")
    assert "ALL TASKS COMPLETED" not in code


# ---------------------------------------------------------------- the recorded Redshift run (historical evidence stays consistent)
EVIDENCE = ROOT / "evidence" / "starter.executed-2026-11-12.ipynb"


def evidence_text():
    nb = json.loads(EVIDENCE.read_text())
    out = []
    for c in nb["cells"]:
        for o in c.get("outputs", []):
            out.append("".join(o.get("text", [])) if "text" in o else "".join(o.get("data", {}).get("text/plain", [])))
    return nb, "\n".join(out)


def test_evidence_notebook_was_executed_completely_without_errors():
    nb, _ = evidence_text()
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert len(code) == 36 and all(c.get("execution_count") for c in code)
    assert not [o for c in nb["cells"] for o in c.get("outputs", []) if o["output_type"] == "error"]


def test_report_log_and_validation_files_agree_with_the_evidence_notebook():
    nb, text = evidence_text()
    report = (ROOT / "reports" / "warehouse_report.md").read_text()
    validation = (ROOT / "reports" / "validation-results.md").read_text()
    log = list(csv.DictReader(open(ROOT / "reports" / "pipeline_log.csv")))
    assert "7,500 fact rows loaded" in report and "27/27 data-quality checks passed" in report
    assert "27 of 27 checks passed" in text
    assert validation.count("| PASS |") == 27 and "FAIL" not in validation.replace("FAILED", "")
    assert len(log) == 19 and {r["status"] for r in log} == {"OK"}
    assert re.search(r"speed-up of the view over the base aggregation: \*\*1\.14x\*\*", report) and "speed-up of the MV over the base aggregation: 1.14x" in text
    assert "(542 rows)" in report and "dw.mv_daily_revenue (542 rows)" in report.replace("`", "")
    assert re.search(r"dw_fact_orders\s*\|\s*2500", validation.replace("public.", "dw_")) or "public.dw_fact_orders | 2500" in validation
    fact_rows = sum(int(m) for m in re.findall(r"public\.dw_fact_\w+ \| (\d+)", validation))
    assert fact_rows == 7500


def test_the_recorded_run_used_the_lab_naming_fallback_and_the_report_says_so():
    _, text = evidence_text()
    report = (ROOT / "reports" / "warehouse_report.md").read_text()
    assert "public_fallback" in text and "public.dw_fact_orders" in report and "Naming note" in report


def test_historical_documents_are_labelled_as_such():
    for name in ("00-project-audit.md", "rubric-checklist.md"):
        assert "HISTORICAL DOCUMENT" in (ROOT / "reports" / name).read_text()[:600], name
