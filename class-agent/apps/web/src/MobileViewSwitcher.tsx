import { Button } from "@class-agent/ui";

export type MobileView = "chat" | "updates" | "workspace";

interface MobileViewSwitcherProps {
  activeView: MobileView;
  count?: number | undefined;
  onViewChange: (view: MobileView) => void;
  secondaryView: Exclude<MobileView, "chat">;
}

export function MobileViewSwitcher({
  activeView,
  count = 0,
  onViewChange,
  secondaryView,
}: MobileViewSwitcherProps) {
  const secondaryLabel = secondaryView === "updates" ? "Updates" : "Workspace";
  const secondaryAccessibleLabel =
    secondaryView === "updates" && count > 0
      ? `${secondaryLabel}, ${count} active items`
      : secondaryLabel;

  return (
    <div aria-label="Mobile view" className="mobile-view-switcher" role="group">
      <Button
        aria-pressed={activeView === "chat"}
        className="mobile-view-switcher-button"
        onClick={() => onViewChange("chat")}
      >
        Chat
      </Button>
      <Button
        aria-label={secondaryAccessibleLabel}
        aria-pressed={activeView === secondaryView}
        className="mobile-view-switcher-button"
        onClick={() => onViewChange(secondaryView)}
      >
        {secondaryLabel}
        {secondaryView === "updates" && count > 0 ? (
          <span aria-hidden="true" className="mobile-view-count">
            {count}
          </span>
        ) : null}
      </Button>
    </div>
  );
}
