"""What the pipeline does with repeated, corrected, removed and conflicting source records (PostgreSQL emulation of Redshift)."""
import pandas as pd
import pytest

from synth import raw_edge, raw_event, raw_order


@pytest.fixture
def loaded(wh, data):
    wh.ddl()
    wh.run(data)
    return wh


def records(wh, sql):
    """Query result as plain dicts with real None for NULL (NaN != NaN would break dictionary equality)."""
    df = wh.df(sql)
    return df.astype(object).where(df.notna(), None).to_dict("records")


def fact_total(wh):
    return float(wh.scalar("SELECT SUM(order_total_usd) FROM dw.fact_orders"))


# ---------------------------------------------------------------- grain, lookups, counts
def test_new_records_produce_exactly_one_fact_row_each(loaded):
    assert (loaded.count("dw.fact_orders"), loaded.count("dw.fact_events"), loaded.count("dw.fact_graph_edges")) == (2, 3, 4)
    for fact, key in [("fact_orders", "order_id"), ("fact_events", "event_id"), ("fact_graph_edges", "edge_id")]:
        assert loaded.scalar(f"SELECT COUNT(*) - COUNT(DISTINCT {key}) FROM dw.{fact}") == 0


def test_dimension_lookups_resolve_to_the_right_member(loaded):
    row = loaded.df("""SELECT f.order_id, ch.channel, cu.customer_id, cp.campaign
                       FROM dw.fact_orders f JOIN dw.dim_channel ch ON ch.channel_sk = f.channel_sk
                       JOIN dw.dim_customer cu ON cu.customer_sk = f.customer_sk
                       LEFT JOIN dw.dim_campaign cp ON cp.campaign_sk = f.campaign_sk ORDER BY f.order_id""")
    assert row.channel.tolist() == ["web", "ios_app"] and row.customer_id.tolist() == ["C1", "C2"]
    assert row.campaign.tolist()[0] == "spring" and row.campaign.isna().tolist()[1]            # organic order keeps a NULL campaign


def test_natural_keys_stay_unique_in_every_dimension(loaded):
    ns = loaded.ns
    for table, col in [("dim_customer", "customer_id"), ("dim_product", "product_id"), ("dim_date", "date_key")] + [(t, c) for t, c, _ in ns["SIMPLE_DIMS"]]:
        assert loaded.scalar(f"SELECT COUNT(*) - COUNT(DISTINCT {col}) FROM dw.{table}") == 0, table


def test_financial_totals_reconcile_between_staging_and_fact(loaded):
    assert float(loaded.scalar("SELECT SUM(order_total_usd) FROM stg.orders_raw")) == fact_total(loaded) == pytest.approx(153.2)
    assert float(loaded.scalar("SELECT SUM(unit_price_usd * quantity) FROM stg.edges_raw")) == \
        float(loaded.scalar("SELECT SUM(unit_price_usd * quantity) FROM dw.fact_graph_edges"))


# ---------------------------------------------------------------- repeated identical run
def test_unchanged_rerun_adds_and_rewrites_nothing(loaded, data):
    snapshot = {t: records(loaded, f"SELECT xmin::text AS x, * FROM dw.{t} ORDER BY 2")
                for t in ("fact_orders", "fact_events", "fact_graph_edges", "dim_customer", "dim_product")}
    loaded.run(data)                                                       # same data again
    again = {t: records(loaded, f"SELECT xmin::text AS x, * FROM dw.{t} ORDER BY 2") for t in snapshot}
    assert again == snapshot                                               # same rows, same surrogate keys, no row version touched


# ---------------------------------------------------------------- corrections
def test_corrected_order_total_reaches_the_fact_and_nothing_else_changes(loaded, data):
    sk_before = loaded.scalar("SELECT order_sk FROM dw.fact_orders WHERE order_id = 'ORD1'")
    other_before = records(loaded, "SELECT * FROM dw.fact_orders WHERE order_id = 'ORD2'")
    data.order("ORD1")["order_total_usd"] = 92.2                           # source corrected 102.2 -> 92.2
    loaded.run(data)
    assert float(loaded.scalar("SELECT order_total_usd FROM dw.fact_orders WHERE order_id = 'ORD1'")) == 92.2
    assert loaded.count("dw.fact_orders") == 2 and loaded.scalar("SELECT order_sk FROM dw.fact_orders WHERE order_id = 'ORD1'") == sk_before
    assert records(loaded, "SELECT * FROM dw.fact_orders WHERE order_id = 'ORD2'") == other_before
    assert fact_total(loaded) == pytest.approx(143.2)


