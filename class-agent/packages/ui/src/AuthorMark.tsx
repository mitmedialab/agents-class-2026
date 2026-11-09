import { useId, type ReactNode } from "react";

const turns = (count: number, draw: (i: number) => ReactNode) =>
  Array.from({length: count}, (_, i) => <g key={i} transform={`rotate(${360*i/count})`}>{draw(i)}</g>);

// Preserve the original portfolio slots. Only the dense variants that converge
// at the galaxy's 23px size get an alternate from the same optical-mark family.
function alternate(index: number, clip: string) {
  switch (index) {
    case 31: // Two offset crescents
      return <g fill="currentColor"><path d="M0-23A23 23 0 0 0 0 23A17 17 0 0 1 0-11Z"/><path d="M0 23A23 23 0 0 0 0-23A17 17 0 0 1 0 11Z"/></g>;
    case 23: // Concentric tangent rings
      return <g fill="none" stroke="currentColor" strokeWidth="2.3">{[21,16,11,6].map(r=><circle key={r} cx={20-r} r={r}/>)}</g>;
    case 24: // Perforated annulus, coarse enough to read at small sizes
      return turns(12,i=><circle cy="-17" r={2.3+1.8*(1+Math.cos(i*Math.PI/6))} fill="currentColor"/>);
    case 25: // Parallel-cut annulus
      return <g><defs><clipPath id={clip}><path clipRule="evenodd" d="M22 0A22 22 0 1 1-22 0A22 22 0 1 1 22 0ZM9 0A9 9 0 1 0-9 0A9 9 0 1 0 9 0Z"/></clipPath></defs><g clipPath={`url(#${clip})`}><g transform="rotate(38)" stroke="currentColor" strokeWidth="3.2">{[-24,-18,-12,-6,0,6,12,18,24].map(x=><path key={x} d={`M${x} -30v60`}/>)}</g></g></g>;
    case 26: // Three sweeping arcs meet the rim around an open center.
      return (
        <g fill="none" stroke="currentColor" strokeWidth="2.7">
          <circle r="21" />
          {turns(3, () => <path d="M0-21C-13-19-17-5-9 4C-5 9 1 11 8 8" />)}
        </g>
      );
    case 30: // Short, curved strokes around a hollow center
      return turns(10,()=><g fill="none" stroke="currentColor" strokeWidth="3.4" strokeLinecap="round"><path d="M-3-20q4 0 6 2"/><path d="M0-13l3 2"/></g>);
    case 32: // Two crossing orbital planes with distinct satellites
      return <g><g fill="none" stroke="currentColor" strokeWidth="2.1"><ellipse rx="21" ry="7" transform="rotate(-30)"/><ellipse rx="16" ry="7" transform="rotate(55)"/></g><g fill="currentColor"><circle cx="17" cy="-11" r="4"/><circle cx="-7" cy="-12" r="3"/></g></g>;
    case 33: // Four inward curls
      return turns(4,()=><path d="M0-21C13-21 20-11 17-2C14 7 3 10-2 4C-7-2-3-8 3-9" fill="none" stroke="currentColor" strokeWidth="2.6"/>);
    case 34: // Optical bands cut by a circular boundary
      return <g><defs><clipPath id={clip}><circle r="22"/></clipPath></defs><g clipPath={`url(#${clip})`} fill="none" stroke="currentColor" strokeWidth="3.7">{[-22,-12,-2,8,18,28].map(y=><path key={y} d={`M-27 ${y} Q-13 ${y-12} 0 ${y} T27 ${y}`}/>)}</g></g>;
    case 35: // Mirrored fans, with open space between the two poles
      return <g fill="currentColor"><path d="M-22-4a22 22 0 0 1 44 0L4-13 0-5-5-13Z"/><path transform="rotate(180)" d="M-22-4a22 22 0 0 1 44 0L4-13 0-5-5-13Z"/></g>;
    default: return null;
  }
}
export function AuthorMark({index}:{index:number}) {
  const clip = useId();
  const family=index%5, n=5+Math.floor(index/5)*2;
  return <svg className="atlas-mark" viewBox="-26 -26 52 52" aria-hidden="true">
    {alternate(index,clip) ?? turns(n,()=> <>
      {family===0 && <ellipse cy="-9" ry="14" rx="6" fill="none" stroke="currentColor" strokeWidth="2"/>}
      {family===1 && <path d="M0 -24 Q16 -23 3 -5 L-2 -7Z" fill="currentColor"/>}
      {family===2 && <g fill="currentColor"><circle cy="-19" r="3"/><circle cy="-12" r="2"/></g>}
      {family===3 && <path d="M0 -23 L6 -11 L0 -5" fill="none" stroke="currentColor" strokeWidth="3"/>}
      {family===4 && <g stroke="currentColor" fill="currentColor"><path d="M0 -21V0"/><circle cy="-20" r="3"/></g>}
    </>)}
  </svg>;
}
