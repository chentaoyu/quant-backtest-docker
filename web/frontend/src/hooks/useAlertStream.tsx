import { App as AntApp } from "antd";
import { useEffect, useState } from "react";
import type { AlertLevel, MonitorAlert } from "../types";

export const LEVEL_META = {
  alert: { label: "告警", color: "red" },
  warn: { label: "注意", color: "orange" },
  info: { label: "提示", color: "blue" },
} as const;

/** 通知偏好只影响本浏览器，存 localStorage。 */
export interface NotifyPrefs {
  levels: AlertLevel[]; // 哪些级别弹窗
  sticky: boolean; // 「告警」级别弹窗是否需要手动关闭
}

const PREFS_KEY = "quant.notify";
const DEFAULT_PREFS: NotifyPrefs = { levels: ["alert", "warn"], sticky: true };

export function loadNotifyPrefs(): NotifyPrefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return DEFAULT_PREFS;
  }
}

export function saveNotifyPrefs(prefs: NotifyPrefs) {
  localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
}

/** 全局订阅盯盘告警（SSE）：按通知偏好弹窗，返回本次打开页面后收到的告警。 */
export function useAlertStream() {
  const { notification } = AntApp.useApp();
  const [incoming, setIncoming] = useState<MonitorAlert[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const source = new EventSource("/api/agent/alerts/stream");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false); // 浏览器会按 retry 自动重连
    source.addEventListener("alert", (event) => {
      const alert = JSON.parse((event as MessageEvent).data) as MonitorAlert;
      setIncoming((list) => (list.some((a) => a.id === alert.id) ? list : [alert, ...list].slice(0, 200)));
      const prefs = loadNotifyPrefs();
      if (!prefs.levels.includes(alert.level)) return;
      notification[alert.level === "alert" ? "error" : alert.level === "warn" ? "warning" : "info"]({
        key: `alert-${alert.id}`,
        message: alert.title,
        description: [alert.message, alert.note].filter(Boolean).join("\n"),
        placement: "bottomRight",
        duration: alert.level === "alert" && prefs.sticky ? 0 : 8,
        style: { whiteSpace: "pre-line" },
      });
    });
    return () => source.close();
  }, [notification]);

  return { incoming, connected };
}
