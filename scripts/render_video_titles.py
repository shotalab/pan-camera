# SPDX-License-Identifier: AGPL-3.0-only
"""Render PAN-CAMERA SVG title animations as 4K/30p H.264 clips.

Uses system librsvg/Cairo through ctypes and the external ffmpeg command.
Run from the checkout with: python scripts/render_video_titles.py
"""

import argparse
import ctypes as C
import html
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/video-titles'
WIDTH, HEIGHT, FPS = 3840, 2160, 30
ASSETS = [
    dict(stem='00_title', duration=4.0, kicker='PHYSICAL AI · FINAL PROJECT',
         title='PAN-CAMERA', subtitle='選んだ被写体を、画面の中央へ。',
         detail='YOLO × Raspberry Pi × M5Stack'),
    dict(stem='01_remote', duration=1.5, kicker='CONTROL',
         title='選ぶ。追う。記録する。', subtitle='M5Stackから起動・対象選択・録画',
         detail='PAN-CAMERA / 操作と追尾'),
    dict(stem='02_recording', duration=1.5, kicker='RECORDING',
         title='カメラが捉えた映像', subtitle='Piで録画した720p映像',
         detail='PAN-CAMERA / 録画結果'),
    dict(stem='03_servo', duration=1.5, kicker='MOTION',
         title='滑らかに、向きを変える。', subtitle='サーボによる左右の自動旋回',
         detail='PAN-CAMERA / 旋回機構'),
    dict(stem='04_switch', duration=1.5, kicker='TARGET SELECTION',
         title='追う相手を、切り替える。', subtitle='2つのコップから選択した対象を中央へ',
         detail='PAN-CAMERA / 対象の切り替え'),
    dict(stem='05_ending', duration=4.0, kicker='THANK YOU FOR WATCHING',
         title='PAN-CAMERA', subtitle='見て、選んで、追いかける。',
         detail='YOLO × Raspberry Pi × M5Stack'),
]


