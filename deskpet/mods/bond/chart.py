"""Deterministic musical chart compilation and frame-independent judgement."""
import hashlib
import json
import math
import random
from bisect import bisect_right

VERSION=3


def digest(chart):
    fields={k:v for k,v in chart.items() if k not in ('id','title','saved','favorite')}
    return hashlib.sha256(json.dumps(fields,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def validate(chart):
    duration=chart['duration'];lanes=chart['lanes'];notes=chart['notes']
    if lanes not in (3,4) or not 15<=duration<=120 or len(notes)>3000:raise ValueError('谱面大小无效')
    ids=set();occupied=[-1.]*lanes
    for n in sorted(notes,key=lambda n:(n['at'],n['lane'])):
        if n['id'] in ids:raise ValueError('重复音符')
        ids.add(n['id'])
        at,end=n['at'],n['end'];lane=n['lane']
        if type(lane) is not int or not 0<=lane<lanes or not all(math.isfinite(x) for x in (at,end)):
            raise ValueError('音符参数无效')
        if not 0<=at<=end<=duration or n['type'] not in ('tap','hold'):raise ValueError('音符超出片段')
        if n['type']=='tap' and end!=at or n['type']=='hold' and end-at<.3:raise ValueError('长条长度无效')
        if at<occupied[lane]+.2:raise ValueError('同轨音符重叠')
        occupied[lane]=end
    events=[]
    for n in notes:events.extend(((n['at'],1),(n['end']+.01,-1)))
    count=0
    for _,change in sorted(events,key=lambda v:(v[0],v[1])):
        count+=change
        if count>(1 if chart['input']=='mouse' else 2):raise ValueError('输入方式无法完成此组合')
    return chart


def generate(analysis, *, source='', offset=0., duration=40., bpm=120., lanes=3,
             difficulty='easy', input_mode='keyboard', seed=0):
    if difficulty not in ('easy','normal','hard'):raise ValueError('难度无效')
    rng=random.Random(seed)
    step=60/max(50,min(220,bpm))
    pulses=[round(float(x)/1000-offset,3) for x in analysis.get('beats_ms',[])
            if offset+2<=float(x)/1000<=offset+duration-1]
    musical=bool(pulses)
    if not pulses:pulses=[round(2+i*step,3) for i in range(max(1,int((duration-3)/step)))]
    onsets=[round(float(x)/1000-offset,3) for x in analysis.get('onsets_ms',[])
            if offset+2<=float(x)/1000<=offset+duration-1]
    candidates=sorted(set(pulses+(onsets if difficulty!='easy' else [])))
    if not musical and difficulty=='hard':candidates=sorted(set(candidates+[round(t+step/2,3) for t in pulses if t+step/2<duration-1]))
    regions=[(a/1000-offset,b/1000-offset) for a,b in analysis.get('sustain_regions_ms',[])]
    notes=[];occupied=[-1.]*lanes;previous=-1;last_at=-1
    # Phrase templates express alternating hands, echoes and inward/outward runs.
    # Seed selects whole phrases; occupied lanes still take priority over style.
    templates=[(0,lanes-1,1,lanes-2),(0,0,lanes-1,lanes-1),tuple(range(lanes)),
               tuple(range(lanes-1,-1,-1)),(0,1,lanes-1,1),(1,0,1,lanes-1)]
    phrase_patterns={};phrase_counts={}
    density={'easy':.73,'normal':.85,'hard':.96}[difficulty]
    minimum={'easy':.38,'normal':.27,'hard':.20}[difficulty]
    for at in candidates:
        phrase=max(0,bisect_right(pulses,at)-1)//8
        if phrase not in phrase_patterns:
            previous_pattern=phrase_patterns.get(phrase-1)
            phrase_patterns[phrase]=(tuple(lanes-1-x for x in previous_pattern) if previous_pattern and rng.random()<.3 else rng.choice(templates))
            phrase_counts[phrase]=0
        pulse_index=max(0,bisect_right(pulses,at)-1)
        local_density=density*(.68 if pulse_index%8==7 else 1.)
        if at-last_at<minimum or rng.random()>local_density:continue
        active=sum(end+.12>at for end in occupied)
        if active >= (1 if input_mode=='mouse' else 2):continue
        available=[lane for lane in range(lanes) if occupied[lane]+.22<=at]
        if not available:continue
        pattern=phrase_patterns[phrase];preferred=pattern[phrase_counts[phrase]%len(pattern)]
        lane=preferred if preferred in available else min(available,key=lambda x:abs(x-preferred))
        phrase_counts[phrase]+=1
        end=at
        region=next((b for a,b in regions if a-.15<=at<b-.4),None)
        can_hold=region is not None or not musical
        if can_hold and rng.random()<(.2 if difficulty=='easy' else .3):
            end=min(at+step*rng.choice((1,2,3)),region if region is not None else duration-1,duration-1)
            if end-at<.4:end=at
        notes.append(dict(id=str(len(notes)),type='hold' if end>at else 'tap',lane=lane,at=at,end=round(end,3)))
        occupied[lane]=end;previous=lane;last_at=at
        if input_mode!='mouse' and difficulty!='easy' and active==0 and rng.random()<.12:
            other=[x for x in available if x!=lane]
            if other:
                lane2=rng.choice(other)
                notes.append(dict(id=str(len(notes)),type='tap',lane=lane2,at=at,end=at));occupied[lane2]=at
    chart=dict(version=VERSION,source=source,offset=offset,duration=duration,bpm=bpm,lanes=lanes,
               difficulty=difficulty,input=input_mode,seed=seed,practice=not musical,notes=notes,
               phrases=[list(phrase_patterns[k]) for k in sorted(phrase_patterns)])
    validate(chart);chart['id']=digest(chart)
    return chart


class Judgement:
    def __init__(self, chart):
        validate(chart)
        self.chart=chart
        self.notes=[dict(n,state='pending',head=0.,covered=0.,last=n['at'],release=None) for n in chart['notes']]
        self.combo=self.best=self.hits=self.misses=self.perfect=self.good=self.holds=0
        self.weight=0.;self.held=set();self.elapsed=0.

    @property
    def score(self):return round(1000000*self.weight/max(1,len(self.notes)))

    def press(self, lane, seconds):
        if lane in self.held:return ''
        self.advance(seconds)
        self.held.add(lane)
        for n in self.notes:
            if n['lane']==lane and n['state']=='holding':n['release']=None
        candidates=[n for n in self.notes if n['lane']==lane and n['state']=='pending' and abs(n['at']-seconds)<=.18]
        if not candidates:return ''
        n=min(candidates,key=lambda n:(abs(n['at']-seconds),n['at']))
        coefficient=1. if abs(n['at']-seconds)<=.085 else .6
        n['head']=coefficient;self.hits+=1;self.combo+=1;self.best=max(self.best,self.combo)
        if n['type']=='tap':self.finish(n,coefficient)
        else:n.update(state='holding',last=max(seconds,n['at']),release=None)
        return '完美' if coefficient==1 else '良好'

    def release(self,lane,seconds):
        self.advance(seconds);self.held.discard(lane)
        for n in self.notes:
            if n['lane']==lane and n['state']=='holding':n['release']=seconds

    def finish(self,n,weight,miss=False):
        if n['state']=='done':return
        n['state']='done';self.weight+=weight
        if miss:self.misses+=1;self.combo=0
        elif n['head']==1:self.perfect+=1
        else:self.good+=1

    def advance(self,seconds):
        if seconds<self.elapsed:return
        self.elapsed=seconds
        for n in self.notes:
            if n['state']=='pending' and seconds>n['at']+.18:self.finish(n,0,True)
            elif n['state']=='holding':
                until=min(seconds,n['end'])
                if n['lane'] in self.held:n['covered']+=max(0,until-max(n['last'],n['at']))
                n['last']=until
                fraction=min(1,n['covered']/max(.001,n['end']-n['at']))
                if n['release'] is not None and seconds-n['release']>.06:
                    self.finish(n,.4*n['head']+.4*fraction,True)
                elif seconds>=n['end'] and n['lane'] in self.held:
                    self.holds+=1;self.finish(n,.4*n['head']+.4*fraction+.2)

    def suspend(self,seconds):
        self.advance(seconds);self.held.clear()
        for n in self.notes:
            if n['state']=='holding':n['release']=None

    def rearm(self):
        # Resuming a suspended hold is allowed; user has to hold its lane again.
        for n in self.notes:
            if n['state']=='holding' and n['lane'] not in self.held:n['release']=self.elapsed
