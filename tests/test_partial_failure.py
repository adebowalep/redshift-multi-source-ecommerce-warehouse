"""Partial failure: what the warehouse looks like when a run stops half-way, and whether a plain re-run repairs it.

The notebook sends every SQL statement through the Redshift Data API as its own ``ExecuteStatement`` call with no explicit
transaction, so a statement that finished stays finished (the PostgreSQL emulation in ``fake_redshift.py`` is in autocommit mode
for the same reason). A failure therefore leaves a *partially updated* warehouse. These tests inject a failure at every single load
statement, inspect the intermediate state, re-run the pipeline and require the final state to equal that of an uninterrupted run.

This is evidence about the notebook's SQL on PostgreSQL. It says nothing about how Amazon Redshift treats a statement that is
cancelled or times out on the client side (the AWS documentation does not specify it).
"""
import pytest

from synth import Dataset


def tables(ns):
    return [t for t in ns["DDL_TABLES"].table if t.startswith(("dim_", "fact_"))]


def snapshot(wh):
    """Every dimension and fact row, surrogate keys included, ordered; only the load timestamp (effective_from) is dropped."""
    out = {}
    for t in tables(wh.ns):
        df = wh.df(f"SELECT * FROM dw.{t} ORDER BY 1")
        df = df.drop(columns=[c for c in ("effective_from",) if c in df.columns])
        out[t] = df.astype(object).where(df.notna(), None).to_dict("records")
    return out


def corrections(data):
    """The source changes used by every scenario: a corrected order (also a new channel member), a corrected event and a
    corrected product price on a graph edge (which also changes the product dimension)."""
    data.order("ORD1")["subtotal_usd"], data.order("ORD1")["order_total_usd"] = 90.0, 92.2      # 90 - 10 + 5 + 7.2: stays consistent for the DQ check
    data.order("ORD1")["channel"] = "mobile_web"                  # a channel that does not exist yet -> dim_channel gets a new member
    data.event("EVT1")["dwell_seconds"] = 77
    data.edge("EDGE3")["unit_price_usd"], data.edge("EDGE3")["price_bucket"] = 24.5, "mid"
    return data


def finish(wh):
    """The notebook's analytical step after the facts: drop and re-create the daily-revenue materialized view."""
    wh.exec(wh.ns["SQL_DROP_MV_DAILY_REVENUE"])
    wh.exec(wh.ns["SQL_CREATE_MV_DAILY_REVENUE"])


def mv_total(wh):
    return float(wh.scalar("SELECT SUM(revenue_usd) FROM dw.mv_daily_revenue"))


def fact_total(wh):
    return float(wh.scalar("SELECT SUM(order_total_usd) FROM dw.fact_orders"))


def dq(wh):
    return {name: int(wh.scalar(sql)) for name, sql in wh.ns["DQ_CHECKS"]}


class FailOnce:
    """Make one specific statement fail the way the Data API reports it (status FAILED), once.

    committed=False: the statement is rejected before it changes anything (a normal SQL error, statement-level atomicity).
    committed=True : the statement runs to completion and is *then* reported as failed (a lost response or client-side timeout)."""

    def __init__(self, api, sql, committed=False):
        self.api, self.sql, self.committed, self.fired = api, sql.strip(), committed, False
        self.real = api.execute_statement
        api.execute_statement = self

    def __call__(self, Sql, **kw):
        if not self.fired and Sql.strip() == self.sql:
            self.fired = True
            resp = self.real(Sql, **kw) if self.committed else {"Id": __import__("uuid").uuid4().hex}
            self.api.stmts[resp["Id"]] = dict(Status="FAILED", HasResultSet=False, Duration=0, Error="injected failure")
            return resp
        return self.real(Sql, **kw)

    def remove(self):
        self.api.execute_statement = self.real


@pytest.fixture(scope="module")
def reference(ns, pgsrv):
    """The state an uninterrupted run reaches: first load, then the corrected data, then the materialized view."""
    from conftest import _drop, _make_wh
    w = _make_wh(ns, pgsrv)
    try:
        d = Dataset()
        w.ddl(); w.run(d); finish(w)
        before = snapshot(w)
        corrections(d)
        w.run(d); finish(w)
        return {"before": before, "after": snapshot(w), "fact_total": fact_total(w), "mv_total": mv_total(w), "dq": dq(w)}
    finally:
        _drop(w)


