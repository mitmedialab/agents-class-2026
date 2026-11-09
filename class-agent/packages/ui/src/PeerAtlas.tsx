import { GalaxySphere } from "./GalaxySphere.js";
import { useState } from "react";
import "./peer-atlas.css";

export const domains = ["Learning","Memory","Attention","Reasoning","Creativity","Reflection","Decision-making","Communication","Social connection"] as const;
export type AtlasTab = "recommendations" | "domains" | "starred" | "galaxy";
export interface AtlasAuthor { id:string; name:string; mark:number; site:string }
export interface AtlasBuild { id:string; author:string; title:string; week:number; domain:string; url:string; image?:string|null; excerpt?:string }
export interface AtlasCatalog {
  ownAuthor?:string;
  authors:AtlasAuthor[]; builds:AtlasBuild[];
  pairs:{mine:string; peer:string; borrow:string}[];
}
export function AuthorMark({index}:{index:number}) {
  const family=index%5, n=5+Math.floor(index/5)*2;
  return <svg className="atlas-mark" viewBox="-26 -26 52 52" aria-hidden="true">
    {Array.from({length:n},(_,i)=><g key={i} transform={`rotate(${360*i/n})`}>
      {family===0 && <ellipse cy="-9" ry="14" rx="6" fill="none" stroke="currentColor" strokeWidth="2"/>}
      {family===1 && <path d="M0 -24 Q16 -23 3 -5 L-2 -7Z" fill="currentColor"/>}
      {family===2 && <g fill="currentColor"><circle cy="-19" r="3"/><circle cy="-12" r="2"/></g>}
      {family===3 && <path d="M0 -23 L6 -11 L0 -5" fill="none" stroke="currentColor" strokeWidth="3"/>}
      {family===4 && <g stroke="currentColor" fill="currentColor"><path d="M0 -21V0"/><circle cy="-20" r="3"/></g>}
    </g>)}
  </svg>
}
const plates = import.meta.glob("./domain-art/*.webp", {eager:true,import:"default"}) as Record<string,string>;