def test_materialized_view_is_stale_until_refreshed_after_a_correction(loaded, data):
    loaded.exec("CREATE MATERIALIZED VIEW dw.mv_daily_revenue AS SELECT order_date_key, COUNT(*) AS orders, SUM(order_total_usd) AS revenue_usd FROM dw.fact_orders GROUP BY 1")
    data.order("ORD1")["order_total_usd"] = 92.2
    loaded.run(data)
    mv = lambda: float(loaded.scalar("SELECT SUM(revenue_usd) FROM dw.mv_daily_revenue"))
    assert mv() == pytest.approx(153.2) != fact_total(loaded)              # documented: dependent objects need REFRESH
    loaded.exec("REFRESH MATERIALIZED VIEW dw.mv_daily_revenue")
    assert mv() == pytest.approx(fact_total(loaded)) == pytest.approx(143.2)


def test_corrected_dimension_attribute_updates_in_place_without_a_new_surrogate_key(loaded, data):
    sk = loaded.scalar("SELECT customer_sk FROM dw.dim_customer WHERE customer_id = 'C1'")
    data.order("ORD1")["country"], data.order("ORD1")["state"] = "CA", "ON"          # customer moved: latest order says CA/ON
    data.edge("EDGE4")["customer_segment"] = "Platinum"                              # the latest edge leaving C1 carries the segment
    loaded.run(data)
    row = loaded.df("SELECT * FROM dw.dim_customer WHERE customer_id = 'C1'")
    assert len(row) == 1 and row.customer_sk[0] == sk and (row.country[0], row.state[0], row.customer_segment[0]) == ("CA", "ON", "Platinum")
    assert loaded.scalar("SELECT customer_sk FROM dw.fact_orders WHERE order_id = 'ORD1'") == sk            # facts keep pointing at the same member
    assert bool(row.is_current[0]) and row.effective_to.isna()[0]                                           # Type 1: no history rows


def test_corrected_product_attribute_updates_in_place(loaded, data):
    data.edge("EDGE3")["unit_price_usd"], data.edge("EDGE3")["price_bucket"] = 24.5, "mid"      # EDGE3 is the latest edge naming P1
    loaded.run(data)
    row = loaded.df("SELECT * FROM dw.dim_product WHERE product_id = 'P1'")
    assert len(row) == 1 and float(row.current_unit_price_usd[0]) == 24.5 and row.price_bucket[0] == "mid"


def test_corrected_graph_relationship_is_applied(loaded, data):
    data.edge("EDGE1")["relationship"], data.edge("EDGE1")["edge_strength"], data.edge("EDGE1")["quantity"] = "ADDED_TO_CART", 0.9, 3
    loaded.run(data)
    row = loaded.df("SELECT relationship, edge_strength, quantity FROM dw.fact_graph_edges WHERE edge_id = 'EDGE1'").iloc[0]
    assert row.relationship == "ADDED_TO_CART" and float(row.edge_strength) == 0.9 and row.quantity == 3
    assert loaded.count("dw.fact_graph_edges") == 4


def assert_event_corrected(wh, before, expected_dwell):
    """Each condition is asserted on its own, so one cannot mask another (an `a and b or c` expression once did)."""
    rows = wh.df("SELECT event_sk, event_id, dwell_seconds, product_sk, category FROM dw.fact_events WHERE event_id = 'EVT2'")
    assert len(rows) == 1                                                  # corrected in place, no duplicate event
    row = rows.iloc[0]
    assert row.dwell_seconds == expected_dwell                             # the corrected value was applied
    assert pd.isna(row.product_sk)                                         # a correction to NULL replaced the old key
    assert pd.isna(row.category)                                           # ... and the old category
    assert row.event_sk == before.event_sk                                 # the existing row (and surrogate key) was updated, not re-inserted
    assert wh.count("dw.fact_events") == 3                                 # event count unchanged
    assert wh.scalar("SELECT COUNT(*) - COUNT(DISTINCT event_id) FROM dw.fact_events") == 0


