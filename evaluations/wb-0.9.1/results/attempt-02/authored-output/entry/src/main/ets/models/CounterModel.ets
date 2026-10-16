export class CounterModel {
  count: number = 0;
  add(): number {
    this.count += 1;
    return this.count;
  }
}
