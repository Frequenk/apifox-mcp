import pytest

from apifox_mcp.core import (
    ApifoxError,
    OpenApiRepository,
    build_minimal_spec,
    deep_merge,
    dependency_closure,
    missing_refs,
    remove_json_pointer,
    subset_mismatches,
)


def test_cache_summary_returns_metadata_without_request(fixture_document):
    repository = OpenApiRepository()
    repository._cache["1"] = (100.0, fixture_document)

    summary = repository.cache_summary("1", now=150.0)

    assert summary == {
        "available": True,
        "fresh": True,
        "age_seconds": 50.0,
        "title": "测试项目",
        "endpoint_count": 1,
        "schema_count": 3,
    }


def test_dependency_closure_only_contains_transitive_refs(fixture_document):
    closure = dependency_closure(fixture_document, ["OrderResponse"])

    assert set(closure) == {"OrderResponse", "OrderItem"}
    assert "Unrelated" not in closure


def test_dependency_closure_handles_cycles(fixture_document):
    fixture_document["components"]["schemas"].update(
        {
            "A": {"type": "object", "properties": {"b": {"$ref": "#/components/schemas/B"}}},
            "B": {"type": "object", "properties": {"a": {"$ref": "#/components/schemas/A"}}},
        }
    )

    assert list(dependency_closure(fixture_document, ["A"])) == ["A", "B"]


def test_missing_refs_reports_unresolved_reference(fixture_document):
    value = {"items": {"$ref": "#/components/schemas/Missing"}}

    assert missing_refs(value, fixture_document["components"]["schemas"]) == ["Missing"]


def test_deep_merge_replaces_arrays_and_remove_pointer():
    target = {"properties": {"name": {"type": "string"}}, "required": ["name"]}
    deep_merge(target, {"properties": {"name": {"description": "名称"}}, "required": ["id"]})
    remove_json_pointer(target, "/properties/name/type")

    assert target == {"properties": {"name": {"description": "名称"}}, "required": ["id"]}


def test_remove_pointer_rejects_unknown_path():
    with pytest.raises(ApifoxError):
        remove_json_pointer({}, "/missing")


def test_build_minimal_spec_excludes_unrelated_schema(fixture_document):
    spec = build_minimal_spec(fixture_document, [("/orders", "get")], [])

    assert set(spec["components"]["schemas"]) == {"OrderResponse", "OrderItem"}


def test_subset_mismatch_detects_apifox_ref_loss():
    expected = {"items": {"$ref": "#/components/schemas/OrderItem"}}
    actual = {"items": {"type": "object", "properties": {}}}

    assert subset_mismatches(expected, actual) == ["/items/$ref: 缺失"]
