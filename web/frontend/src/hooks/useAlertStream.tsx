import { App as AntApp } from "antd";
import { useEffect, useState } from "react";
import type { MonitorAlert } from "../types";

export const LEVEL_META = {
  alert: { label: "告警", color: "red" },
  warn: { label: "注意", color: "orange" },
  info: { label: "提示", color: "blue" },
} as const;

/** 全局订阅盯盘告警（SSE）：注意/告警级别弹通知，返回本次打开页面后收到的告警。 */
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
      if (alert.level === "info") return;
      notification[alert.level === "alert" ? "error" : "warning"]({
        key: `alert-${alert.id}`,
        message: alert.title,
        description: [alert.message, alert.note].filter(Boolean).join("\n"),
        placement: "bottomRight",
        duration: alert.level === "alert" ? 0 : 8,
        style: { whiteSpace: "pre-line" },
      });
    });
    return () => source.close();
  }, [notification]);

  return { incoming, connected };
}
