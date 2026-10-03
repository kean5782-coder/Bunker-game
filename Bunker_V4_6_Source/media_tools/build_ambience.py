"""Deterministic, original synthesized ambience. No recordings or Freesound keys.
Build-time dependencies: NumPy, SciPy, FFmpeg. Not needed by the game/EXE.
Circular spectral noise makes sample-accurate loops; exports both OGG and MP3.
"""
from pathlib import Path
import argparse, json, subprocess, hashlib
import numpy as np
from scipy.signal import butter, sosfilt
from scipy.io.wavfile import write
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'app/static/audio/realistic_bunker'
SR=32000
rng=np.random.default_rng(4601)

def periodic_noise(n,low,high,slope=0):
    f=np.fft.rfftfreq(n,1/SR)
    weight=(np.maximum(f,20)/100)**slope
    weight*=1/(1+(np.maximum(f,1)/high)**6)* (1/(1+(low/np.maximum(f,1))**6))
    weight[0]=0
    z=(rng.normal(size=len(f))+1j*rng.normal(size=len(f)))*weight
    x=np.fft.irfft(z,n)
    return x/(np.std(x)+1e-12)

def normal(x,rms,peak):
    x=x-np.mean(x,axis=0)
    x=x*(rms/(np.sqrt(np.mean(x*x))+1e-12))
    x*=min(1,peak/(np.max(np.abs(x))+1e-12))
    return x

def room(x,delays=(0.029,0.047,0.083),circular=True):
    y=x.copy()
    for i,d in enumerate(delays):
        s=int(d*SR)
        if circular:y+=np.roll(x,s)*(0.13/(i+1))
        else:y[s:]+=x[:-s]*(0.13/(i+1))
    return y

def base(kind,dur):
    n=round(SR*dur);t=np.arange(n)/SR
    # Only integer cycle counts: modulation matches across the loop boundary.
    mod=.9+.055*np.cos(2*np.pi*t/dur)+.03*np.sin(2*np.pi*3*t/dur)
    a=periodic_noise(n,60,1200,-.65)
    b=periodic_noise(n,90,1900,-.5)
    if kind=='ventilation':
        breath=periodic_noise(n,130,750,-.4)
        blade=np.sin(2*np.pi*(round(82.3*dur)/dur)*t)
        common=(.70*a+.10*breath)*(1+.065*blade)*mod
        x=np.column_stack([room(common+.14*b),room(common+.14*np.roll(b,1731))])
        return normal(x,.12,.42)
    if kind=='equipment':
        motor=np.zeros(n)
        for hz,g in [(48.6,.12),(97.2,.052),(145.8,.025),(194.4,.012),(243,.006)]:
            motor+=g*np.sin(2*np.pi*round(hz*dur)*t/dur+rng.uniform(0,6.28))
        turbulence=periodic_noise(n,40,540,-.9)
        x=(.22*turbulence+motor)*mod
        return normal(np.column_stack([room(x),room(np.roll(x,53))]),.065,.32)
    if kind=='wind':
        gust=(.65+.2*np.sin(2*np.pi*t/dur)+.1*np.cos(2*np.pi*3*t/dur))
        x=periodic_noise(n,80,900,-.8)*gust
        return normal(np.column_stack([x+.15*a,np.roll(x,463)+.15*b]),.085,.36)
    if kind=='rain':
        bed=periodic_noise(n,190,2400,-.15)*.3
        # Small irregular splashes, circularly wrapped; no sharp impacts.
        for _ in range(int(dur*27)):
            length=int(SR*rng.uniform(.008,.035));start=rng.integers(n)
            env=np.hanning(length)*np.exp(-np.arange(length)/(length*.38))
            drop=env*rng.normal(0,.45,length)
            np.add.at(bed,(start+np.arange(length))%n,drop)
        bed=sosfilt(butter(2,1900,fs=SR,output='sos'),bed)
        return normal(np.column_stack([bed+.1*a,np.roll(bed,367)+.1*b]),.085,.38)
    x=periodic_noise(n,32,320,-.8)*mod
    return normal(np.column_stack([room(x),room(np.roll(x,619))]),.095,.38)

def detail(kind,dur):
    n=round(dur*SR);t=np.arange(n)/SR;x=np.zeros(n)
    if kind=='relay':
        for at,loud in [(0.03,1),(.15,.5)]:
            q=t-at;active=q>=0;q=np.maximum(q,0)
            for hz,g in [(310,.19),(670,.15),(1120,.10),(1820,.045)]:
                x+=active*g*np.sin(2*np.pi*hz*q)*np.exp(-q*85)
            x+=active*rng.normal(0,.035,n)*np.exp(-q*180)
    elif kind=='metal':
        friction=sosfilt(butter(2,[170,1500],btype='bandpass',fs=SR,output='sos'),rng.normal(size=n))
        env=np.sin(np.pi*np.clip(t/(dur-.12),0,1))**2
        for hz,g in [(171,.13),(439,.045),(713,.027),(1071,.015)]:
            f=hz+4*np.sin(2*np.pi*1.3*t)+2*np.sin(2*np.pi*4.1*t)
            x+=g*np.sin(np.cumsum(2*np.pi*f/SR))*env
        x+=friction*env*.17
    else:
        x=periodic_noise(n,120,1300,-.7)*np.sin(np.pi*t/dur)**2*.08
    x=room(x,circular=False)
    fade=min(n//3,int(.04*SR));x[:fade]*=np.linspace(0,1,fade);x[-fade:]*=np.linspace(1,0,fade)
    x=normal(np.column_stack([x,np.roll(x,27)]),.03 if kind=='relay' else .065,.24)
    x[:64]*=np.linspace(0,1,64)[:,None];x[-64:]*=np.linspace(1,0,64)[:,None]
    return x

def export(name,x):
    OUT.mkdir(parents=True,exist_ok=True)
    wav=OUT/(name+'.wav');write(wav,SR,(np.clip(x,-1,1)*32767).astype(np.int16))
    for ext,codec,args in [('ogg','libvorbis',['-q:a','5']),('mp3','libmp3lame',['-b:a','128k'])]:
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(wav),'-c:a',codec,*args,str(OUT/(name+'.'+ext))],check=True)
    wav.unlink()
    return {'duration':len(x)/SR,'sample_rate':SR,'channels':2,'peak_dbfs':round(20*np.log10(np.abs(x).max()+1e-12),2),'rms_dbfs':round(20*np.log10(np.sqrt(np.mean(x*x))+1e-12),2),'urls':[name+'.ogg',name+'.mp3'],'sha256':{e:hashlib.sha256((OUT/(name+'.'+e)).read_bytes()).hexdigest() for e in ['ogg','mp3']}}

def main():
    manifest={'version':'4.6.0','origin':'Original procedural sound design; not a Freesound recording','notes':'No speech, melody, heartbeat, gunshots or siren. All assets bundled offline.','assets':{}}
    for kind,d in [('ventilation',36),('equipment',43),('wind',32),('rain',31),('rumble',37)]:
        manifest['assets'][kind]=export(kind,base(kind,d))
    for kind,d in [('relay',.45),('metal',2.6),('air_release',4.2)]:
        manifest['assets'][kind]=export(kind,detail(kind,d))
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
