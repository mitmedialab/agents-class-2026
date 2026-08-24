import { useEffect, useState } from "react";

export interface PageCardItem {
  id: string;
  url: string;
  title: string;
  description?: string;
  imageUrl?: string;
}

export interface PageCardsProps {
  items: PageCardItem[];
  heading?: string;
  description?: string;
  selectedId?: string;
  onSelect?: (id: string) => void;
}

function hostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function PagePreview({ item }: { item: PageCardItem }) {
  const [failed, setFailed] = useState(false);
  if (!item.imageUrl || failed) {
    return (
      <div className="ca-page-card-placeholder">
        <span>Preview unavailable</span>
        <a href={item.url} rel="noreferrer" target="_blank">
          Open page
        </a>
      </div>
    );
  }
  return (
    <img
      alt={`Preview of ${item.title}`}
      draggable={false}
      onError={() => setFailed(true)}
      src={item.imageUrl}
    />
  );
}

export function PageCards({
  items,
  heading = "Website candidates",
  description,
  selectedId,
  onSelect,
}: PageCardsProps) {
  const [activeId, setActiveId] = useState(selectedId);
  useEffect(() => setActiveId(selectedId), [selectedId]);
  return (
    <section aria-label={heading} className="ca-page-cards">
      <header className="ca-page-cards-heading">
        <div>
          <strong>{heading}</strong>
          {description ? <p>{description}</p> : null}
        </div>
        <span>{items.length} candidates</span>
      </header>
      <div className="ca-page-cards-track">
        {items.map((item) => {
          const selected = item.id === activeId;
          return (
            <article
              className="ca-page-card"
              data-selected={selected || undefined}
              key={item.id}
            >
              <div
                aria-label={`Scrollable preview of ${item.title}`}
                className="ca-page-card-preview"
                role="region"
                tabIndex={0}
              >
                <PagePreview item={item} />
              </div>
              <footer>
                <button
                  aria-pressed={selected}
                  onClick={() => {
                    setActiveId(item.id);
                    onSelect?.(item.id);
                  }}
                  type="button"
                >
                  <strong>{item.title}</strong>
                  <span>{hostname(item.url)}</span>
                </button>
                {item.description ? <p>{item.description}</p> : null}
                <a href={item.url} rel="noreferrer" target="_blank">
                  Open externally <span aria-hidden="true">↗</span>
                </a>
              </footer>
            </article>
          );
        })}
      </div>
      <p className="ca-page-cards-status">
        Independent read-only previews · hover a column to scroll it
      </p>
    </section>
  );
}
