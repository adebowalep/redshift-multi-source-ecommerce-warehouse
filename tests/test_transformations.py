"""Transformation layer: conform() / coerce_by_kind() / schema-drift handling (pure pandas, no database)."""
import numpy as np
import pandas as pd
import pytest

from synth import raw_edge, raw_event, raw_order


def conform_orders(ns, rows):
    return ns["conform"](pd.DataFrame(rows), ns["ORDERS_COLSPEC"], "orders")


def test_conformed_frame_matches_staging_spec_exactly(ns):
    out = conform_orders(ns, [raw_order()])
    assert list(out.columns) == [c for c, _ in ns["ORDERS_COLSPEC"]]
    assert str(out["order_datetime"].dtype).startswith("datetime64")
    assert str(out["num_distinct_items"].dtype) == "Int64"
    assert str(out["returned"].dtype) == "boolean"


# ---- required columns / schema drift ----
def test_missing_critical_column_is_an_error(ns):
    df = pd.DataFrame([raw_order()]).drop(columns=["customer_id"])
    with pytest.raises(ValueError, match="critical column"):
        ns["conform"](df, ns["ORDERS_COLSPEC"], "orders")


def test_missing_optional_column_is_added_as_null_and_logged(ns):
    ns["SCHEMA_DRIFT_LOG"].clear()
    df = pd.DataFrame([raw_order()]).drop(columns=["campaign"])
    out = ns["conform"](df, ns["ORDERS_COLSPEC"], "orders")
    assert out["campaign"].isna().all()
    assert any("campaign" in m for m in ns["SCHEMA_DRIFT_LOG"])


def test_unexpected_extra_column_is_dropped_and_logged(ns):
    ns["SCHEMA_DRIFT_LOG"].clear()
    out = conform_orders(ns, [raw_order(surprise="x")])
    assert "surprise" not in out.columns
    assert any("surprise" in m for m in ns["SCHEMA_DRIFT_LOG"])


# ---- null handling ----
@pytest.mark.parametrize("token", ["", "nan", "NaN", "None", "null", "NULL", None, np.nan])
def test_null_tokens_become_real_nulls_never_the_string_nan(ns, token):
    out = conform_orders(ns, [raw_order(campaign=token)])
    assert out["campaign"].isna().all()
    assert not (out["campaign"] == "nan").any()


def test_null_critical_key_is_rejected(ns):
    with pytest.raises(ValueError, match="critical column customer_id"):
        conform_orders(ns, [raw_order(customer_id=None)])


# ---- invalid dates / numbers / booleans ----
def test_invalid_timestamp_raises_with_column_name(ns):
    with pytest.raises(ValueError, match="order_datetime.*un-parseable timestamp"):
        conform_orders(ns, [raw_order(order_datetime="not-a-date")])


def test_invalid_number_raises(ns):
    with pytest.raises(ValueError, match="subtotal_usd.*non-numeric"):
        conform_orders(ns, [raw_order(subtotal_usd="twelve")])


@pytest.mark.parametrize("raw,expected", [("true", True), ("FALSE", False), ("1", True), ("0", False), ("Yes", True), ("no", False), (True, True)])
def test_boolean_conversion(ns, raw, expected):
    out = conform_orders(ns, [raw_order(returned=raw)])
    assert bool(out["returned"].iloc[0]) is expected


def test_invalid_boolean_raises(ns):
    with pytest.raises(ValueError, match="returned.*un-parseable boolean"):
        conform_orders(ns, [raw_order(returned="maybe")])


# ---- id standardisation ----
def test_ids_are_trimmed_and_upper_cased(ns):
    out = conform_orders(ns, [raw_order(order_id="  ord7 ", customer_id="c9")])
    assert out["order_id"].iloc[0] == "ORD7"
    assert out["customer_id"].iloc[0] == "C9"


def test_malformed_id_is_rejected(ns):
    with pytest.raises(ValueError, match="malformed order_id"):
        conform_orders(ns, [raw_order(order_id="ORDER-7")])


def test_graph_node_ids_follow_the_node_pattern(ns):
    with pytest.raises(ValueError, match="malformed from_node_id"):
        ns["conform"](pd.DataFrame([raw_edge(from_node_id="X9")]), ns["EDGES_COLSPEC"], "edges")


# ---- categories / case rules ----
def test_category_case_is_standardised_and_unknown_values_are_kept(ns):
    out = conform_orders(ns, [raw_order(channel="  WEB ", payment_method="Card"), raw_order(order_id="ORD2", channel="new_channel")])
    assert out["channel"].tolist() == ["web", "new_channel"]      # unexpected categories are not dropped or invented
    assert out["payment_method"].iloc[0] == "card"


def test_graph_relationship_upper_case_and_node_type_title_case(ns):
    out = ns["conform"](pd.DataFrame([raw_edge(relationship="viewed", from_node_type="customer")]), ns["EDGES_COLSPEC"], "edges")
    assert out["relationship"].iloc[0] == "VIEWED" and out["from_node_type"].iloc[0] == "Customer"


# ---- duplicate natural keys ----
@pytest.mark.parametrize("name,rows,spec", [
    ("orders", [raw_order(), raw_order()], "ORDERS_COLSPEC"),
    ("events", [raw_event(), raw_event()], "EVENTS_COLSPEC"),
    ("edges", [raw_edge(), raw_edge()], "EDGES_COLSPEC"),
])
def test_duplicate_natural_key_is_rejected(ns, name, rows, spec):
    with pytest.raises(ValueError, match="duplicate"):
        ns["conform"](pd.DataFrame(rows), ns[spec], name)


# ---- decimal precision ----
def test_money_and_rates_are_rounded_to_the_ddl_precision(ns):
    out = conform_orders(ns, [raw_order(subtotal_usd=10.005, discount_rate=0.12345, tax_rate=0.123456)])
    assert out["subtotal_usd"].iloc[0] == round(10.005, 2)
    assert out["discount_rate"].iloc[0] == 0.123
    assert out["tax_rate"].iloc[0] == 0.1235


def test_compare_frames_detects_a_single_changed_cell(ns):
    a = conform_orders(ns, [raw_order(), raw_order(order_id="ORD2")])
    b = a.copy()
    assert ns["compare_frames"](a, b, "order_id").mismatches.sum() == 0
    b.loc[1, "order_total_usd"] = 1.0
    res = ns["compare_frames"](a, b, "order_id").set_index("column").mismatches
    assert res["order_total_usd"] == 1 and res.sum() == 1
