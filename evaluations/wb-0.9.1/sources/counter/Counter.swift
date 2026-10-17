import SwiftUI
struct Counter: View {
    @State private var count: Int = 0
    var body: some View {
        VStack {
            Text("Count: \(count)")
            Button("Add") { count += 1 }
        }
    }
}
@main
struct CounterApplication: App {
    var body: some Scene {
        WindowGroup { Counter() }
    }
}
