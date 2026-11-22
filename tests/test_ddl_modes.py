"""Setup safety: INITIALIZE / LOAD / REBUILD, the rebuild guard and the two naming conventions."""
import psycopg2
import pytest

# ---------------------------------------------------------------- pure planning logic
def logical_tables(ns):
    return ns["project_tables"](ns["DDL_TABLES"])


def test_project_has_18_tables_and_the_ddl_only_touches_them(ns):
    assert len(logical_tables(ns)) == 18
    touched = ns["touched_objects"](ns["DDL_STATEMENTS"])
    assert touched - logical_tables(ns) == {"dw.v_lookup_customer", "dw.v_lookup_product"}      # the two optional helper views
    assert {t.split(".")[0] for t in touched} == {"stg", "dw"}


def test_initialize_on_an_empty_database_creates_everything_and_never_drops(ns):
    plan = ns["plan_ddl"](ns["DDL_STATEMENTS"], "INITIALIZE", set())
    assert not any(s.upper().startswith("DROP") for s in plan)
    assert sum(s.upper().startswith("CREATE TABLE") for s in plan) == 18


def test_initialize_keeps_tables_that_exist(ns):
    existing = logical_tables(ns)
    plan = ns["plan_ddl"](ns["DDL_STATEMENTS"], "INITIALIZE", existing)
    assert not any(s.upper().startswith(("DROP", "CREATE TABLE")) for s in plan)


def test_initialize_creates_only_the_missing_tables(ns):
    existing = logical_tables(ns) - {"dw.dim_channel"}
    plan = ns["plan_ddl"](ns["DDL_STATEMENTS"], "INITIALIZE", existing)
    creates = [s for s in plan if s.upper().startswith("CREATE TABLE")]
    assert len(creates) == 1 and "dw.dim_channel" in creates[0]


def test_load_needs_every_table_and_executes_nothing(ns):
    assert ns["plan_ddl"](ns["DDL_STATEMENTS"], "LOAD", logical_tables(ns)) == []
    with pytest.raises(RuntimeError, match="LOAD but 1 project table"):
        ns["plan_ddl"](ns["DDL_STATEMENTS"], "LOAD", logical_tables(ns) - {"dw.fact_orders"})


def test_rebuild_plans_every_statement_including_the_drops(ns):
    plan = ns["plan_ddl"](ns["DDL_STATEMENTS"], "REBUILD", logical_tables(ns))
    assert plan == list(ns["DDL_STATEMENTS"]) and sum(s.upper().startswith("DROP TABLE") for s in plan) == 18


def test_unknown_mode_is_rejected(ns):
    with pytest.raises(ValueError):
        ns["plan_ddl"](ns["DDL_STATEMENTS"], "REBUILT", set())
    with pytest.raises(ValueError):
        ns["check_rebuild_allowed"]("DROP_ALL", "ecom", {"ecom"}, "")


@pytest.mark.parametrize("mode", ["INITIALIZE", "LOAD"])
def test_non_destructive_modes_need_no_confirmation(ns, mode):
    ns["check_rebuild_allowed"](mode, "production_db", {"ecom"}, "")


def test_rebuild_is_fail_closed(ns):
    ok = ns["check_rebuild_allowed"]
    ok("REBUILD", "ecom", {"ecom"}, "REBUILD ecom")                                   # the only passing combination
    with pytest.raises(PermissionError, match="not in REBUILD_ALLOWED_DATABASES"):
        ok("REBUILD", "prod", {"ecom"}, "REBUILD prod")                                # right confirmation, wrong database
    with pytest.raises(PermissionError, match="REBUILD_CONFIRM"):
        ok("REBUILD", "ecom", {"ecom"}, "")                                            # allowed database, no confirmation
    with pytest.raises(PermissionError, match="REBUILD_CONFIRM"):
        ok("REBUILD", "ecom", {"ecom"}, "REBUILD other")                               # confirmation for another database
    with pytest.raises(PermissionError):
        ok("REBUILD", "ecom", set(), "REBUILD ecom")                                   # empty allow-list


def test_detect_naming(ns):
    project, detect = logical_tables(ns), ns["detect_naming"]
    assert detect([], project) is None
    assert detect([("dw", "fact_orders")], project) == "schemas"
    assert detect([("public", "dw_fact_orders")], project) == "public_fallback"
    assert detect([("public", "customers"), ("public", "dw_unrelated"), ("sales", "fact_orders")], project) is None   # unrelated objects ignored
    with pytest.raises(RuntimeError, match="BOTH naming conventions"):
        detect([("dw", "fact_orders"), ("public", "stg_orders_raw")], project)


# ---------------------------------------------------------------- PostgreSQL emulation of the Data API
def tables(wh):
    return set(wh.df("SELECT schemaname || '.' || tablename AS t FROM pg_tables WHERE schemaname IN ('stg','dw','public')").t)


def test_fresh_setup_creates_all_18_tables_in_schemas(wh):
    wh.ddl()
    assert not wh.fallback
    assert {t for t in tables(wh) if t.startswith(("stg.", "dw."))} == logical_tables(wh.ns)


def test_repeated_setup_keeps_the_data(wh, data):
    wh.ddl()
    wh.run(data)
    before = wh.count("dw.fact_orders"), wh.count("dw.dim_customer"), wh.count("stg.orders_raw")
    executed = wh.ddl()                                                   # second INITIALIZE
    assert (wh.count("dw.fact_orders"), wh.count("dw.dim_customer"), wh.count("stg.orders_raw")) == before
    assert before[0] == 2 and executed <= 4                                # only CREATE SCHEMA x2 and the two CREATE OR REPLACE VIEW


