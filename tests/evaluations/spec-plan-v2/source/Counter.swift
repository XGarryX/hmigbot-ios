import SwiftUI

@MainActor final class CounterStore: ObservableObject {
    @Published var count = 0
    @Published var message = "Ready"
    private var saveTask: Task<Void, Never>?
    func add() { count += 1 }
    func save() {
        saveTask?.cancel()
        message = "Saving"
        let captured = count
        saveTask = Task {
            do {
                try await Task.sleep(nanoseconds: 100_000_000)
                try Task.checkCancellation()
                UserDefaults.standard.set(captured, forKey: "savedCount")
                message = "Saved"
            } catch is CancellationError { message = "Cancelled" }
            catch { message = "Failed" }
        }
    }
    func cancel() { saveTask?.cancel() }
}

struct CounterScreen: View {
    @StateObject private var store = CounterStore()
    var body: some View {
        VStack(spacing: 16) {
            Text("Count: \(store.count)")
            Text(store.message)
            Button("Add", action: store.add)
            Button("Save", action: store.save)
            Button("Cancel", action: store.cancel)
        }
        .padding(20)
    }
}

#Preview { Text("Saved") }
