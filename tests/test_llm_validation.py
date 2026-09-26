"""Pre-dispatch argument validation (S8).

Phase 1b of docs/archive/model-backends.md. The rule table and its evaluation
order are section S8; property names are checked against the live registry.
"""

from __future__ import annotations

from tools.llm import validation
from tools.registry import TOOL_SCHEMAS

INDEX = validation.index_schemas(TOOL_SCHEMAS)


def _fault(name, args):
    return validation.validate_tool_call(name, args, INDEX)


# --- index --------------------------------------------------------------


def test_index_schemas_is_keyed_by_tool_name():
    assert "search_vizier" in INDEX
    assert INDEX["search_ned"]["type"] == "object"
    assert set(INDEX) == {s["name"] for s in TOOL_SCHEMAS}


# --- the rule table, in order ---------------------------------------


def test_unknown_tool_name():
    fault = _fault("teleport", {})
    assert fault is not None and fault.type == "unknown_tool"


def test_arguments_that_are_not_a_mapping():
    fault = _fault("search_ned", ["name", "M31"])
    assert fault.type == "schema_violation"


def test_missing_required_property():
    fault = _fault("search_ned", {})  # `name` is required
    assert fault.type == "schema_violation"
    assert "name" in fault.detail


def test_a_property_not_in_the_schema():
    fault = _fault("search_ned", {"name": "M31", "bogus": 1})
    assert fault.type == "schema_violation"
    assert "bogus" in fault.detail


def test_stringified_null_on_a_null_accepting_property():
    for spelling in ("None", "null", "nil", "NULL", "none", "NuLl"):
        fault = _fault("search_vizier", {"max_catalogs": spelling})
        assert fault is not None, spelling
        assert fault.type == "stringified_null", spelling


def test_stringified_null_beats_the_type_check_in_evaluation_order():
    # "None" is both a string (wrong type for integer) and a stringy null;
    # the stringy-null rule is evaluated first.
    fault = _fault("search_mast", {"name": "M31", "max_observations": "None"})
    assert fault.type == "stringified_null"


def test_the_string_None_on_a_non_null_property_is_a_plain_type_violation():
    fault = _fault("search_ned", {"name": "M31", "table": "None"})
    # table is an enum string; "None" is a valid string type but not in the enum
    assert fault.type == "schema_violation"


def test_wrong_json_type():
    fault = _fault("search_mast", {"name": "M31", "max_observations": "lots"})
    assert fault.type == "schema_violation"


def test_value_not_in_enum():
    fault = _fault("search_ned", {"name": "M31", "table": "spectra"})
    assert fault.type == "schema_violation"
    assert "enum" in fault.detail or "table" in fault.detail


def test_array_element_type_mismatch():
    fault = _fault("search_simbad", {"name": "M31", "fields": ["ra", 5, "dec"]})
    assert fault.type == "schema_violation"


def test_a_boolean_where_an_integer_is_declared_is_rejected():
    fault = _fault("search_mast", {"name": "M31", "max_observations": True})
    assert fault is not None
    assert fault.type == "schema_violation"


# --- what passes ------------------------------------------------------


def test_a_valid_call_returns_no_fault():
    assert _fault("search_ned", {"name": "NGC 6334", "table": "photometry"}) is None


def test_json_null_on_a_null_accepting_property_is_the_correct_usage():
    assert _fault("search_vizier", {"max_catalogs": None}) is None


def test_a_real_integer_on_an_integer_or_null_union_is_fine():
    assert _fault("search_vizier", {"max_catalogs": 12}) is None


def test_an_integer_is_accepted_where_number_is_declared():
    assert _fault("search_ned", {"name": "M31", "min_frequency_hz": 3}) is None


def test_a_missing_optional_property_is_fine():
    assert _fault("search_vizier", {"target": "M31"}) is None


def test_an_absent_properties_schema_does_not_police_extra_arguments_without_a_func():
    index = validation.index_schemas(
        [{"name": "fake_lookup", "input_schema": {"type": "object"}}]
    )
    assert validation.validate_tool_call("fake_lookup", {"target": "M31"}, index) is None


def test_an_absent_properties_schema_falls_back_to_the_function_signature():
    index = validation.index_schemas(
        [{"name": "no_args", "input_schema": {"type": "object"}}]
    )

    def no_args(directory=None):
        return None

    # an accepted argument passes
    assert validation.validate_tool_call(
        "no_args", {"directory": "/tmp"}, index, func=no_args
    ) is None
    # a junk argument the callable rejects is a schema_violation, not a crash
    fault = validation.validate_tool_call(
        "no_args", {"bogus": 1}, index, func=no_args
    )
    assert fault is not None and fault.type == "schema_violation"


def test_a_declared_empty_properties_schema_takes_no_arguments():
    """Second review: the signature fallback let a model reach `directory` on
    list_pulsar_scans and four other listers, which declare no properties."""
    index = validation.index_schemas(
        [{"name": "no_args", "input_schema": {"type": "object", "properties": {}}}]
    )

    def no_args(directory=None):
        return None

    fault = validation.validate_tool_call(
        "no_args", {"directory": "/tmp"}, index, func=no_args
    )
    assert fault is not None and fault.type == "schema_violation"
    assert validation.validate_tool_call("no_args", {}, index, func=no_args) is None


def test_no_registered_lister_accepts_an_undeclared_directory():
    from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

    index = validation.index_schemas(TOOL_SCHEMAS)
    for name in ("list_pulsar_scans", "list_zeropoint_references", "list_variable_star_fixtures"):
        fault = validation.validate_tool_call(
            name, {"directory": "/"}, index, func=TOOL_FUNCTIONS[name]
        )
        assert fault is not None and fault.type == "schema_violation", name


def test_a_schema_with_no_registered_function_is_an_unknown_tool_fault():
    index = validation.index_schemas(
        [{"name": "orphan", "input_schema": {"type": "object", "properties": {}}}]
    )
    fault = validation.validate_tool_call("orphan", {}, index, func=None)
    assert fault is not None and fault.type == "unknown_tool"


def test_the_call_id_is_carried_onto_the_fault_when_given():
    fault = validation.validate_tool_call("teleport", {}, INDEX, call_id="call_7")
    assert fault.call_id == "call_7"
    assert fault.tool_name == "teleport"