def test_corrected_event_is_applied_and_a_null_can_replace_a_value(loaded, data):
    before = loaded.df("SELECT event_sk, dwell_seconds, product_sk, category FROM dw.fact_events WHERE event_id = 'EVT2'").iloc[0]
    assert before.dwell_seconds != 99 and pd.notna(before.product_sk) and pd.notna(before.category)       # the correction really changes something
    event = data.event("EVT2")
    event["dwell_seconds"], event["product_id"], event["category"] = 99, None, None
    loaded.run(data)
    assert_event_corrected(loaded, before, 99)


def test_the_corrected_event_check_fails_when_the_applied_value_is_wrong(loaded, data):
    """Negative control: the same checks must reject a wrong dwell_seconds (the old assertion would have accepted it)."""
    before = loaded.df("SELECT event_sk, dwell_seconds, product_sk, category FROM dw.fact_events WHERE event_id = 'EVT2'").iloc[0]
    event = data.event("EVT2")
    event["dwell_seconds"], event["product_id"], event["category"] = 98, None, None                      # wrong value, NULLs as before
    loaded.run(data)
    with pytest.raises(AssertionError):
        assert_event_corrected(loaded, before, 99)


def test_new_record_added_between_runs_is_inserted_once(loaded, data):
    data.orders.append(raw_order(order_id="ORD3", customer_id="C3", order_total_usd=102.2))
    loaded.run(data)
    loaded.run(data)
    assert loaded.count("dw.fact_orders") == 3 and loaded.count("dw.dim_customer") == 3


# ---------------------------------------------------------------- removal and interruption
def test_removed_source_record_is_detected_not_silently_kept_and_not_deleted(loaded, data):
    data.orders = [o for o in data.orders if o["order_id"] != "ORD2"]
    loaded.stage(data)
    with pytest.raises(RuntimeError, match=r"source records were removed.*'fact_orders': 1"):
        loaded.ns["check_no_stale_facts"]()
    loaded.load()                                                          # even if someone loads anyway: documented, no delete logic
    assert loaded.count("dw.fact_orders") == 2


def test_clean_state_passes_the_stale_check(loaded):
    loaded.ns["check_no_stale_facts"]()


def test_interrupted_staging_load_is_detected_and_a_rerun_recovers(loaded, data):
    before = (fact_total(loaded), loaded.count("dw.fact_graph_edges"))
    ns = loaded.ns
    data.edges.extend(raw_edge(edge_id=f"EDGE{n}", relationship="VIEWED") for n in range(10, 16))
    data.event("EVT1")["dwell_seconds"] = 77                                 # an upstream correction that must NOT be applied from partial staging
    orders, events, edges = data.frames()
    frames = {"stg.orders_raw": (ns["ORDERS_COLSPEC"], ns["conform"](orders, ns["ORDERS_COLSPEC"], "orders")),
              "stg.events_raw": (ns["EVENTS_COLSPEC"], ns["conform"](events, ns["EVENTS_COLSPEC"], "events")),
              "stg.edges_raw": (ns["EDGES_COLSPEC"], ns["conform"](edges, ns["EDGES_COLSPEC"], "edges"))}
    ns["BATCH_SIZE"] = 3
    for t in ("stg.orders_raw", "stg.events_raw"):
        ns["rs_batch_insert"](t, *frames[t])
    inserts = {"n": 0}
    real = loaded.api.execute_statement

    def flaky(Sql, **kw):                                                   # the connection dies on the 2nd edge batch
        if Sql.startswith("INSERT INTO stg.edges_raw") or Sql.startswith("INSERT INTO public.stg_edges_raw"):
            inserts["n"] += 1
            if inserts["n"] == 2:
                raise RuntimeError("connection reset")
        return real(Sql, **kw)
    loaded.api.execute_statement = flaky
    with pytest.raises(RuntimeError, match="connection reset"):
        ns["rs_batch_insert"]("stg.edges_raw", *frames["stg.edges_raw"])
    loaded.api.execute_statement = real

    assert 0 < loaded.count("stg.edges_raw") < len(edges)                    # staging is partial
    with pytest.raises(RuntimeError, match="staging is incomplete, facts NOT touched"):
        ns["check_staging_complete"]({"stg.orders_raw": len(orders), "stg.events_raw": len(events), "stg.edges_raw": len(edges)})
    assert (fact_total(loaded), loaded.count("dw.fact_graph_edges")) == before
    assert loaded.scalar("SELECT dwell_seconds FROM dw.fact_events WHERE event_id = 'EVT1'") == 30       # facts untouched

    ns["BATCH_SIZE"] = 1000                                                  # rerun the whole run
    loaded.run(data)
    assert loaded.count("dw.fact_graph_edges") == 10 and loaded.scalar("SELECT dwell_seconds FROM dw.fact_events WHERE event_id = 'EVT1'") == 77


