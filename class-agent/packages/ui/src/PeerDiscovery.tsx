import { useState } from "react";
import { PeerAtlas, type AtlasCatalog } from "./PeerAtlas.js";
import { Button } from "./Button.js";

export interface PeerProfile {
  long_term_focus?: string;
  goal: string;
  challenges: string[];
  interests: string[];
}
export interface PeerBuild {
  id: string;
  project_id: string;
  title: string;
  week: number | null;
  source_url: string;
  observed_at: string;
  truncated: boolean;
}
export interface PeerRecommendation {
  build_id: string;
  reason: string;
  borrow: string;
  evidence_quote: string;
  profile: PeerProfile;
  created_at: string;
  build: PeerBuild;
}
export interface PeerFeedback {
  build_id: string;
  rating: "helpful" | "not_relevant" | "already_seen" | "unsaved" | "saved" | "opened";
  note: string;
}
export interface PeerDiscoveryData {
  atlas?: AtlasCatalog;
  memory: {
    profile: PeerProfile;
    profile_origin: string;
    updated_at: string | null;
    feedback: PeerFeedback[];
  };
  recommendations: PeerRecommendation[];
  coverage: Record<string, Record<string, string>>;
  indexed_builds: number;
  privacy: string;
  freshness: string;
}
export interface PeerDiscoveryProps {
  data: PeerDiscoveryData;
  view?: "recommendations" | "memory" | "coverage";
  busy?: boolean;
  readOnly?: boolean;
  notice?: string;
  onOpenWeekly?: () => void;
  onSaveProfile: (profile: PeerProfile) => void;
  onForget: () => void;
  onFeedback: (feedback: PeerFeedback) => void;
  onRefresh: (projectIds: string[], weeks: number[]) => void;
}

const lines = (value: string) =>
  value
    .split("\n")
    .map((v) => v.trim())
    .filter(Boolean);

function BuildMark({ seed }: { seed?: string }) {
  const count = 5 + Array.from(seed || "").reduce((sum, char) => sum + char.charCodeAt(0), 0) % 8;
  return (
    <svg className="ca-peer__mark" viewBox="0 0 100 100" aria-hidden="true">
      {seed ? Array.from({ length: count }, (_, i) => (
        <ellipse key={i} cx="50" cy="35" rx="7" ry="28" fill="none"
          stroke="currentColor" strokeWidth="1.6" transform={`rotate(${360 * i / count} 50 50)`} />
      )) : <path fill="currentColor" d="M50 5 Q53 45 95 50 Q55 54 50 95 Q46 55 5 50 Q46 46 50 5Z" />}
    </svg>
  );
}

