"""Byte-bound, explicit human review records. Not proof of viewing or consent."""
import hashlib,tempfile
from pathlib import Path
from . import core,audio
SCOPE='Human declarations only; not proof of viewing, complete privacy protection or publication consent.'
def _hash(raw):return hashlib.sha256(raw).hexdigest()
def _snapshot(folder,dest,kind):
    if kind=='audio':
        audio._snapshot_bundle(folder,dest)
        result=audio.verify_audio(dest)
        media='review.mkv';frames=core.parse(core.read(dest/'video'/'receipt.json'))['output']['frames'];a=result['audio']
    elif kind=='silent':
        root=Path(folder)
        if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()}!={'redacted.mkv','plan.json','receipt.json'}:raise core.Invalid('Unexpected review bundle.')
        for name,limit in [('redacted.mkv',core.MAX_OUTPUT),('plan.json',core.INPUT_LIMIT),('receipt.json',core.INPUT_LIMIT)]:
            (dest/name).write_bytes(core.read(root/name,limit,False))
        result=core.audit_masks(dest);media='redacted.mkv';frames=core.parse(core.read(dest/'receipt.json'))['output']['frames'];a=None
    else:raise core.Invalid('Unknown review kind.')
    # Bind every expected bundle file, not only the playable media.
    hashes={str(p.relative_to(dest)).replace('\\','/'):_hash(core.read(p,core.MAX_OUTPUT,False)) for p in sorted(dest.rglob('*')) if p.is_file()}
    items=[]
    for start in range(0,frames,60):
        items.append({'id':'video-'+str(start),'kind':'video','start':start,'end':min(start+60,frames),'checks':{'names_and_text':'pending','faces_and_avatars':'pending','notifications_and_other':'pending'}})
    if a:
        step=a['sample_rate']*10
        for start in range(0,a['samples'],step):
            items.append({'id':'audio-'+str(start),'kind':'audio','start':start,'end':min(start+step,a['samples']),'checks':{'speech_and_other_audio':'pending'}})
    return {'schema':1,'kind':kind,'bundle_sha256':_hash(core.canonical(hashes)),'media_sha256':hashes[media],'video_frames':frames,'audio':a,'items':items,'scope':SCOPE},dest/media

def _load(raw,expected):
    value=core.parse(raw);core.fields(value,expected.keys())
    if type(value['items']) is not list or len(value['items'])!=len(expected['items']):raise core.Invalid('Review coverage differs.')
    normalized=core.parse(core.canonical(value))
    for item,want in zip(normalized['items'],expected['items']):
        core.fields(item,want.keys());core.fields(item['checks'],want['checks'].keys())
        for k,v in item['checks'].items():
            if type(v) is not str or v not in ('pending','reviewed','blocked'):raise core.Invalid('Unknown review decision.')
            item['checks'][k]='pending'
    if core.canonical(normalized)!=core.canonical(expected):raise core.Invalid('Review is stale or coverage was changed.')
    return value

def _write(path,value):
    raw=core.canonical(value)
    if len(raw)>core.INPUT_LIMIT:raise core.Invalid('Review record exceeds bound.')
    with Path(path).open('xb') as f:f.write(raw)

def prepare(folder,kind,out):
    with tempfile.TemporaryDirectory(prefix='frame-review-') as t:
        expected,_=_snapshot(folder,Path(t),kind);_write(out,expected)
    return {'review_created':True,'items':len(expected['items']),'all_pending':True,'scope':SCOPE}

def decide(folder,record,item_id,check,decision,out):
    raw=core.read(record);parsed=core.parse(raw)
    if not isinstance(parsed,dict):raise core.Invalid('Invalid record.')
    kind=parsed.get('kind')
    with tempfile.TemporaryDirectory(prefix='frame-review-') as t:
        expected,_=_snapshot(folder,Path(t),kind);value=_load(raw,expected)
        matches=[i for i in value['items'] if i['id']==item_id]
        if len(matches)!=1 or check not in matches[0]['checks'] or decision not in ('pending','reviewed','blocked'):raise core.Invalid('Unknown review item, check or decision.')
        matches[0]['checks'][check]=decision;_write(out,value)
    return {'decision_recorded':True,'complete':all(v=='reviewed' for i in value['items'] for v in i['checks'].values()),'scope':SCOPE}

def export(folder,record,out,acknowledge=False):
    if acknowledge is not True:raise core.Invalid('Explicit human review acknowledgement required.')
    raw=core.read(record);parsed=core.parse(raw)
    if not isinstance(parsed,dict):raise core.Invalid('Invalid record.')
    with tempfile.TemporaryDirectory(prefix='frame-review-') as t:
        expected,media=_snapshot(folder,Path(t),parsed.get('kind'));value=_load(raw,expected)
        if any(v!='reviewed' for i in value['items'] for v in i['checks'].values()):raise core.Invalid('Pending or blocked review checks remain.')
        # Snapshot was audited and bound; export that exact snapshot, not a reread.
        payload=core.read(media,core.MAX_OUTPUT,False);record_bytes=core.canonical(value)
        dest=Path(out);dest.mkdir(exist_ok=False)
        (dest/'reviewed.mkv').write_bytes(payload);(dest/'human-review.json').write_bytes(record_bytes)
        (dest/'SCOPE.txt').write_bytes((SCOPE+'\nDo not share until you independently have all necessary permissions.\n').encode())
    return {'exported':True,'media_sha256':_hash(payload),'human_declarations_complete':True,'privacy_certified':False,'publication_authorized':False,'scope':SCOPE}
