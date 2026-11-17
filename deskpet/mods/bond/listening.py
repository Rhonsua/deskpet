"""Conservative coverage of actual audible intervals, never time spent idle."""
import uuid


class Coverage:
    def __init__(self):self.reset()
    def reset(self):
        self.source='';self.duration=0.;self.title='';self.ranges=[];self.last=0.

    def sample(self,data):
        track=data.get('track') or {}
        source=track.get('source','');position=track.get('position',0);duration=track.get('duration',0)
        seconds=data.get('seconds',0)
        if not source or not 0<seconds<=5 or duration<30 or not 0<=position<=duration+1:return
        if source!=self.source or abs(duration-self.duration)>1 or position<self.last-2:
            self.reset();self.source=source;self.duration=duration
        self.title=data.get('title','未命名歌曲');self.last=position
        start=max(0,position-seconds);end=min(position,duration)
        if self.ranges and start<=self.ranges[-1][1]+.15:
            self.ranges[-1]=(self.ranges[-1][0],max(end,self.ranges[-1][1]))
        else:self.ranges.append((start,end))

    def finish(self,source):
        if source!=self.source:return None
        total=sum(b-a for a,b in self.ranges)
        result=None
        if self.duration and total>=self.duration*.9 and self.duration-self.last<=3:
            result=dict(session=uuid.uuid4().hex,source=self.source,title=self.title)
        self.reset()
        return result
