#import "CounterController.h"
@interface CounterController ()
@property (nonatomic) NSInteger count;
@end
@implementation CounterController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.count = 0;
    self.countLabel.text = @"Count: 0";
}
- (IBAction)add:(id)sender {
    self.count += 1;
    self.countLabel.text = [NSString stringWithFormat:@"Count: %ld", (long)self.count];
}
@end