@pytest.fixture
def loaded(wh, data):
    wh.ddl()
    wh.run(data)
    finish(wh)
    return wh


def test_the_reference_run_really_changes_something(reference):
    """Guard against a vacuous scenario: the corrections must change dimensions AND all three facts."""
    b, a = reference["before"], reference["after"]
    changed = {t for t in b if b[t] != a[t]}
    assert {"fact_orders", "fact_events", "fact_graph_edges", "dim_product", "dim_channel"} <= changed
    assert reference["fact_total"] == pytest.approx(143.2) and reference["mv_total"] == pytest.approx(143.2)
    assert set(reference["dq"].values()) == {0}


def statement_labels(ns):
    return [label for label, _ in ns["dimension_statements"]()] + [label for label, _ in ns["fact_statements"]()]


def pytest_generate_tests(metafunc):
    if "failing_label" in metafunc.fixturenames:
        from nbload import load_notebook
        labels = statement_labels(load_notebook())
        metafunc.parametrize("failing_label", labels, ids=labels)
        metafunc.parametrize("committed", [False, True], ids=["rejected", "applied-but-reported-failed"])


def statement_sql(ns, label):
    return dict(ns["dimension_statements"]() + ns["fact_statements"]())[label]


def test_a_failure_at_any_statement_is_reported_leaves_only_old_or_new_rows_and_a_rerun_repairs_it(
        loaded, data, reference, failing_label, committed):
    ns, before = loaded.ns, reference["before"]
    corrections(data)
    flaky = FailOnce(loaded.api, statement_sql(ns, failing_label), committed)

    with pytest.raises(RuntimeError, match=r"Redshift statement FAILED: injected failure"):
        loaded.run(data)                                           # staging is complete, the load stops at the chosen statement
    assert flaky.fired
    flaky.remove()

    # intermediate state: partial writes may exist, but never a duplicate, a lost row or a row that is neither old nor corrected
    mid = snapshot(loaded)
    for t, rows in mid.items():
        old, new = before[t], reference["after"][t]
        assert len(rows) in {len(old), len(new)}, f"{t}: {len(rows)} rows, expected {len(old)} (before) or {len(new)} (after)"
        for row in rows:
            assert row in old or row in new, f"{t}: a row that is neither the old nor the corrected version: {row}"
    for fact, key in [("fact_orders", "order_id"), ("fact_events", "event_id"), ("fact_graph_edges", "edge_id")]:
        assert loaded.scalar(f"SELECT COUNT(*) - COUNT(DISTINCT {key}) FROM dw.{fact}") == 0

    # recovery: the same pipeline run again, nothing else
    loaded.run(data)
    assert snapshot(loaded) == reference["after"]                  # every row, every surrogate key identical to an uninterrupted run
    assert fact_total(loaded) == pytest.approx(reference["fact_total"])
    assert dq(loaded) == reference["dq"] and set(dq(loaded).values()) == {0}
    for t in ("dim_customer", "dim_product"):                      # surrogate keys that existed before the failure are unchanged
        old_sk = {r[f"{t[4:]}_id"]: r[f"{t[4:]}_sk"] for r in before[t]}
        new_sk = {r[f"{t[4:]}_id"]: r[f"{t[4:]}_sk"] for r in snapshot(loaded)[t]}
        assert {k: new_sk[k] for k in old_sk} == old_sk


# ---- the three situations named in the review, with exact intermediate states ----------------------------------------------
def intermediate(wh, data, label, committed=False):
    corrections(data)
    flaky = FailOnce(wh.api, statement_sql(wh.ns, label), committed)
    with pytest.raises(RuntimeError, match="injected failure"):
        wh.run(data)
    flaky.remove()
    return snapshot(wh)


def test_dimension_updated_but_the_facts_not_yet(loaded, data, reference):
    mid = intermediate(loaded, data, "fact_orders: update changed")
    b, a = reference["before"], reference["after"]
    assert mid["dim_product"] == a["dim_product"] and mid["dim_channel"] == a["dim_channel"]     # dimensions are already corrected ...
    assert mid["fact_orders"] == b["fact_orders"] and mid["fact_events"] == b["fact_events"] and mid["fact_graph_edges"] == b["fact_graph_edges"]   # ... facts are not
    assert fact_total(loaded) == pytest.approx(153.2) and reference["fact_total"] == pytest.approx(143.2)
    loaded.run(data)
    assert snapshot(loaded) == a


