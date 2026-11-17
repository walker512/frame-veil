"""Explicit-region OCR evidence. Trusted local tools, not a privacy clearance."""
import argparse, json, os, re, subprocess, sys, tempfile
from pathlib import Path
from . import core, ocr
Invalid = core.Invalid
MAX_CALLS = 64
MAX_DERIVED = 64 * 1024 * 1024
MAX_TSV = 32 * 1024 * 1024
MAX_BUNDLE = 2 * ocr.MAX_SAMPLES + MAX_TSV + 8 * core.INPUT_LIMIT
CONFIG = {'language': 'eng', 'oem': 1, 'psm': 6,
          'preprocess': 'crop-rgb-nearest-integer-luma601-threshold-v1',
          'coordinates': 'floor-left-top-ceil-right-bottom-v1',
          'normalization': 'casefold-whitespace-token-v1'}
SCOPE = ('Explicit-region and baseline selected-frame text candidates only. '
         'Misses remain possible. Not complete privacy detection, proof of viewing or publication consent.')

def regions(raw, info=None):
    result = core.parse(raw)
    if type(result) is not list or not 1 <= len(result) <= 8:
        raise Invalid('Supply 1..8 explicit regions.')
    seen = set()
    for r in result:
        core.fields(r, ('id', 'x', 'y', 'width', 'height', 'scale', 'threshold'))
        if type(r['id']) is not str or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,39}', r['id']) or r['id'] in seen:
            raise Invalid('Unique bounded region IDs required.')
        seen.add(r['id'])
        w, h = (info['width'], info['height']) if info else (1920, 1080)
        core.integer(r['x'], 0, w - 1); core.integer(r['y'], 0, h - 1)
        core.integer(r['width'], 1, w - r['x']); core.integer(r['height'], 1, h - r['y'])
        core.integer(r['scale'], 1, 3)
        if r['threshold'] is not None: core.integer(r['threshold'], 0, 255)
    return result

def paired_regions(raw):
    """Keep explicit variants, adding an unthresholded control where missing.

    The expanded regions.json is retained verbatim by the normal scan workflow.
    No region, scale or sampling interval is inferred.
    """
    requested = regions(raw)
    result = [dict(r) for r in requested]
    ids = {r['id'] for r in result}
    keys = ('x', 'y', 'width', 'height', 'scale')
    for r in requested:
        if r['threshold'] is None:
            continue
        if any(c['threshold'] is None and all(c[k] == r[k] for k in keys) for c in result):
            continue
        suffix = 1
        while 'control-' + str(suffix) in ids:
            suffix += 1
        ident = 'control-' + str(suffix); ids.add(ident)
        result.append({**r, 'id': ident, 'threshold': None})
    # Respect existing evidence/resource bounds; never drop variants to fit.
    return regions(core.canonical(result))

def scan_paired(source, terms_path, frames_path, regions_path, out):
    expanded = paired_regions(core.read(regions_path))
    # Fail before spawning media tools when the expanded execution bound fails.
    indexes = ocr.indices(core.read(frames_path))
    if len(indexes) * (1 + len(expanded)) > MAX_CALLS:
        raise Invalid('Paired region execution count exceeds limit.')
    with tempfile.TemporaryDirectory(prefix='frame-paired-') as td:
        config = Path(td) / 'regions.json'
        ocr.private_write(config, core.canonical(expanded))
        return scan(source, terms_path, frames_path, config, out)

def scan_interval(source, terms_path, start, end, regions_path, out, pair_unthresholded=False):
    indexes = ocr.interval_indices(start, end)
    rs = paired_regions(core.read(regions_path)) if pair_unthresholded else regions(core.read(regions_path))
    if len(indexes) * (1 + len(rs)) > MAX_CALLS:
        raise Invalid('Interval scan exceeds 64 OCR executions.')
    with tempfile.TemporaryDirectory(prefix='frame-region-interval-') as td:
        frames = Path(td) / 'frames.json'; ocr.private_write(frames, core.canonical(indexes))
        config = Path(td) / 'regions.json'; ocr.private_write(config, core.canonical(rs))
        return scan(source, terms_path, frames, config, out)

