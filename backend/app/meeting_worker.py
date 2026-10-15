"""Explicitly provisioned local engine only. Run as a cancellable child process."""
import json
import sys
from pathlib import Path


def main():
    from faster_whisper import WhisperModel
    audio,output,model=sys.argv[1:]
    engine=WhisperModel(model,device='cpu',compute_type='int8',local_files_only=True)
    segments,_=engine.transcribe(audio,vad_filter=True)
    result=[]
    for segment in segments:
        if segment.end>7200 or len(result)>=100000:raise ValueError('Meeting exceeds two-hour processing limit')
        result.append({'start':segment.start,'end':segment.end,'text':segment.text.strip()})
    Path(output).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':main()
