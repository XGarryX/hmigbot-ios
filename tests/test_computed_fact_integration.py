"""Computed members add unresolved source signals without changing legacy facts."""
from hmigbot_ios import ios_facts


def capture(tmp_path, source):
    path = tmp_path / 'Permissions.swift'
    path.write_text(source, encoding='utf-8')
    return ios_facts.extract(tmp_path)


def computed(graph):
    return [fact for fact in graph['facts']
            if fact['kind'] == 'state' and fact['value'].get('storage') == 'computed_property']


def test_permissions_are_unresolved_state_with_real_source_bounds(tmp_path):
    graph = capture(tmp_path, '''struct Permissions {
    var canCreate: Bool {
        quota > 0 && isMember
    }
    var canInvite:
        Bool
    {
        get async throws {
            roles.contains { role in role == .owner }
        }
    }
}''')
    create, invite = computed(graph)
    assert [create['symbol'], invite['symbol']] == ['canCreate', 'canInvite']
    assert [(f['anchor']['line'], f['anchor']['end_line']) for f in (create, invite)] == [(2, 4), (5, 11)]
    for fact in (create, invite):
        assert fact['owner'] == 'Permissions'
        assert fact['resolution'] == 'token_signal'
        assert fact['value']['semantics'] == 'unresolved'
        assert fact['value']['initializer'] is None
        assert fact['value']['type'] == 'Bool'
        assert fact['value']['property_role'] == 'derived_property'
        assert not any(isinstance(value, bool) for value in fact['value'].values())
    assert invite['value']['accessor_evidence']['accessors'][0]['effects'] == ['async', 'throws']
    obligations = ios_facts.obligations(graph)['obligations']
    assert {create['id'], invite['id']} <= {item['fact_id'] for item in obligations}
    assert create['anchor']['snippet'] == '    var canCreate: Bool {\n        quota > 0 && isMember\n    }'


def test_rendering_property_is_explicit_and_nested_local_is_excluded(tmp_path):
    graph = capture(tmp_path, '''struct Screen: View {
    var body: some View {
        let label = { () -> String in
            var local: String { "local" }
            return local
        }
        return Text(label())
    }
}''')
    body, = computed(graph)
    assert body['symbol'] == 'body'
    assert body['value']['property_role'] == 'rendering_property'
    assert body['value']['semantics'] == 'unresolved'
    assert body['anchor']['end_line'] == 8


def test_locals_requirements_observers_strings_and_initializers_are_excluded(tmp_path):
    graph = capture(tmp_path, '''protocol Permissions {
    var canCreate: Bool { get }
    var canInvite: Bool { get set }
}
var global: Bool { true }
struct Store {
    // var commented: Bool { true }
    let text = "var quoted: Bool { true }"
    var stored: Bool = { true }()
    var observed: Bool { didSet { print(observed) } }
    var observedOther: Bool { willSet(next) { print(next) } }
    func work() {
        var local: Bool { true }
    }
    class func sharedWork() {
        var classFunctionLocal: Bool { true }
    }
    class var shared: Bool {
        var getterLocal: Bool { true }
        return getterLocal
    }
}''')
    shared, = computed(graph)
    assert shared['symbol'] == 'shared'
    assert shared['owner'] == 'Store'
    assert any(f['kind'] == 'state' and f['symbol'] == 'stored'
               and f['value']['storage'] == 'stored_property' for f in graph['facts'])


def test_type_members_and_extension_members_keep_their_owner(tmp_path):
    graph = capture(tmp_path, '''class Root {
    struct Nested {
        var nested: Bool { true }
    }
    var root: Bool { false }
}
extension Root {
    var extended: Bool { root }
}''')
    assert [(f['symbol'], f['owner']) for f in computed(graph)] == [
        ('nested', 'Nested'), ('root', 'Root'), ('extended', 'Root')]


def test_incomplete_computed_body_is_not_emitted(tmp_path):
    graph = capture(tmp_path, 'struct Store { var canCreate: Bool { get { true }')
    assert computed(graph) == []
    assert any(issue['rule'] == 'IOS.TOKEN_BALANCE' for issue in graph['issues'])


def test_existing_fact_ids_and_values_are_identical_when_adding_computed_signals(tmp_path, monkeypatch):
    source = '''struct Store {
    @State var count: Int = 0
    #if DERIVED
    var canCreate: Bool { count > 0 }
    #else
    var canCreate: Bool = true
    #endif
    var body: some View { Button("Create") { count += 1 } }
}'''
    updated = capture(tmp_path, source)
    with monkeypatch.context() as context:
        context.setattr(ios_facts, 'computed_property', lambda tokens, index: None)
        legacy = ios_facts.extract(tmp_path)
    legacy_by_id = {fact['id']: fact for fact in legacy['facts']}
    updated_by_id = {fact['id']: fact for fact in updated['facts']}
    assert legacy_by_id.items() <= updated_by_id.items()
    assert len(updated_by_id) == len(updated['facts'])
    assert len(updated['facts']) == len(legacy['facts']) + 2
    assert [f['symbol'] for f in computed(updated)] == ['canCreate', 'body']
