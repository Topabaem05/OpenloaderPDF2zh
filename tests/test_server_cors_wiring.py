from __future__ import annotations

import ast
from pathlib import Path


def test_server_app_configures_cors_from_settings() -> None:
    source = Path("src/openpdf2zh/server.py").read_text(encoding="utf-8")
    module = ast.parse(source)

    create_server_app = next(
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "create_server_app"
    )
    configure_calls = [
        node
        for node in ast.walk(create_server_app)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "configure_cors"
    ]

    assert len(configure_calls) == 1
    call = configure_calls[0]
    assert len(call.args) == 2
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "app"
    assert isinstance(call.args[1], ast.Attribute)
    assert isinstance(call.args[1].value, ast.Name)
    assert call.args[1].value.id == "resolved_settings"
    assert call.args[1].attr == "cors_allowed_origins"
