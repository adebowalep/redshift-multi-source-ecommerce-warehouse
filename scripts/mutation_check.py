"""Mutation check: break the notebook code in 14 deliberate ways and confirm that the test suite fails each time.
Usage (from the repository root):  python scripts/mutation_check.py $(which python)
It never modifies starter.ipynb: each mutant is written to a temporary file and selected through STARTER_NOTEBOOK."""
import json, os, subprocess, sys, tempfile
ROOT = os.getcwd(); PY = sys.argv[1]
base = json.load(open("starter.ipynb"))
MUT = [
 ("INITIALIZE no longer skips DROP", 'if kind == "DROP TABLE IF EXISTS":\n            continue', 'if False:\n            continue', "tests/test_ddl_modes.py"),
 ("rebuild guard removed", 'if mode != "REBUILD":\n        return\n    if database not in allowed_databases:', 'if True:\n        return\n    if database not in allowed_databases:', "tests/test_ddl_modes.py"),
 ("rebuild confirmation not checked", 'if confirm != f"REBUILD {database}":', 'if False:', "tests/test_ddl_modes.py"),
 ("fact update never matches", "f\"WHERE dw.{fact}.{key} = s.{key} AND ({diff})\")", "f\"WHERE dw.{fact}.{key} = s.{key} AND 1 = 0 AND ({diff})\")", "tests/test_warehouse_semantics.py"),
 ("customer geo tie-break removed", "ORDER BY src_rank, ts DESC, rid DESC) AS rn\n        FROM (\n            SELECT customer_id AS cid", "ORDER BY src_rank, ts DESC) AS rn\n        FROM (\n            SELECT customer_id AS cid", "tests/test_warehouse_semantics.py"),
 ("graph routing ignores node type", "LEFT JOIN dw.dim_customer fc ON g.from_node_type = 'Customer' AND", "LEFT JOIN dw.dim_customer fc ON", "tests/test_warehouse_semantics.py"),
 ("stale-fact check disabled", "if any(stale.values()):", "if False:", "tests/test_warehouse_semantics.py"),
 ("staging guard disabled", "if got != n:", "if False:", "tests/test_warehouse_semantics.py"),
 ("oversize guard removed", "if len(head) + len(tup) > _MAX_SQL_CHARS:", "if False:", "tests/test_redshift_api.py"),
 ("PG ingestion back to DO NOTHING", "ON CONFLICT (order_id) DO UPDATE SET {sets} WHERE {changed}", "ON CONFLICT (order_id) DO NOTHING", "tests/test_sources.py"),
 ("diagram check ignores relationships", "if c != own_key and (c.endswith(\"_sk\") or c.endswith(\"_date_key\")) and (table, c) not in have:", "if False:", "tests/test_schema_artifacts.py"),
 ("DQ check duplicate order_id weakened", "SELECT COUNT(*) FROM (SELECT order_id FROM dw.fact_orders GROUP BY 1 HAVING COUNT(*) > 1) d", "SELECT 0", "tests/test_negative_controls.py"),
 ("string escaping removed", """.replace("'", "''")""", "", "tests/test_redshift_api.py"),
 ("expired-credential detection removed", 'if e.response["Error"]["Code"] in _AUTH_ERRORS:', 'if False:', "tests/test_redshift_api.py"),
]
for name, old, new, tests in MUT:
    nb = json.loads(json.dumps(base)); hit = 0
    for c in nb["cells"]:
        if c["cell_type"] == "code":
            s = "".join(c["source"])
            if old in s:
                c["source"] = s.replace(old, new).splitlines(keepends=True); hit += 1
    if not hit: print(f"{name:45s} MUTATION NOT APPLIED"); continue
    f = tempfile.NamedTemporaryFile("w", suffix=".ipynb", delete=False); json.dump(nb, f); f.close()
    r = subprocess.run([PY, "-m", "pytest", tests, "-q", "-x", "-p", "no:cacheprovider"], env={**os.environ, "STARTER_NOTEBOOK": f.name}, capture_output=True, text=True)
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:]
    print(f"{name:45s} -> {'CAUGHT' if r.returncode != 0 else 'SURVIVED'}  ({last})")
