import { useCallback, useEffect, useState } from "react";

const ABOUT_PATH = "/about";

function isAboutPath(pathname: string): boolean {
  return pathname === ABOUT_PATH || pathname === `${ABOUT_PATH}/`;
}

export function urlForAboutState(href: string, open: boolean): string {
  const url = new URL(href);
  if (open) {
    url.pathname = ABOUT_PATH;
  } else if (isAboutPath(url.pathname)) {
    url.pathname = "/";
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

export function useAboutRoute(): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(() => isAboutPath(window.location.pathname));

  useEffect(() => {
    const handlePopState = () => setOpen(isAboutPath(window.location.pathname));
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = useCallback((nextOpen: boolean) => {
    const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    const nextUrl = urlForAboutState(window.location.href, nextOpen);
    if (nextUrl !== currentUrl) {
      window.history.pushState(window.history.state, "", nextUrl);
    }
    setOpen(nextOpen);
  }, []);

  return [open, navigate];
}
