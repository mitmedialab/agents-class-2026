import type {
  NotificationCenterData,
  NotificationCenterItem,
} from "./api.js";

function mergeItems(
  current: NotificationCenterItem[],
  incoming: NotificationCenterItem[],
): NotificationCenterItem[] {
  const incomingIds = new Set(incoming.map((item) => item.id));
  return [...incoming, ...current.filter((item) => !incomingIds.has(item.id))];
}

export function mergeNotificationCenterUpdates(
  current: NotificationCenterData,
  incoming: NotificationCenterData,
): NotificationCenterData {
  const items = mergeItems(current.items, incoming.items);
  const historyItems =
    current.history_items || incoming.history_items
      ? mergeItems(current.history_items ?? [], incoming.history_items ?? [])
      : undefined;

  return {
    ...incoming,
    items,
    unread_count: items.filter((item) => item.unread).length,
    ...(historyItems ? { history_items: historyItems } : {}),
  };
}
