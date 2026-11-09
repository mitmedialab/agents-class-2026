import { useCallback, useEffect, useState } from "react";

export type PageRoute = "about" | "onboarding" | "memories" | null;

function routeFromPath(pathname: string): PageRoute {
  if (pathname === "/about" || pathname === "/about/") return "about";
  if (pathname === "/onboarding" || pathname === "/onboarding/") return "onboarding";
  if (pathname === "/memories" || pathname === "/memories/") return "memories";
  return null;
}

export function urlForPageRoute(href: string, route: PageRoute): string {
  const url = new URL(href);
  if (route) {
    url.pathname = `/${route}`;
  } else if (routeFromPath(url.pathname)) {
    url.pathname = "/";
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

export function usePageRoute(): [PageRoute, (route: PageRoute) => void] {
  const [route, setRoute] = useState(() => routeFromPath(window.location.pathname));

  useEffect(() => {
    const handlePopState = () => setRoute(routeFromPath(window.location.pathname));
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = useCallback((nextRoute: PageRoute) => {
    const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    const nextUrl = urlForPageRoute(window.location.href, nextRoute);
    if (nextUrl !== currentUrl) {
      window.history.pushState(window.history.state, "", nextUrl);
    }
    setRoute(nextRoute);
  }, []);

  return [route, navigate];
}
