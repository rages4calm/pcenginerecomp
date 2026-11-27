"""A checkpoint may precede the first real completed guest video frame."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from examples.widescreen.workflow import session
from scripts.dev_client import DevError
from tests.test_dev_server_cli import DESKTOP


MPR = [255, 248, 128, 129, 130, 131, 132, 0]


@unittest.skipUnless(DESKTOP.is_file(), 'configured desktop host required')
class PreframeCheckpointTests(unittest.TestCase):
    def test_cold_and_ordinary_restore_execute_before_first_frame_without_fabricating_video(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'authored.bin';image.write_bytes(bytes.fromhex('78 EA 80 FE'))
            checkpoints=root/'checkpoints';checkpoints.mkdir()
            argv=[str(DESKTOP.resolve()),str(image),'0x100000','0x4000',','.join(map(str,MPR)),
                '10000000','100000000','hybrid','--video-output','continuous','--audio-output','off',
                '--dev-port','0','--dev-start-paused','on','--wall-seconds','30',
                '--checkpoint-dir',str(checkpoints),'--checkpoint-context','c'*64,
                '--hidden','on','--unthrottled','on','--window-scale','1']
            environment=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',SDL_AUDIODRIVER='dummy')
            with session(argv,root,'cold',environment) as client:
                cold=client.call('status');self.assertEqual((cold['frame'],cold['ticks']),(0,0))
                for source in ('guest','present'):
                    with self.assertRaisesRegex(DevError,'no completed video frame'):client.capture(source)
                first=client.run_until(0x4001,MPR,instructions=1,ticks=1000)
                self.assertEqual(first['frame'],0);self.assertGreater(first['ticks'],0)
                seed=client.call('save_checkpoint',name='seed.pcec')['checkpoint']
                self.assertEqual(seed['frame'],0)
                self.assertEqual(first['host']['native_steps']+first['host']['interpreter_steps'],1)
            original=(checkpoints/'seed.pcec').read_bytes()
            with session(argv+['--checkpoint-load','seed.pcec'],root,'ordinary',environment) as client:
                restored=client.call('status')
                self.assertEqual((restored['frame'],restored['ticks']),(0,seed['ticks']))
                self.assertEqual(restored['host']['checkpoint']['window'],dict(ticks=0,native_steps=0,interpreter_steps=0))
                for source in ('guest','present'):
                    with self.assertRaisesRegex(DevError,'no completed video frame'):client.capture(source)
                second=client.run_until(0x4002,MPR,instructions=1,ticks=1000)
                self.assertEqual(second['frame'],0)
                self.assertGreater(second['ticks'],restored['ticks'])
                for source in ('guest','present'):
                    with self.assertRaisesRegex(DevError,'no completed video frame'):client.capture(source)
                self.assertEqual(client.call('status')['ticks'],second['ticks'])
                client.advance(1)
                frame,pixels=client.capture('guest')
                self.assertEqual(frame['frame'],1)
                self.assertEqual(len(pixels),frame['width']*frame['height']*3)
                client.capture('present')
            self.assertEqual((checkpoints/'seed.pcec').read_bytes(),original)
            final=json.loads((root/'ordinary.stdout').read_text())
            self.assertEqual(final['stop'],'dev_quit')


if __name__=='__main__':unittest.main()
