"""Explicit sample-bound muting for one continuous, zero-start authorized audio track."""
import hashlib,io,json,shutil,tempfile,wave
from pathlib import Path
from . import core
MAX_PCM=64*1024*1024
RATES=(8000,16000,22050,24000,32000,44100,48000)
class AudioMismatch(core.Invalid):
    def __init__(self,interval,sample):
        super().__init__('Declared mute interval is not silent.')
        self.location={'mute_index':interval,'sample_index':sample}
def sha(raw):return hashlib.sha256(raw).hexdigest()

def _audio_meta(path,fmt,source=False):
    data=core.run('ffprobe',['-v','error',*core.input_options(fmt),'-select_streams','a','-show_entries','stream=codec_name,sample_rate,channels,start_time,time_base','-of','json',str(path)])
    try:
        streams=json.loads(data)['streams']
        if len(streams)!=1:raise core.Invalid('Exactly one audio stream required.')
        s=streams[0];rate=int(s['sample_rate']);channels=int(s['channels'])
        if rate not in RATES or channels not in (1,2) or s.get('start_time')!='0.000000':raise core.Invalid('Unsupported audio clock or layout.')
        if s['codec_name'] not in (('aac','pcm_s16le') if source else ('pcm_s16le',)):raise core.Invalid('Unsupported audio codec.')
        if source:
            if s['time_base']!='1/'+str(rate):raise core.Invalid('Source audio needs a sample-based time base.')
            frames=json.loads(core.run('ffprobe',['-v','error',*core.input_options(fmt),'-select_streams','a','-show_frames','-show_entries','frame=pts,nb_samples','-of','json',str(path)],limit=4*1024*1024))['frames']
            count=0
            for frame in frames:
                if type(frame.get('pts')) is not int or frame['pts']!=count or type(frame.get('nb_samples')) is not int or not 1<=frame['nb_samples']<=65536:raise core.Invalid('Source audio timestamps must be contiguous from zero.')
                count+=frame['nb_samples']
                if count*channels*2>MAX_PCM:raise core.Invalid('Decoded audio exceeds bound.')
            if not count:raise core.Invalid('No decoded audio samples.')
        return {'sample_rate':rate,'channels':channels,'codec':s['codec_name'],**({'samples':count} if source else {})}
    except (ValueError,KeyError,TypeError,OverflowError):raise core.Invalid('Unsupported audio metadata or discontinuous timestamps.') from None

def _pcm(path,fmt,dest):
    core.run('ffmpeg',['-hide_banner','-loglevel','error','-nostdin','-n',*core.input_options(fmt),'-i',str(path),'-map','0:a:0','-vn','-sn','-dn','-c:a','pcm_s16le','-threads','1','-fs',str(MAX_PCM+1),'-f','s16le',str(dest)])
    return core.read(dest,MAX_PCM,utf8=False)

def _source(source,temp):
    src=temp/'source.mp4';source_sha=core.snapshot(source,src);info=core.probe(src,'mov');types=core.stream_types(src,'mov')
    if types.count('audio')!=1:raise core.Invalid('Exactly one source audio track required.')
    video=json.loads(core.run('ffprobe',['-v','error',*core.input_options('mov'),'-select_streams','v','-show_entries','stream=start_time','-of','json',str(src)]))
    if video.get('streams')!=[{'start_time':'0.000000'}]:raise core.Invalid('Source video must start at zero.')
    audio=_audio_meta(src,'mov',True);pcm=_pcm(src,'mov',temp/'source.pcm')
    if len(pcm)!=audio['samples']*audio['channels']*2:raise core.Invalid('Decoded audio size differs from timestamp scan.')
    return src,source_sha,info,audio,pcm

def inspect_audio(source):
    with tempfile.TemporaryDirectory(prefix='frame-veil-audio-') as t:
        _,source_sha,video,audio,_=_source(source,Path(t))
        return {'source_sha256':source_sha,'video':video,'audio':audio,'indexing':'Zero-based decoded PCM sample frames, both channels together; exclusive end. Not encoded AAC packets or video frames.','manual_review_required':True}

def load_audio_plan(raw,source_sha,audio):
    p=core.parse(raw);core.fields(p,['schema','source_sha256','sample_rate','channels','samples','mute_ranges']);core.integer(p['schema'],1,1)
    if type(p['source_sha256']) is not str or p['source_sha256']!=source_sha:raise core.Invalid('Audio plan source binding differs.')
    for k in ('sample_rate','channels','samples'):
        if type(p[k]) is not int or p[k]!=audio[k]:raise core.Invalid('Audio plan parameters differ.')
    if type(p['mute_ranges']) is not list or not 1<=len(p['mute_ranges'])<=100:raise core.Invalid('Supply 1..100 explicit mute ranges.')
    for r in p['mute_ranges']:
        core.fields(r,['start_sample','end_sample']);core.integer(r['start_sample'],0,audio['samples']-1);core.integer(r['end_sample'],r['start_sample']+1,audio['samples'])
    return p

