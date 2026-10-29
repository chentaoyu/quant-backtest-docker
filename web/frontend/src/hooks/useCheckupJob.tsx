import { App as AntApp, Progress, Space, Spin, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Job } from "../types";

/** 策略体检任务：轮询进度、每完成一只回调刷新、按股票给出预计剩余秒数。 */
export function useCheckupJob(onProgress: () => void) {
  const { message } = AntApp.useApp();
  const [job, setJobState] = useState<Job | null>(null);
  const [jobAt, setJobAt] = useState(0); // 收到 job 快照的本地时间，用于倒计时
  const [now, setNow] = useState(Date.now());
  const running = job?.status === "running";

  const setJob = useCallback((next: Job | null) => {
    setJobState(next);
    setJobAt(Date.now());
  }, []);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  useEffect(() => {
    if (!job || !running) return;
    const timer = window.setInterval(() => {
      api
        .job(job.id)
        .then((next) => {
          const progressed = next.done !== job.done;
          setJob(next);
          if (progressed || next.status === "done") onProgress(); // 每体检完一只就刷新那一行
          if (next.status === "done") {
            const failed = Object.entries(next.errors);
            if (failed.length) message.warning(`体检完成，${failed.length} 只失败：${failed.map(([k, v]) => `${k} ${v}`).join("；")}`);
            else message.success("策略体检完成");
          }
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [job, running, onProgress, message, setJob]);

  /** 某只股票还要多少秒体检完；不在队列里返回 null */
  const etaOf = (symbol: string): number | null => {
    if (!job || !running) return null;
    const index = job.pending.indexOf(symbol);
    if (index < 0) return null;
    const elapsed = job.current ? job.current_elapsed + (now - jobAt) / 1000 : 0;
    return Math.max(job.avg_sec - elapsed, 0) + index * job.avg_sec;
  };

  const start = async (force: boolean, symbols?: string[]) => {
    try {
      const result = await api.checkup(force, symbols);
      if (result.job) setJob(result.job);
      else message.info(result.message ?? "无需体检");
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  /** 行内展示：体检中/排队中 + 倒计时；不在队列里返回 null */
  const rowStatus = (symbol: string) => {
    const eta = etaOf(symbol);
    if (eta === null) return null;
    return (
      <Space size={6}>
        <Spin size="small" />
        <span style={{ fontSize: 12.5, color: "#475569" }}>
          {job?.current === symbol ? "体检中" : "排队中"}
          {eta >= 1 ? ` · 约 ${Math.ceil(eta)} 秒` : " · 即将完成"}
        </span>
      </Space>
    );
  };

  const progressBar = (nameOf: (symbol: string) => string) =>
    running && job ? (
      <div style={{ marginTop: 12 }}>
        <Typography.Text type="secondary">
          策略体检中 {job.done}/{job.total}
          {job.current ? ` · ${nameOf(job.current)}` : ""}，预计还需{" "}
          {Math.ceil(etaOf(job.pending[job.pending.length - 1]) ?? 0)} 秒
        </Typography.Text>
        <Progress percent={Math.round((job.done / Math.max(job.total, 1)) * 100)} size="small" />
      </div>
    ) : null;

  return { job, running, setJob, start, rowStatus, progressBar };
}
