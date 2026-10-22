"""Qt audio decoder helper. stdout is a JSON-lines progress/result protocol."""
import json
import os
import sys

def emit(kind,**fields):
    print(json.dumps({'type':kind,**fields},ensure_ascii=False),flush=True)

def run():
    # The GUI deliberately uses windows for playback; decoding needs Qt FFmpeg.
    os.environ["QT_MEDIA_BACKEND"]="ffmpeg"
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8")
    from PySide6.QtCore import QCoreApplication,QUrl,QTimer
    from PySide6.QtMultimedia import QAudioDecoder,QAudioFormat
    import numpy as np
    from .core import estimate
    args=[arg for arg in sys.argv[1:] if arg!='--beat-worker']
    if not args:emit('error',message='未指定本地音频');return
    app=QCoreApplication.instance() or QCoreApplication([])
    decoder=QAudioDecoder()
    # Decode in the file's native format. Forcing 48 kHz MP3 to 22.05 kHz
    # makes Qt 6.8's resampler yield an empty first buffer and stall on some
    # encoder-delay frames. Energy extraction needs no audio resampling.
    energy=[];tail=np.empty(0,dtype=np.float32);count=0
    sample_rate=0;hop=0;done=False
    timer=QTimer();timer.setSingleShot(True)
    def fail(message):
        nonlocal done
        if done:return
        done=True;timer.stop()
        emit('error',message=str(message));decoder.stop();QTimer.singleShot(0,app.quit)
    timer.timeout.connect(lambda:fail('音频解码超时，请使用手动BPM'))
    def consume():
        nonlocal tail,count,sample_rate,hop
        if done:return
        try:
            buffer=decoder.read()
            # An empty buffer is not an unsupported sample format. Keep the
            # inactivity timer running so a stalled decoder still terminates.
            if not buffer.isValid() or buffer.frameCount()==0:return
            format=buffer.format()
            mapping={QAudioFormat.SampleFormat.Float:np.float32,QAudioFormat.SampleFormat.Int16:np.int16,QAudioFormat.SampleFormat.Int32:np.int32,QAudioFormat.SampleFormat.UInt8:np.uint8}
            dtype=mapping.get(format.sampleFormat())
            if dtype is None:raise ValueError('解码器返回不支持的采样格式')
            rate,channels=format.sampleRate(),format.channelCount()
            if rate<=0 or channels<=0:raise ValueError('解码器返回无效采样率或声道数')
            if sample_rate and sample_rate!=rate:raise ValueError('音频中途改变采样率，暂不支持分析')
            sample_rate=rate;hop=max(1,round(rate*.01))
            samples=np.frombuffer(bytes(buffer.data()),dtype=dtype).astype(np.float32)
            if dtype==np.uint8:samples=(samples-128)/128
            elif dtype!=np.float32:samples/=np.iinfo(dtype).max
            if not np.isfinite(samples).all():raise ValueError('解码音频包含无效采样')
            # Average channel energy, not signed waveforms: opposite-phase
            # stereo channels must not cancel into artificial silence.
            power=np.mean(samples.reshape(-1,channels)**2,axis=1)
            power=np.concatenate((tail,power));usable=len(power)//hop*hop
            if usable:energy.extend(np.sqrt(np.mean(power[:usable].reshape(-1,hop),axis=1)).tolist())
            tail=power[usable:];count+=1
            if count%30==0:emit('progress',progress=min(90,round(max(0,decoder.position())/max(1,decoder.duration())*90)))
            if len(energy)*hop/rate>6*60*60:raise ValueError('音频超过6小时分析限制')
            timer.start(30000)
        except Exception as exc:
            fail(str(exc) if isinstance(exc,ValueError) else '音频采样处理失败')
    def finished():
        nonlocal done
        if done:return
        done=True
        timer.stop()
        try:
            if not sample_rate:raise ValueError('解码完成但未取得音频采样')
            emit('progress',progress=95)
            emit('result',data=estimate(energy,hop_ms=hop*1000/sample_rate))
        except Exception as exc:emit('error',message=str(exc))
        app.quit()
    decoder.bufferReady.connect(consume);decoder.finished.connect(finished)
    decoder.error.connect(lambda *_:fail(decoder.errorString() or '本地音频解码失败'))
    decoder.setSource(QUrl.fromLocalFile(args[-1]));timer.start(30000);decoder.start();app.exec()
if __name__=='__main__':run()