def budget(rs, indexes, info):
    if len(indexes) * (1 + len(rs)) > MAX_CALLS:
        raise Invalid('Baseline plus region OCR exceeds 64 executions.')
    if sum(r['width'] * r['height'] * r['scale'] ** 2 * 3 for r in rs) * len(indexes) > MAX_DERIVED:
        raise Invalid('Derived RGB samples exceed 64 MiB.')
    if info['width'] * info['height'] * 3 * len(indexes) > ocr.MAX_SAMPLES:
        raise Invalid('Original samples exceed 64 MiB.')

def preprocess(raw, w, h, region):
    """Nearest-neighbor RGB crop; optional integer BT.601 luma >= threshold -> white."""
    ocr.ppm(raw, w, h)
    regions(core.canonical([region]), {'width': w, 'height': h})
    r = region; scale = r['scale']; width = r['width'] * scale; height = r['height'] * scale
    pixels = memoryview(raw)[len(f'P6\n{w} {h}\n255\n'.encode()):]
    out = bytearray(f'P6\n{width} {height}\n255\n'.encode())
    for y in range(r['y'], r['y'] + r['height']):
        row = bytearray()
        for x in range(r['x'], r['x'] + r['width']):
            rgb = bytes(pixels[(y * w + x) * 3:(y * w + x + 1) * 3])
            if r['threshold'] is not None:
                luma = (299 * rgb[0] + 587 * rgb[1] + 114 * rgb[2] + 500) // 1000
                rgb = b'\xff' * 3 if luma >= r['threshold'] else b'\0' * 3
            row.extend(rgb * scale)
        out.extend(row * scale)
    return bytes(out)

def frame_box(box, r):
    s = r['scale']; left = box['x'] // s; top = box['y'] // s
    right = (box['x'] + box['width'] + s - 1) // s
    bottom = (box['y'] + box['height'] + s - 1) // s
    return {'x': r['x'] + left, 'y': r['y'] + top, 'width': right - left, 'height': bottom - top}

def matches(tsv, phrases, index, r):
    result = ocr.candidates(tsv, phrases, index, r['width'] * r['scale'], r['height'] * r['scale'])
    for c in result:
        c['id'] = 'region-' + r['id'] + '-' + c['id']; c['region_id'] = r['id']; c['origin'] = 'region'
        c['derived_box'] = c['box']; c['box'] = frame_box(c['derived_box'], r)
        for word in c['words']:
            word['derived_box'] = word['box']; word['box'] = frame_box(word['derived_box'], r)
    return result

def baseline_matches(found):
    return [{**c, 'id': 'base-' + c['id'], 'origin': 'full-frame', 'region_id': None} for c in found]

def names(i, j):
    stem = f'region-{j:02d}-frame-{i:04d}'
    return stem + '.ppm', stem + '.tsv'

def layout(indexes, rs):
    base = {'manifest.json', 'terms.json', 'frames.json', 'candidates.json'} | {n for i in indexes for n in ocr.names(i)}
    return {'base-' + n for n in base} | {'manifest.json', 'regions.json', 'candidates.json'} | {n for i in indexes for j in range(len(rs)) for n in names(i, j)}