def _wav(pcm,audio):
    out=io.BytesIO()
    with wave.open(out,'wb') as w:w.setnchannels(audio['channels']);w.setsampwidth(2);w.setframerate(audio['sample_rate']);w.writeframes(pcm)
    return out.getvalue()

def _read_wav(raw):
    try:
        with wave.open(io.BytesIO(raw),'rb') as w:
            if w.getsampwidth()!=2 or w.getcomptype()!='NONE' or w.getnchannels() not in (1,2) or w.getframerate() not in RATES:raise core.Invalid('Unsupported normalized WAV.')
            audio={'sample_rate':w.getframerate(),'channels':w.getnchannels(),'samples':w.getnframes()};core.integer(audio['samples'],1,MAX_PCM//(audio['channels']*2));pcm=w.readframes(audio['samples']+1)
            if len(pcm)!=audio['samples']*audio['channels']*2:raise core.Invalid('WAV data size differs.')
            if raw!=_wav(pcm,audio):raise core.Invalid('Only the exact normalized WAV layout is accepted; extra chunks/trailing data rejected.')
            return audio,pcm
    except (wave.Error,EOFError,OSError):raise core.Invalid('Invalid normalized WAV.') from None

def _snapshot_bundle(folder,temp):
    root=Path(folder);names={'video','audio-plan.json','redacted.wav','review.mkv','receipt.json'}
    if root.is_symlink() or not root.is_dir() or {p.name for p in root.iterdir()}!=names:raise core.Invalid('Unexpected audio bundle structure.')
    video=root/'video'
    if video.is_symlink() or not video.is_dir() or {p.name for p in video.iterdir()}!={'redacted.mkv','plan.json','receipt.json'}:raise core.Invalid('Unexpected nested video bundle.')
    (temp/'video').mkdir()
    for name,limit in [('audio-plan.json',core.INPUT_LIMIT),('redacted.wav',MAX_PCM+1024),('review.mkv',core.MAX_OUTPUT),('receipt.json',core.INPUT_LIMIT)]:
        (temp/name).write_bytes(core.read(root/name,limit,utf8=False))
    for name,limit in [('redacted.mkv',core.MAX_OUTPUT),('plan.json',core.INPUT_LIMIT),('receipt.json',core.INPUT_LIMIT)]:
        (temp/'video'/name).write_bytes(core.read(video/name,limit,utf8=False))

def _check(temp):
    base=core.verify(temp/'video');r=core.parse(core.read(temp/'receipt.json'))
    core.fields(r,['schema','source_sha256','video_output_sha256','audio_plan_sha256','wav_sha256','review_sha256','audio','manual_review_required','scope']);core.integer(r['schema'],1,1)
    if r['manual_review_required'] is not True or r['scope']!='Manual sample muting; no automatic privacy detection or publication authorization.':raise core.Invalid('Invalid audio receipt scope.')
    if r['video_output_sha256']!=base['output_sha256']:raise core.Invalid('Video base differs.')
    plan_raw=core.read(temp/'audio-plan.json');wav_raw=core.read(temp/'redacted.wav',MAX_PCM+1024,utf8=False);review_raw=core.read(temp/'review.mkv',core.MAX_OUTPUT,utf8=False)
    if any(r[k]!=sha(v) for k,v in [('audio_plan_sha256',plan_raw),('wav_sha256',wav_raw),('review_sha256',review_raw)]):raise core.Invalid('Audio bundle hashes differ.')
    a,pcm=_read_wav(wav_raw)
    if core.canonical(r['audio'])!=core.canonical(a):raise core.Invalid('Audio receipt parameters differ.')
    vplan=core.load_plan(core.read(temp/'video'/'plan.json'),base['output'])
    if r['source_sha256']!=vplan['source_sha256']:raise core.Invalid('Audio and video source bindings differ.')
    plan=load_audio_plan(plan_raw,r['source_sha256'],a)
    if core.stream_types(temp/'review.mkv','matroska')!=['video','audio']:raise core.Invalid('Combined output must contain only one video and one audio.')
    combined_video=core.probe(temp/'review.mkv','matroska')
    if core.canonical(combined_video)!=core.canonical(base['output']):raise core.Invalid('Combined video frame properties differ.')
    combined_audio=_audio_meta(temp/'review.mkv','matroska')
    if any(combined_audio[k]!=a[k] for k in ('sample_rate','channels')):raise core.Invalid('Combined audio parameters differ.')
    decoded=_pcm(temp/'review.mkv','matroska',temp/'combined.pcm')
    if decoded!=pcm:raise core.Invalid('Combined audio differs from reviewed WAV samples.')
    return r,plan,a,pcm

def render_audio(source,video_plan,audio_plan,out):
    audio_raw=core.read(audio_plan)
    with tempfile.TemporaryDirectory(prefix='frame-veil-audio-') as t:
        temp=Path(t);src,source_sha,_,a,pcm=_source(source,temp);plan=load_audio_plan(audio_raw,source_sha,a)
        bundle=temp/'bundle';bundle.mkdir();core.render(src,video_plan,bundle/'video')
        muted=bytearray(pcm);width=a['channels']*2
        for interval in plan['mute_ranges']:muted[interval['start_sample']*width:interval['end_sample']*width]=bytes((interval['end_sample']-interval['start_sample'])*width)
        wav=_wav(muted,a);(bundle/'redacted.wav').write_bytes(wav);(bundle/'audio-plan.json').write_bytes(audio_raw)
        core.run('ffmpeg',['-hide_banner','-loglevel','error','-nostdin','-n',*core.input_options('matroska'),'-i',str(bundle/'video'/'redacted.mkv'),*core.input_options('wav'),'-i',str(bundle/'redacted.wav'),'-map','0:v:0','-map','1:a:0','-sn','-dn','-map_metadata','-1','-map_metadata:s','-1','-map_chapters','-1','-c:v','copy','-c:a','pcm_s16le','-threads','1','-fs',str(core.MAX_OUTPUT),'-f','matroska',str(bundle/'review.mkv')])
        params={k:a[k] for k in ('sample_rate','channels','samples')};r={'schema':1,'source_sha256':source_sha,'video_output_sha256':sha(core.read(bundle/'video'/'redacted.mkv',core.MAX_OUTPUT,utf8=False)),'audio_plan_sha256':sha(audio_raw),'wav_sha256':sha(wav),'review_sha256':sha(core.read(bundle/'review.mkv',core.MAX_OUTPUT,utf8=False)),'audio':params,'manual_review_required':True,'scope':'Manual sample muting; no automatic privacy detection or publication authorization.'};(bundle/'receipt.json').write_bytes(core.canonical(r));_check(bundle)
        shutil.copytree(bundle,out,ignore=shutil.ignore_patterns('combined.pcm'))
        return {'rendered':True,'audio':params,'all_audio_removed':False,'manual_review_required':True}

def verify_audio(folder):
    with tempfile.TemporaryDirectory(prefix='frame-veil-audio-check-') as t:
        temp=Path(t);_snapshot_bundle(folder,temp);r,plan,a,pcm=_check(temp);width=a['channels']*2;checks=0
        for i,interval in enumerate(plan['mute_ranges']):
            first=interval['start_sample'];last=interval['end_sample'];segment=pcm[first*width:last*width]
            if segment.count(0)!=len(segment):
                bad=next(j for j,b in enumerate(segment) if b);raise AudioMismatch(i,first+bad//width)
            checks+=last-first
        # Audit the actual combined video's frames, not only the fallback video.
        only=temp/'combined-video.mkv'
        core.run('ffmpeg',['-hide_banner','-loglevel','error','-nostdin','-n',*core.input_options('matroska'),'-i',str(temp/'review.mkv'),'-map','0:v:0','-an','-sn','-dn','-map_metadata','-1','-c:v','copy','-f','matroska',str(only)])
        raw=core.read(only,core.MAX_OUTPUT,utf8=False);(temp/'video'/'redacted.mkv').write_bytes(raw);receipt=core.parse(core.read(temp/'video'/'receipt.json'));receipt['output_sha256']=sha(raw);(temp/'video'/'receipt.json').write_bytes(core.canonical(receipt));video_audit=core.audit_masks(temp/'video')
        return {'consistent':True,'declared_mutes_silent':True,'declared_video_masks_opaque':video_audit['declared_masks_opaque'],'sample_frame_checks_including_overlap':checks,'audio':a,'manual_review_required':True,'scope':'Declared decoded sample ranges and video rectangles only; unmarked privacy, source authenticity and semantic/timing correctness are not certified.'}