# ---------------------------------------------------------------- deterministic attribute selection
def _customer(wh, cid):
    r = wh.df(f"SELECT country, state, customer_segment, is_logged_in FROM dw.dim_customer WHERE customer_id = '{cid}'").iloc[0]
    return r.country, r.state, bool(r.is_logged_in) if r.is_logged_in is not None else None


@pytest.mark.parametrize("reverse", [False, True])
def test_equal_timestamps_with_conflicting_locations_resolve_identically_regardless_of_row_order(wh, data, reverse):
    wh.ddl()
    rows = [raw_order(order_id="ORD10", customer_id="C9", country="US", state="CA", order_datetime="2025-02-01 10:00:00", ship_datetime="2025-02-02 10:00:00"),
            raw_order(order_id="ORD11", customer_id="C9", country="DE", state="BE", order_datetime="2025-02-01 10:00:00", ship_datetime="2025-02-02 10:00:00")]
    data.orders = rows[::-1] if reverse else rows
    wh.run(data)
    assert _customer(wh, "C9")[:2] == ("DE", "BE")        # higher order_id wins the tie; country and state come from ONE record


def test_orders_take_precedence_over_newer_events_for_geography(wh, data):
    wh.ddl()
    data.orders = [raw_order(order_id="ORD10", customer_id="C9", country="US", state="CA", order_datetime="2025-01-01 10:00:00")]
    data.events = [raw_event(event_id="EVT10", customer_id="C9", country="DE", state="BE", event_ts="2025-03-01 10:00:00")]
    wh.run(data)
    assert _customer(wh, "C9")[:2] == ("US", "CA")


def test_events_supply_geography_when_the_customer_has_no_order(wh, data):
    wh.ddl()
    data.events = [raw_event(event_id="EVT10", customer_id="C8", country="DE", state=None, event_ts="2025-03-01 10:00:00")]
    wh.run(data)
    assert _customer(wh, "C8")[:2] == ("DE", None)


def test_latest_record_with_missing_country_is_skipped_not_used(wh, data):
    wh.ddl()
    data.orders = [raw_order(order_id="ORD10", customer_id="C9", country="US", state="CA", order_datetime="2025-01-01 10:00:00"),
                   raw_order(order_id="ORD11", customer_id="C9", country=None, state=None, order_datetime="2025-06-01 10:00:00")]
    wh.run(data)
    assert _customer(wh, "C9")[:2] == ("US", "CA")


def test_login_flag_and_segment_ties_are_deterministic(wh, data):
    wh.ddl()
    data.events = [raw_event(event_id="EVT10", customer_id="C9", is_logged_in=False, event_ts="2025-03-01 10:00:00"),
                   raw_event(event_id="EVT11", customer_id="C9", is_logged_in=True, event_ts="2025-03-01 10:00:00")]
    data.edges = [raw_edge(edge_id="EDGE10", from_node_id="C9", customer_segment="Silver", timestamp="2025-03-01 10:00:00"),
                  raw_edge(edge_id="EDGE11", from_node_id="C9", customer_segment="Gold", timestamp="2025-03-01 10:00:00")]
    wh.run(data)
    row = wh.df("SELECT customer_segment, is_logged_in FROM dw.dim_customer WHERE customer_id = 'C9'").iloc[0]
    assert row.customer_segment == "Gold" and bool(row.is_logged_in) is True      # EDGE11 / EVT11 are the higher ids


