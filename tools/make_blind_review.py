#!/usr/bin/env python3
"""Tạo phiếu chấm mù từ HAI kết quả local thật. Không tự chấm hoặc bịa câu thiếu."""
from __future__ import annotations
import argparse,csv,json,random
from pathlib import Path
from benchmark_translation import read_jsonl

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-a',type=Path,required=True);p.add_argument('--run-b',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--seed',type=int,default=20260923)
    a=p.parse_args()
    def indexed(path):
        rows=read_jsonl(path)
        d={(x['id'],x.get('repeat',0)):x for x in rows}
        if len(d)!=len(rows):raise ValueError('Trùng id/repeat ở '+str(path))
        return d
    left,right=indexed(a.run_a),indexed(a.run_b)
    if not left or left.keys()!=right.keys():raise ValueError('Hai lượt phải có cùng id/repeat, không tự bỏ câu thiếu.')
    if a.out.exists() and any(a.out.iterdir()):raise ValueError('Thư mục output đã có dữ liệu.')
    a.out.mkdir(parents=True,exist_ok=True)
    fields=['id','repeat','source_text','reference_vi_unreviewed','output_A','output_B',
            'reviewer','A_adequacy','A_naturalness','A_terminology','A_critical',
            'B_adequacy','B_naturalness','B_terminology','B_critical','preferred_A_B_tie','notes']
    rng=random.Random(a.seed);keys=[]
    with (a.out/'review.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        order=list(left);rng.shuffle(order)
        for k in order:
            x,y=left[k],right[k]
            if x['source_text']!=y['source_text'] or x.get('reference_vi')!=y.get('reference_vi'):
                raise ValueError('Nguồn/reference khác nhau tại '+str(k))
            swapped=rng.choice([False,True]);one,two=(y,x) if swapped else (x,y)
            w.writerow({'id':k[0],'repeat':k[1],'source_text':x['source_text'],
                        'reference_vi_unreviewed':x.get('reference_vi',''),
                        'output_A':(('' if one.get('valid_structure') else '[KHÔNG QUA KIỂM CẤU TRÚC] ') + (one.get('target_text') or '[KHÔNG CÓ ĐẦU RA]')),
                        'output_B':(('' if two.get('valid_structure') else '[KHÔNG QUA KIỂM CẤU TRÚC] ') + (two.get('target_text') or '[KHÔNG CÓ ĐẦU RA]'))})
            keys.append({'id':k[0],'repeat':k[1],'A':one['model_alias'],'B':two['model_alias'],
                         'A_flags':one.get('flags',[]),'B_flags':two.get('flags',[])})
    (a.out/'review_key.json').write_text(json.dumps(keys,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Đã tạo {len(keys)} cặp; giữ review_key.json riêng khỏi người chấm.')
    return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,KeyError,OSError) as exc:raise SystemExit('Lỗi: '+str(exc))
