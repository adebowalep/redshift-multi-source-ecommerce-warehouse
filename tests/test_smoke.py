def test_notebook_namespace_loads(ns):
    for name in ("conform", "rs_exec", "plan_ddl", "dimension_statements", "fact_statements", "DDL_TABLES", "DQ_CHECKS", "check_diagram"):
        assert name in ns, name


def test_pipeline_runs_end_to_end_on_postgres_emulation(wh, data):
    wh.ddl()
    wh.run(data)
    assert wh.count("dw.fact_orders") == 2
    assert wh.count("dw.fact_events") == 3
    assert wh.count("dw.fact_graph_edges") == 4
