// Converted target logic for sources/binding-navigation/BindingNavigation.swift.
// ArkUI page would hold @State enabled and pass $enabled (two-way Binding) to
// SwitchRow and Detail; this plain class is the shared backing store that models
// the binding. Host oracle executes THIS real artifact (no ArkUI renderer).
export class EnabledStore {
  enabled: boolean = false;
  toggle(): void {
    this.enabled = !this.enabled;
  }
  disable(): void {
    this.enabled = false;
  }
}