function Thumb({down=false}:{down?:boolean}){
  return <svg width="17" height="17" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"><g transform={down?"rotate(180 12 12)":undefined}><path d="M3 10h4v11H3zM7 11l5-7q2-3 3 0v5h5q2 0 1.5 2L19 19q-.5 2-3 2H7z"/></g></svg>
}
export function PeerAtlas({catalog,tab,saved,toggle,rate,busy}:{catalog:AtlasCatalog;tab:AtlasTab;saved:string[];toggle:(id:string)=>void;rate:(id:string,rating:"helpful"|"not_relevant")=>void;busy?:boolean}){
  const weeks=[...new Set(catalog.builds.map(b=>b.week))].sort((a,b)=>b-a);
  const [week,setWeek]=useState(weeks.find(w => catalog.pairs.some(pair => catalog.builds.some(b => b.id === pair.mine && b.week === w))) ?? weeks[0]);
  const [domain,setDomain]=useState("");
  const [message,setMessage]=useState<{id:string;text:string}|null>(null);
  const [copied,setCopied]=useState(false);
  const [failedImages, setFailedImages] = useState<Set<string>>(() => new Set());

  const getAuthor=(id:string)=>catalog.authors.find(a=>a.id===id)!;
  function card(build:AtlasBuild,side?:string){
    const author=getAuthor(build.author), starred=saved.includes(build.id);
    return <article className="atlas-build" key={build.id}>
      <div className="atlas-byline"><AuthorMark index={author.mark}/><div><small>{side ? (side === "Your build" ? "You · " : "") + author.name : build.domain}</small><strong>{side ? build.title : author.name}</strong></div>
      {(tab==="starred" || (build.author!==catalog.ownAuthor && side!=="Your build")) && <button className="atlas-star" disabled={busy} aria-label={(starred?"Unstar ":"Star ")+build.title} aria-pressed={starred} onClick={()=>toggle(build.id)}>{starred?"★":"☆"}</button>}</div>
      {build.image?.startsWith("https://") && !failedImages.has(build.image) ? <a className="atlas-source-image" href={build.url} target="_blank" rel="noreferrer"><img src={build.image} alt={build.title+" · project preview"} referrerPolicy="no-referrer" onError={event => {
        const failed = event.currentTarget.src;
        setFailedImages(previous => new Set(previous).add(failed));
      }}/></a> : <div className="atlas-text-cover">{build.excerpt ? <><small>Project description</small><p>{build.excerpt}</p></> : <div className="atlas-author-cover" role="img" aria-label={author.name + "’s portfolio mark"}><AuthorMark index={author.mark}/></div>}</div>}
      {!side && <h3>{build.title}</h3>}<a target="_blank" rel="noreferrer" href={build.url}>View build ↗</a>
    </article>
  }
  const selected=catalog.builds.filter(b=>b.week===week);
  return <div className="atlas">
    <div className="atlas-heading"><h2>{{recommendations:"Weekly pairs",domains:"cognitive augmentation-Domain",starred:"Starred builds",galaxy:"Class galaxy"}[tab]}</h2>
    {(tab==="domains"||tab==="recommendations") && <select aria-label="Week" value={week} onChange={e=>setWeek(Number(e.target.value))}>{weeks.map(w=><option value={w} key={w}>Week {w}</option>)}</select>}</div>
    {tab==="recommendations" && !catalog.pairs.some(pair=>selected.some(b=>b.id===pair.mine)) && <p>No same-week match is available in the indexed builds yet.</p>}
    {tab==="recommendations" && catalog.pairs.filter(pair=>selected.some(b=>b.id===pair.mine)).map(pair=>{
      const mine=catalog.builds.find(b=>b.id===pair.mine)!,peer=catalog.builds.find(b=>b.id===pair.peer)!,author=getAuthor(peer.author);
      return <article className="atlas-pair" key={mine.id+peer.id}><div className="atlas-twins">{card(mine,"Your build")}<div className="atlas-orbit" aria-hidden="true">✦</div>{card(peer,"Paired build")}</div>
      <p>{pair.borrow}</p><button onClick={()=>{setCopied(false);setMessage({id:peer.id,text:`Hi ${author.name}, I saw your build “${peer.title}” while working on “${mine.title}”. ${pair.borrow} Could we chat about how you designed it?`})}}>
      <svg width="17" height="17" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M17 9a7 7 0 0 1-8 7l-5 2 1-4A7 7 0 1 1 17 9Z" stroke="currentColor" strokeWidth="1.4"/></svg> Connect</button> <button disabled={busy} onClick={()=>rate(peer.id,"helpful")}><Thumb/> Helpful</button> <button disabled={busy} onClick={()=>rate(peer.id,"not_relevant")}><Thumb down/> Not for me</button>
      {message?.id===peer.id && <div className="atlas-compose"><label>Your message<textarea value={message.text} onChange={e=>{setCopied(false);setMessage({...message,text:e.target.value})}}/></label><button onClick={async()=>{await navigator.clipboard.writeText(message.text);setCopied(true)}}>{copied?"Copied":"Copy message"}</button> <button onClick={()=>setMessage(null)}>Close</button></div>}</article>
    })}
    {tab==="domains" && <><div className="atlas-domains">{domains.map(d=><button key={d} aria-pressed={domain===d} onClick={()=>setDomain(d)}>
      <strong>{d}</strong><img alt="" src={plates["./domain-art/"+d.replaceAll(" ","-")+".webp"]}/><small>{selected.filter(b=>b.domain===d).length} builds ↗</small></button>)}</div>
      {domain && <section aria-live="polite"><h3>{domain} · Week {week}</h3><div className="atlas-list">{selected.filter(b=>b.domain===domain).map(b=>card(b))}</div>{!selected.some(b=>b.domain===domain)&&<p>No builds indexed for this week.</p>}</section>}</>}
    {tab==="starred" && <div className="atlas-list">{catalog.builds.filter(b=>saved.includes(b.id)).map(b=>card(b))}{!saved.length&&<p>Star a build to keep it here.</p>}</div>}
    {tab==="galaxy" && <><p>{catalog.authors.length} course portfolios · Select a star to visit the student’s site.</p><GalaxySphere authors={catalog.authors}/></>}
  </div>
}
