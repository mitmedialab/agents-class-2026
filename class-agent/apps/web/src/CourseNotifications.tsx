import { Button } from "@class-agent/ui";
import type { CourseNotification } from "./api.js";

interface CourseNotificationsProps {
  notifications: CourseNotification[];
  onRead: (notificationId: string) => void;
}

export function CourseNotifications({
  notifications,
  onRead,
}: CourseNotificationsProps) {
  if (notifications.length === 0) return null;

  return (
    <aside aria-label="Course updates" className="course-notifications">
      <p className="course-notifications-label">New course knowledge</p>
      <ol>
        {notifications.map((notification) => (
          <li key={notification.id}>
            <div>
              <h2>{notification.question}</h2>
              <p>{notification.answer}</p>
            </div>
            <Button onClick={() => onRead(notification.id)}>Mark read</Button>
          </li>
        ))}
      </ol>
    </aside>
  );
}
