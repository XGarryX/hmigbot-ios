// Converted target logic for sources/cross-page-async/SharedSave.swift.
// ArkUI page would wrap this @Observed model; host runs the plain logic.
// Cancellation token and a setTimeout/prefs are injected by the host runtime
// (ArkUI provides taskpool + preferences); the branching logic below is the real artifact.
export class SharedSave {
  count: number = 0;
  message: string = "Ready";
  private timer: any = null;
  add(): void {
    this.count += 1;
  }
  save(prefs: any, token: any): Promise<void> {
    const captured = this.count;
    this.message = "Saving";
    return new Promise<void>((resolve, reject) => {
      this.timer = setTimeout(() => {
        if (token.cancelled) {
          this.message = "Cancelled";
          reject(new Error("Cancellation"));
          return;
        }
        try {
          prefs.set(captured);
          this.message = "Saved";
          resolve();
        } catch (e) {
          this.message = "Failed";
          reject(e);
        }
      }, 200);
      token.onCancel = () => {
        if (this.timer) {
          clearTimeout(this.timer);
          this.timer = null;
        }
        this.message = "Cancelled";
        reject(new Error("Cancellation"));
      };
    });
  }
  cancel(token: any): void {
    token.cancelled = true;
    if (token.onCancel) {
      token.onCancel();
    }
  }
}
