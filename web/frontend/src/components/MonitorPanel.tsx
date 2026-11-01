import { App as AntApp, Alert, Button, Card, Col, Empty, Row, Segmented, Space, Spin, Table, Tag, Tooltip, Typography } from "antd";
import { ReloadOutlined, RobotOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { cnColor, pct } from "../format";
import { LEVEL_META } from "../hooks/useAlertStream";
import type { AlertLevel, LiveMarket, LiveSector, MonitorAlert, MonitorStatus } from "../types";

const { Text } = Typography;

interface Props {
  incoming: MonitorAlert[];
  connected: boolean;
}

const today = () => new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD

function SectorList({ title, rows }: { title: string; rows: LiveSector[] }) {
  return (
    <div>
      <Text type="secondary">{title}</Text>
      {rows.map((s) => (
        <div key={s.name} style={{ display: "flex", justifyContent: "space-between", lineHeight: "26px" }}>
          <span>
            {s.name}
            <Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
              {s.leader} {pct(s.leader_change_pct)}
            </Text>
          </span>
          <span style={{ color: cnColor(s.change_pct), fontVariantNumeric: "tabular-nums" }}>{pct(s.change_pct)}</span>
        </div>
      ))}
    </div>
  );
}

export default function MonitorPanel({ incoming, connected }: Props) {
  const { message } = AntApp.useApp();
  const [market, setMarket] = useState<LiveMarket | null>(null);
  const [status, setStatus] = useState<MonitorStatus | null>(null);
  const [alerts, setAlerts] = useState<MonitorAlert[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [ticking, setTicking] = useState(false);
  const [range, setRange] = useState<"today" | "all">("today");
  const [level, setLevel] = useState<"all" | AlertLevel>("all");

  const load = useCallback(
    async (refresh = false) => {
      setLoading(true);
      try {
        const [m, s, a] = await Promise.all([
          api.monitorMarket(refresh),
          api.monitorStatus(),
          api.alerts(300, range === "today" ? today() : undefined),
        ]);
        setMarket(m);
        setStatus(s);
        setAlerts(a);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "盯盘服务不可用");
      } finally {
        setLoading(false);
      }
    },
    [range],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // 盘中每分钟刷新一次市场快照（告警本身走 SSE 实时推送）
  useEffect(() => {
    if (!status?.trading) return;
    const timer = window.setInterval(() => void api.monitorMarket(true).then(setMarket).catch(() => {}), 60_000);
    return () => window.clearInterval(timer);
  }, [status?.trading]);

  const tick = async () => {
    setTicking(true);
    try {
      const res = await api.monitorTick();
      setStatus(res.status);
      message.success(res.new.length ? `新增 ${res.new.length} 条告警` : "检查完成，没有新告警");
      void load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "检查失败");
    } finally {
      setTicking(false);
    }
  };

  const rows = useMemo(() => {
    const seen = new Set(alerts.map((a) => a.id));
    const extra = incoming.filter((a) => !seen.has(a.id) && (range === "all" || a.day === today()));
    return [...extra, ...alerts].filter((a) => level === "all" || a.level === level);
  }, [alerts, incoming, range, level]);

  if (error && !market) {
    return (
      <Alert
        type="warning"
        showIcon
        message="盯盘服务不可用"
        description={`${error}。请确认 agent 服务已启动（docker compose up -d agent）。`}
        action={<Button onClick={() => void load()}>重试</Button>}
      />
    );
  }

  const b = market?.breadth;
  return (
    <Spin spinning={loading && !market}>
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Card
          className="panel-card"
          title="市场快照"
          extra={
            <Space>
              {market && <Text type="secondary">更新于 {market.at.slice(11)}</Text>}
              <Button size="small" icon={<ReloadOutlined />} onClick={() => void load(true)}>
                刷新
              </Button>
            </Space>
          }
        >
          {Object.keys(market?.errors ?? {}).length > 0 && (
            <Alert type="warning" showIcon style={{ marginBottom: 12 }}
              message={`部分数据获取失败：${Object.entries(market!.errors).map(([k, v]) => `${k} ${v}`).join("；")}`} />
          )}
          <Row gutter={[16, 16]}>
            {(market?.indexes ?? []).map((i) => (
              <Col xs={12} md={6} key={i.code}>
                <Text type="secondary">{i.name}</Text>
                <div style={{ fontSize: 20, fontWeight: 600, color: cnColor(i.change_pct) }}>{i.price.toFixed(2)}</div>
                <Text style={{ color: cnColor(i.change_pct) }}>{pct(i.change_pct)}</Text>
              </Col>
            ))}
          </Row>
          {b && (
            <div style={{ marginTop: 16 }}>
              <Space size={[8, 8]} wrap>
                <Tag color="red">上涨 {b.up}</Tag>
                <Tag color="green">下跌 {b.down}</Tag>
                <Tag>平盘 {b.flat}</Tag>
                <Tag color="volcano">涨停 {b.limit_up}</Tag>
                <Tag color="cyan">跌停 {b.limit_down}</Tag>
                <Tag>涨超 5%：{b.up_over_5pct}</Tag>
                <Tag>跌超 5%：{b.down_over_5pct}</Tag>
              </Space>
              <div style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", marginTop: 10 }}>
                <div style={{ flex: b.up, background: "#dc2626" }} />
                <div style={{ flex: b.flat, background: "#94a3b8" }} />
                <div style={{ flex: b.down, background: "#16a34a" }} />
              </div>
            </div>
          )}
          {market?.sectors && (
            <Row gutter={32} style={{ marginTop: 16 }}>
              <Col xs={24} md={12}><SectorList title="领涨行业" rows={market.sectors.top} /></Col>
              <Col xs={24} md={12}><SectorList title="领跌行业" rows={market.sectors.bottom} /></Col>
            </Row>
          )}
        </Card>

        <Card
          className="panel-card"
          title={
            <Space>
              告警
              <Tooltip title={connected ? "实时推送已连接" : "实时推送未连接，正在重试"}>
                <Tag color={connected ? "success" : "default"}>{connected ? "实时" : "离线"}</Tag>
              </Tooltip>
              {status && (
                <Text type="secondary" style={{ fontWeight: 400, fontSize: 13 }}>
                  {status.trading ? "盘中盯盘中" : "非交易时段"} · 盯 {status.watch_count} 只（持仓 {status.holdings}）· 每 {status.interval}s
                  {status.last_tick ? ` · 上次检查 ${status.last_tick.slice(11)}` : ""}
                </Text>
              )}
            </Space>
          }
          extra={
            <Space>
              <Segmented size="small" value={range} onChange={(v) => setRange(v as "today" | "all")}
                options={[{ label: "今天", value: "today" }, { label: "全部", value: "all" }]} />
              <Segmented size="small" value={level} onChange={(v) => setLevel(v as "all" | AlertLevel)}
                options={[{ label: "全部级别", value: "all" }, ...(["alert", "warn", "info"] as const).map((k) => ({ label: LEVEL_META[k].label, value: k }))]} />
              <Tooltip title="不论是否开盘，立即按当前行情检查一轮">
                <Button size="small" type="primary" icon={<ThunderboltOutlined />} loading={ticking} onClick={() => void tick()}>
                  立即检查
                </Button>
              </Tooltip>
            </Space>
          }
        >
          {status?.last_error && <Alert type="error" showIcon style={{ marginBottom: 12 }} message={`上次盯盘失败：${status.last_error}`} />}
          <Table<MonitorAlert>
            rowKey="id"
            size="small"
            dataSource={rows}
            pagination={{ pageSize: 20, hideOnSinglePage: true }}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无告警" /> }}
            columns={[
              {
                title: "时间",
                dataIndex: "ts",
                width: 110,
                render: (ts: string, r) => (r.day === today() ? ts.slice(11) : `${ts.slice(5, 10)} ${ts.slice(11, 16)}`),
              },
              {
                title: "级别",
                dataIndex: "level",
                width: 70,
                render: (lv: AlertLevel) => <Tag color={LEVEL_META[lv].color}>{LEVEL_META[lv].label}</Tag>,
              },
              {
                title: "内容",
                render: (_, r) => (
                  <div>
                    <Text strong>{r.title}</Text>
                    {r.message && <Text type="secondary" style={{ marginLeft: 8 }}>{r.message}</Text>}
                    {r.note && (
                      <div style={{ marginTop: 2 }}>
                        <RobotOutlined style={{ color: "#6366f1", marginRight: 6 }} />
                        <Text style={{ color: "#4f46e5" }}>{r.note}</Text>
                      </div>
                    )}
                  </div>
                ),
              },
            ]}
          />
        </Card>
      </Space>
    </Spin>
  );
}
