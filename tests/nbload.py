"""Load the importable cells of starter.ipynb into a namespace so the notebook code can be tested without a notebook server.

The notebook stays the single source of truth: cells tagged ``importable`` are executed in notebook order. Third-party
modules that the tests do not need (cassandra-driver, neo4j, IPython, tqdm, and boto3 when absent) are replaced by tiny stubs.
"""
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = Path(os.environ.get("STARTER_NOTEBOOK", ROOT / "starter.ipynb"))      # override only for mutation checks


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


def _install_stubs():
    def try_import(name):
        try:
            __import__(name)
            return True
        except ImportError:
            return False

    if not try_import("IPython.display"):
        _stub("IPython")
        _stub("IPython.display", display=lambda *a, **k: None, Markdown=lambda s: s)
    if not try_import("cassandra.cluster"):
        _stub("cassandra")
        _stub("cassandra.cluster", Cluster=object)
        _stub("cassandra.auth", PlainTextAuthProvider=object)
        _stub("cassandra.concurrent", execute_concurrent_with_args=None)
        _stub("cassandra.query", dict_factory=None, UNSET_VALUE=object())
    if not try_import("neo4j"):
        _stub("neo4j", GraphDatabase=types.SimpleNamespace(driver=lambda *a, **k: (_ for _ in ()).throw(ConnectionError("no neo4j in tests"))))
    if not try_import("boto3"):
        class ClientError(Exception):
            def __init__(self, error_response, operation_name):
                super().__init__(str(error_response))
                self.response = error_response
                self.operation_name = operation_name
        exc = _stub("botocore.exceptions", ClientError=ClientError)
        _stub("botocore", exceptions=exc)
        _stub("boto3", Session=lambda **k: types.SimpleNamespace(client=lambda *a, **kw: None))


def load_notebook(env=None):
    """Execute every cell tagged 'importable' and return the resulting namespace (a dict)."""
    _install_stubs()
    old = {k: os.environ.get(k) for k in (env or {})}
    os.environ.update({"PROJECT_BASE_DIR": str(ROOT), **(env or {})})
    try:
        ns = {"__name__": "notebook"}
        nb = json.loads(NOTEBOOK.read_text())
        for i, cell in enumerate(nb["cells"]):
            if cell["cell_type"] == "code" and "importable" in cell.get("metadata", {}).get("tags", []):
                exec(compile("".join(cell["source"]), f"starter.ipynb[cell {i}]", "exec"), ns)
        return ns
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
