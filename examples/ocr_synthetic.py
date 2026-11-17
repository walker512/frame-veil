"""Original public fictional name/notice video. Uses an existing system font, never bundles it."""
import sys
from pathlib import Path
from frame_veil.ocr import bounded_tool
from frame_veil.core import canonical
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
def generate(out):
    if not Path(FONT).is_file():raise ValueError('Synthetic fixture requires an existing DejaVu Sans system font; nothing is downloaded.')
    root=Path(out);root.mkdir(exist_ok=False)
    filters="drawtext=fontfile="+FONT+":text='Student ALICE SAMPLE':fontcolor=black:fontsize=36:x=35:y=60,drawbox=x=20:y=180:w=600:h=70:color=gray:t=fill,drawtext=fontfile="+FONT+":text='NOTICE DEMO ONLY':fontcolor=black:fontsize=30:x=35:y=200"
    bounded_tool('ffmpeg',['-v','error','-nostdin','-n','-f','lavfi','-i','color=white:s=640x360:r=2:d=3','-vf',filters,'-an','-c:v','libx264','-pix_fmt','yuv420p','-threads','1',str(root/'synthetic.mp4')],16384,30,strict_stderr=True)
    (root/'terms.json').write_bytes(canonical(['ALICE SAMPLE','NOTICE DEMO ONLY']));(root/'frames.json').write_bytes(canonical([0,3]));return root
if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python -m examples.ocr_synthetic NEW_DIRECTORY')
    generate(sys.argv[1])
