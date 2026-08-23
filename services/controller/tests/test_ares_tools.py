"""Tests for ARES Controller Toolpack and AST Repo Map generator."""

import tempfile
from pathlib import Path
from core.knowledge.repomap import build_workspace_repomap, extract_file_symbols
from api.ares_tools import (
    ares_list_workspaces,
    ares_get_mode,
    ares_set_mode,
    ares_get_repo_map,
    dispatch_ares_tool,
)


def test_extract_file_symbols_python():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        py_file = root / "module.py"
        py_file.write_text(
            "class MyService:\n"
            "    def start(self):\n"
            "        pass\n"
            "    async def fetch_data(self):\n"
            "        pass\n\n"
            "def helper_func():\n"
            "    pass\n"
        )
        res = extract_file_symbols(py_file, root)
        assert res is not None
        assert res.language == "python"
        assert len(res.symbols) == 2
        # Class symbol
        cls_sym = res.symbols[0]
        assert cls_sym.name == "MyService"
        assert cls_sym.kind == "class"
        assert len(cls_sym.children) == 2
        # Helper func symbol
        fn_sym = res.symbols[1]
        assert fn_sym.name == "helper_func"
        assert fn_sym.kind == "function"


def test_build_workspace_repomap():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "main.py").write_text("def run(): pass\n")
        (root / "models.swift").write_text("struct User { let id: String }\n")
        (root / "app.ts").write_text("export function initialize() { return true; }\n")

        repomap = build_workspace_repomap(root)
        assert repomap["scanned_files"] == 3
        assert repomap["total_symbols"] >= 3
        assert "Codebase Symbol Map" in repomap["formatted_map"]
        assert "main.py" in repomap["formatted_map"]
        assert "models.swift" in repomap["formatted_map"]
        assert "app.ts" in repomap["formatted_map"]


def test_ares_tools_dispatch():
    # Test ares_list_workspaces
    res = dispatch_ares_tool("ares_list_workspaces", {})
    assert res.get("ok") is True
    assert isinstance(res.get("workspaces"), list)

    # Test ares_set_mode & ares_get_mode
    res_mode = dispatch_ares_tool("ares_set_mode", {"mode": "standby"})
    assert res_mode.get("ok") is True
    assert res_mode.get("state", {}).get("current_mode") == "standby"

    res_get = dispatch_ares_tool("ares_get_mode", {})
    assert res_get.get("ok") is True
    assert res_get.get("state", {}).get("current_mode") == "standby"

    # Test unknown tool
    res_unknown = dispatch_ares_tool("nonexistent_tool", {})
    assert res_unknown.get("ok") is False
