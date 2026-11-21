"""Builds tools/students.csv from the students' public agentic websites (GitHub Pages).

Input: a text file with one site per line, either a full URL or just the repo slug
(e.g. agents2026-leticia -> https://mitmedialab.github.io/agents2026-leticia/).
Output: tools/students.csv with columns
  code, team, site, bio, final_project, W00, W01, W02, ... (one column per weekly build)
No names are written: the code is S01, S02, ... in the order of the input file.

Usage: python3 tools/sites2csv.py tools/sites.txt [--base https://mitmedialab.github.io/]
Then:  python3 tools/roster2profiles.py tools/students.csv
"""
import csv,html,pathlib,re,sys,urllib.request
from html.parser import HTMLParser

class Text(HTMLParser):
    """Keeps headings and paragraphs in order, with links of each block."""
    SKIP={"script","style","nav","noscript","svg","head"}
    def __init__(s):super().__init__();s.blocks=[];s.cur=None;s.skip=0;s.title=""
    def handle_starttag(s,tag,attrs):
        if tag in s.SKIP:s.skip+=1
        if s.skip:return
        if tag in("h1","h2","h3","h4","p","li","title","summary"):s.cur=[tag,[],dict(attrs).get("id","")]
        if tag=="a" and s.cur:
            href=dict(attrs).get("href","");s.cur[1].append(("link",href))
    def handle_endtag(s,tag):
        if tag in s.SKIP:s.skip=max(0,s.skip-1)
        if s.cur and tag==s.cur[0]:
            txt=" ".join(x for k,x in s.cur[1] if k=="t").strip();links=[x for k,x in s.cur[1] if k=="link"]
            if tag=="title":s.title=txt
            elif txt:s.blocks.append((tag,re.sub(r"\s+"," ",txt),links))
            s.cur=None
    def handle_data(s,d):
        if s.cur and not s.skip:s.cur[1].append(("t",d))

def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"placelab-sites2csv"})
    return urllib.request.urlopen(req,timeout=30).read().decode("utf-8","replace")

WEEK=re.compile(r"\b(W|Week\s*)(\d{1,2})\b",re.I)
def parse(url):
    p=Text();p.feed(fetch(url));B=p.blocks
    weeks={};bio="";final="";team=""
    # weekly builds: headings or list items that start with W05 / Week 5
    for tag,txt,links in B:
        m=WEEK.match(txt)
        if m and tag in("h1","h2","h3","h4","li","summary"):
            k="W%02d"%int(m.group(2));title=WEEK.sub("",txt,count=1).strip(" :·-–—")
            if k not in weeks or len(title)>len(weeks[k]):weeks[k]=title
            if "final" in txt.lower():final=final or title
    # bio: paragraph after a heading mentioning about/bio/who, else the first long paragraph
    for i,(tag,txt,_) in enumerate(B):
        if tag.startswith("h") and re.search(r"about|bio|who am i|me\b",txt,re.I):
            paras=[t for tg,t,_ in B[i+1:i+4] if tg=="p"];bio=" ".join(paras);break
    if not bio:
        paras=[t for tg,t,_ in B if tg=="p" and len(t)>120];bio=paras[0] if paras else ""
    if not final:
        for tag,txt,_ in B:
            if re.search(r"final project",txt,re.I) and tag.startswith("h"):final=txt;break
    m=re.search(r"\b(City Science|Fluid Interfaces|Tangible Media|Affective Computing|Personal Robots|Opera of the Future|Biomechatronics|Human Dynamics|Future Sketches|Sculpting Evolution|Viral Communications|Multisensory Intelligence|Social Algorithms|Community Biotech|[A-Z][a-z]+ [A-Z][a-z]+ group)\b"," ".join(t for _,t,_ in B))
    if m:team=m.group(1)
    return {"team":team,"bio":bio[:600],"final_project":final,"weeks":weeks,"title":p.title}

def main():
    if len(sys.argv)<2:print(__doc__);sys.exit(1)
    base="https://mitmedialab.github.io/"
    if "--base" in sys.argv:base=sys.argv[sys.argv.index("--base")+1]
    rows=[];allweeks=set()
    for i,line in enumerate([l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]):
        url=line if line.startswith("http") else base.rstrip("/")+"/"+line.strip("/")+"/"
        try:d=parse(url)
        except Exception as e:print("!!",url,e);d={"team":"","bio":"","final_project":"","weeks":{},"title":""}
        allweeks|=set(d["weeks"]);rows.append({"code":"S%02d"%(i+1),"site":url,**d});print(d["title"] or url,"->",len(d["weeks"]),"weeks")
    weeks=sorted(allweeks);out=pathlib.Path(__file__).resolve().parent/"students.csv"
    with open(out,"w",newline="",encoding="utf-8") as f:
        w=csv.writer(f);w.writerow(["code","team","site","bio","final_project"]+weeks+["interests","skills","project"])
        for r in rows:
            w.writerow([r["code"],r["team"],r["site"],r["bio"],r["final_project"]]+[r["weeks"].get(k,"") for k in weeks]+["","",r["final_project"] or r["weeks"].get(weeks[-1],"") if weeks else ""])
    print(len(rows),"students ->",out)
if __name__=="__main__":main()
