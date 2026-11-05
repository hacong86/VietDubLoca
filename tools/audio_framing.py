"""Codec tham chiếu audio protocol v1; không phải audio engine/Native Messaging.
4-byte big-endian header length + JSON UTF-8 + PCM16LE mono.
Epoch/revision ownership và authentication phải kiểm ở consumer bên ngoài.
"""
from __future__ import annotations
import json,math,struct
from typing import Any
MAX_HEADER=4096
MAX_FRAME=256*1024
REQUIRED={'protocol_version','kind','session_id','timeline_epoch','segment_id','revision',
          'seq','sample_rate','channels','codec','sample_count','is_last'}
ALLOWED=REQUIRED|{'capture_monotonic_ms','source_media_ms'}

def validate_header(h:dict[str,Any],pcm_length:int)->None:
    if not isinstance(h,dict) or not REQUIRED<=h.keys() or h.keys()-ALLOWED:
        raise ValueError('Sai keys audio header.')
    if type(h['protocol_version']) is not int or h['protocol_version']!=1:
        raise ValueError('Sai protocol version.')
    if type(h['channels']) is not int or h['channels']!=1 or h['codec']!='pcm_s16le':
        raise ValueError('Chỉ hỗ trợ PCM16LE mono.')
    for k in ['timeline_epoch','revision','seq','sample_count']:
        if type(h[k]) is not int or h[k]<0:raise ValueError('Số nguyên không âm bắt buộc: '+k)
    if type(h['is_last']) is not bool:raise ValueError('is_last phải boolean.')
    if not isinstance(h['session_id'],str) or not 1<=len(h['session_id'])<=128:
        raise ValueError('session_id không hợp lệ.')
    if h['segment_id'] is not None and (not isinstance(h['segment_id'],str) or not 1<=len(h['segment_id'])<=128):
        raise ValueError('segment_id không hợp lệ.')
    if h['kind']=='asr_pcm':
        if h['sample_rate']!=16000 or h['segment_id'] is not None:raise ValueError('ASR cần16k, segment=null.')
        for k in ['capture_monotonic_ms','source_media_ms']:
            value=h.get(k)
            if type(value) not in (int,float) or not math.isfinite(value) or value<0:
                raise ValueError('ASR thiếu/sai source clock: '+k)
        if type(h['source_media_ms']) is not int:raise ValueError('source_media_ms phải int.')
    elif h['kind']=='tts_pcm':
        if h['sample_rate']!=48000 or not h['segment_id']:raise ValueError('Turbo cần48k và segment_id.')
    else:raise ValueError('kind không hỗ trợ.')
    if pcm_length!=h['sample_count']*2:raise ValueError('Độ dài PCM không khớp sample_count.')

def pack_frame(header:dict[str,Any],pcm:bytes)->bytes:
    validate_header(header,len(pcm))
    raw=json.dumps(header,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    if len(raw)>MAX_HEADER or 4+len(raw)+len(pcm)>MAX_FRAME:raise ValueError('Frame vượt giới hạn.')
    return struct.pack('>I',len(raw))+raw+pcm

def unpack_frame(frame:bytes)->tuple[dict[str,Any],bytes]:
    if len(frame)<4 or len(frame)>MAX_FRAME:raise ValueError('Độ dài frame không hợp lệ.')
    n=struct.unpack('>I',frame[:4])[0]
    if not 1<=n<=MAX_HEADER or 4+n>len(frame):raise ValueError('Độ dài header không hợp lệ.')
    def no_duplicates(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('JSON có key trùng.')
            result[k]=v
        return result
    h=json.loads(frame[4:4+n].decode('utf-8'),object_pairs_hook=no_duplicates)
    pcm=frame[4+n:];validate_header(h,len(pcm))
    return h,pcm
