import base64, os, subprocess
from playwright.sync_api import sync_playwright
F = "/home/claude/manzi-studio/render/fonts/"
def font(n): return "data:font/ttf;base64," + base64.b64encode(open(F + n, 'rb').read()).decode()
DUR, FPS = 5.0, 30
html = f"""<html><head><style>
@font-face{{font-family:Lora;src:url('{font('Lora-Variable.ttf')}')}}
html,body{{margin:0;width:1920px;height:1080px;background:#000;overflow:hidden}}
#glow{{position:absolute;left:50%;top:44%;width:1400px;height:1400px;margin:-700px 0 0 -700px;border-radius:50%;
  background:radial-gradient(circle,rgba(255,170,60,.38) 0%,rgba(140,70,10,.16) 28%,rgba(0,0,0,0) 60%);
  opacity:0;animation:glow 5s linear forwards}}
@keyframes glow{{0%{{opacity:0;transform:scale(.6)}} 14%{{opacity:.5}} 17%{{opacity:.25}} 21%{{opacity:.8}} 40%{{opacity:1;transform:scale(1)}}
  85%{{opacity:1}} 100%{{opacity:0}}}}
svg{{position:absolute;left:50%;top:300px;margin-left:-90px}}
#ring{{fill:none;stroke:#d9a441;stroke-width:5;stroke-dasharray:540;stroke-dashoffset:540;animation:draw 1.4s .5s ease-in-out forwards}}
@keyframes draw{{to{{stroke-dashoffset:0}}}}
#m{{font-family:Lora;font-size:104px;fill:#e2b65a;opacity:0;animation:fade .8s 1.3s forwards}}
@keyframes fade{{to{{opacity:1}}}}
#name{{position:absolute;top:530px;width:100%;text-align:center;font-family:Lora;font-size:76px;letter-spacing:26px;
  color:#e9d3a0;opacity:0;animation:rise 1.2s 1.7s ease-out forwards;
  background:linear-gradient(100deg,#b8893a 0%,#f7e3b0 45%,#fff6dc 50%,#f7e3b0 55%,#b8893a 100%);background-size:300% 100%;
  -webkit-background-clip:text;color:transparent}}
#name.s{{animation:rise 1.2s 1.7s ease-out forwards, sweep 1.6s 2.6s ease-in-out forwards}}
@keyframes rise{{from{{opacity:0;transform:translateY(18px);letter-spacing:40px}} to{{opacity:1;transform:none;letter-spacing:26px}}}}
@keyframes sweep{{from{{background-position:100% 0}} to{{background-position:0 0}}}}
#sub{{position:absolute;top:650px;width:100%;text-align:center;font-family:Lora;font-size:40px;letter-spacing:22px;color:#bfa77a;
  opacity:0;animation:fade 1s 2.9s forwards}}
#all{{animation:out .6s 4.4s forwards}} @keyframes out{{to{{opacity:0}}}}
.dust{{position:absolute;width:4px;height:4px;border-radius:50%;background:#ffd99a;opacity:0}}
</style></head><body><div id="all"><div id="glow"></div>
<svg width="180" height="180"><circle id="ring" cx="90" cy="90" r="84" transform="rotate(-90 90 90)"/>
<text id="m" x="90" y="124" text-anchor="middle">M</text></svg>
<div id="name" class="s">MANZI STUDIO</div><div id="sub">PRESENTS</div>
""" + "".join(f'<div class="dust" style="left:{600+ (i*137)%720}px;top:{260+(i*89)%520}px;animation:d{i%3} {3+i%3}s {0.4+(i%7)*0.3}s linear forwards"></div>' for i in range(28)) + """
</div><style>
@keyframes d0{0%{opacity:0}30%{opacity:.7}100%{opacity:0;transform:translate(40px,-120px)}}
@keyframes d1{0%{opacity:0}30%{opacity:.5}100%{opacity:0;transform:translate(-30px,-90px)}}
@keyframes d2{0%{opacity:0}30%{opacity:.6}100%{opacity:0;transform:translate(10px,-150px)}}
</style></body></html>"""
os.makedirs("fr", exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={'width': 1920, 'height': 1080})
    pg.set_content(html); pg.wait_for_timeout(500)
    pg.evaluate("document.getAnimations().forEach(a=>a.pause());0")
    for i in range(int(DUR * FPS)):
        pg.evaluate(f"document.getAnimations().forEach(a=>a.currentTime={i*1000/FPS});0")
        pg.screenshot(path=f"fr/{i:04d}.png")
    b.close()
# sound: a warm low drone (tanpura-like) swelling in, a soft bell when the name appears
snd = ("sine=f=110:d=5,volume=0.35[a];sine=f=165:d=5,volume=0.22[b];sine=f=220.5:d=5,volume=0.12[c];"
       "[a][b][c]amix=inputs=3:normalize=0,afade=t=in:d=1.5,afade=t=out:st=4:d=1,aecho=0.8:0.7:120|240:0.3|0.2[dr];"
       "sine=f=880:d=2.5,volume=0.25,afade=t=out:st=0.05:d=2.4,adelay=1700|1700,aecho=0.8:0.6:180:0.35[bell];"
       "[dr][bell]amix=inputs=2:normalize=0,lowpass=f=4000,aformat=channel_layouts=stereo[s]")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", "fr/%04d.png",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex", snd, "-map", "0:v", "-map", "[s]",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-c:a", "aac", "-b:a", "192k", "-shortest",
                "manzi-studio-ident.mp4"], check=True)
