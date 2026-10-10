"""llm --compile: models are built with fastdyn.build_models (codegen/compile.py)."""

from types import SimpleNamespace

import pytest

from boardrunner.viomapper.codegen import compile as compile_module
from boardrunner.viomapper.codegen.compile import CompilationError, compile_models
from boardrunner.viomapper.codegen.llm.handlers import handle_compilation
from fastdyn.model_build import BUILT, FAILED, ModelBuildError


def _result(name, status, diagnostics=""):
    return SimpleNamespace(name=name, status=status, output=f"/out/{name}.so", diagnostics=diagnostics)


def _fake_build(results, calls):
    def build(sources, out_dir, **kwargs):
        calls.append((list(map(str, sources)), str(out_dir), kwargs))
        return SimpleNamespace(results=results, ok=all(r.status != FAILED for r in results))
    return build


def test_each_source_is_built_into_the_build_dir(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(compile_module, "build_models", _fake_build([_result("usart2", BUILT)], calls))

    ok, output = compile_models([tmp_path / "usart2.c"], tmp_path / "build")

    assert ok and output == ""
    assert calls == [([str(tmp_path / "usart2.c")], str(tmp_path / "build"), {"keep_going": True})]


def test_compiler_errors_go_back_to_the_llm(monkeypatch, tmp_path):
    results = [_result("usart2", FAILED, "usart2.c:10: error: 'x' undeclared"), _result("gpioa", BUILT)]
    monkeypatch.setattr(compile_module, "build_models", _fake_build(results, []))

    ok, error_context, is_setup_error = handle_compilation([tmp_path / "usart2.c"], tmp_path / "build")

    assert not ok and not is_setup_error
    assert "usart2.c:10: error: 'x' undeclared" in error_context
    assert error_context.startswith("Compilation Error:")


def test_a_build_that_cannot_start_is_a_setup_error(monkeypatch, tmp_path):
    def broken(*args, **kwargs):
        raise ModelBuildError("no C compiler found")
    monkeypatch.setattr(compile_module, "build_models", broken)

    with pytest.raises(CompilationError, match="no C compiler found"):
        compile_models([tmp_path / "usart2.c"], tmp_path / "build")
    assert handle_compilation([tmp_path / "usart2.c"], tmp_path / "build") == (False, "no C compiler found", True)
