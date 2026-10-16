import SwiftUI
@MainActor final class SharedSave: ObservableObject {
    @Published var count = 0
    @Published var message = "Ready"
    private var job: Task<Void, Never>?
    func add() { count += 1 }
    func save() {
        let captured = count
        message = "Saving"
        job = Task {
            do {
                try await Task.sleep(for: .milliseconds(200))
                try Task.checkCancellation()
                UserDefaults.standard.set(captured, forKey: "savedCount")
                message = "Saved"
            } catch is CancellationError { message = "Cancelled" }
              catch { message = "Failed" }
        }
    }
    func cancel() { job?.cancel() }
}
struct SaveHome: View {
    @StateObject private var model = SharedSave()
    var body: some View {
        NavigationStack {
            VStack {
                Text(model.message)
                Button("Add") { model.add() }
                Button("Save") { model.save() }
                NavigationLink("Details") { SaveDetail(model: model) }
            }
        }
    }
}
struct SaveDetail: View {
    @ObservedObject var model: SharedSave
    var body: some View { Button("Cancel") { model.cancel() } }
}