def test_two_facts_updated_and_the_third_fails(loaded, data, reference):
    mid = intermediate(loaded, data, "fact_graph_edges: update changed")
    b, a = reference["before"], reference["after"]
    assert mid["fact_orders"] == a["fact_orders"] and mid["fact_events"] == a["fact_events"]      # two facts corrected
    assert mid["fact_graph_edges"] == b["fact_graph_edges"]                                      # the third still old
    assert fact_total(loaded) == pytest.approx(143.2)
    loaded.run(data)
    assert snapshot(loaded) == a


def test_new_fact_rows_are_not_half_inserted_when_the_insert_statement_fails(loaded, data, reference):
    data.orders.append(__import__("synth").raw_order(order_id="ORD3", customer_id="C3", order_total_usd=10.0))
    corrections(data)
    flaky = FailOnce(loaded.api, statement_sql(loaded.ns, "fact_orders: insert new"))
    with pytest.raises(RuntimeError, match="injected failure"):
        loaded.run(data)
    flaky.remove()
    assert loaded.count("dw.fact_orders") == 2                      # ORD3 absent, corrections already applied to ORD1
    assert float(loaded.scalar("SELECT order_total_usd FROM dw.fact_orders WHERE order_id = 'ORD1'")) == 92.2
    loaded.run(data)
    assert loaded.count("dw.fact_orders") == 3 and fact_total(loaded) == pytest.approx(153.2)
    assert loaded.scalar("SELECT COUNT(*) - COUNT(DISTINCT order_id) FROM dw.fact_orders") == 0


# ---- dependent analytical object --------------------------------------------------------------------------------------------
def test_materialized_view_is_stale_when_the_run_stops_before_it_and_a_rerun_rebuilds_it(loaded, data, reference):
    corrections(data)
    flaky = FailOnce(loaded.api, statement_sql(loaded.ns, "fact_graph_edges: insert new"))
    with pytest.raises(RuntimeError, match="injected failure"):
        loaded.run(data)
    flaky.remove()
    assert fact_total(loaded) == pytest.approx(143.2)               # orders already corrected ...
    assert mv_total(loaded) == pytest.approx(153.2)                 # ... the view still shows the old total: stale, not wrong in structure
    loaded.run(data)
    finish(loaded)
    assert mv_total(loaded) == pytest.approx(fact_total(loaded)) == pytest.approx(143.2)


def test_failed_view_creation_leaves_no_view_until_the_rerun(loaded, data):
    corrections(data)
    loaded.run(data)
    flaky = FailOnce(loaded.api, loaded.ns["SQL_CREATE_MV_DAILY_REVENUE"])
    loaded.exec(loaded.ns["SQL_DROP_MV_DAILY_REVENUE"])
    with pytest.raises(RuntimeError, match="injected failure"):
        loaded.exec(loaded.ns["SQL_CREATE_MV_DAILY_REVENUE"])
    flaky.remove()
    assert loaded.scalar("SELECT COUNT(*) FROM pg_matviews WHERE matviewname = 'mv_daily_revenue'") == 0
    finish(loaded)                                                  # the notebook's rerun: DROP IF EXISTS, then CREATE
    assert mv_total(loaded) == pytest.approx(fact_total(loaded))


def test_failed_refresh_leaves_a_stale_view_and_a_second_refresh_repairs_it(loaded, data):
    corrections(data)
    loaded.run(data)
    flaky = FailOnce(loaded.api, "REFRESH MATERIALIZED VIEW dw.mv_daily_revenue")
    with pytest.raises(RuntimeError, match="injected failure"):
        loaded.exec("REFRESH MATERIALIZED VIEW dw.mv_daily_revenue")
    flaky.remove()
    assert mv_total(loaded) == pytest.approx(153.2) != fact_total(loaded)
    loaded.exec("REFRESH MATERIALIZED VIEW dw.mv_daily_revenue")
    assert mv_total(loaded) == pytest.approx(fact_total(loaded)) == pytest.approx(143.2)


# ---- negative control -------------------------------------------------------------------------------------------------------
def test_negative_control_without_a_rerun_the_warehouse_stays_partially_updated(loaded, data, reference):
    """If the recovery step were not working (or not run) the comparison used above must see the difference."""
    intermediate(loaded, data, "fact_events: update changed")
    assert snapshot(loaded) != reference["after"]
