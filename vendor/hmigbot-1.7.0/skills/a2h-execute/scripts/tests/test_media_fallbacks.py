import base64
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
import seed_resources as s

class MediaFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.res=self.root/'entry/src/main/resources'
        self.sentinel=base64.b64decode(s._PLACEHOLDER_PNG_B64)
    def put(self,q,name,data):
        p=self.res/q/'media'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
    def run_restore(self): return s.restore_media_fallbacks(self.root,'entry')
    def test_restores_exact_sentinel_and_keeps_density_original(self):
        p=self.put('base','icon.png',self.sentinel);src=self.put('xxldpi','icon.webp',b'RIFFactual webp pixels')
        r=self.run_restore();self.assertEqual(len(r),1)
        self.assertFalse(p.exists());self.assertEqual((p.parent/'icon.webp').read_bytes(),src.read_bytes())
        self.assertEqual(self.run_restore(),[])
    def test_real_base_asset_and_legitimate_one_pixel_are_preserved(self):
        p=self.put('base','icon.png',b'legitimate 1x1 color');self.put('xxldpi','icon.webp',b'real')
        self.assertEqual(self.run_restore(),[]);self.assertEqual(p.read_bytes(),b'legitimate 1x1 color')
    def test_language_dark_orientation_cannot_supply_base(self):
        p=self.put('base','icon.png',self.sentinel)
        for q in ['dark-xxldpi','en_US-xxldpi','horizontal-xxldpi']:
            self.put(q,'icon.webp',b'wrong variant')
        self.assertEqual(self.run_restore(),[]);self.assertEqual(p.read_bytes(),self.sentinel)
    def test_prefers_highest_density(self):
        self.put('base','icon.png',self.sentinel);self.put('ldpi','icon.webp',b'low');self.put('xxldpi','icon.webp',b'high')
        self.run_restore();self.assertEqual((self.res/'base/media/icon.webp').read_bytes(),b'high')
    def test_missing_source_stays_explicit(self):
        p=self.put('base','icon.png',self.sentinel);self.assertEqual(self.run_restore(),[]);self.assertTrue(p.exists())
    def test_different_real_base_extension_is_not_overwritten(self):
        self.put('base','icon.png',self.sentinel);p=self.put('base','icon.webp',b'base real');self.put('xxldpi','icon.webp',b'qualified')
        self.assertEqual(self.run_restore(),[]);self.assertEqual(p.read_bytes(),b'base real')
    def test_backfill_does_not_seed_sentinel_when_density_asset_exists_and_restores_old_one(self):
        # E155 根因：media_names 只看 base/media，xxldpi 里已转换的图标被当成缺失而播透明哨兵
        self.put('xxldpi','icon.webp',b'RIFFreal')
        self.put('base','old.png',self.sentinel);self.put('xxldpi','old.webp',b'RIFFold')
        ets=self.root/'entry/src/main/ets/pages';ets.mkdir(parents=True)
        (ets/'P.ets').write_text("Image($r('app.media.icon'))Image($r('app.media.old'))Image($r('app.media.gone'))")
        rep=s.backfill_refs(self.root,'entry',self.root/'entry/src/main/ets')
        self.assertFalse((self.res/'base/media/icon.png').exists())
        self.assertTrue((self.res/'base/media/gone.png').exists())          # 真缺的仍播哨兵
        self.assertEqual((self.res/'base/media/old.webp').read_bytes(),b'RIFFold')
        self.assertEqual([r['name'] for r in rep['assets_restored']],['old'])
        self.assertEqual([a['name'] for a in rep['added'] if a['kind']=='media'],['gone'])

if __name__=='__main__': unittest.main()
