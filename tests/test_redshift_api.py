"""Redshift Data API helpers of the notebook, tested against a scripted fake client (no AWS)."""
import pandas as pd
import pytest

from fake_redshift import ScriptedDataApi, client_error

PAGE = lambda rows: {"ColumnMetadata": [{"name": "n", "label": "n", "typeName": "int8"}, {"name": "x", "label": "x", "typeName": "numeric"}],
                     "Records": rows}


@pytest.fixture
def api(ns):
    def install(**kw):
        a = ScriptedDataApi(**kw)
        ns["rsd"] = a
        return a
    return install


def test_successful_statement_returns_statement_id_and_records_duration(ns, api):
    a = api(statuses=("SUBMITTED", "STARTED", "FINISHED"), has_result=False)
    assert ns["rs_exec"]("SELECT 1") == "stmt-1"
    assert a.polls == 3 and ns["LAST_STATEMENT"]["Duration"] == 5_000_000


def test_failed_statement_raises_with_error_and_sql(ns, api):
    api(statuses=("FAILED",), error_text="syntax error at or near FROM")
    with pytest.raises(RuntimeError, match="(?s)FAILED.*syntax error at or near FROM.*SELECT broken"):
        ns["rs_exec"]("SELECT broken")


def test_aborted_statement_is_an_error_too(ns, api):
    api(statuses=("ABORTED",))
    with pytest.raises(RuntimeError, match="ABORTED"):
        ns["rs_exec"]("SELECT 1")


def test_timeout_cancels_the_statement_and_raises(ns, api, monkeypatch):
    a = api(statuses=("STARTED",))
    monkeypatch.setitem(ns, "time", type("T", (), {"time": iter([0, 0, 5, 5, 5]).__next__, "sleep": staticmethod(lambda s: None)}))
    with pytest.raises(TimeoutError, match="still STARTED"):
        ns["rs_exec"]("SELECT slow", timeout_s=1)
    assert a.cancelled == ["stmt-1"]


@pytest.mark.parametrize("code", ["ExpiredTokenException", "ExpiredToken", "UnrecognizedClientException", "InvalidClientTokenId", "AccessDeniedException"])
def test_expired_credentials_are_reported_separately_from_sql_errors(ns, api, code):
    api(execute_error=client_error(code))
    with pytest.raises(RuntimeError, match="credentials are expired or invalid.*NOT a SQL problem"):
        ns["rs_exec"]("SELECT 1")


def test_other_client_errors_are_not_masked(ns, api):
    api(execute_error=client_error("ThrottlingException"))
    with pytest.raises(Exception) as exc:
        ns["rs_exec"]("SELECT 1")
    assert "credentials are expired" not in str(exc.value)


def test_multiple_result_pages_are_concatenated_in_order(ns, api):
    pages = [PAGE([[{"longValue": 1}, {"stringValue": "1.50"}], [{"longValue": 2}, {"stringValue": "2.25"}]]),
             PAGE([[{"longValue": 3}, {"isNull": True}]]),
             PAGE([[{"longValue": 4}, {"stringValue": "4.00"}]])]
    a = api(pages=pages)
    rows = ns["rs_exec"]("SELECT n, x FROM t", return_results=True)
    assert [r["n"] for r in rows] == [1, 2, 3, 4]
    assert [r["x"] for r in rows] == [1.5, 2.25, None, 4.0]       # numeric strings -> float, isNull -> None
    assert a.page_tokens == [None, "1", "2"]


def test_statement_without_result_set_returns_empty_list(ns, api):
    api(has_result=False)
    assert ns["rs_exec"]("DELETE FROM t", return_results=True) == []


def test_rs_scalar_and_rs_df(ns, api):
    api(pages=[PAGE([[{"longValue": 7}, {"stringValue": "0.5"}]])])
    assert ns["rs_scalar"]("SELECT n FROM t") == 7
    api(pages=[PAGE([[{"longValue": 7}, {"stringValue": "0.5"}]])])
    assert isinstance(ns["rs_df"]("SELECT n FROM t"), pd.DataFrame)


