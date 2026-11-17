"""Reproduce the public gray notice miss and explicit-region mitigation, no bundled font."""
import sys
from .ocr_synthetic import generate as base_generate
from frame_veil.core import canonical

def generate(out):
    root = base_generate(out)
    (root / 'regions.json').write_bytes(canonical([
        {'id': 'notice', 'x': 20, 'y': 180, 'width': 600, 'height': 70, 'scale': 2, 'threshold': None}
    ]))
    return root

if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit('Usage: python -m examples.region_ocr_synthetic NEW_DIRECTORY')
    generate(sys.argv[1])
