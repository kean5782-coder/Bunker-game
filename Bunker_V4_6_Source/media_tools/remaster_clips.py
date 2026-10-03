"""V4.6 short-scene remaster. This is compositing/animation, NOT generated footage.
12 schematic clips are rebuilt from the game's existing detailed art; 13 original
clips retain their motion with conservative restoration. No invented 1080p label.
Build-time: FFmpeg, NumPy, Pillow, OpenCV. Game needs none of these tools.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import zipfile, json, subprocess, hashlib, math, io
import numpy as np
import cv2
from PIL import Image, ImageEnhance
cv2.setNumThreads(1)
ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'app/static'
INPUT=ROOT/'media_tools/input_v4_5.zip'
W,H,FPS,N=1280,720,24,120
if not INPUT.exists():
    with zipfile.ZipFile(INPUT,'w',zipfile.ZIP_STORED) as z:
        for kind,ext in [('images','jpg'),('videos','mp4')]:
            for f in sorted((STATIC/kind/'catastrophes').glob('*.'+ext)):
                z.write(f,f'{kind}/{f.name}')
ZIP=zipfile.ZipFile(INPUT)
TMP=ROOT/'media_tools/.render';TMP.mkdir(exist_ok=True)
for name in ZIP.namelist():
    dest=TMP/name;dest.parent.mkdir(exist_ok=True)
    if not dest.exists():dest.write_bytes(ZIP.read(name))

SPECS={
 'biological_mutation':('zombie_outbreak',(0.90,1.04,.84),1.065,'fog'),
 'black_hole_approach':('cosmic_radiation',(.88,.93,1.03),1.00,'gravity'),
 'cyber_blackout':('super_virus',(.74,.80,.93),1.04,'smoke'),
 'dark_matter_storm':('nuclear_winter',(.66,.70,.88),1.035,'dark'),
 'magnetic_flip':('nuclear_winter',(.80,.98,1.00),1.02,'aurora'),
 'mirror_virus':('ice_age',(.89,1.05,1.10),1.13,'crystal'),
 'orbital_debris':('super_virus',(.87,.91,1.05),1.025,'debris'),
 'parasite_infestation':('nanite_swarm',(1.06,.90,.72),1.075,'dust'),
 'permafrost_thaw':('ice_age',(.92,1.00,.90),1.08,'thaw'),
 'supervolcano':('atmospheric_fire',(1.00,.90,.77),1.075,'ash'),
 'synthetic_spores':('acid_rains',(.85,.91,1.04),1.09,'chemical'),
 'toxic_bloom':('global_flood',(1.02,.90,.94),1.01,'redwater'),
}

def img(name):
    x=np.asarray(Image.open(TMP/'images'/f'{name}.jpg').convert('RGB'))
    return cv2.resize(x,(W,H),interpolation=cv2.INTER_LANCZOS4).astype(np.float32)/255

def grain(seed):
    rng=np.random.default_rng(seed);out=np.zeros((H,W),np.float32)
    for w,h,k in [(9,5,.56),(21,12,.27),(47,27,.12),(93,53,.05)]:
        out+=cv2.resize(rng.random((h,w)).astype(np.float32),(W,H),interpolation=cv2.INTER_CUBIC)*k
    return np.clip(out,0,1)

Y,X=np.mgrid[:H,:W].astype(np.float32)
VIGNETTE=np.clip(1-.11*((X-W*.5)/(W*.8))**2-.08*((Y-H*.52)/(H*.9))**2,.8,1)[...,None]

def make_base(key):
    source,tint,zoom,fx=SPECS[key];b=img(source)
    # Different crop for a materially different composition without upscaling claims.
    m=cv2.getRotationMatrix2D((W*(.49 if fx in ['dust','ash'] else .53),H*.5),0,zoom)
    b=cv2.warpAffine(b,m,(W,H),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REFLECT_101)
    luma=b@np.array([.2126,.7152,.0722],np.float32)
    saturation=.72 if fx in ['dark','smoke','dust','ash'] else .88
    b=(luma[...,None]+(b-luma[...,None])*saturation)*np.array(tint,np.float32)
    if fx=='aurora':
        sky=img('cosmic_radiation');sky=cv2.resize(sky[:390,:860],(W,420))
        a=np.clip((315-Y)/210,0,.84)[...,None]
        padded=np.zeros_like(b);padded[:420]=sky
        b=b*(1-a)+padded*a
    if fx=='gravity':
        # Interpret the public scenario visually: a textured sky singularity.
        # Stylised artwork; no claim of a physically exact lensing simulation.
        # Remove the gamma beam by using the left side of the original sky.
        left=cv2.resize(img('cosmic_radiation')[:410,:730],(W,480));sky=np.zeros_like(b);sky[:480]=left
        blend=np.clip((470-Y)/150,0,1)[...,None];b=b*(1-blend)+sky*blend
        cx,cy=830,194;dx=X-cx;dy=Y-cy
        n=grain(940)
        r=np.sqrt(dx*dx+(dy*2.6)**2)
        arc=np.exp(-((r-178)/21)**2)*(0.45+.75*n)
        ring=np.exp(-((np.sqrt(dx*dx+dy*dy)-77)/9)**2)
        bloom=cv2.GaussianBlur(arc,(0,0),14)
        b=np.clip(b+arc[...,None]*np.array([.92,.59,.25])+bloom[...,None]*.25,0,1)
        mask=np.clip((77-np.sqrt(dx*dx+dy*dy))/3,0,1)
        b=b*(1-mask[...,None])+.004*mask[...,None]
        b+=ring[...,None]*np.array([.35,.28,.16])
    if fx=='redwater':
        a=np.clip((Y-290)/160,0,.74)[...,None]
        water=np.stack([luma*.94+.11,luma*.37,luma*.35],axis=-1)
        b=b*(1-a)+water*a
    if fx=='thaw':
        # Warmer thaw light in lower streets; retain snowy upper skyline.
        a=np.clip((Y-370)/350,0,.28)[...,None]
        b=b*(1-a)+b*np.array([1.12,1.04,.85])*a
    if fx=='crystal':
        b=np.clip(b*1.035,0,1)
    if fx=='ash':
        # Softer highlights avoid the original bright posterised fire.
        b=np.power(np.clip(b,0,1),1.05)
    if fx=='dark':
        b=np.power(np.clip(b,0,1),1.12)*.84
    return np.clip(b*VIGNETTE,0,1).astype(np.float32),fx

def cue(name):
    if name in ['acid_rains','global_flood','toxic_bloom','permafrost_thaw']:return 'rain'
    if name in ['nuclear_winter','ice_age','dark_matter_storm','cosmic_radiation','synthetic_spores']:return 'wind'
    if name in ['asteroid_impact','atmospheric_fire','supervolcano','black_hole_approach','orbital_debris','alien_invasion','nanite_swarm']:return 'rumble'
    return 'ventilation'

def rebuild(key):
    b,fx=make_base(key)
    (STATIC/'images/catastrophes'/f'{key}.jpg').write_bytes(b'')
    Image.fromarray(np.uint8(np.clip(b*255,0,255))).save(STATIC/'images/catastrophes'/f'{key}.jpg',quality=94,subsampling=0)
    # Noise overlays drift smoothly through one cycle rather than flickering.
    n=grain(460+list(SPECS).index(key));fog=np.maximum(n-.22,0)[...,None]
    mask=np.exp(-((Y-H*.64)/(H*.30))**2)[...,None]
    col=np.array({'fog':(.30,.40,.25),'chemical':(.41,.35,.45),'dust':(.39,.33,.24),'ash':(.28,.25,.22),'dark':(.10,.13,.20),'smoke':(.17,.18,.22)}.get(fx,(.40,.44,.46)),np.float32)
    amount=.10 if fx in ['fog','chemical','ash'] else .045
    audio=STATIC/'audio/realistic_bunker'/f'{cue(key)}.mp3'
    cmd=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','pipe:0','-i',str(audio),'-t','5','-map','0:v','-map','1:a','-c:v','libx264','-preset','medium','-crf','18','-profile:v','high','-level','3.1','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-b:a','112k','-af','volume=0.6,afade=t=in:d=0.18,afade=t=out:st=4.65:d=0.35','-movflags','+faststart',str(STATIC/'videos/catastrophes'/f'{key}.mp4')]
    p=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    try:
        for i in range(N):
            phase=2*math.pi*i/N
            scale=1.012+.004*math.sin(phase-math.pi/2)
            m=cv2.getRotationMatrix2D((W*.5,H*.5),0,scale)
            m[0,2]+=2.3*math.sin(phase);m[1,2]+=1.2*math.sin(phase+.6)
            frame=cv2.warpAffine(b,m,(W,H),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
            shift=int(20*math.sin(phase));mist=np.roll(fog,shift,axis=1)*mask*amount
            frame=frame*(1-mist)+col*mist
            if fx=='debris':
                # Three small visible orbital streaks, not giant abstract symbols.
                for j in range(3):
                    s=(i/N+j*.27)%1
                    if .07<s<.65:
                        a=math.sin(math.pi*(s-.07)/.58)*.65
                        x=int(W*(.14+j*.25)+s*150);y=int(30+s*200)
                        overlay=frame.copy();cv2.line(overlay,(x-30,y-44),(x,y),(.95,.72,.35),1,cv2.LINE_AA)
                        frame=frame*(1-a)+overlay*a
            if fx=='crystal':
                glint=(.5+.5*math.sin(phase))*.018
                high=(frame.mean(axis=2)>.72)[...,None]
                frame+=high*glint
            p.stdin.write(np.ascontiguousarray(np.uint8(np.clip(frame*255,0,255))).tobytes())
    finally:p.stdin.close()
    if p.wait()!=0:raise RuntimeError(f'Encoder failed: {key}')
    print('Rebuilt',key,flush=True)
    return {'id':key,'action':'recomposed animated illustration','sources':[SPECS[key][0]]+(['cosmic_radiation'] if fx=='aurora' else []),'cue':cue(key)}

def restore(key):
    src=TMP/'videos'/f'{key}.mp4';out=STATIC/'videos/catastrophes'/f'{key}.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(src),'-i',str(STATIC/'audio/realistic_bunker'/f'{cue(key)}.mp3'),'-t','5','-map','0:v:0','-map','1:a:0','-vf','hqdn3d=0.55:0.4:0.8:0.6,unsharp=5:5:0.18:3:3:0,eq=gamma=1.015:saturation=0.985','-c:v','libx264','-preset','medium','-crf','18','-profile:v','high','-level','3.1','-pix_fmt','yuv420p','-threads','2','-c:a','aac','-b:a','112k','-af','volume=0.6,afade=t=in:d=0.18,afade=t=out:st=4.65:d=0.35','-movflags','+faststart',str(out)],check=True)
    print('Restored',key,flush=True)
    return {'id':key,'action':'original motion, mild denoise and sharpening','sources':[key],'cue':cue(key)}

def work(k):
    out=STATIC/'videos/catastrophes'/f'{k}.mp4'
    try:
        probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(out)],stderr=subprocess.DEVNULL))
        v=next(x for x in probe['streams'] if x['codec_type']=='video')
        if any(x['codec_type']=='audio' for x in probe['streams']) and int(v.get('nb_frames','0'))>=120:
            return {'id':k,'action':'recomposed animated illustration' if k in SPECS else 'original motion, mild denoise and sharpening','sources':[SPECS[k][0] if k in SPECS else k]+(['cosmic_radiation'] if k=='magnetic_flip' else []),'cue':cue(k)}
    except (ValueError,subprocess.CalledProcessError,StopIteration):pass
    return rebuild(k) if k in SPECS else restore(k)

def main():
    keys=sorted(x.stem for x in (TMP/'videos').glob('*.mp4'))
    with ThreadPoolExecutor(max_workers=3) as pool:
        items=list(pool.map(work,keys))
    for item in items:
        item.update({'duration':5,'width':1280,'height':720,'fps':24,'audio':'AAC','sha256':hashlib.sha256((STATIC/'videos/catastrophes'/f'{item["id"]}.mp4').read_bytes()).hexdigest()})
    (STATIC/'videos/catastrophes/media_manifest.json').write_text(json.dumps({'version':'4.6.0','notes':'12 re-composed animated illustrations, 13 restored existing clips. Native delivery 720p; not AI-generated video or recovered HD detail. Audio is locally synthesized, not external recordings.','clips':items},ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
