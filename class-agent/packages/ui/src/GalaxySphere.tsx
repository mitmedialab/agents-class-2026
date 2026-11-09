import {useEffect,useRef} from "react";
import {AuthorMark,type AtlasAuthor} from "./PeerAtlas.js";

function project(a:number,b:number,turn:number){
  const z=Math.cos(a+turn)*Math.sin(b), scale=1/(1.8-z*.25);
  return {x:50+72*Math.sin(a+turn)*Math.sin(b)*scale,y:50+72*Math.cos(b)*scale,z};
}
export function GalaxySphere({authors}:{authors:AtlasAuthor[]}){
  const canvas=useRef<HTMLCanvasElement>(null), links=useRef<(HTMLAnchorElement|null)[]>([]);
  const paused=useRef(false);
  useEffect(()=>{
    const el=canvas.current,ctx=el?.getContext("2d");
    if(!el||!ctx)return;
    const media=matchMedia("(prefers-reduced-motion: reduce)");
    let frame=0,turn=.18,last=0;
    function draw(now:number){
      if(!el||!ctx)return;
      if(!paused.current&&!media.matches)turn+=Math.min(now-last,80)*.000055;
      last=now;
      const size=Math.max(1,Math.round(el.clientWidth*Math.min(devicePixelRatio,2)));
      if(el.width!==size||el.height!==size){el.width=size;el.height=size}
      ctx.setTransform(size/100,0,0,size/100,0,0);ctx.clearRect(0,0,100,100);
      for(let arm=0;arm<96;arm++){
        const angle=arm*2.39996,lat=Math.acos(1-2*(arm+.5)/96);
        for(let j=1;j<104;j++){
          const r=j/104,p=project(angle+.75*Math.sin(r*4+arm)*r,lat+.13*Math.sin(r*9+arm),turn);
          const x=50+(p.x-50)*r,y=50+(p.y-50)*r;
          ctx.fillStyle='rgba(241,244,248,'+(.13+.46*(1+p.z)/2)+')';
          const s=j%19===0?.28:.095+.065*(1+p.z);ctx.beginPath();ctx.arc(x,y,s,0,Math.PI*2);ctx.fill();
        }
      }
      // Stagger particle lifetimes so the outward flow has no visible loop boundary.
      for(let i=0;i<180;i++){
        const phase=(Math.sin(i*53.817)*43758.5453%1+1+(media.matches?0:now*.000085))%1;
        const angle=i*2.39996+.025*Math.sin(phase*4+i);
        const radius=38+3*Math.sin(i*17.13)+phase*(4+3*Math.sin(i*5.37));
        const alpha=Math.sin(phase*Math.PI)*(.18+.36*(i%7)/6);
        ctx.fillStyle=`rgba(240,242,247,${alpha})`;
        const size=.10+(i%5)*.035;
        ctx.fillRect(50+radius*Math.cos(angle),50+radius*Math.sin(angle),size,size);
      }
      const positions=authors.map((_,i)=>project(i*2.39996,Math.acos(1-2*(i+.5)/authors.length),turn));
      // Separate projected neighbors enough to keep their names readable.
      const gap=Math.min(14,4600/el.clientWidth);
      for(let pass=0;pass<4;pass++){
        positions.forEach((p,i)=>{
          for(const q of positions.slice(i+1)){
            const dx=q.x-p.x,dy=q.y-p.y,d=Math.hypot(dx,dy);
            if(d>=gap || d===0) continue;
            const shift=(gap-d)/(2*d);
            p.x-=dx*shift;p.y-=dy*shift;q.x+=dx*shift;q.y+=dy*shift;
          }
        });
      }
      links.current.forEach((link,i)=>{const p=positions[i];if(!link||!p)return;
        link.style.left=p.x+"%";link.style.top=p.y+"%";link.style.zIndex=String(Math.round(20+p.z*10));link.style.scale=String(.82+(p.z+1)*.15);
      });
      frame=requestAnimationFrame(draw)
    }
    frame=requestAnimationFrame(draw);return ()=>cancelAnimationFrame(frame)
  },[authors]);
  function focus(id:string){paused.current=Boolean(id)}
  return <div className="sphere"><canvas ref={canvas} aria-hidden="true"/>{authors.map((a,i)=>
    <a key={a.id} ref={el=>{links.current[i]=el}} href={a.site} target="_blank" rel="noreferrer" aria-label={a.name+"’s website"} onMouseEnter={()=>focus(a.id)} onMouseLeave={()=>focus("")} onFocus={()=>focus(a.id)} onBlur={()=>focus("")}><AuthorMark index={a.mark}/><span>{a.name}</span></a>)}</div>
}
