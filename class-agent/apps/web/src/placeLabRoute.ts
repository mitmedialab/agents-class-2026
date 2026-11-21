import { useCallback, useEffect, useState } from "react";

/* The Place Lab simulation (GenerativeAgents/) opens inside the course site at /placelab, the same
   way About opens at /about: a real URL, so the browser's back button and a reload both work. */
const PLACE_LAB_PATH = "/placelab";
// the site is dark; the simulation follows. The static build always exists; the live one is
// GenerativeAgents/serve.py behind the dev proxy, used when it answers (Gemini, memory across runs).
export const PLACE_LAB_APP_URL = "/placelab/index.html?theme=dark";
export const PLACE_LAB_LIVE_URL = "/placelab-live/src/?theme=dark";
export const PLACE_LAB_LIVE_PROBE = "/placelab-live/api/status";

function isPlaceLabPath(pathname: string): boolean {
  return pathname === PLACE_LAB_PATH || pathname === `${PLACE_LAB_PATH}/`;
}

export function urlForPlaceLabState(href: string, open: boolean): string {
  const url = new URL(href);
  if (open) {
    url.pathname = PLACE_LAB_PATH;
  } else if (isPlaceLabPath(url.pathname)) {
    url.pathname = "/";
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

export function usePlaceLabRoute(): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(() => isPlaceLabPath(window.location.pathname));

  useEffect(() => {
    const handlePopState = () => setOpen(isPlaceLabPath(window.location.pathname));
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = useCallback((nextOpen: boolean) => {
    const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    const nextUrl = urlForPlaceLabState(window.location.href, nextOpen);
    if (nextUrl !== currentUrl) {
      window.history.pushState(window.history.state, "", nextUrl);
    }
    setOpen(nextOpen);
  }, []);

  return [open, navigate];
}
