import { useEffect, useState } from "react";

import { PLACE_LAB_APP_URL, PLACE_LAB_LIVE_PROBE, PLACE_LAB_LIVE_URL } from "./placeLabRoute.js";

/* Place Lab as a page of the course site: the simulation from GenerativeAgents/ in a frame under the
   site's own header. The header stays, so Place Lab (pressed), any other entry or the browser's back
   button is the way out. The frame shows the live server (serve.py: conversations written by the model,
   memory across runs) when it answers, otherwise the single-file build in public/placelab/. */
export function PlaceLabPage() {
  const [src, setSrc] = useState(PLACE_LAB_APP_URL);

  useEffect(() => {
    if (typeof fetch !== "function") return;
    const controller = new AbortController();
    fetch(PLACE_LAB_LIVE_PROBE, { signal: controller.signal })
      .then((response) => {
        if (response.ok) setSrc(PLACE_LAB_LIVE_URL);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  return (
    <section aria-label="Place Lab" className="placelab-page">
      <iframe allow="camera" className="placelab-frame" src={src} title="Place Lab simulation" />
    </section>
  );
}
