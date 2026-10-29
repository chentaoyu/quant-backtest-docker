import { useEffect, useRef, useState } from "react";
import { Alert, Button, Input, Modal, Popconfirm, Space, Spin, Steps, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { api } from "../api";
import type { UpdateStatus, VersionInfo } from "../types";

const { Paragraph, Text } = Typography;

const TOKEN_KEY = "quant_update_token";

/** 更新流程阶段（组件内部状态机） */
type Phase = "view" | "running" | "restart-wait" | "done" | "failed";

interface Props {
  open: boolean;
  onClose: () => void;
}

function fmtDate(value: string | null | undefined): string {
  if (!value) return "";
  const d = dayjs(value);
  return d.isValid() ? d.format("YYYY-MM-DD HH:mm") : "";
}

/** 版本与在线更新弹窗：检查版本 / 触发更新 / 展示执行日志 / 等待重启 / 回滚。 */
export default function UpdateModal({ open, onClose }: Props) {
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [phase, setPhase] = useState<Phase>("view");
  const [error, setError] = useState("");
  const [needToken, setNeedToken] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [target, setTarget] = useState("");
  const [doneVersion, setDoneVersion] = useState("");
  const [countdown, setCountdown] = useState(5);
  const logRef = useRef<HTMLPreElement>(null);

  const loadInfo = async () => {
    try {
      const data = await api.version();
      setInfo(data);
    } catch {
      setInfo(null);
    }
  };

  const loadStatus = async () => {
    try {
      const st = await api.updateStatus();
      setStatus(st);
      if (st.state === "building" || st.state === "restarting") setPhase("running");
    } catch {
      /* ignore */
    }
  };

  // 打开时加载；若已有进行中的更新任务则直接进入 running
  useEffect(() => {
    if (!open) return;
    setInfo(null);
    setStatus(null);
    setPhase("view");
    setError("");
    setNeedToken(false);
    setTokenInput("");
    setTarget("");
    setDoneVersion("");
    void loadInfo();
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // running：轮询宿主机更新状态；容器被替换时请求失联 → 进入 restart-wait（失联 ≠ 失败）
  useEffect(() => {
    if (phase !== "running") return;
    const id = setInterval(() => {
      void (async () => {
        try {
          const st = await api.updateStatus();
          setStatus(st);
          if (st.state === "done") {
            const ver = await api.version().catch(() => null);
            setDoneVersion(ver?.current_version ?? "");
            setPhase("done");
          } else if (st.state === "failed" || st.state === "rolled_back") {
            setError(st.error ?? "更新失败");
            setPhase("failed");
          }
        } catch {
          setPhase("restart-wait");
        }
      })();
    }, 2000);
    return () => clearInterval(id);
  }, [phase]);

  // restart-wait：等 /api/health 恢复，再确认最终状态
  useEffect(() => {
    if (phase !== "restart-wait") return;
    let tries = 0;
    const id = setInterval(() => {
      void (async () => {
        tries += 1;
        const ok = await api.health();
        if (!ok) {
          if (tries > 150) {
            // ~5 分钟
            clearInterval(id);
            setError("服务重启超时，请人工检查：docker compose logs web / journalctl -u quant-updater.service");
            setPhase("failed");
          }
          return;
        }
        clearInterval(id);
        const st = await api.updateStatus().catch(() => null);
        const ver = await api.version().catch(() => null);
        if (st && (st.state === "failed" || st.state === "rolled_back")) {
          setError(st.error ?? "更新失败");
          setPhase("failed");
        } else {
          setDoneVersion(ver?.current_version ?? "");
          setPhase("done");
        }
      })();
    }, 2000);
    return () => clearInterval(id);
  }, [phase]);

  // done：倒计时后自动刷新页面（加载新前端）
  useEffect(() => {
    if (phase !== "done") return;
    setCountdown(5);
    const id = setInterval(() => {
      setCountdown((n) => {
        if (n <= 1) {
          clearInterval(id);
          window.location.reload();
        }
        return n - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [phase]);

  // 日志自动滚到底
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [status?.log_tail]);

  const trigger = async () => {
    const token = localStorage.getItem(TOKEN_KEY) ?? "";
    if (!token) {
      setNeedToken(true);
      return;
    }
    try {
      const res = await api.triggerUpdate(token);
      setTarget(res.target);
      setPhase("running");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const saveTokenAndTrigger = async () => {
    const token = tokenInput.trim();
    if (!token) return;
    localStorage.setItem(TOKEN_KEY, token);
    setNeedToken(false);
    try {
      const res = await api.triggerUpdate(token);
      setTarget(res.target);
      setPhase("running");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const rollback = async () => {
    const token = localStorage.getItem(TOKEN_KEY) ?? "";
    if (!token) {
      setNeedToken(true);
      return;
    }
    try {
      const res = await api.triggerRollback(token);
      setTarget(res.target);
      setPhase("running");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const retryFromView = () => {
    setError("");
    setPhase("view");
    void loadInfo();
    void loadStatus();
  };

  const logBlock = (
    <pre
      ref={logRef}
      style={{
        background: "#0b1021",
        color: "#c8d3f5",
        fontSize: 11,
        lineHeight: 1.5,
        padding: 12,
        borderRadius: 8,
        maxHeight: 240,
        overflow: "auto",
        margin: 0,
        whiteSpace: "pre-wrap",
        wordBreak: "break-all",
      }}
    >
      {status?.log_tail || "（暂无日志）"}
    </pre>
  );

  const manualCommand = "git pull && docker compose pull web && docker compose up -d";

  return (
    <Modal
      open={open}
      title="版本与在线更新"
      width={640}
      onCancel={onClose}
      footer={null}
      destroyOnClose
    >
      {phase === "view" && (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          {!info && <Spin />}
          {info && (
            <>
              <div>
                当前版本 <Tag color="blue">v{info.current_version}</Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {" "}
                  {info.current_commit !== "unknown" ? info.current_commit.slice(0, 8) : ""}
                </Text>
              </div>
              {info.latest ? (
                <div>
                  最新版本 <Tag color={info.has_update ? "green" : "default"}>{info.latest.tag}</Tag>
                  {info.latest.published_at && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      发布于 {fmtDate(info.latest.published_at)}
                    </Text>
                  )}
                  {info.latest.notes && (
                    <Paragraph
                      ellipsis={{ rows: 4, expandable: true, symbol: "展开" }}
                      style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}
                    >
                      {info.latest.notes}
                    </Paragraph>
                  )}
                </div>
              ) : (
                <Alert type="warning" showIcon message={info.warning ?? "无法获取最新版本信息"} />
              )}
              {info.update_mode !== "host-updater" && (
                <Alert
                  type="info"
                  showIcon
                  message="当前是本地开发模式（未启用在线更新），请手动执行："
                  description={
                    <Paragraph copyable={{ text: manualCommand }} style={{ marginBottom: 0, fontSize: 12 }}>
                      {manualCommand}
                    </Paragraph>
                  }
                />
              )}
              {needToken && (
                <Space.Compact style={{ width: "100%" }}>
                  <Input.Password
                    placeholder="输入更新令牌（在服务器 .env 中查看 UPDATE_TOKEN）"
                    value={tokenInput}
                    onChange={(e) => setTokenInput(e.target.value)}
                    onPressEnter={() => void saveTokenAndTrigger()}
                  />
                  <Button type="primary" onClick={() => void saveTokenAndTrigger()}>
                    保存并更新
                  </Button>
                </Space.Compact>
              )}
              {error && <Alert type="error" showIcon message={error} />}
              {info.update_mode === "host-updater" && info.has_update && !needToken && (
                <Popconfirm
                  title="确认更新？"
                  description="更新会拉取新镜像并重启服务，正在运行的回测/体检任务会被中断（数据卷不受影响）。"
                  okText="更新"
                  cancelText="取消"
                  onConfirm={() => void trigger()}
                >
                  <Button type="primary" loading={false}>
                    更新到 {info.latest?.tag}
                  </Button>
                </Popconfirm>
              )}
              {info.update_mode === "host-updater" && info.has_update === false && (
                <Text type="secondary">已是最新版本。</Text>
              )}
              {info.update_mode === "host-updater" && info.last_update?.last_good_tag && !needToken && (
                <Popconfirm
                  title="确认回滚？"
                  description={`回滚到 ${info.last_update.last_good_tag}，同样会重启服务。`}
                  okText="回滚"
                  cancelText="取消"
                  onConfirm={() => void rollback()}
                >
                  <Button danger type="text">
                    回滚到 {info.last_update.last_good_tag}
                  </Button>
                </Popconfirm>
              )}
            </>
          )}
        </Space>
      )}

      {(phase === "running" || phase === "restart-wait") && (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Steps
            size="small"
            current={phase === "running" ? 0 : 1}
            items={[
              { title: "拉取镜像", description: status?.state === "building" ? "执行中" : "" },
              { title: "替换容器" },
              { title: "完成" },
            ]}
          />
          <Alert
            type={phase === "running" ? "info" : "warning"}
            showIcon
            message={
              phase === "running"
                ? status?.stale
                  ? "更新疑似卡死（超过 20 分钟无进展），可关闭弹窗后重试"
                  : "正在拉取镜像并替换容器…"
                : "服务重启中，等待恢复…"
            }
            description={target ? `目标版本：${target}` : undefined}
          />
          {logBlock}
          <Button onClick={onClose}>后台运行，关闭弹窗</Button>
        </Space>
      )}

      {phase === "done" && (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="success"
            showIcon
            message="更新完成"
            description={doneVersion ? `当前版本：v${doneVersion}` : undefined}
          />
          <Text type="secondary">{countdown} 秒后自动刷新页面…</Text>
          <Button type="primary" onClick={() => window.location.reload()}>
            立即刷新
          </Button>
        </Space>
      )}

      {phase === "failed" && (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert type="error" showIcon message="更新失败" description={error || "未知错误"} />
          {logBlock}
          <Space>
            <Button onClick={retryFromView}>返回重试</Button>
            <Button danger onClick={() => void rollback()}>
              回滚到上一版本
            </Button>
          </Space>
        </Space>
      )}
    </Modal>
  );
}