# ---- literal serialisation ----
@pytest.mark.parametrize("value,kind,expected", [
    (None, "s", "NULL"), (float("nan"), "f", "NULL"), (pd.NA, "i", "NULL"), (pd.NaT, "ts", "NULL"),
    ("O'Brien", "s", "'O''Brien'"), ("back\\slash", "s", "'back\\\\slash'"), ("nul\x00byte", "s", "'nulbyte'"),
    (5, "i", "5"), (2.5, "f", "2.5"), (True, "b", "TRUE"), (False, "b", "FALSE"),
    (pd.Timestamp("2025-01-02 03:04:05"), "ts", "'2025-01-02 03:04:05'"),
])
def test_sql_literals_escape_and_serialise_nulls(ns, value, kind, expected):
    assert ns["_sql_literal"](value, kind) == expected


def test_unknown_literal_kind_is_rejected(ns):
    with pytest.raises(ValueError):
        ns["_sql_literal"](1, "?")


# ---- batching ----
def _frame(ns, n):
    return ns["conform"](pd.DataFrame([raw for raw in (__import__("synth").raw_order(order_id=f"ORD{i}") for i in range(1, n + 1))]),
                         ns["ORDERS_COLSPEC"], "orders")


def test_batch_size_controls_the_number_of_insert_statements(ns, api):
    a = api()
    ns["BATCH_SIZE"], ns["TQDM"] = 2, False
    sent = ns["rs_batch_insert"]("stg.orders_raw", ns["ORDERS_COLSPEC"], _frame(ns, 5))
    inserts = [s for s in a.executed if s.startswith("INSERT")]
    assert sent == 5 and len(inserts) == 3                       # 2 + 2 + 1
    assert a.executed[0] == "TRUNCATE TABLE stg.orders_raw"      # staging is emptied first so a re-run never duplicates


def test_truncate_can_be_switched_off(ns, api):
    a = api()
    ns["TQDM"] = False
    ns["rs_batch_insert"]("stg.orders_raw", ns["ORDERS_COLSPEC"], _frame(ns, 1), truncate=False)
    assert not any(s.startswith("TRUNCATE") for s in a.executed)


def test_statements_stay_under_the_size_limit(ns, api, monkeypatch):
    a = api()
    ns["BATCH_SIZE"], ns["TQDM"] = 10_000, False
    monkeypatch.setitem(ns, "_MAX_SQL_CHARS", 3_000)
    ns["rs_batch_insert"]("stg.orders_raw", ns["ORDERS_COLSPEC"], _frame(ns, 40))
    inserts = [s for s in a.executed if s.startswith("INSERT")]
    assert len(inserts) > 1 and max(len(s) for s in inserts) <= 3_000
    assert sum(s.count("('ORD") for s in inserts) == 40           # no row lost or duplicated by the splitting


def test_a_single_row_that_cannot_fit_is_refused_before_anything_is_sent(ns, api, monkeypatch):
    a = api()
    ns["TQDM"] = False
    monkeypatch.setitem(ns, "_MAX_SQL_CHARS", 100)
    with pytest.raises(ValueError, match="more than the 100"):
        ns["rs_batch_insert"]("stg.orders_raw", ns["ORDERS_COLSPEC"], _frame(ns, 1))
    assert not any(s.startswith("INSERT") for s in a.executed)


def test_naming_fallback_rewrites_every_logical_name_consistently(ns):
    ns["NAMING"]["public_fallback"] = True
    try:
        sql = ns["_apply_naming"]("INSERT INTO dw.fact_orders SELECT * FROM stg.orders_raw o JOIN dw.dim_customer c ON c.x = o.y")
        assert sql == "INSERT INTO public.dw_fact_orders SELECT * FROM public.stg_orders_raw o JOIN public.dw_dim_customer c ON c.x = o.y"
        ns["NAMING"]["public_fallback"] = False
        assert ns["_apply_naming"]("SELECT * FROM dw.fact_orders") == "SELECT * FROM dw.fact_orders"
    finally:
        ns["NAMING"]["public_fallback"] = False
