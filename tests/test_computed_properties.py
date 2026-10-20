"""Token evidence only; member ownership and Swift semantic proof belong elsewhere."""
import pytest

from hmigbot_ios.computed_properties import computed_property
from hmigbot_ios.swiftui import tokenize


def properties(source):
    tokens = tokenize(source)
    return [match for i in range(len(tokens)) if (match := computed_property(tokens, i)) is not None]


def test_can_create_and_can_invite_keep_unresolved_derived_state():
    result = properties("""struct Permissions {
    var canCreate: Bool { quota > 0 && isMember }
    var canInvite: Bool { role == .owner || isAdmin }
}""")
    assert [p["symbol"] for p in result] == ["canCreate", "canInvite"]
    assert [p["type"] for p in result] == ["Bool", "Bool"]
    for prop in result:
        assert prop["storage"] == "computed_property"
        assert prop["initializer"] is None
        assert prop["semantics"] == "unresolved"
        assert prop["resolution"] == "token_signal"
        assert prop["property_role"] == "derived_property"
        assert "value" not in prop
        assert "owner" not in prop


def test_multiline_type_and_nested_closures_have_exact_property_bounds():
    source = """var allowed:
    [String: Bool]
{
    let evaluate = { (value: Bool) in
        [value].map { item in item }
    }
    return ["create": evaluate(true)[0]]
}
var following: Int = 1
"""
    tokens = tokenize(source)
    result = computed_property(tokens, 0)
    assert result["type"] == "[ String : Bool ]"
    assert (result["line"], result["end_line"]) == (1, 8)
    evidence = result["accessor_evidence"]
    assert tokens[evidence["body_end_token"]].line == 8
    assert tokens[evidence["body_end_token"] + 1].value == "var"


def test_get_set_accessors_preserve_parameters_and_nested_bodies():
    result, = properties("""var canInvite: Bool {
    get {
        values.contains { value in value.enabled }
    }
    set(next) {
        update { target in target.enabled = next }
    }
}""")
    assert result["end_line"] == 8
    evidence = result["accessor_evidence"]
    assert evidence["kind"] == "explicit_accessors"
    assert [a["kind"] for a in evidence["accessors"]] == ["get", "set"]
    assert [a["end_line"] for a in evidence["accessors"]] == [4, 7]
    assert evidence["accessors"][1]["parameter"] == "next"


def test_multiline_async_throws_getter_and_function_type():
    result, = properties("""var callback:
    (Int) -> Bool
{
    get
    async
    throws {
        return { value in value > 0 }
    }
}""")
    assert result["type"] == "( Int ) -> Bool"
    getter, = result["accessor_evidence"]["accessors"]
    assert getter["effects"] == ["async", "throws"]
    assert (getter["line"], getter["end_line"]) == (4, 8)


def test_swiftui_body_is_marked_rendering_property_only():
    result, = properties('var body: some View { VStack { Text("{ get }") } }')
    assert result["property_role"] == "rendering_property"
    assert result["semantics"] == "unresolved"


def test_local_scope_is_not_claimed_and_function_keyword_does_not_match():
    tokens = tokenize("func work() { var local: Bool { true } }")
    assert computed_property(tokens, 0) is None
    result, = properties("func work() { var local: Bool { true } }")
    assert result["symbol"] == "local"
    assert "owner" not in result
    assert "scope" not in result


@pytest.mark.parametrize("source", [
    "var canCreate: Bool = true",
    "var canCreate: Bool = { true }()",
    "var callback: () -> Bool = { true }",
    "var count: Int { didSet { print(count) } }",
    "var count: Int { willSet(next) { print(next) } didSet {} }",
    "var count: Int { @available(*, deprecated) get { 1 } }",
    "var count: Int { _read { yield stored } }",
    "var _: Bool { true }",
    "protocol Permissions { var canCreate: Bool { get } }",
    "protocol Permissions { var canCreate: Bool { get set } }",
    "var canCreate: Bool { get async throws }",
    "var canCreate: Bool { get { true } set }",
    "var canCreate: Bool { get { true } didSet {} }",
    "var canCreate: Bool { get { true } get { false } }",
    "var canCreate: Bool { true",
    "var canCreate: Bool { get { true }",
    "var canCreate: [String: Bool { true }",
    "var canCreate: Bool {}",
    "var (canCreate, canInvite): (Bool, Bool) { (true, false) }",
    "var canCreate: Bool; func work() { true }",
    "// var canCreate: Bool { true }\nlet label = 1",
    'let label = "var canCreate: Bool { true }"',
    '/* var canCreate: Bool { true } */ let label = "get { }"',
])
def test_stored_observer_requirement_unsupported_or_incomplete_forms_are_refused(source):
    assert properties(source) == []


def test_strings_and_comments_do_not_change_accessor_boundaries():
    result, = properties('''var label: String {
    // } get set didSet
    /* { var fake: Int { get } } */
    return "} get { var fake: Bool { true }"
}''')
    assert (result["line"], result["end_line"]) == (1, 5)
    assert result["accessor_evidence"]["kind"] == "implicit_getter"


def test_out_of_range_indices_are_refused():
    tokens = tokenize("var flag: Bool { true }")
    assert computed_property(tokens, -1) is None
    assert computed_property(tokens, len(tokens)) is None
