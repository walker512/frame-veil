"""32-frame fictional notice fixture for resumable multi-batch OCR."""
import sys
from pathlib import Path
from frame_veil import core,ocr
from .ocr_synthetic import FONT

def generate(out):
    if not Path(FONT).is_file():raise ValueError('Existing DejaVu Sans font required; nothing is downloaded.')
    root=Path(out);root.mkdir(exist_ok=False)
    vf=f"drawtext=fontfile={FONT}:text='NOTICE DEMO':fontcolor=black:fontsize=28:x=40:y=100:enable='eq(n,1)+eq(n,25)'"
    ocr.bounded_tool('ffmpeg',['-v','error','-nostdin','-n','-f','lavfi','-i','color=white:s=640x360:r=2:d=16','-vf',vf,'-an','-c:v','libx264','-pix_fmt','yuv420p','-threads','1',str(root/'synthetic.mp4')],16384,30,strict_stderr=True)
    (root/'terms.json').write_bytes(core.canonical(['NOTICE DEMO']))
    (root/'regions.json').write_bytes(core.canonical([{'id':'band','x':20,'y':80,'width':600,'height':80,'scale':1,'threshold':None}]))
    return root

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python -m examples.batch_text_synthetic NEW_DIRECTORY')
    generate(sys.argv[1])
