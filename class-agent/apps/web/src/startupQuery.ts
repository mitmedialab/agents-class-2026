const MAX_STARTUP_QUERY_CHARACTERS = 20_000;

const QUERY_TOO_LONG_MESSAGE =
  "This shared query is too long. Shorten it to 20,000 characters or fewer and try again.";

export type StartupQuery = {
  isPresent: boolean;
  prompt: string | null;
  error: string | null;
};

export function readStartupQuery(href: string): StartupQuery {
  const url = new URL(href);
  const value = url.searchParams.get("q");
  if (value === null) {
    return { isPresent: false, prompt: null, error: null };
  }

  const prompt = value.trim();
  if (!prompt) {
    return { isPresent: true, prompt: null, error: null };
  }
  if (Array.from(prompt).length > MAX_STARTUP_QUERY_CHARACTERS) {
    return { isPresent: true, prompt: null, error: QUERY_TOO_LONG_MESSAGE };
  }
  return { isPresent: true, prompt, error: null };
}

export function urlWithoutStartupQuery(href: string): string {
  const url = new URL(href);
  url.searchParams.delete("q");
  return `${url.pathname}${url.search}${url.hash}`;
}
