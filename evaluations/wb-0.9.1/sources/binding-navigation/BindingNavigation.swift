import SwiftUI
struct BindingNavigation: View {
    @State private var enabled = false
    var body: some View {
        NavigationStack {
            VStack {
                SwitchRow(enabled: $enabled)
                if enabled { Text("Enabled").id("enabled-label") }
                NavigationLink("Details") { Detail(enabled: $enabled) }
            }
        }
    }
}
struct SwitchRow: View {
    @Binding var enabled: Bool
    var body: some View { Toggle("Enabled", isOn: $enabled) }
}
struct Detail: View {
    @Binding var enabled: Bool
    var body: some View { Button("Disable") { enabled = false } }
}
