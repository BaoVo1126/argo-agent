from __future__ import annotations
import builtins
import datetime as dt
import types
import pytest
from modes.research import bank_rates, snapshots, sources
from modes.research.registry import CATALOGUE

MODULES = [sources, bank_rates, snapshots]


def _functions(module: types.ModuleType):
    for name, value in vars(module).items():
        if isinstance(value, types.FunctionType) and value.__module__ == module.__name__:
            yield name, value


def _codes(code):
    yield code
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from _codes(const)


def _unresolved(module: types.ModuleType, function) -> list[str]:
    known = set(vars(module)) | set(dir(builtins))
    missing = []
    for code in _codes(function.__code__):
        local = known | set(code.co_varnames) | set(code.co_freevars)                 | set(code.co_cellvars)
        for name in code.co_names:
            if name.startswith("_") and not name.startswith("__") and name not in local:
                missing.append(name)
    return sorted(set(missing))


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__.split(".")[-1])
def test_no_function_reaches_for_a_name_that_was_deleted(module):
    broken = {}
    for name, function in _functions(module):
        missing = _unresolved(module, function)
        if missing:
            broken[name] = missing
    assert not broken, f"{module.__name__} references missing globals: {broken}"


def test_every_catalogue_entry_builds_well_formed_sources():
    window = [dt.date(2026, 6, 1) + dt.timedelta(days=i) for i in range(90)]
    for key, entry in CATALOGUE.items():
        built = entry.build(window)
        assert built, f"{key} built no sources"
        for source in built:
            assert source.url.startswith("http"), f"{key}: {source.name} has no URL"
            assert source.plan, f"{key}: {source.name} has no plan"
            assert callable(source.extract)
            assert source.value_field == entry.value_field
            assert all(action in {"navigate", "wait_for", "click", "type",
                                  "select", "scroll", "extract", "finish"}
                       for action, _ in source.plan), f"{key}: unknown action"


def test_every_catalogue_entry_declares_a_known_category():
    from modes.research.registry import CATEGORIES
    for key, entry in CATALOGUE.items():
        assert entry.category in CATEGORIES, f"{key} has category {entry.category!r}"


def test_the_rate_board_constants_stay_in_step():
    assert bank_rates.HEADLINE_TENOR in bank_rates.TENORS
    assert set(bank_rates.BIG_FOUR) <= set(bank_rates.WANTED.values())
    assert not set(bank_rates.UNAVAILABLE) & set(bank_rates.WANTED.values())