def validate_files(files):
    m = core.parse(files['manifest.json'])
    if files['manifest.json'] != core.canonical(m): raise Invalid('Canonical region manifest required.')
    core.fields(m, ('schema', 'source_sha256', 'indexes', 'config', 'diagnostics', 'files', 'scan_completed', 'privacy_complete', 'scope'))
    core.integer(m['schema'], 1, 1)
    if m['scan_completed'] is not True or m['privacy_complete'] is not False or m['scope'] != SCOPE or core.canonical(m['config']) != core.canonical(CONFIG):
        raise Invalid('Region scope/configuration mismatch.')
    base = {n[5:]: b for n, b in files.items() if n.startswith('base-')}
    bm, bc = ocr.validate_files(base)
    rs = regions(files['regions.json'], bm['info']); indexes = bm['indexes']; info = bm['info']
    budget(rs, indexes, info)
    if core.canonical(m['indexes']) != core.canonical(indexes) or m['source_sha256'] != bm['source_sha256']:
        raise Invalid('Source or sampled coverage mismatch.')
    expected = layout(indexes, rs)
    if set(files) != expected or type(m['files']) is not dict or set(m['files']) != expected - {'manifest.json'}:
        raise Invalid('Exact region evidence files required.')
    if sum(map(len, files.values())) > MAX_BUNDLE or sum(len(b) for n, b in files.items() if n.endswith('.tsv')) > MAX_TSV:
        raise Invalid('Aggregate evidence budget exceeded.')
    for n, b in files.items():
        if n != 'manifest.json' and m['files'][n] != ocr.sha(b): raise Invalid('Region artifact hash mismatch.')
    keys = {names(i, j)[1] for i in indexes for j in range(len(rs))}
    if type(m['diagnostics']) is not dict or set(m['diagnostics']) != keys: raise Invalid('Diagnostic coverage mismatch.')
    for d in m['diagnostics'].values():
        core.fields(d, ('stderr_bytes', 'stderr_sha256')); core.integer(d['stderr_bytes'], 0, 65536)
        if type(d['stderr_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', d['stderr_sha256']) or (d['stderr_bytes'] == 0 and d['stderr_sha256'] != ocr.sha(b'')):
            raise Invalid('Diagnostic hash invalid.')
    found = baseline_matches(bc)
    for i in indexes:
        original = base[ocr.names(i)[0]]
        for j, r in enumerate(rs):
            pn, tn = names(i, j)
            if files[pn] != preprocess(original, info['width'], info['height'], r): raise Invalid('Derived pixels differ from original crop/configuration.')
            found.extend(matches(files[tn], ocr.terms(base['terms.json']), i, r))
    if len(found) > 100 or files['candidates.json'] != core.canonical(found): raise Invalid('Candidate evidence mismatch or count exceeded.')
    return {**m, 'info': info}, found

def load_scan(folder):
    p = Path(folder)
    if p.is_symlink() or not p.is_dir(): raise Invalid('Regular region scan directory required.')
    mr = core.read(p / 'manifest.json'); m = core.parse(mr)
    if type(m) is not dict: raise Invalid('Manifest must be an object.')
    indexes = ocr.indices(core.canonical(m.get('indexes'))); rr = core.read(p / 'regions.json'); rs = regions(rr)
    if len(indexes) * (1 + len(rs)) > MAX_CALLS: raise Invalid('Execution count exceeds limit.')
    expected = layout(indexes, rs)
    if {x.name for x in p.iterdir()} != expected: raise Invalid('Unexpected region directory members.')
    files = {}; total = 0
    for n in sorted(expected):
        limit = MAX_DERIVED + 100 if n.endswith('.ppm') else core.INPUT_LIMIT
        b = core.read(p / n, limit, False); total += len(b)
        if total > MAX_BUNDLE: raise Invalid('Bundle size exceeded.')
        files[n] = b
    m, c = validate_files(files)
    return files, m, c

def publish(files, out):
    # Validation and tool work precedes creation. I/O failure may leave a partial,
    # non-verifying directory; never overwrite or silently remove user files.
    root = Path(out); root.mkdir(mode=0o700, exist_ok=False)
    for n, raw in files.items():
        ocr.private_write(root / n, raw)

def scan(source, terms_path, frames_path, regions_path, out):
    if Path(out).exists() or Path(out).is_symlink(): raise Invalid('Output must be new.')
    rr = core.read(regions_path); rs = regions(rr); ix = ocr.indices(core.read(frames_path))
    if len(ix) * (1 + len(rs)) > MAX_CALLS: raise Invalid('Execution count exceeds limit.')
    with tempfile.TemporaryDirectory(prefix='frame-regions-') as td:
        root = Path(td); baseline = root / 'base'
        ocr.scan(source, terms_path, frames_path, baseline)
        bf, bm, bc = ocr.load_scan(baseline); rs = regions(rr, bm['info']); indexes = bm['indexes']; info = bm['info']
        budget(rs, indexes, info)
        files = {'base-' + n: b for n, b in bf.items()}; files['regions.json'] = rr
        found = baseline_matches(bc); diagnostics = {}; tsv_bytes = sum(len(b) for n, b in bf.items() if n.endswith('.tsv'))
        for i in indexes:
            for j, r in enumerate(rs):
                pn, tn = names(i, j); image = preprocess(bf[ocr.names(i)[0]], info['width'], info['height'], r)
                path = root / pn; ocr.private_write(path, image)
                tsv, diag = ocr.bounded_tool('tesseract', [str(path), 'stdout', '-l', 'eng', '--oem', '1', '--psm', '6', 'tsv'], ocr.TSV_LIMIT, 30)
                tsv_bytes += len(tsv)
                if tsv_bytes > MAX_TSV: raise Invalid('Aggregate TSV size exceeded.')
                found.extend(matches(tsv, ocr.terms(bf['terms.json']), i, r))
                if len(found) > 100: raise Invalid('More than 100 merged candidates.')
                files[pn] = image; files[tn] = tsv; diagnostics[tn] = diag
        files['candidates.json'] = core.canonical(found)
        if len(files['candidates.json']) > core.INPUT_LIMIT: raise Invalid('Candidates exceed JSON limit.')
        m = {'schema': 1, 'source_sha256': bm['source_sha256'], 'indexes': indexes, 'config': CONFIG, 'diagnostics': diagnostics,
             'files': {n: ocr.sha(b) for n, b in files.items()}, 'scan_completed': True, 'privacy_complete': False, 'scope': SCOPE}
        files['manifest.json'] = core.canonical(m)
        validate_files(files)
        publish(files, out)
    return {'scan_completed': True, 'sampled_frames': len(indexes), 'regions': len(rs), 'candidate_count': len(found), 'baseline_candidates': len(bc), 'privacy_complete': False, 'manual_review_required': True}

def coverage(folder):
    files, manifest, found = load_scan(folder)
    report = ocr.coverage_report(files, manifest, found, 'base-terms.json')
    report['baseline'] = ocr.coverage_report(files, manifest, [c for c in found if c['origin'] == 'full-frame'], 'base-terms.json')['terms']
    report['regions'] = [
        {'region_id': r['id'], 'threshold': r['threshold'], 'scale': r['scale'],
         'terms': ocr.coverage_report(files, manifest, [c for c in found if c['origin'] == 'region' and c['region_id'] == r['id']], 'base-terms.json')['terms']}
        for r in regions(files['regions.json'], manifest['info'])]
    return report

def prepare(folder, out):
    files, m, found = load_scan(folder)
    d = {'schema': 1, 'scan_manifest_sha256': ocr.sha(files['manifest.json']), 'source_sha256': m['source_sha256'],
         'decisions': [{'id': c['id'], 'decision': 'pending', 'note': '', 'mask': None} for c in found]}
    ocr.private_write(out, core.canonical(d))
    return {'candidates': len(found), 'all_pending': True, 'privacy_complete': False}

def plan(source, folder, decision_path, out):
    files, m, found = load_scan(folder)
    return ocr.plan_from_evidence(source, files, m, found, decision_path, out, SCOPE, 0o700)

def main():
    p = argparse.ArgumentParser(description=SCOPE); sub = p.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('scan'); a.add_argument('source')
    for arg in ('terms', 'regions', 'out'): a.add_argument('--' + arg, required=True)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument('--frames')
    g.add_argument('--frame-range', nargs=2, type=int, metavar=('START', 'END'), help='Every frame in [START,END), at most 24 and 64 OCR calls; human review still required.')
    a.add_argument('--pair-unthresholded', action='store_true', help='Retain an unthresholded control for each thresholded crop/scale; bounds still apply.')
    a = sub.add_parser('verify'); a.add_argument('scan')
    a = sub.add_parser('coverage'); a.add_argument('scan')
    a = sub.add_parser('prepare'); a.add_argument('scan'); a.add_argument('--out', required=True)
    a = sub.add_parser('plan'); a.add_argument('source'); a.add_argument('scan'); a.add_argument('decisions'); a.add_argument('--out', required=True)
    args = p.parse_args()
    try:
        if args.cmd == 'scan':
            if args.frame_range:
                r = scan_interval(args.source, args.terms, *args.frame_range, args.regions, args.out, args.pair_unthresholded)
            else:
                runner = scan_paired if args.pair_unthresholded else scan
                r = runner(args.source, args.terms, args.frames, args.regions, args.out)
        elif args.cmd == 'coverage': r = coverage(args.scan)
        elif args.cmd == 'prepare': r = prepare(args.scan, args.out)
        elif args.cmd == 'plan': r = plan(args.source, args.scan, args.decisions, args.out)
        else:
            _, m, c = load_scan(args.scan)
            r = {'internally_consistent': True, 'sampled_frames': len(m['indexes']), 'candidates': len(c), 'ocr_rerun': False, 'privacy_complete': False}
        print(json.dumps(r)); return 0
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError, UnicodeError, RecursionError):
        print('Region OCR failed: unsupported input/tools, evidence mismatch, pending decisions, bound or I/O failure. No private text or paths echoed.', file=sys.stderr); return 2

if __name__ == '__main__': sys.exit(main())
