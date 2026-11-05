"""Chỉ kiểm helper/protocol bằng fixture và HTTP mock; không kiểm AI thật."""
import copy,json,os,struct,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from unittest.mock import patch
import audio_framing as audio
import benchmark_translation as bench

class ToolTests(unittest.TestCase):
    def setUp(self):
        self.row={'id':'t1','source_text':'Do not run git status yet.', 'domain':'coding',
                  'protected_terms':['git status'],'reference_vi':'SECRET_GOLD_REFERENCE',
                  'review_notes':'HIDDEN_REVIEW_NOTES','context_before':['A demonstration.']}
        self.profile={'temperature':.2,'chat_template_kwargs':{'enable_thinking':False}}
        self.req,self.mapping=bench.make_request(self.row,'local-model',self.profile,'Translate only.')
        self.h={'protocol_version':1,'kind':'tts_pcm','session_id':'s1','timeline_epoch':0,
                'segment_id':'t1','revision':1,'seq':0,'sample_rate':48000,'channels':1,
                'codec':'pcm_s16le','sample_count':2,'is_last':True}
    def response(self,text='Đừng chạy VDTERM_000 vội.'):
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(
            {'translations':[{'segment_id':'t1','target_text':text}]})}}]}
    def test_reference_not_in_prompt(self):
        serialized=json.dumps(self.req)
        self.assertNotIn('SECRET_GOLD_REFERENCE',serialized);self.assertNotIn('HIDDEN_REVIEW_NOTES',serialized)
    def test_reasoning_disabled(self):
        self.assertFalse(self.req['chat_template_kwargs']['enable_thinking'])
        self.assertEqual(self.req['response_format']['type'],'json_object')
    def test_placeholder_restore(self):
        text,flags=bench.parse_response(self.response(),self.req,self.mapping)
        self.assertIn('git status',text);self.assertEqual(flags,[])
    def test_placeholder_missing(self):
        _,flags=bench.parse_response(self.response('Đừng chạy lệnh đó.'),self.req,self.mapping)
        self.assertTrue(flags)
    def test_reasoning_flag(self):
        r=self.response();r['choices'][0]['message']['reasoning_content']='internal'
        self.assertIn('REASONING_OR_TOOL_OUTPUT',bench.parse_response(r,self.req,self.mapping)[1])
    def test_truncated_flag(self):
        r=self.response();r['choices'][0]['finish_reason']='length'
        self.assertIn('TRUNCATED',bench.parse_response(r,self.req,self.mapping)[1])
    def test_wrong_id(self):
        r=self.response();r['choices'][0]['message']['content']=json.dumps({'translations':[{'segment_id':'old','target_text':'VDTERM_000'}]})
        self.assertIn('WRONG_ID',bench.parse_response(r,self.req,self.mapping)[1])
    def test_extra_key_rejected(self):
        r=self.response();r['choices'][0]['message']['content']='{"translations":[],"reason":"x"}'
        with self.assertRaises(ValueError):bench.parse_response(r,self.req,self.mapping)
    def test_external_endpoint_rejected(self):
        for url in ['https://api.example.com/v1','http://192.168.1.1/v1','http://localhost/v1',
                    'http://127.0.0.1/v1?key=x','http://user:pass@127.0.0.1/v1']:
            with self.subTest(url=url),self.assertRaises(ValueError):bench.local_endpoint(url)
    def test_loopback_v4_v6(self):
        self.assertEqual(bench.local_endpoint('http://127.0.0.1:8766/v1')[1],8766)
        self.assertEqual(bench.local_endpoint('http://[::1]:8766/v1')[0],'::1')
    def test_percentile(self):
        self.assertEqual(bench.percentile([1,2,3],.5),2);self.assertIsNone(bench.percentile([],.95))
    def test_audio_roundtrip(self):
        pcm=b'\x00\x00\xff\x7f';self.assertEqual(audio.unpack_frame(audio.pack_frame(self.h,pcm)),(self.h,pcm))
    def test_audio_length_rejected(self):
        with self.assertRaises(ValueError):audio.pack_frame(self.h,b'\0\0')
    def test_audio_wrong_rate(self):
        h={**self.h,'sample_rate':16000}
        with self.assertRaises(ValueError):audio.pack_frame(h,b'\0'*4)
    def test_audio_asr_clock_required(self):
        h={**self.h,'kind':'asr_pcm','sample_rate':16000,'segment_id':None}
        with self.assertRaises(ValueError):audio.pack_frame(h,b'\0'*4)
        h.update(capture_monotonic_ms=1.25,source_media_ms=100)
        self.assertEqual(audio.unpack_frame(audio.pack_frame(h,b'\0'*4))[0],h)
    def test_audio_bool_is_not_integer(self):
        h={**self.h,'seq':True}
        with self.assertRaises(ValueError):audio.pack_frame(h,b'\0'*4)
    def test_audio_bad_prefix(self):
        for data in [b'',struct.pack('>I',99999)+b'{}',struct.pack('>I',4096)+b'x']:
            with self.subTest(data=data[:4]),self.assertRaises(ValueError):audio.unpack_frame(data)
    def test_http_mock_end_to_end(self):
        captures=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(server):
                payload=json.loads(server.rfile.read(int(server.headers['Content-Length'])))
                captures.append((payload,server.headers.get('Authorization')))
                sid=json.loads(payload['messages'][1]['content'])['segments'][0]['segment_id']
                result={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(
                    {'translations':[{'segment_id':sid,'target_text':'Bản dịch giả để kiểm đường gọi.'}]})}}],
                    'usage':{'completion_tokens':12}}
                raw=json.dumps(result).encode();server.send_response(200)
                server.send_header('Content-Length',str(len(raw)));server.end_headers();server.wfile.write(raw)
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'VIETDUB_LLM_KEY':'unit-test-not-real'}):
                out=Path(td)/'result'
                rc=bench.main(['--base-url',f'http://127.0.0.1:{server.server_port}/v1',
                    '--model','mock-not-AI','--profile','qwen_non_thinking','--out',str(out),
                    '--limit','1','--warmup','0'])
                self.assertEqual(rc,0);self.assertEqual(captures[0][1],'Bearer unit-test-not-real')
                self.assertNotIn('reference_vi',json.dumps(captures[0][0]))
                meta=json.loads((out/'run.json').read_text());self.assertIsNone(meta['model_sha256'])
        finally:server.shutdown();server.server_close();thread.join(timeout=3)

if __name__=='__main__':unittest.main()
