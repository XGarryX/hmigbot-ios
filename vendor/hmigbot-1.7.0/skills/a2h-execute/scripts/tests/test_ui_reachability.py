import tempfile
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _ui_reachability import ui_sources
from depth_gate import ARKUI_NODE_RE


class Reachability(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.page = self.write('pages/Page.ets', '')

    def write(self, relative, text):
        path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        return path

    def count(self):
        sources, files = ui_sources(self.page, self.root)
        return sum(len(ARKUI_NODE_RE.findall(body)) for _, _, body in sources), files

    def test_shared_alias_provider_counts_but_unused_export_and_import_do_not(self):
        self.write('pages/Page.ets', "import { Player as Shared, Other } from '../components/Player'; struct Page { build(){Shared()} }")
        self.write('components/Player.ets', "export struct Player {build(){Column(){Text()Image()Slider()}}} export struct Other{build(){Text()Text()Text()Text()Text()}}")
        self.assertEqual(self.count()[0], 4)

    def test_native_builder_callback_reaches_body_once_even_with_cycle(self):
        self.write('pages/Page.ets', "import { Host } from '../components/Host'; struct Page{host=new Host(); build(){NavDestination(){}}}")
        self.write('components/Host.ets', "import { Body } from './Body'; @Builder function content(){Body()} export class Host{show(){new ComponentContent(context,wrapBuilder(content));}}")
        self.write('components/Body.ets', "import { Host } from './Host'; export struct Body{host=new Host();build(){Column(){Text()Image()}}}")
        self.assertEqual(self.count()[0], 4)

    def test_dead_private_file_comments_strings_type_imports_and_outside_escape_do_not_count(self):
        self.write('pages/Page.ets', "import type { Bad } from '../components/Bad'; import { Bad2 } from '../../outside'; struct Page{build(){Text('Image()')} // Column()\n}")
        self.write('components/Bad.ets', 'export struct Bad{build(){Image()Image()Image()}}')
        self.write('components/Page/Dead.ets', 'struct Dead{build(){Column(){Text()Image()}}}')
        self.assertEqual(self.count()[0], 1)

    def test_barrel_reexport_named_symbol_and_namespace_usage(self):
        self.write('pages/Page.ets', "import * as UI from '../components/Index'; struct Page{build(){UI.Card()}}")
        self.write('components/Index.ets', "export { RealCard as Card } from './Card'; export { Bad } from './Bad';")
        self.write('components/Card.ets', 'export struct RealCard{build(){Row(){Text()}}}')
        self.write('components/Bad.ets', 'export struct Bad{build(){Text()Text()Text()}}')
        self.assertEqual(self.count()[0], 2)

    def test_local_helpers_and_repeated_imports_are_not_double_counted(self):
        self.write('pages/Page.ets', "import { Card } from '../components/Card'; @Builder function local(){Card()} struct Page{build(){Column(){this.local();local();Card();Card()}}}")
        self.write('components/Card.ets', 'export struct Card{build(){Text()}}')
        self.assertEqual(self.count()[0], 2)

    def test_transparent_canonical_adapter_counts_destination_but_ordinary_navigation_does_not(self):
        adapter = "struct Page{ private open(context:NavDestinationContext):void{const indices:number[]=this.stack.getIndexByName(context.pathInfo.name); const ownIndex:number=indices[indices.length-1];this.stack.pushPathByName('Canonical',params);this.stack.removeByIndexes([ownIndex]);}build(){NavDestination(){Stack().width('100%')}.onReady((context:NavDestinationContext):void=>{this.open(context);})}}"
        self.write('pages/Page.ets', adapter)
        self.write('pages/Canonical.ets', 'struct Canonical{build(){Column(){Text()Image()}}}')
        self.assertEqual(self.count()[0], 5)
        self.write('pages/Page.ets', adapter.replace('this.stack.removeByIndexes([ownIndex]);', ''))
        self.assertEqual(self.count()[0], 2)
