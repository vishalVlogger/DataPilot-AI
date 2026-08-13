"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { getNotifications, markNotificationRead, NotificationItem } from "@/services/api";

export function NotificationBell() {
  const auth = useAuth();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    let active = true;
    const load = () => getNotifications().then((result) => {
      if (active) { setItems(result.items); setUnread(result.unread_count); }
    }).catch(() => undefined);
    void load();
    const timer = window.setInterval(load, 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [auth.workspace?.id]);

  async function open(item: NotificationItem) {
    if (!item.read_at) {
      await markNotificationRead(item.id).catch(() => undefined);
      setItems((current) => current.map((entry) => entry.id === item.id ? { ...entry, read_at: new Date().toISOString() } : entry));
      setUnread((current) => Math.max(0, current - 1));
    }
  }

  return (
    <details className="notification-center">
      <summary aria-label={unread ? `${unread} unread notifications` : "Notifications"} title="Notifications">
        <svg aria-hidden="true" viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></svg>
        {unread > 0 && <b>{unread > 9 ? "9+" : unread}</b>}
      </summary>
      <div className="notification-popover">
        <div className="notification-heading"><strong>Notifications</strong><small>{unread ? `${unread} unread` : "You're up to date"}</small></div>
        {items.length ? items.slice(0, 6).map((item) => (
          <Link className={item.read_at ? "" : "unread"} href="/feedback" key={item.id} onClick={async (event) => { event.preventDefault(); await open(item); window.location.assign("/feedback"); }}>
            <i aria-hidden="true" />
            <span><strong>{item.title}</strong><small>{item.message}</small><time>{new Date(item.created_at).toLocaleString()}</time></span>
          </Link>
        )) : <p>No notifications yet.</p>}
        <Link className="notification-footer" href="/feedback">View feedback status</Link>
      </div>
    </details>
  );
}
