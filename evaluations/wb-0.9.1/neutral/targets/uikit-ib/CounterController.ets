// Converted target logic for sources/uikit-ib/CounterController.{h,m,xib}.
// ArkUI page would wire Button.onClick -> add() and Text -> countLabel;
// this plain class is the controller logic the host oracle executes (no UIKit/IB runtime).
export class CounterController {
  count: number = 0;
  countLabel: string = "Count: 0";
  viewDidLoad(): void {
    this.count = 0;
    this.countLabel = "Count: 0";
  }
  add(): void {
    this.count += 1;
    this.countLabel = "Count: " + this.count;
  }
}
