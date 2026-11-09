"""Render a course-slide-style, editable SVG and matching PNG agent diagram."""
from html import escape
from math import hypot
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/assets'
OUT.mkdir(exist_ok=True)
SCALE = 2
image = Image.new('RGB', (1600 * SCALE, 900 * SCALE), '#000000')
draw = ImageDraw.Draw(image)
svg = ['''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
<title>Weekly Dream agent architecture</title>
<desc>A student communicates with an LLM call guided by the Weekly Dream prompt. Its tool pack acts on course materials and student builds. Observations return to the model. State and memory supply the student profile, past dreams and feedback. The loop ends with an email draft.</desc>
<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse"><path d="M 0 0 L 8 4 L 0 8" fill="none" stroke="#d4d4d4" stroke-width="1.3"/></marker></defs>
<rect width="1600" height="900" fill="black"/>
''']
GRAY = '#d4d4d4'
WHITE = '#f5f5f5'
PURPLE = '#b0a0ed'
ORANGE = '#f48658'
GREEN = '#85d167'


def text(x, y, value, size=21, color=WHITE, bold=False, align='middle'):
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial' + (' Bold' if bold else '') + '.ttf', round(size*SCALE))
    draw.text((x*SCALE, y*SCALE), value, font=font, fill=color, anchor='mm' if align=='middle' else 'lm')
    svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" text-anchor="{align}" dominant-baseline="central">{escape(value)}</text>')


def box(x, y, w, h, stroke, fill, radius=0):
    draw.rounded_rectangle((x*SCALE,y*SCALE,(x+w)*SCALE,(y+h)*SCALE), radius=radius*SCALE, fill=fill, outline=stroke, width=2*SCALE)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')


def arrow(points, d, dashed=False, both=False):
    scaled=[(x*SCALE,y*SCALE) for x,y in points]
    if dashed:
        for i in range(0,len(scaled)-1,2):
            draw.line(scaled[i:i+2],fill=GRAY,width=2*SCALE)
    else:
        draw.line(scaled,fill=GRAY,width=2*SCALE)
    def head(tip, before):
        dx,dy=tip[0]-before[0],tip[1]-before[1]
        n=hypot(dx,dy)
        ux,uy=dx/n,dy/n
        a=(tip[0]-ux*12*SCALE-uy*5*SCALE,tip[1]-uy*12*SCALE+ux*5*SCALE)
        b=(tip[0]-ux*12*SCALE+uy*5*SCALE,tip[1]-uy*12*SCALE-ux*5*SCALE)
        draw.line([a,tip,b],fill=GRAY,width=2*SCALE)
    head(scaled[-1],scaled[-2])
    if both: head(scaled[0],scaled[1])
    dash=' stroke-dasharray="6 6"' if dashed else ''
    start=' marker-start="url(#arrow)"' if both else ''
    svg.append(f'<path d="{d}" fill="none" stroke="{GRAY}" stroke-width="2"{dash}{start} marker-end="url(#arrow)"/>')


def line(x1,y1,x2,y2,dashed=False,both=False):
    points=[(x1+(x2-x1)*i/30,y1+(y2-y1)*i/30) for i in range(31)]
    arrow(points,f'M {x1} {y1} L {x2} {y2}',dashed,both)


def curve(p0,p1,p2,p3):
    points=[]
    for i in range(81):
        t=i/80;u=1-t
        points.append((u**3*p0[0]+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t**3*p3[0],u**3*p0[1]+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t**3*p3[1]))
    arrow(points,f'M {p0[0]} {p0[1]} C {p1[0]} {p1[1]}, {p2[0]} {p2[1]}, {p3[0]} {p3[1]}')


text(80,70,'Weekly Dream',44,bold=True,align='start')
text(80,120,'LLM agent architecture',23,color='#b5b5b5',align='start')

box(70,425,200,80,ORANGE,'#25130d',40)
text(170,465,'Student',27,ORANGE,True)
box(475,410,300,110,GREEN,'#0c1909')
text(625,446,'LLM call',29,GREEN,True)
text(625,484,'Weekly Dream prompt',21)
box(475,170,300,110,PURPLE,'#141020')
text(625,200,'State / Memory',25,PURPLE,True)
text(625,233,'Student profile',20)
text(625,259,'Past dreams + feedback',20)
box(925,220,270,135,PURPLE,'#141020')
text(1060,249,'Tool pack',25,PURPLE,True)
text(1060,283,'Read context',20)
text(1060,309,'Update memory',20)
text(1060,335,'Save dream',20)
box(1250,405,280,130,ORANGE,'#25130d',44)
text(1390,438,'Environment',26,ORANGE,True)
text(1390,475,'Course materials',20)
text(1390,502,'Student builds + activity',19)
box(475,710,300,90,PURPLE,'#141020')
text(625,741,'Weekly dream',27,PURPLE,True)
text(625,775,'Email draft',20)

line(284,465,460,465,True,True)
text(373,434,'Input / feedback',17)
line(625,295,625,395,both=True)
text(647,346,'Context / updates',18,align='start')
curve((787,438),(850,385),(858,300),(910,288))
text(855,402,'Action',21)
curve((1209,288),(1330,288),(1390,340),(1390,390))
curve((1238,511),(1120,661),(918,657),(788,510))
text(1030,659,'Observations',21)
line(625,535,625,695,True)
text(650,618,'Finish',20,align='start')

text(80,863,'Adapted from course slides: Week 2, slide 7; Week 7, slide 5.',16,color='#999999',align='start')
svg.append('</svg>')
(OUT/'weekly-dream-architecture.svg').write_text('\n'.join(svg))
image.save(OUT/'weekly-dream-architecture.png')
print(OUT/'weekly-dream-architecture.png')