def svg(spec, seconds):
    progress = min(1, max(0, seconds / .5))
    reveal = 1 - (1 - min(1, max(0, seconds / .4))) ** 3
    opacity = min(reveal, max(0, (spec['duration'] - seconds) / .2))
    intro = spec['stem'] in ('00_title', '05_ending')
    title_size = 224 if intro else 148
    title_y = 890 if intro else 990
    sub_y = 1060 if intro else 1150
    kicker_y = 615 if intro else 720
    graphic = '''<g transform="translate(2770 660)" stroke="#167d78" fill="none" stroke-width="10">
    <path d="M0 170V0H170 M470 0H640V170 M640 470V640H470 M170 640H0V470"/>
    <path d="M160 220H440L410 470Q300 530 190 470Z" fill="#e3eeE7" stroke="none"/>
    <ellipse cx="300" cy="220" rx="140" ry="35" fill="#c1d9ce" stroke="none"/>
    <path d="M440 260H490Q545 320 460 380" stroke-width="22"/>
    <path d="M300 -70l-16 -26h32Z M300 710l-16 26h32Z" fill="#167d78" stroke="none"/>
    </g>''' if intro else '''<g transform="translate(3210 820)" stroke="#167d78" fill="none" stroke-width="8" opacity=".5">
    <path d="M0 90V0H90 M230 0H320V90 M320 230V320H230 M90 320H0V230"/>
    <circle cx="160" cy="160" r="10" fill="#167d78" stroke="none"/></g>'''
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">
<!-- SPDX-License-Identifier: AGPL-3.0-only -->
<rect width="3840" height="2160" fill="#f5f4ee"/>
<path d="M230 250H3610 M230 1860H3610" stroke="#d0ded5" stroke-width="3"/>
<g data-reveal="1" opacity="{opacity:.5f}" transform="translate({(1-reveal)*60:.3f} 0)">
<g font-family="Noto Sans CJK JP, Noto Sans JP, sans-serif" fill="#19343e">
<text x="235" y="{kicker_y}" font-size="42" font-weight="600" letter-spacing="9" fill="#167d78">{html.escape(spec['kicker'])}</text>
<text x="220" y="{title_y}" font-size="{title_size}" font-weight="700" letter-spacing="-5">{html.escape(spec['title'])}</text>
<text x="235" y="{sub_y}" font-size="66" font-weight="500">{html.escape(spec['subtitle'])}</text>
<text x="235" y="1765" font-size="40" fill="#5e7177" letter-spacing="2">{html.escape(spec['detail'])}</text>
</g>{graphic}</g>
<rect data-progress="1" x="230" y="1857" width="{progress*1400:.2f}" height="6" fill="#167d78"/>
</svg>'''


def write_sources():
    OUT.mkdir(parents=True, exist_ok=True)
    cards = []
    for spec in ASSETS:
        vector = svg(spec, spec['duration'] / 2)
        (OUT / (spec['stem'] + '.svg')).write_text(vector)
        cards.append(f'<section data-duration="{spec["duration"]}"><h2>{spec["stem"]} · {spec["duration"]}秒</h2>{vector}<button onclick="play(this.parentNode)">再生</button></section>')
    preview = '''<!doctype html><html lang="ja"><!-- SPDX-License-Identifier: AGPL-3.0-only -->
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PAN-CAMERA 動画タイトル</title><style>
body{max-width:1120px;margin:40px auto;padding:0 24px;background:#e6eae5;color:#19343e;font-family:'Noto Sans CJK JP',sans-serif}h1{font-size:28px}p{line-height:1.8}h2{font-size:16px}section{margin:32px 0}svg{width:100%;height:auto;border-radius:10px}button{padding:10px 24px;border:0;border-radius:5px;background:#167d78;color:white;cursor:pointer}
</style><h1>PAN-CAMERA · 動画タイトル</h1><p>3840×2160 / 30 FPS。冒頭・エンディング各4秒、章タイトル各1.5秒。動画は outputs/video-titles/ の同名MP4をFinal Cut Proへ読み込む。すべて入れると実演93秒＋タイトル14秒＝約1分47秒。</p>
''' + '\n'.join(cards) + '''<script>
function play(section){
const duration=Number(section.dataset.duration),start=performance.now(),g=section.querySelector('[data-reveal]'),bar=section.querySelector('[data-progress]');
if(section._raf)cancelAnimationFrame(section._raf);
function tick(now){const t=(now-start)/1000,p=Math.min(1,Math.max(0,t/.5)),r=1-Math.pow(1-Math.min(1,Math.max(0,t/.4)),3),opacity=Math.min(r,Math.max(0,(duration-t)/.2));g.setAttribute('opacity',opacity);g.setAttribute('transform',`translate(${(1-r)*60} 0)`);bar.setAttribute('width',p*1400);if(t<duration)section._raf=requestAnimationFrame(tick);}
section._raf=requestAnimationFrame(tick);}
</script></html>'''
    (ROOT / 'docs/video-titles.html').write_text(preview)


class Renderer:
    def __init__(self):
        self.rsvg=C.CDLL('librsvg-2.so.2')
        self.cairo=C.CDLL('libcairo.so.2')
        self.gobject=C.CDLL('libgobject-2.0.so.0')
        self.rsvg.rsvg_handle_new_from_data.argtypes=[C.c_char_p,C.c_size_t,C.c_void_p]
        self.rsvg.rsvg_handle_new_from_data.restype=C.c_void_p
        self.rsvg.rsvg_handle_render_cairo.argtypes=[C.c_void_p,C.c_void_p]
        self.rsvg.rsvg_handle_render_cairo.restype=C.c_int
        self.gobject.g_object_unref.argtypes=[C.c_void_p]
        self.cairo.cairo_image_surface_create.argtypes=[C.c_int,C.c_int,C.c_int]
        self.cairo.cairo_image_surface_create.restype=C.c_void_p
        self.cairo.cairo_create.argtypes=[C.c_void_p]
        self.cairo.cairo_create.restype=C.c_void_p
        self.cairo.cairo_surface_flush.argtypes=[C.c_void_p]
        self.cairo.cairo_image_surface_get_data.argtypes=[C.c_void_p]
        self.cairo.cairo_image_surface_get_data.restype=C.c_void_p
        self.cairo.cairo_surface_write_to_png.argtypes=[C.c_void_p,C.c_char_p]
        self.cairo.cairo_destroy.argtypes=[C.c_void_p]
        self.cairo.cairo_surface_destroy.argtypes=[C.c_void_p]
        self.surface=self.cairo.cairo_image_surface_create(0,WIDTH,HEIGHT)
        self.context=self.cairo.cairo_create(self.surface)

    def frame(self, data):
        encoded=data.encode()
        handle=self.rsvg.rsvg_handle_new_from_data(encoded,len(encoded),None)
        if not handle:
            raise RuntimeError('SVG could not be loaded')
        try:
            if not self.rsvg.rsvg_handle_render_cairo(handle,self.context):
                raise RuntimeError('SVG render failed')
            self.cairo.cairo_surface_flush(self.surface)
            return C.string_at(self.cairo.cairo_image_surface_get_data(self.surface), WIDTH*HEIGHT*4)
        finally:
            self.gobject.g_object_unref(handle)

    def close(self):
        self.cairo.cairo_destroy(self.context)
        self.cairo.cairo_surface_destroy(self.surface)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=[spec['stem'] for spec in ASSETS])
    args=parser.parse_args()
    selected=[spec for spec in ASSETS if args.only is None or spec['stem']==args.only]
    write_sources()
    renderer=Renderer()
    try:
        for spec in selected:
            started=time.monotonic()
            path=OUT/(spec['stem']+'.mp4')
            args=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo',
                  '-pixel_format','bgra','-video_size',f'{WIDTH}x{HEIGHT}','-framerate',str(FPS),
                  '-i','pipe:0','-an','-c:v','libx264','-preset','ultrafast','-crf','18',
                  '-threads','2','-pix_fmt','yuv420p','-movflags','+faststart',str(path)]
            process=subprocess.Popen(args,stdin=subprocess.PIPE)
            try:
                for index in range(round(spec['duration']*FPS)):
                    process.stdin.write(renderer.frame(svg(spec,index/FPS)))
                process.stdin.close()
                if process.wait()!=0:
                    raise RuntimeError(f'FFmpeg failed: {spec["stem"]}')
            except BaseException:
                process.kill();process.wait();raise
            renderer.frame(svg(spec,spec['duration']/2))
            renderer.cairo.cairo_surface_write_to_png(renderer.surface,str(OUT/(spec['stem']+'.png')).encode())
            print(f'{path.name}: {spec["duration"]}s, {path.stat().st_size/1024/1024:.1f} MiB, rendered in {time.monotonic()-started:.1f}s',flush=True)
    finally:
        renderer.close()
    print(json.dumps(dict(resolution=[WIDTH,HEIGHT],fps=FPS,clips=len(selected)),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