export function PeerDiscovery({
  data,
  view = "recommendations",
  busy,
  readOnly,
  notice,
  onOpenWeekly,
  onSaveProfile,
  onForget,
  onFeedback,
  onRefresh,
}: PeerDiscoveryProps) {
  const [tab, setTab] = useState<NonNullable<PeerDiscoveryProps["view"]> | "domains" | "starred" | "galaxy">(view);
  const [profile, setProfile] = useState(data.memory.profile);
  const [challengeText, setChallengeText] = useState(
    profile.challenges.join("\n"),
  );
  const [interestText, setInterestText] = useState(
    profile.interests.join("\n"),
  );
  const [erase, setErase] = useState(false);
  const [projectIds, setProjectIds] = useState("");
  const [weeks, setWeeks] = useState("");
  const [draft, setDraft] = useState<string | null>(null);
  const disabled = busy || readOnly;
  const unique = data.recommendations.filter(
    (r, i, all) => all.findIndex((v) => v.build_id === r.build_id) === i,
  );
  const domains = [...new Set(unique.flatMap(item => item.profile.interests))];
  const starred = unique.filter(item => data.memory.feedback.filter(
    feedback => feedback.build_id === item.build_id && feedback.rating !== "opened"
  ).at(-1)?.rating === "saved");
  return (
    <section className="ca-peer" aria-label="Personalized peer learning">
      <header className="ca-peer__header">
        <p className="ca-peer__eyebrow">Course Agent</p>
        <h1>Peer learning</h1>

      </header>
      <nav className="ca-peer__tabs" aria-label="Peer learning views">
        {(
          [
            ["recommendations", "My Weekly Paired Stars"],
            ["domains", "Domains"],
            ["galaxy", "Class galaxy"],
            ["starred", "Starred builds"],

          ] as const
        ).map(([id, label]) => (
          <Button key={id} aria-pressed={tab === id} onClick={() => { setTab(id); if (id === "recommendations") onOpenWeekly?.(); }}>
            <svg className="peer-tab-icon" viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.45" strokeLinecap="round" strokeLinejoin="round">
              {id === "recommendations" && <><ellipse cx="10" cy="10" rx="8" ry="3.5" transform="rotate(-32 10 10)"/><circle cx="4" cy="13" r="2" fill="currentColor"/><circle cx="16" cy="7" r="2" fill="currentColor"/></>}
              {id === "domains" && <path d="M3 3h5v5H3z M12 3h5v5h-5z M3 12h5v5H3z M12 12h5v5h-5z"/>}
              {id === "galaxy" && <><path d="m3 13 6-9 7 4-4 8-9-3"/>{[[3,13],[9,4],[16,8],[12,16]].map(([x,y])=><circle key={x} cx={x} cy={y} r="1.7" fill="currentColor"/>)}</>}
              {id === "starred" && <path d="m10 2 2.5 5 5.5.8-4 4 .95 5.5L10 14.7l-4.95 2.6.95-5.5-4-4L7.5 7z"/>}
            </svg>{label}
          </Button>
        ))}
      </nav>
      {data.atlas && tab !== "memory" && tab !== "coverage" && <PeerAtlas catalog={data.atlas} tab={tab} busy={Boolean(disabled)} rate={(id,rating)=>onFeedback({build_id:id,rating,note:""})}
        saved={data.atlas.builds.filter(build => data.memory.feedback.filter(f => f.build_id === build.id && (f.rating === "saved" || f.rating === "unsaved")).at(-1)?.rating === "saved").map(b=>b.id)}
        toggle={id => { const last = data.memory.feedback.filter(f => f.build_id === id && (f.rating === "saved" || f.rating === "unsaved")).at(-1);
          onFeedback({build_id:id,rating:last?.rating === "saved" ? "unsaved" : "saved",note:""}); }}/>}

      {!data.atlas && tab === "domains" && <section>
        <h2>Domains</h2><p>Interests associated with your current matches.</p>
        {domains.length ? domains.map(domain => <article key={domain}>
          <h3>{domain}</h3>
          {unique.filter(item => item.profile.interests.includes(domain)).map(item =>
            <p key={item.build_id}>{item.build.title}</p>)}
        </article>) : <p>No interests recorded for these matches yet.</p>}
      </section>}
      {!data.atlas && tab === "starred" && <section>
        <h2>Starred builds</h2>
        {starred.length ? starred.map(item => <p key={item.build_id}>
          <a href={item.build.source_url}>{item.build.title}</a>
        </p>) : <p>Choose Save on a weekly pair to find it here.</p>}
      </section>}
      {!data.atlas && tab === "galaxy" && <section>
        <h2>Class galaxy</h2><p>Projects in your current source coverage.</p>
        {Object.keys(data.coverage).length ? Object.entries(data.coverage).map(([id, source]) =>
          <p key={id}>{id} · {source.status}</p>) : <p>No projects indexed yet.</p>}
      </section>}
      {notice && (
        <p role="status" className="ca-peer__notice">
          {notice}
        </p>
      )}
      {readOnly && (
        <p className="ca-peer__notice">
          Historical view. Your current private profile is not loaded here.
        </p>
      )}
      {!data.atlas && tab === "recommendations" && (
        <>
          <div className="ca-peer__context">
            <span>Your current focus</span>
            <p>
              {data.memory.profile.goal ||
                "Tell the Course Agent what you are working on, or add your learning needs."}
            </p>
            <Button onClick={() => setTab("memory")}>
              Edit learning needs ↗
            </Button>
          </div>
          {!unique.length && (
            <div className="ca-peer__empty">
              <h2>Start with a question.</h2>
              <p>
                Ask the Course Agent to find peer builds for your current
                challenge. It will read your saved needs, compare available
                sources and explain what you could borrow.
              </p>
              <p>
                Try: “Find classmates’ builds that could help with my current
                project.”
              </p>
            </div>
          )}
          <div className="ca-peer__grid">{unique.map((item) => {
            const feedback = [...data.memory.feedback]
              .reverse()
              .find(
                (f) => f.build_id === item.build_id && f.rating !== "opened",
              );
            const name = item.build.project_id.replace(/^agents2026-/, "");
            return (
              <article className="ca-peer__recommendation" key={item.build_id}>
                <div className="ca-peer__pair">
                  <div className="ca-peer__node">
                    <BuildMark />
                    <span className="ca-peer__eyebrow">Your focus</span>
                    <strong>{item.profile.goal || item.profile.challenges[0] || "Your request"}</strong>
                  </div>
                  <div className="ca-peer__node">
                    <BuildMark seed={item.build_id} />
                    <span className="ca-peer__eyebrow">{name} · {item.build.week ? `Week ${item.build.week}` : "Public project"}</span>
                    <h2>{item.build.title}</h2>
                  </div>
                </div>
                <p>{item.reason}</p>
                <div className="ca-peer__borrow">
                  <h3>Something to borrow</h3>
                  <p>{item.borrow}</p>
                </div>
                <details>
                  <summary>Why this recommendation?</summary>
                  <blockquote>{item.evidence_quote}</blockquote>
                  <p>Matched to: {item.profile.goal || "your request"}</p>
                  <p>
                    Source read{" "}
                    {new Date(item.build.observed_at).toLocaleDateString(
                      "en-US",
                    )}
                    {item.build.truncated ? " · partial text snapshot" : ""}.
                  </p>
                </details>
                <a
                  href={item.build.source_url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={() => {
                    if (!disabled)
                      onFeedback({
                        build_id: item.build_id,
                        rating: "opened",
                        note: "",
                      });
                  }}
                >
                  Open original build ↗
                </a>
                <div className="ca-peer__actions">
                  <Button
                    disabled={readOnly}
                    onClick={() =>
                      setDraft(
                        `Hi ${name}, I came across your build, “${item.build.title}”. I’m working on ${data.memory.profile.goal || "a related project"}. ${item.borrow} I’d love to learn more about your approach. Would you be open to a quick conversation?`,
                      )
                    }
                  >
                    💬 Message
                  </Button>
                  {(
                    [
                      ["helpful", "Helpful", "＋"],
                      ["not_relevant", "Not relevant", "−"],
                      ["saved", "Save", "☆"],
                    ] as const
                  ).map(([rating, label, icon]) => (
                    <Button
                      key={rating}
                      disabled={disabled}
                      aria-pressed={feedback?.rating === rating}
                      onClick={() =>
                        onFeedback({
                          build_id: item.build_id,
                          rating,
                          note: "",
                        })
                      }
                    >
                      <span aria-hidden="true">{icon}</span>{label}
                    </Button>
                  ))}

                </div>
                {feedback && (
                  <p className="ca-peer__feedback">
                    Remembered: {feedback.rating.replaceAll("_", " ")}. You can
                    explain more in chat.
                  </p>
                )}
              </article>
            );
          })}</div>
          {draft !== null && (
            <aside className="ca-peer__draft">
              <h2>Contact draft</h2>
              <p>
                Review and copy this into your preferred channel. Nothing has
                been sent.
              </p>
              <label className="ca-field">
                <span className="ca-field__label">Your message</span>
                <textarea
                  className="ca-input"
                  rows={5}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                />
              </label>
              <Button onClick={() => setDraft(null)}>Close draft</Button>
            </aside>
          )}
        </>
      )}
      {tab === "memory" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSaveProfile({
              ...profile,
              challenges: lines(challengeText),
              interests: lines(interestText),
            });
          }}
          className="ca-peer__form"
        >
          <h2>My matching preferences</h2>
          <p>
            The Course Agent uses your saved goals, challenges and interests to find relevant builds. {data.privacy}
          </p>
          <label className="ca-field">
            <span className="ca-field__label">Long-term focus</span>
            <textarea className="ca-input" rows={2} maxLength={1200} disabled={disabled}
              placeholder="What would you like to keep exploring across weekly builds?"
              value={profile.long_term_focus ?? ""}
              onChange={(e) => setProfile({ ...profile, long_term_focus: e.target.value })}
            />
          </label>
          <label className="ca-field">
            <span className="ca-field__label">
              Current project or learning goal
            </span>
            <textarea
              className="ca-input"
              rows={3}
              maxLength={1200}
              disabled={disabled}
              value={profile.goal}
              onChange={(e) => setProfile({ ...profile, goal: e.target.value })}
            />
          </label>
          <label className="ca-field">
            <span className="ca-field__label">
              Current difficulties · one per line
            </span>
            <textarea
              className="ca-input"
              rows={3}
              maxLength={3000}
              disabled={disabled}
              value={challengeText}
              onChange={(e) => setChallengeText(e.target.value)}
            />
          </label>
          <label className="ca-field">
            <span className="ca-field__label">Interests · one per line</span>
            <textarea
              className="ca-input"
              rows={3}
              maxLength={3000}
              disabled={disabled}
              value={interestText}
              onChange={(e) => setInterestText(e.target.value)}
            />
          </label>
          <Button type="submit" variant="outline" disabled={disabled}>
            Save my learning needs
          </Button>
          <p className="ca-peer__feedback">
            Source: {data.memory.profile_origin}
            {data.memory.updated_at
              ? ` · updated ${new Date(data.memory.updated_at).toLocaleDateString("en-US")}`
              : ""}
          </p>
          <div className="peer-delete-memory">
          {!erase ? (
            <Button
              type="button"
              disabled={disabled}
              onClick={() => setErase(true)}
            >
              Forget my peer-learning memory
            </Button>
          ) : (
            <div>
              <p>
                Delete your profile, recommendations and feedback? This does not
                erase chat history or public build sources.
              </p>
              <Button
                type="button"
                disabled={disabled}
                onClick={() => {
                  onForget();
                  setErase(false);
                }}
              >
                Confirm delete
              </Button>{" "}
              <Button type="button" onClick={() => setErase(false)}>
                Cancel
              </Button>
            </div>
          )}
          </div>
        </form>
      )}
      {tab === "coverage" && (
        <div className="ca-peer__form">
          <h2>Weekly builds the agent has read</h2>
          <p>{data.indexed_builds} builds indexed across the available course sites.</p>
          <ul className="peer-source-list">
            {(data.atlas?.builds ?? []).map(build => <li key={build.id}>
              <a href={build.url} target="_blank" rel="noreferrer">{build.title} ↗</a>
              <small>{build.author.replace(/^agents2026-/, "")} · Week {build.week}</small>
            </li>)}
          </ul>
          <details><summary>Manage source refresh</summary>
          <label className="ca-field">
            <span className="ca-field__label">
              Course project IDs · one per line, up to eight
            </span>
            <textarea
              className="ca-input"
              rows={3}
              placeholder="agents2026-raine"
              value={projectIds}
              disabled={disabled}
              onChange={(e) => setProjectIds(e.target.value)}
            />
          </label>
          <label className="ca-field">
            <span className="ca-field__label">
              Weeks · comma separated; leave blank for discovered weeks
            </span>
            <input
              className="ca-input"
              value={weeks}
              disabled={disabled}
              onChange={(e) => setWeeks(e.target.value)}
            />
          </label>
          <Button
            variant="outline"
            disabled={disabled || !projectIds.trim()}
            onClick={() =>
              onRefresh(
                lines(projectIds),
                weeks.trim() ? weeks.split(",").map(Number) : [],
              )
            }
          >
            {busy ? "Reading sources…" : "Refresh selected sources"}
          </Button>
          </details>
          {Object.entries(data.coverage).map(([id, coverage]) => (
            <details key={id}>
              <summary>{id.replace(/^agents2026-/, "")}</summary>
              <dl>
                {Object.entries(coverage).map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </details>
          ))}
        </div>
      )}
      {tab === "recommendations" && data.atlas && <div className="peer-context-link">
        <Button onClick={() => setTab("memory")}>Edit my matching preferences ↗</Button>
      </div>}
      {tab === "galaxy" && <div className="peer-context-link">
        <Button onClick={() => setTab("coverage")}>View indexed weekly builds ↗</Button>
      </div>}

    </section>
  );
}