@pytest.mark.parametrize("reverse", [False, True])
def test_product_price_bucket_and_category_ties_are_deterministic(wh, data, reverse):
    wh.ddl()
    edges = [raw_edge(edge_id="EDGE10", from_node_id="C1", to_node_id="P9", product_id="P9", unit_price_usd=10.0, price_bucket="low", category="Toys", timestamp="2025-03-01 10:00:00"),
             raw_edge(edge_id="EDGE11", from_node_id="C1", to_node_id="P9", product_id="P9", unit_price_usd=99.0, price_bucket="high", category="Books", timestamp="2025-03-01 10:00:00")]
    data.edges = edges[::-1] if reverse else edges
    wh.run(data)
    row = wh.df("SELECT category, price_bucket, current_unit_price_usd FROM dw.dim_product WHERE product_id = 'P9'").iloc[0]
    assert (row.category, row.price_bucket, float(row.current_unit_price_usd)) == ("Books", "high", 99.0)


def test_graph_category_beats_event_category_and_latest_graph_price_wins(wh, data):
    wh.ddl()
    data.events = [raw_event(event_id="EVT10", product_id="P9", category="Garden", event_ts="2025-06-01 10:00:00")]
    data.edges = [raw_edge(edge_id="EDGE10", to_node_id="P9", product_id="P9", category="Toys", unit_price_usd=10.0, timestamp="2025-01-01 10:00:00"),
                  raw_edge(edge_id="EDGE11", to_node_id="P9", product_id="P9", category="Toys", unit_price_usd=12.0, timestamp="2025-02-01 10:00:00")]
    wh.run(data)
    row = wh.df("SELECT category, current_unit_price_usd FROM dw.dim_product WHERE product_id = 'P9'").iloc[0]
    assert row.category == "Toys" and float(row.current_unit_price_usd) == 12.0


# ---------------------------------------------------------------- graph node routing
def test_node_type_decides_the_dimension_not_the_id_shape(wh, data):
    wh.ddl()
    data.edges = [raw_edge(edge_id="EDGE10", from_node_id="C1", from_node_type="Product", to_node_id="P1", to_node_type="Product",
                           relationship="ALSO_BOUGHT_WITH", product_id=None)]              # a PRODUCT whose id looks like a customer id
    data.orders = [raw_order(customer_id="C1")]
    wh.run(data)
    r = wh.df("SELECT from_customer_sk, to_customer_sk, from_product_sk, to_product_sk FROM dw.fact_graph_edges").iloc[0]
    assert r.from_customer_sk is None or str(r.from_customer_sk) == "nan"             # not resolved against dim_customer, although C1 is a customer too
    assert wh.scalar("SELECT COUNT(*) FROM dw.dim_product WHERE product_id = 'C1'") == 1 and r.from_product_sk is not None
    assert wh.scalar("SELECT COUNT(*) FROM dw.dim_customer WHERE customer_id = 'P1'") == 0


def test_all_three_edge_shapes_resolve_to_the_right_keys(loaded):
    r = loaded.df("""SELECT edge_id, from_customer_sk IS NOT NULL AS fc, to_customer_sk IS NOT NULL AS tc,
                            from_product_sk IS NOT NULL AS fp, to_product_sk IS NOT NULL AS tp FROM dw.fact_graph_edges ORDER BY edge_id""")
    got = {row.edge_id: (bool(row.fc), bool(row.tc), bool(row.fp), bool(row.tp)) for row in r.itertuples()}
    assert got == {"EDGE1": (True, False, False, True),      # Customer -> Product
                   "EDGE2": (True, False, False, True),
                   "EDGE3": (False, False, True, True),      # Product -> Product
                   "EDGE4": (True, True, False, False)}      # Customer -> Customer


def test_order_typed_endpoint_has_no_surrogate_key_and_is_not_forced_into_a_dimension(wh, data):
    wh.ddl()
    data.edges = [raw_edge(edge_id="EDGE10", from_node_id="ORD1", from_node_type="Order", to_node_id="P1", relationship="PURCHASED")]
    wh.run(data)
    r = wh.df("SELECT from_customer_sk, from_product_sk FROM dw.fact_graph_edges").iloc[0]
    assert str(r.from_customer_sk) in ("None", "nan") and str(r.from_product_sk) in ("None", "nan")


def test_missing_optional_references_stay_null(loaded):
    r = loaded.df("SELECT product_sk FROM dw.fact_events WHERE event_id = 'EVT3'").iloc[0]      # page_view without a product
    assert str(r.product_sk) in ("None", "nan")
