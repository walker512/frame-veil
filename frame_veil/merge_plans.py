"""Explicit composition of source-bound, human-decided region OCR plans."""
import argparse, sys, tempfile
from pathlib import Path
from . import core, ocr, region_ocr as reg, cancellation

Invalid=core.Invalid
MAX_INPUTS=16
SCOPE='Explicit plan composition only. No inferred masks, privacy clearance or proof of human viewing.'

def selection(path):
    raw=core.read(path);items=core.parse(raw)
    if type(items) is not list or not 1<=len(items)<=MAX_INPUTS:
        raise Invalid('Select 1..16 explicit scan/plan pairs.')
    result=[]
    for item in items:
        core.fields(item,('scan','plan'))
        for value in item.values():
            if type(value) is not str or not value or len(value)>4096 or any(ord(c)<32 for c in value):
                raise Invalid('Bounded local directory paths required.')
        result.append((Path(path).parent/item['scan'],Path(path).parent/item['plan']))
    return result

def plan_files(folder):
    p=Path(folder)
    if p.is_symlink() or not p.is_dir() or {f.name for f in p.iterdir()}!={'plan.json','decisions.json','receipt.json'}:
        raise Invalid('Exact regular plan directory required.')
    return {name:core.read(p/name) for name in ('plan.json','decisions.json','receipt.json')}

def missing_ranges(indexes,total):
    result=[];start=0
    for index in sorted(indexes):
        if start<index:result.append([start,index])
        start=index+1
    if start<total:result.append([start,total])
    return result

def build(source,selection_path):
    pairs=selection(selection_path);source_hash=ocr.sha(core.read(source,core.MAX_SOURCE,False))
    masks=[];seen=set();observed=set();output={};origins=[];info=None
    with tempfile.TemporaryDirectory(prefix='frame-merge-') as td:
        root=Path(td)
        for i,(scan,plan_folder) in enumerate(pairs):
            evidence,manifest,found=reg.load_scan(scan)
            if manifest['source_sha256']!=source_hash:raise Invalid('Selected scan belongs to another source.')
            if info is None:info=manifest['info']
            elif info!=manifest['info']:raise Invalid('Selected source dimensions differ.')
            manifest_hash=ocr.sha(evidence['manifest.json'])
            if manifest_hash in seen:raise Invalid('Duplicate selected scan evidence.')
            seen.add(manifest_hash)
            originals=plan_files(plan_folder)
            decisions=root/f'decisions-{i:04d}.json';ocr.private_write(decisions,originals['decisions.json'])
            regenerated=root/f'validated-{i:04d}'
            # Revalidate the actual evidence and human decisions, not just a plan
            # hash or an untrusted receipt asserting that review happened.
            ocr.plan_from_evidence(source,evidence,manifest,found,decisions,regenerated,reg.SCOPE,0o700)
            expected=plan_files(regenerated)
            if originals!=expected:raise Invalid('Selected plan/receipt differs from its evidence and decisions.')
            parsed=core.load_plan(originals['plan.json'],info)
            first=len(masks);masks.extend(parsed['masks'])
            if len(masks)>100:raise Invalid('Combined plan exceeds 100 explicit masks; nothing is dropped or extrapolated.')
            observed.update(manifest['indexes'])
            names={}
            for name,raw in originals.items():
                target=f'input-{i:04d}-{name}';output[target]=raw;names[target]=ocr.sha(raw)
            origins.append({'input_index':i,'scan_manifest_sha256':manifest_hash,'sampled_frame_indexes':manifest['indexes'],
                            'mask_index_range':[first,len(masks)],'files':names})
            del evidence,found
    plan={'schema':1,'source_sha256':source_hash,**{k:info[k] for k in ('width','height','frames')},'masks':masks}
    output['plan.json']=core.canonical(plan);core.load_plan(output['plan.json'],info)
    masked_frames={i for mask in masks for i in range(mask['start_frame'],mask['end_frame'])}
    output['merge-receipt.json']=core.canonical({
        'schema':1,'source_sha256':source_hash,'plan_sha256':ocr.sha(output['plan.json']),'inputs':origins,
        'unobserved_by_selected_scans_ranges':missing_ranges(observed,info['frames']),
        'frames_without_any_declared_mask_ranges':missing_ranges(masked_frames,info['frames']),
        'selected_candidates_have_explicit_decisions':True,
        'all_batch_scans_included':None,
        'range_semantics':'start-inclusive,end-exclusive','privacy_complete':False,
        'manual_full_output_review_required':True,'scope':SCOPE})
    # Source must still match after input validation. No media tool is invoked.
    if ocr.sha(core.read(source,core.MAX_SOURCE,False))!=source_hash:raise Invalid('Source changed during composition.')
    return output

@cancellation.cancellable
def merge(source,selection_path,out):
    p=Path(out)
    if p.exists() or p.is_symlink():raise Invalid('Output must be new.')
    files=build(source,selection_path)
    p.mkdir(mode=0o700,exist_ok=False)
    for name,raw in files.items():ocr.private_write(p/name,raw)
    receipt=core.parse(files['merge-receipt.json'])
    return {'plan_created':True,'inputs':len(receipt['inputs']),
            'masks':len(core.parse(files['plan.json'])['masks']),
            'unobserved_by_selected_scans_ranges':receipt['unobserved_by_selected_scans_ranges'],
            'frames_without_any_declared_mask_ranges':receipt['frames_without_any_declared_mask_ranges'],
            'privacy_complete':False,'manual_full_output_review_required':True}

@cancellation.cancellable
def verify(source,selection_path,bundle):
    expected=build(source,selection_path);p=Path(bundle)
    if p.is_symlink() or not p.is_dir() or {f.name for f in p.iterdir()}!=set(expected):raise Invalid('Exact regular merged directory required.')
    for name,raw in expected.items():
        if core.read(p/name)!=raw:raise Invalid('Merged artifact differs from revalidated selections.')
    return {'composition_revalidated':True,'ocr_rerun':False,'privacy_complete':False,'manual_full_output_review_required':True}

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('create');a.add_argument('source');a.add_argument('selection');a.add_argument('--out',required=True)
    a=sub.add_parser('verify');a.add_argument('source');a.add_argument('selection');a.add_argument('bundle')
    args=p.parse_args()
    try:
        result=merge(args.source,args.selection,args.out) if args.command=='create' else verify(args.source,args.selection,args.bundle)
        print(core.canonical(result).decode());return 0
    except (ValueError,TypeError,KeyError,OSError,UnicodeError,RecursionError):
        print('Plan composition failed: check selected evidence, source/decision binding, exact bundles, mask limits and new output. No private paths or notes echoed.',file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
