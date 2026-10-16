import { CounterModel } from '../models/CounterModel';

@Entry
@Component
struct CounterPage {
  private model: CounterModel = new CounterModel();
  @State private count: number = 0;
  private add(): void {
    this.count = this.model.add();
  }
  build() {
    Column() {
      Text($r('app.string.count_text', this.count))
      Button($r('app.string.add_text'))
        .onClick(() => { this.add(); })
    }
  }
}
