import os
import json
import tempfile
import subprocess
import shutil
import re
import logging
from flask import Flask, request, jsonify, send_file

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

SUBTITLE_STYLES = {
    'tiktok_bold': {'FontName': 'Arial Black','FontSize': 24,'PrimaryColour': '&H00FFFFFF','OutlineColour': '&H00000000','Outline': 3,'Bold': 1,'Shadow': 0,'Alignment': 2,'MarginV': 50},
    'clean': { 'FontName': 'Arial','FontSize': 20,'PrimaryColour': '&H00FFFFFF','OutlineColour': '&H00000000','Outline': 1,'Bold': 0,'Shadow': 1,'Alignment': 2,'MarginV': 40},
    'impacto': {'FontName': 'Impact','FontSize': 28,'PrimaryColour': '&H00FFFFFF','OutlineColour': '&H00000000','Outline': 3,'Bold': 1,'Shadow': 0,'Alignment': 5,'MarginV': 0},
    'minimalista': {'FontName': 'Arial','FontSize': 16,'PrimaryColour': '&H00FFFFFF','OutlineColour': '&H80000000','Outline': 1,'Bold': 0,'Shadow': 0,'Alignment': 2,'MarginV': 30},
    'karaoke': {'FontName': 'Arial Black','FontSize': 22,'PrimaryColour': '&H00FFFFFF','OutlineColour': '&H00000000','Outline': 2,'Bold': 1,'Shadow': 0,'Alignment': 2,'MarginV': 50},
}

import os, json, tempfile, subprocess, shutil, re, logging
from flask import Flask, request, jsonify, send_file

def get_video_duration(p):
    r=subprocess.run(['ffprobe','-v','quiet','-print_format','json','-show_streams',p],capture_output=True,text=True)
    try:
        for s in json.loads(r.stdout).get('streams',[]):
            if s.get('codec_type')=='video' and float(s.get('duration',0))>0: return float(s.get('duration'))
    except: pass
    return 60.0

def hex_to_ass(c):
    c=c.lstrip('#'); r,g,b=int(c[:2],16),int(c[2:4],16),int(c[4:6],16)
    return f'&H00{b:02X}{g:02X}{r:02X}'

def text_to_srt(text,dur,srt_path):
    parts=re.split(r'(?<=[.!?\s*]).+|(?<=,).+', text.strip())
    parts=[p.strip() for p in parts if p.strip()]
    chunks=[]
    for p in parts:
        w=p.split()
        for i in range(0,max(len(w),1),8): chunks.append(' '.join(w[i:i+8]))
    if not chunks: chunks=[text.strip()]
    cd=dur/len(chunks)
    def fmt(s): return f'{int(s//3600):02d}:{int((s%3600)//60):02d}:{int(s%60):02d},{int((s%1)*1000):03d}'
    with open(srt_path,'w',encoding='utf-8') as f:
        for i,c in enumerate(chunks): f.write(f'{i+1}\n{fmt(i*cd)} --> {fmt(i*cd+cd-0.05)}\n{c}\n\n')

def build_style(n,pos,col):
    s=SUBTITLE_STYLES,¿¿Wt(n,SUBTITLE_STYLES['tiktok_bold']).copy()
    s.get(n,SUBTITLE_STYLES['tiktok_bold'])
    s=SUBTITLE_STYLES.get(n,SUBTITLE_STYLES['tiktok_bold']).copy()
    s['Alignment']={'top':8,'center':5,'bottom':2}.get(pos,2)
    if pos=='top': s['MarginV']=50
    elif pos=='center': s['MarginV']=0
    if col and col.startswith('#') and col!='#FFFFFF': s['PrimaryColour']=hex_to_ass(col)
    return ','.join(f'{k}={v}' for k,v in s.items())

def burn_subs(inp,srt,out,n,pos,col):
    f=build_style(n,pos,col)
    e=srt.replace('\\','/').replace(':','\\:')
    r=subprocess.run(['ffmpeg','-i',inp,'-vf',f"subtitles='{e}':force_style='{f}'",\
        '-c:a','copy','-preset','fast','-y' ,out],capture_output=True,text=True,timeout=600)
    if r.returncode!=0: raise RuntimeError(f'FFmpeg: {r.stderr[-500:]}')

@app.route('/health')
def health(): return jsonify({'status':'ok','service':'genius-ffmpeg'})

@app.route('/process-video', methods=['POST'])
def process_video():
    if 'video' not in request.files: return jsonify({'error':'Missing video'}),400
    vf=request.files['video']
    try: cfg=json.loads(request.form.get('config','{}'))
    except: return jsonify({'error':'Bad JSON'}),400
    sub=cfg.get('subtitles',{})
    tmp=tempfile.mkdtemp()
    try:
        inp=os.path.join(tmp,'input.mp4'); out=os.path.join(tmp,'output.mp4'); srt=os.path.join(tmp,'s.srt')
        vf.save(inp)
        if sub.get('enabled') and sub.get('text','').strip():
            text_to_srt(sub['text'],get_video_duration(inp),srt)
            burn_subs(inp,srt,out,sub.get('style','tiktok_bold'),sub.get('position','bottom'),sub.get('color','#FFFFFF'))
        else: shutil.copy(inp,out)
        return send_file(out,mimetype='video/mp4',as_attachment=True,download_name='processed.mp4')
    except Exception as e: return jsonify({'error':str(e)}),500
    finally: shutil.rmtree(tmp,ignore_errors=True)

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',8080)),debug=False)