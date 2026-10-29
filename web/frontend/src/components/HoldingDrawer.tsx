import { Alert, Button, Descriptions, Drawer, Segmented, Space, Spin, Table, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { cnColor, paramsText, pct, ratio, signed } from "../format";
import type { HoldingAnalysis, KlineResponse, StrategySignal, Triggers } from "../types";
import KlineChart, { type PriceLine } from "./KlineChart";

export function triggerText(t?: Triggers | null): string {
  if (!t) return "—";
  const label = t.action === "SELL" ? "卖出" : "买入";
  if (t.fires_flat) {
    return `收盘在 ${t.below ?? "跌停"} ~ ${t.above ?? "涨停"} 之间都会触发${label}`;
  }
  const parts = [];
  if (t.below !== null) parts.push(`收盘 ≤ ${t.below} 触发${label}`);
  if (t.above !== null) parts.push(`收盘 ≥ ${t.above} 触发${label}`);
  return parts.length ? parts.join("；") : `明日涨跌停范围内不会触发${label}`;
}

function stateText(s: StrategySignal): string {
  if (s.action) return s.action === "BUY" ? "今日买入信号" : "今日卖出信号";
  return `${s.hold ? "持有中" : "空仓"}${s.since ? `（自 ${s.since}）` : ""}`;
}

interface Props {
  row: HoldingAnalysis | null;
  onClose: () => void;
  onRecheck: (symbol: string) => void;
}

const RANGES = [
  { label: "3 月", value: 66 },
  { label: "6 月", value: 130 },
  { label: "1 年", value: 250 },
  { label: "3 年", value: 750 },
];

export default function HoldingDrawer({ row, onClose, onRecheck }: Props) {
  const [kline, setKline] = useState<KlineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visible, setVisible] = useState(130);
  const main = row?.main ?? null;

  useEffect(() => {
    if (!row) return;
    setKline(null);
    setError(null);
    api
      .kline(row.symbol, 1100, main?.name)
      .then(setKline)
      .catch((e: Error) => setError(e.message));
  }, [row?.symbol, main?.name]);

  const lines = useMemo<PriceLine[]>(() => {
    if (!row) return [];
    const result: PriceLine[] = [{ label: "成本", price: row.cost_price, color: "#7c3aed" }];
    const t = main?.triggers;
    if (t && !t.fires_flat) {
      const color = t.action === "SELL" ? "#16a34a" : "#dc2626";
      if (t.below !== null) result.push({ label: `${t.action === "SELL" ? "卖" : "买"}触发`, price: t.below, color });
      if (t.above !== null) result.push({ label: `${t.action === "SELL" ? "卖" : "买"}触发`, price: t.above, color });
    }
    return result;
  }, [row, main]);

  return (
    <Drawer
      width={980}
      open={!!row}
      onClose={onClose}
      destroyOnClose
      title={
        row && (
          <Space>
            <span>{row.name}</span>
            <Typography.Text type="secondary">{row.symbol}</Typography.Text>
            {row.advice && <Tag color={row.advice.color}>{row.advice.label}</Tag>}
          </Space>
        )
      }
      extra={
        row && (
          <Button size="small" onClick={() => onRecheck(row.symbol)}>
            重新体检
          </Button>
        )
      }
    >
      {row && !row.error && (
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          {row.advice && <Alert type="info" showIcon message={row.advice.reason} />}
          <Descriptions size="small" column={4} bordered>
            <Descriptions.Item label="现价">{row.close}</Descriptions.Item>
            <Descriptions.Item label="成本">{row.cost_price}</Descriptions.Item>
            <Descriptions.Item label="浮动盈亏">
              <span style={{ color: cnColor(row.pnl) }}>
                {signed(row.pnl)}（{pct(row.pnl_pct)}）
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="数据日期">{row.data_date}</Descriptions.Item>
            <Descriptions.Item label="主策略">
              {main ? `${main.label}（夏普 ${ratio(main.oos_sharpe)}）` : "—"}
            </Descriptions.Item>
            <Descriptions.Item label="明日触发" span={2}>
              {triggerText(main?.triggers)}
            </Descriptions.Item>
            <Descriptions.Item label="6 策略共识">
              {row.consensus ? `${row.consensus.bull} 多 / ${row.consensus.bear} 空` : "—"}
            </Descriptions.Item>
            {row.since_buy && (
              <>
                <Descriptions.Item label="买入后持有收益">{pct(row.since_buy.hold_return_pct)}</Descriptions.Item>
                <Descriptions.Item label="买入后最大回撤">{pct(row.since_buy.max_dd_pct)}</Descriptions.Item>
                <Descriptions.Item label="若按策略首次卖出" span={2}>
                  {row.since_buy.first_exit
                    ? `${row.since_buy.first_exit.date} 以 ${row.since_buy.first_exit.price} 离场，收益 ${pct(row.since_buy.first_exit.return_pct)}`
                    : "买入后主策略还没有给出卖出信号"}
                </Descriptions.Item>
              </>
            )}
          </Descriptions>

          <div>
            <Space style={{ marginBottom: 8 }}>
              <Segmented size="small" options={RANGES} value={visible} onChange={(v) => setVisible(Number(v))} />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                图上“买/卖”为主策略的历史信号，虚线为成本价与明日触发价
              </Typography.Text>
            </Space>
            {error ? (
              <Alert type="error" message={error} />
            ) : (
              <Spin spinning={!kline}>
                <KlineChart
                  key={visible}
                  bars={kline?.bars ?? []}
                  trades={kline?.signal?.trades}
                  lines={lines}
                  visibleBars={visible}
                />
              </Spin>
            )}
          </div>

          <Table<StrategySignal>
            size="small"
            rowKey="name"
            pagination={false}
            dataSource={row.strategies ?? []}
            title={() => <b>6 策略信号（参数来自体检时最近 3 年的优化结果）</b>}
            rowClassName={(s) => (s.name === main?.name ? "main-strategy-row" : "")}
            columns={[
              {
                title: "策略",
                render: (_, s) => (
                  <Space size={4}>
                    {s.label}
                    {s.name === main?.name && <Tag color="blue">主策略</Tag>}
                  </Space>
                ),
              },
              {
                title: "样本外夏普",
                dataIndex: "oos_sharpe",
                render: (v) => <span style={{ color: cnColor(v) }}>{ratio(v)}</span>,
              },
              {
                title: "状态 / 今日信号",
                render: (_, s) => (
                  <span style={{ color: s.action ? cnColor(s.action === "BUY" ? 1 : -1) : undefined }}>
                    {stateText(s)}
                  </span>
                ),
              },
              { title: "执行后", render: (_, s) => <Tag color={s.hold_after ? "red" : "green"}>{s.hold_after ? "多" : "空"}</Tag> },
              { title: "参数", render: (_, s) => <Typography.Text type="secondary">{paramsText(s.params)}</Typography.Text> },
            ]}
          />
          {row.checkup && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              体检时间 {row.checkup.checked_at.replace("T", " ")}
              {row.checkup.stale && "（已超过 30 天，建议重新体检）"}；样本外夏普来自近 5 年滚动验证（训练 3 年 / 测试 1 年）。
              结果只作研究参考，不构成投资建议。
            </Typography.Text>
          )}
        </Space>
      )}
      {row?.error && <Alert type="error" showIcon message="分析失败" description={row.error} />}
    </Drawer>
  );
}
