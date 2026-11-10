import { useEffect, useState } from "react";
import { PeerDiscovery, type PeerDiscoveryData } from "@class-agent/ui";
import {
  getPeerDiscovery,
  openWeeklyPairs,
  updatePeerProfile,
  forgetPeerMemory,
  postPeerFeedback,
  sendPeerMessage,
  refreshPeerBuilds,
} from "./api.js";

export function PeerDiscoveryPanel({
  view = "recommendations",
  historical = false,
  matchedBuildIds,
}: {
  view?: "recommendations" | "memory" | "coverage";
  historical?: boolean;
  matchedBuildIds?: string[] | undefined;
}) {
  const [data, setData] = useState<PeerDiscoveryData | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (historical) return;
    let active = true;
    (view === "recommendations" && !matchedBuildIds ? openWeeklyPairs() : getPeerDiscovery())
      .then((value) => {
        if (active) setData(value);
      })
      .catch(() => {
        if (active)
          setNotice(
            "Peer learning could not load. Check your student login and try again.",
          );
      });
    return () => {
      active = false;
    };
  }, [historical, view, matchedBuildIds]);
  async function change(
    action: () => Promise<PeerDiscoveryData>,
    message: string,
    resetForm = false,
  ) {
    setBusy(true);
    setNotice("");
    try {
      setData(await action());
      setNotice(message);
      if (resetForm) setRevision((v) => v + 1);
    } catch {
      setNotice(
        "The change could not be saved. Check your input and try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (historical)
    return (
      <p className="workspace-panel-message">
        Peer-learning memory is private live state. Return to the present to
        view it.
      </p>
    );
  if (!data)
    return (
      <p role="status" className="workspace-panel-message peer-panel-loading">
        {notice || "Finding your weekly pairs…"}
      </p>
    );
  return (
    <PeerDiscovery
      key={revision}
      data={data}
      matchedBuildIds={matchedBuildIds}
      sendMessage={sendPeerMessage}
      view={view}
      busy={busy}
      notice={notice}
      onOpenWeekly={() => { if (!busy) void change(openWeeklyPairs, ""); }}
      onSaveProfile={(profile) =>
        void change(
          () => updatePeerProfile(profile),
          "Learning needs saved. The Course Agent can use them in later conversations.",
        )
      }
      onForget={() =>
        void change(forgetPeerMemory, "Peer-learning memory deleted.", true)
      }
      onFeedback={(feedback) =>
        void change(
          () => postPeerFeedback(feedback),
          feedback.rating === "saved" || feedback.rating === "unsaved" ? "" : "Feedback remembered for future recommendations.",
        )
      }
      onRefresh={(ids, weeks) =>
        void change(async () => {
          await refreshPeerBuilds(ids, weeks);
          return getPeerDiscovery();
        }, "Refresh finished. Check source coverage for successes and unavailable pages.")
      }
    />
  );
}
