"""Generates src/profiles.js from two sources:
  - people/*.json   the team: one file per person who agreed to be simulated (see people/README.md).
                    These are the only ACTIVE characters (they walk, talk and form ideas).
  - background      idle characters that stay in room 341 and never talk. Either
                    tools/students.csv (default; columns code,team,interests,skills,project,...; lists separated by ';')
                    or course-members.json (the Course Agent's COURSE_ROSTER_PATH, schema 1).
A background row whose code matches a team member's code is skipped (the people/ file wins).
Usage: python tools/roster2profiles.py [tools/students.csv | /path/course-members.json]
"""
import csv,json,pathlib,re,sys
ROOT=pathlib.Path(__file__).resolve().parent.parent
PEOPLE=ROOT/"people"
MAX_LIST=5  # the simulation's own profile form also caps interests/skills at 5
MAX_TERM=40  # interest terms are matched word for word and spoken inside idea titles, so they stay short

def load_person(path):
    """Reads one people/*.json file and returns (profile, errors)."""
    p=json.loads(path.read_text(encoding="utf-8"));err=[]
    def strings(key,lo,hi):
        v=p.get(key)
        if not isinstance(v,list) or not lo<=len(v)<=hi or not all(isinstance(x,str) and x.strip() for x in v):
            err.append(f"{key}: expected {lo}-{hi} non-empty strings");return []
        return [x.strip() for x in v]
    def interest_terms():
        # each interest is a short term, or {"term": ..., "description": ...}; only the term reaches the simulation
        v=p.get("interests")
        ok=lambda x:(isinstance(x,str) and x.strip() and len(x.strip())<=MAX_TERM) or (isinstance(x,dict) and isinstance(x.get("term"),str)
             and x["term"].strip() and len(x["term"].strip())<=MAX_TERM and isinstance(x.get("description",""),str))
        if not isinstance(v,list) or not 1<=len(v)<=MAX_LIST or not all(ok(x) for x in v):
            err.append(f'interests: expected 1-{MAX_LIST} terms of at most {MAX_TERM} characters, each a string or {{"term": "...", "description": "..."}}');return []
        return [(x if isinstance(x,str) else x["term"]).strip() for x in v]
    if p.get("schema_version")!=1:err.append("schema_version: expected 1")
    code=p.get("code")
    if not isinstance(code,str) or not code.strip():err.append("code: required (e.g. S02); keep it stable, browsers store it")
    project=p.get("project")
    if not isinstance(project,str) or not project.strip() or len(project)>200:err.append("project: required, one sentence, at most 200 characters")
    for key in ("name","team","site","bio"):
        if not isinstance(p.get(key,""),str):err.append(f"{key}: expected a string")
    weeks=p.get("weekly_builds",[])
    if not isinstance(weeks,list) or not all(isinstance(w,dict) and re.fullmatch(r"W\d{2}",str(w.get("week",""))) and isinstance(w.get("title"),str) and w["title"].strip() and isinstance(w.get("summary",""),str) for w in weeks):
        err.append('weekly_builds: expected a list of {"week": "W03", "title": "...", "summary": "..."}');weeks=[]
    interests,skills=interest_terms(),strings("skills",1,MAX_LIST)
    if err:return None,err
    return {"code":code.strip(),"team":p.get("team","").strip() or "—","interests":interests,"skills":skills,"project":project.strip(),
            "alt":[w["title"].strip() for w in sorted(weeks,key=lambda w:w["week"])],"bio":p.get("bio","").strip()[:400],
            "site":p.get("site","").strip(),"name":p.get("name","").strip(),"active":True},[]

def load_background(src):
    out=[]
    if src.suffix.lower()==".json":
        data=json.loads(src.read_text(encoding="utf-8"))
        for i,m in enumerate([m for m in data["members"] if m.get("course_status","active")=="active"]):
            kw=[k.strip() for k in m.get("keywords",[]) if k.strip()];ideas=[p.strip() for p in m.get("project_ideas",[]) if p.strip()]
            out.append({"code":f"S{i+1:02d}","team":m.get("department","—"),"interests":kw[:3] or ["agents"],
                        "skills":[m.get("department","—")]+kw[3:5],"project":ideas[0] if ideas else "a cognitive agents project","alt":ideas[1:]})
    else:
        L=lambda s:[x.strip() for x in (s or "").split(";") if x.strip()]
        for i,r in enumerate(csv.DictReader(open(src,encoding="utf-8"))):
            weeks={k:v.strip() for k,v in r.items() if k and k.upper().startswith("W") and k[1:].isdigit() and v and v.strip()}
            wk=[weeks[k] for k in sorted(weeks)]
            project=(r.get("project") or r.get("final_project") or (wk[-1] if wk else "") or "a cognitive agents project").strip()
            out.append({"code":(r.get("code") or f"S{i+1:02d}").strip(),"team":(r.get("team") or "—").strip(),
                        "interests":L(r.get("interests")) or [w[:40] for w in wk[-3:]] or ["agents"],
                        "skills":L(r.get("skills")) or [w[:40] for w in wk[:2]] or ["—"],
                        "project":project,"alt":wk,"bio":(r.get("bio") or "").strip()[:400],"site":(r.get("site") or "").strip(),"name":(r.get("name") or "").strip()})
    for b in out:b["active"]=False  # only people/ files are active agents
    return out

team,errors=[],[]
for f in sorted(PEOPLE.glob("*.json")):
    prof,err=load_person(f)
    errors+=[f"people/{f.name}: {e}" for e in err]
    if prof:team.append(prof)
codes=[p["code"] for p in team]
errors+=[f"code {c} is used by more than one people/ file" for c in sorted({c for c in codes if codes.count(c)>1})]
if errors:sys.exit("Not generated:\n  "+"\n  ".join(errors))
src=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/"tools"/"students.csv"
background=[]
for b in load_background(src):
    if b["code"] in codes:print(f"skipped background {b['code']}: people/ has a file with that code");continue
    background.append(b)
out=sorted(team,key=lambda p:p["code"])+background
dst=ROOT/"src"/"profiles.js"
dst.write_text("// PROFILES generated by tools/roster2profiles.py from people/*.json (active team) and "+src.name+" (idle background). Do not edit by hand.\nconst PROFILES="+json.dumps(out,ensure_ascii=False)+";\n",encoding="utf-8")
print(f"{len(team)} team + {len(background)} background profiles -> {dst}")
