import { AuthorMark } from "./AuthorMark.js";
export { AuthorMark } from "./AuthorMark.js";
import { parseScheduleMarkdown } from "./ScheduleMarkdown.js";
import publishedSchedule from "../../../shared/course/schedule/schedule.md?raw";
import { GalaxySphere } from "./GalaxySphere.js";
import { useRef, useState } from "react";
import "./peer-atlas.css";

export const domains = ["Learning","Memory","Attention","Reasoning","Creativity","Reflection","Decision-making","Communication","Social connection"] as const;
export type AtlasTab = "recommendations" | "domains" | "starred" | "galaxy" | "matches";
export interface AtlasAuthor { id:string; name:string; mark:number; site:string }
export interface AtlasBuild { id:string; author:string; title:string; week:number; domain:string; url:string; image?:string|null; excerpt?:string }
export interface AtlasCatalog {
  ownAuthor?:string;
  authors:AtlasAuthor[]; builds:AtlasBuild[];
  pairs:{mine:string; peer:string; borrow:string; reason?:string}[];
}
const weekTitles = new Map(parseScheduleMarkdown(publishedSchedule).events.map(event => [event.week, event.title]));
const plates = import.meta.glob("./domain-art/*.webp", {eager:true,import:"default"}) as Record<string,string>;

function Thumb({down=false}:{down?:boolean}){
  return <svg width="17" height="17" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"><g transform={down?"rotate(180 12 12)":undefined}><path d="M3 10h4v11H3zM7 11l5-7q2-3 3 0v5h5q2 0 1.5 2L19 19q-.5 2-3 2H7z"/></g></svg>
}
export type SendPeerMessage = (buildId: string, body: string, requestId: string) => Promise<void>;
export function PeerAtlas({catalog,tab,saved,toggle,rate,busy,sendMessage,matchedBuildIds,initialWeek}:{catalog:AtlasCatalog;tab:AtlasTab;saved:string[];toggle:(id:string)=>void;rate:(id:string,rating:"helpful"|"not_relevant")=>void;busy?:boolean;sendMessage?:SendPeerMessage | undefined;matchedBuildIds?:string[] | undefined;initialWeek?:number}){
  const weeks=[...new Set(catalog.builds.map(b=>b.week))].sort((a,b)=>b-a);
  const [week,setWeek]=useState(initialWeek ?? weeks.find(w => catalog.pairs.some(pair => catalog.builds.some(b => b.id === pair.mine && b.week === w))) ?? weeks[0]);
  const [domain,setDomain]=useState("");
  const [message,setMessage]=useState<{id:string;text:string;requestId:string}|null>(null);
  const [sendStatus, setSendStatus] = useState("");
  const sending = useRef(false);
  const [isSending,setIsSending] = useState(false);
  async function submitMessage() {
    if (!message || !sendMessage || sending.current || !message.text.trim()) return;
    sending.current = true; setIsSending(true); setSendStatus("");
    try {
      await sendMessage(message.id, message.text.trim(), message.requestId);
      setMessage(null); setSendStatus("Message sent.");
    } catch (error) {
      setSendStatus(error instanceof Error ? error.message : "Sending failed. Try again.");
    } finally {
      sending.current = false; setIsSending(false);
    }
  }
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
    {sendStatus && <p role="status">{sendStatus}</p>}
    <div className="atlas-heading"><h2>{{recommendations:"Weekly pairs",domains:"cognitive augmentation-Domain",starred:"Starred builds",galaxy:"Class galaxy",matches:"Matching builds"}[tab]}</h2>
    {(tab==="recommendations") && <select aria-label="Week" value={week} onChange={e=>setWeek(Number(e.target.value))}>{weeks.map(w=><option value={w} key={w}>Week {w}</option>)}</select>}</div>
    {tab==="recommendations" && !catalog.pairs.some(pair=>selected.some(b=>b.id===pair.mine)) && <p>No supported connection found in the indexed builds for this week yet.</p>}
    {tab==="recommendations" && catalog.pairs.filter(pair=>selected.some(b=>b.id===pair.mine)).map(pair=>{
      const mine=catalog.builds.find(b=>b.id===pair.mine)!,peer=catalog.builds.find(b=>b.id===pair.peer)!,author=getAuthor(peer.author);
      return <article className="atlas-pair" key={mine.id+peer.id}><div className="atlas-twins">{card(mine,"Your build")}<div className="atlas-orbit" aria-hidden="true">✦</div>{card(peer,"Paired build")}</div>
      {pair.reason && <p>{pair.reason}</p>}<button onClick={()=>{setSendStatus("");setMessage({id:peer.id,requestId:crypto.randomUUID(),text:`Hi ${author.name}, I saw your build “${peer.title}” while working on “${mine.title}”. What did you learn from your approach that I could try in mine?`})}}>
      <svg width="17" height="17" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M17 9a7 7 0 0 1-8 7l-5 2 1-4A7 7 0 1 1 17 9Z" stroke="currentColor" strokeWidth="1.4"/></svg> Connect</button> <button disabled={busy} onClick={()=>rate(peer.id,"helpful")}><Thumb/> Helpful</button> <button disabled={busy} onClick={()=>rate(peer.id,"not_relevant")}><Thumb down/> Not for me</button>
      {message?.id===peer.id && <div className="atlas-compose"><label>Message to {author.name}<textarea disabled={isSending} maxLength={10000} value={message.text} onChange={e=>{setSendStatus("");setMessage({...message,requestId:crypto.randomUUID(),text:e.target.value})}}/></label>
        <button disabled={isSending || !message.text.trim() || !sendMessage} onClick={()=>void submitMessage()}>{isSending ? "Sending…" : "Send"}</button> <button disabled={isSending} onClick={()=>{setMessage(null);setSendStatus("")}}>Close</button></div>}
      </article>
    })}
    {tab==="domains" && <><div className="atlas-domains">{domains.map(d=><button key={d} aria-pressed={domain===d} onClick={()=>setDomain(d)}>
      <strong>{d}</strong><img alt="" src={plates["./domain-art/"+d.replaceAll(" ","-")+".webp"]}/><small>{catalog.builds.filter(b=>b.domain===d).length} builds ↗</small></button>)}</div>
      {domain && <section aria-label={domain + " builds"}><h3>{domain}</h3>
        {weeks.map(w => {
          const builds = catalog.builds.filter(b => b.week === w && b.domain === domain);
          return builds.length > 0 && <section key={w}><h4>Week {w}{weekTitles.has(w) && " · " + weekTitles.get(w)}</h4><div className="atlas-list">{builds.map(b=>card(b))}</div></section>;
        })}
        {!catalog.builds.some(b=>b.domain===domain) && <p>No builds indexed in this domain yet.</p>}
      </section>}</>}
    {tab==="matches" && <div className="atlas-list">{matchedBuildIds?.map(id => catalog.builds.find(b=>b.id===id)).filter((b): b is AtlasBuild=>Boolean(b)).map(b=>card(b))}{!matchedBuildIds?.length && <p>No matching builds found.</p>}</div>}
    {tab==="starred" && <div className="atlas-list">{catalog.builds.filter(b=>saved.includes(b.id)).map(b=>card(b))}{!saved.length&&<p>Star a build to keep it here.</p>}</div>}
    {tab==="galaxy" && <><p>{catalog.authors.length} course portfolios · Select a star to visit the student’s site.</p><GalaxySphere authors={catalog.authors}/></>}
  </div>
}
