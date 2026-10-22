"""Pure beat estimation and sampling utilities (numpy imported only for analysis)."""
import bisect
import math
import re


def netease_source_id(source_key):
    match = re.fullmatch(r'netease:([1-9][0-9]{0,18})', source_key) if isinstance(source_key, str) else None
    return match[1] if match else None

def estimate(energy, hop_ms=10):
    import numpy as np
    values=np.asarray(energy,dtype=float)
    if len(values)<200 or not np.isfinite(values).all() or values.max()<1e-7:
        raise ValueError('音频过短或没有足够清晰的节拍')
    novelty=np.maximum(values-np.concatenate(([0.0],values[:-1])),0)
    novelty=np.maximum(novelty-np.mean(novelty),0)
    if float(novelty.max())<1e-8: raise ValueError('未检测到清晰起音')
    lo,hi=int(60000/200/hop_ms),int(60000/55/hop_ms)
    scores=[float(np.dot(novelty[:-lag],novelty[lag:])) for lag in range(lo,min(hi,len(values)//2)+1)]
    lag=lo+int(np.argmax(scores))
    if max(scores)<=0: raise ValueError('未检测到重复节拍')
    # Stable periodic pulses often have equal half-tempo peaks: prefer the first strong peak.
    candidates=[i+lo for i,s in enumerate(scores) if s>=max(scores)*.94]
    lag=min(candidates)
    phase=max(range(lag),key=lambda offset:float(novelty[offset::lag].sum()))
    beats=[]
    radius=max(1,int(lag*.16))
    for predicted in range(phase,len(values),lag):
        left=max(0,predicted-radius);right=min(len(values),predicted+radius+1)
        peak=left+int(np.argmax(novelty[left:right]))
        if novelty[peak]>=float(novelty.max())*.06:
            point=peak*hop_ms
            if not beats or point>beats[-1]: beats.append(point)
    if len(beats)<3: raise ValueError('可用拍点不足')
    return {'bpm':60000/(lag*hop_ms),'beats_ms':beats,'duration_ms':len(values)*hop_ms}

def clock(position_ms,bpm,beats=(),offset_ms=0,speed=1):
    position=float(position_ms)-offset_ms
    if not math.isfinite(bpm) or not 20<=bpm<=400: return (-1,0.0,False,0.0)
    if beats:
        index=bisect.bisect_right(beats,position)-1
        if index<0:return (-1,0.0,False,bpm*speed)
        end=beats[index+1] if index+1<len(beats) else beats[index]+60000/bpm
        fraction=index+(position-beats[index])/max(1,end-beats[index])
    else:
        fraction=position*bpm/60000
        if fraction<0:return (-1,0.0,False,bpm*speed)
    fraction*=speed
    return (math.floor(fraction),fraction%1,True,bpm*speed)
