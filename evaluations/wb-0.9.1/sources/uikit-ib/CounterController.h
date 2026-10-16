#import <UIKit/UIKit.h>
@interface CounterController : UIViewController
@property (nonatomic, weak) IBOutlet UILabel *countLabel;
- (IBAction)add:(id)sender;
@end