def test_initialize_after_a_manual_drop_recreates_only_that_table(wh, data):
    wh.ddl()
    wh.run(data)
    wh.exec("DROP TABLE dw.dim_ab_variant")
    wh.ddl()
    assert wh.count("dw.dim_ab_variant") == 0 and wh.count("dw.fact_orders") == 2


def test_load_mode_fails_on_an_empty_database_and_changes_nothing_when_tables_exist(wh, data):
    with pytest.raises(RuntimeError, match="LOAD but"):
        wh.ddl("LOAD")
    wh.ddl()
    wh.run(data)
    assert wh.ddl("LOAD") == 0
    assert wh.count("dw.fact_orders") == 2


def test_rebuild_without_confirmation_is_refused_and_data_survives(wh, data):
    wh.ddl()
    wh.run(data)
    with pytest.raises(PermissionError):
        wh.ddl("REBUILD", confirm="")
    with pytest.raises(PermissionError):
        wh.ddl("REBUILD", allowed={"some_other_db"})
    assert wh.count("dw.fact_orders") == 2 and wh.count("dw.dim_customer") > 0


def test_confirmed_rebuild_drops_the_materialized_view_and_recreates_empty_tables(wh, data):
    wh.ddl()
    wh.run(data)
    wh.exec("CREATE MATERIALIZED VIEW dw.mv_daily_revenue AS SELECT order_date_key, SUM(order_total_usd) AS revenue_usd FROM dw.fact_orders GROUP BY 1")
    wh.ddl("REBUILD")
    assert wh.count("dw.fact_orders") == 0 and wh.count("dw.dim_customer") == 0
    assert wh.scalar("SELECT COUNT(*) FROM pg_matviews WHERE matviewname = 'mv_daily_revenue'") == 0


def test_rebuild_leaves_unrelated_objects_alone(wh, data):
    wh.ddl()
    wh.exec("CREATE SCHEMA other")
    wh.exec("CREATE TABLE other.notes (id INT)")
    wh.exec("CREATE TABLE public.customers_backup (id INT)")
    wh.exec("CREATE TABLE dw.my_own_table (id INT)")                      # unrelated table inside a project schema
    wh.exec("INSERT INTO other.notes VALUES (1)")
    wh.ddl("REBUILD")
    wh.ddl("INITIALIZE")
    t = tables(wh)
    assert {"public.customers_backup", "dw.my_own_table"} <= t
    assert wh.count("other.notes") == 1


def test_only_project_tables_are_touched_by_the_ddl_statements(wh):
    wh.ddl("REBUILD")
    touched = wh.ns["touched_objects"]([s for s in wh.api.log if s.upper().startswith(("DROP TABLE", "CREATE TABLE", "CREATE OR REPLACE VIEW"))])
    assert touched <= logical_tables(wh.ns) | {"dw.v_lookup_customer", "dw.v_lookup_product"}


# ---- lab mode: CREATE SCHEMA is denied -> public.stg_* / public.dw_* everywhere
def test_lab_fallback_uses_public_prefixed_names_for_every_object(wh_lab, data):
    wh_lab.ddl()
    assert wh_lab.fallback
    names = {t.split(".")[1] for t in tables(wh_lab) if t.startswith("public.")}
    assert {"stg_orders_raw", "dw_fact_orders", "dw_dim_customer"} <= names
    assert not {t for t in tables(wh_lab) if t.startswith(("stg.", "dw."))}                 # never mixed
    wh_lab.run(data)
    assert wh_lab.count("dw.fact_orders") == 2                                                # logical name works through the mapping
    assert int(wh_lab.scalar("SELECT COUNT(*) FROM public.dw_fact_orders")) == 2


def test_lab_fallback_second_run_is_detected_from_the_database_and_keeps_data(wh_lab, data):
    wh_lab.ddl()
    wh_lab.run(data)
    wh_lab.ns["NAMING"]["public_fallback"] = False                                           # fresh kernel: nothing remembered
    wh_lab.api.deny_create_schema = False                                                    # even if schemas could be created now ...
    wh_lab.ddl()
    assert wh_lab.fallback and wh_lab.count("dw.fact_orders") == 2                           # ... the existing naming wins
    assert not {t for t in tables(wh_lab) if t.startswith(("stg.", "dw."))}


def test_lab_rebuild_is_guarded_and_keeps_unrelated_public_tables(wh_lab, data):
    wh_lab.ddl()
    wh_lab.run(data)
    wh_lab.exec("CREATE TABLE public.dw_unrelated (id INT)")                                  # looks like a project name but is not one
    with pytest.raises(PermissionError):
        wh_lab.ddl("REBUILD", confirm="yes")
    assert wh_lab.count("dw.fact_orders") == 2
    wh_lab.ddl("REBUILD")
    assert wh_lab.count("dw.fact_orders") == 0 and "public.dw_unrelated" in tables(wh_lab)


def test_mixed_naming_in_one_database_is_refused(wh):
    wh.ddl()
    wh.exec("CREATE TABLE public.dw_fact_orders (order_id VARCHAR(32))")                      # a second convention appears
    with pytest.raises(RuntimeError, match="BOTH naming conventions"):
        wh.ddl()
