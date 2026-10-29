import {
  App as AntApp,
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { cnColor, money, paramsText, pct, ratio, signed } from "../format";
import type { SimAccountBrief, SimOrder, SimPosition, SimScore, SimSlot, SimState, SimTrade, Stock } from "../types";
import StockSelect from "./StockSelect";

interface Props {
  stocks: Stock[];
  stocksLoading: boolean;
}

const ORDER_STATUS: Record<SimOrder["status"], [string, string]> = {
  pending: ["挂单中", "processing"],
  filled: ["已成交", "success"],
  failed: ["失败", "error"],
  cancelled: ["已撤销", "default"],
};
const SLOT_STATUS: Record<SimSlot["status"], [string, string]> = {
  active: ["跟单中", "processing"],
  stopping: ["停止中（次日清仓）", "warning"],
  stopped: ["已停止", "default"],
  error: ["取数失败", "error"],
};

function EquityCurve({ state }: { state: SimState }) {
  const option = useMemo<EChartsOption>(() => {
    const dates = state.curve.map((p) => p.date);
    const base = state.account.initial_cash;
    const series: EChartsOption["series"] = [
      {
        name: "模拟账户",
        type: "line",
        showSymbol: false,
        data: state.curve.map((p) => Number(((p.equity / base - 1) * 100).toFixed(2))),
        lineStyle: { width: 2, color: "#2563eb" },
        itemStyle: { color: "#2563eb" },
        areaStyle: { color: "rgba(37,99,235,0.08)" },
      },
    ];
    if (state.benchmark) {
      const bench = state.benchmark.series;
      series.push({
        name: state.benchmark.name,
        type: "line",
        showSymbol: false,
        data: dates.map((d) => Number(((bench[d] - 1) * 100).toFixed(2))),
        lineStyle: { width: 1.5, color: "#94a3b8", type: "dashed" },
        itemStyle: { color: "#94a3b8" },
      });
    }
    return {
      animation: false,
      legend: { top: 0 },
      grid: { left: 50, right: 20, top: 30, bottom: 30 },
      tooltip: { trigger: "axis", valueFormatter: (v) => `${v}%` },
      xAxis: { type: "category", data: dates },
      yAxis: { type: "value", axisLabel: { formatter: "{value}%" }, splitLine: { lineStyle: { color: "#eef2f7" } } },
      series,
    };
  }, [state]);
  return <ReactECharts option={option} style={{ height: 280 }} notMerge />;
}

export default function SimPanel({ stocks, stocksLoading }: Props) {
  const { message } = AntApp.useApp();
  const [accounts, setAccounts] = useState<SimAccountBrief[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [state, setState] = useState<SimState | null>(null);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [ordering, setOrdering] = useState<{ symbol?: string; side: "BUY" | "SELL" } | null>(null);
  const [accountForm] = Form.useForm<{ name: string; initial_cash: number }>();
  const [orderForm] = Form.useForm<{ symbol: string; side: "BUY" | "SELL"; shares: number }>();

  const loadAccounts = useCallback(async () => {
    const list = await api.simAccounts();
    setAccounts(list);
    setActive((current) => (current && list.some((a) => a.id === current) ? current : list[0]?.id ?? null));
  }, []);

  const loadState = useCallback(async () => {
    if (!active) return setState(null);
    setLoading(true);
    try {
      setState(await api.simState(active));
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setLoading(false);
    }
  }, [active, message]);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);
  useEffect(() => {
    void loadState();
  }, [loadState]);

  const run = async (action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      message.success(success);
      void loadState();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const createAccount = async () => {
    const v = await accountForm.validateFields();
    try {
      const account = await api.createSimAccount(v.name, v.initial_cash);
      setCreating(false);
      await loadAccounts();
      setActive(account.id);
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const submitOrder = async () => {
    const v = await orderForm.validateFields();
    await run(() => api.placeOrder(active!, v), "已下单，下一交易日开盘按开盘价成交");
    setOrdering(null);
  };

  const s = state?.summary;
  const pendingOrders = state?.orders.filter((o) => o.status === "pending") ?? [];

  if (!accounts.length) {
    return (
      <Card className="panel-card">
        <Empty description="还没有模拟账户。建一个账户，然后在“自选股”里把股票加入模拟跟单，或在这里手动下单。">
          <Button type="primary" onClick={() => { accountForm.setFieldsValue({ name: "策略验证", initial_cash: 1_000_000 }); setCreating(true); }}>
            新建模拟账户
          </Button>
        </Empty>
        <AccountModal open={creating} form={accountForm} onCancel={() => setCreating(false)} onOk={() => void createAccount()} />
      </Card>
    );
  }

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card className="panel-card">
        <Row gutter={[12, 12]} align="middle">
          <Col flex="auto">
            <Space wrap>
              <Select style={{ width: 200 }} value={active} onChange={setActive} options={accounts.map((a) => ({ value: a.id, label: a.name }))} />
              <Button icon={<PlusOutlined />} onClick={() => { accountForm.setFieldsValue({ name: "", initial_cash: 1_000_000 }); setCreating(true); }}>
                新建账户
              </Button>
              <Button type="primary" onClick={() => { orderForm.setFieldsValue({ side: "BUY", shares: 100 }); setOrdering({ side: "BUY" }); }}>
                手动下单
              </Button>
              <Button icon={<ReloadOutlined />} onClick={() => void loadState()} loading={loading}>
                刷新
              </Button>
              <Popconfirm title="删除这个模拟账户？跟单和订单记录都会删除。" onConfirm={() => void run(async () => { await api.deleteSimAccount(active!); await loadAccounts(); }, "已删除")}>
                <Button danger type="text">删除账户</Button>
              </Popconfirm>
            </Space>
          </Col>
          {state && (
            <Col>
              <Typography.Text type="secondary">
                {state.account.created_date} 开始 · 已运行 {s?.days ?? 0} 个交易日{s?.data_date ? ` · 数据截至 ${s.data_date}` : ""}
              </Typography.Text>
            </Col>
          )}
        </Row>
        {s && (
          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={12} md={5}><Statistic title="总资产" value={money(s.equity, 2)} /></Col>
            <Col xs={12} md={5}>
              <Statistic title="累计收益" value={`${signed(s.pnl)}（${pct(s.pnl_pct)}）`} valueStyle={{ color: cnColor(s.pnl) }} />
            </Col>
            <Col xs={12} md={4}><Statistic title="今日盈亏" value={signed(s.day_pnl)} valueStyle={{ color: cnColor(s.day_pnl) }} /></Col>
            <Col xs={12} md={4}><Statistic title="可用现金" value={money(s.cash, 0)} /></Col>
            <Col xs={12} md={3}><Statistic title="持仓市值" value={money(s.market_value, 0)} /></Col>
            <Col xs={12} md={3}><Statistic title="最大回撤" value={pct(s.max_dd_pct)} /></Col>
          </Row>
        )}
      </Card>

      <Spin spinning={loading && !state}>
        {state && (
          <Card className="panel-card">
            {state.curve.length > 1 ? (
              <EquityCurve state={state} />
            ) : (
              <Alert
                type="info"
                showIcon
                message="模拟从创建当天开始往后跑：今天收盘出的信号，下一交易日开盘成交。过几个交易日这里会出现净值曲线和沪深300对比。"
              />
            )}
            <Tabs
              style={{ marginTop: 8 }}
              items={[
                { key: "positions", label: `持仓 ${state.positions.length}`, children: <PositionsTable rows={state.positions} onSell={(p) => { orderForm.setFieldsValue({ symbol: p.symbol, side: "SELL", shares: p.shares }); setOrdering({ symbol: p.symbol, side: "SELL" }); }} /> },
                { key: "slots", label: `策略跟单 ${state.slots.filter((x) => x.status !== "stopped").length}`, children: <SlotsTable rows={state.slots} onStop={(slot) => void run(() => api.stopSlot(active!, slot.id), "已停止跟单")} /> },
                { key: "orders", label: `手动订单${pendingOrders.length ? `（挂单 ${pendingOrders.length}）` : ""}`, children: <OrdersTable rows={state.orders} onCancel={(o) => void run(() => api.cancelOrder(active!, o.id), "已撤单")} /> },
                { key: "trades", label: `成交记录 ${state.trades.length}`, children: <TradesTable rows={state.trades} /> },
                { key: "score", label: "策略成绩单", children: <ScoreTable rows={state.scorecard} /> },
              ]}
            />
          </Card>
        )}
      </Spin>

      <AccountModal open={creating} form={accountForm} onCancel={() => setCreating(false)} onOk={() => void createAccount()} />
      <Modal title="手动下单" open={!!ordering} onCancel={() => setOrdering(null)} onOk={() => void submitOrder()} destroyOnClose>
        <Form form={orderForm} layout="vertical" preserve={false}>
          <Form.Item name="symbol" label="股票" rules={[{ required: true, message: "请选择股票" }]}>
            <StockSelect stocks={stocks} loading={stocksLoading} />
          </Form.Item>
          <Form.Item name="side" label="方向">
            <Radio.Group optionType="button" options={[{ value: "BUY", label: "买入" }, { value: "SELL", label: "卖出" }]} />
          </Form.Item>
          <Form.Item name="shares" label="股数" rules={[{ required: true }]} extra="买入需为 100 的整数倍；下一交易日开盘价成交，T+1 规则下当日买入的股票次日才能卖出">
            <InputNumber min={100} step={100} precision={0} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}

function AccountModal({ open, form, onCancel, onOk }: { open: boolean; form: ReturnType<typeof Form.useForm<{ name: string; initial_cash: number }>>[0]; onCancel: () => void; onOk: () => void }) {
  return (
    <Modal title="新建模拟账户" open={open} onCancel={onCancel} onOk={onOk}>
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="名称" rules={[{ required: true }]}>
          <Input maxLength={30} placeholder="例如：策略验证 / 手动练习" />
        </Form.Item>
        <Form.Item name="initial_cash" label="初始资金" rules={[{ required: true }]}>
          <InputNumber min={10000} step={100000} style={{ width: "100%" }} addonAfter="元" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function PositionsTable({ rows, onSell }: { rows: SimPosition[]; onSell: (p: SimPosition) => void }) {
  return (
    <Table<SimPosition>
      size="small"
      rowKey={(r) => `${r.source}-${r.symbol}`}
      dataSource={rows}
      pagination={false}
      locale={{ emptyText: "暂无持仓" }}
      columns={[
        { title: "股票", render: (_, r) => <span>{r.name} <Typography.Text type="secondary">{r.symbol}</Typography.Text></span> },
        { title: "来源", render: (_, r) => (r.source === "strategy" ? <Tag color="purple">{r.strategy}</Tag> : <Tag>手动</Tag>) },
        { title: "股数", dataIndex: "shares" },
        { title: "成本", dataIndex: "cost" },
        { title: "现价", dataIndex: "close" },
        { title: "市值", render: (_, r) => money(r.market_value, 0) },
        { title: "浮动盈亏", render: (_, r) => <span style={{ color: cnColor(r.pnl) }}>{signed(r.pnl)}（{pct((r.close / r.cost - 1) * 100)}）</span> },
        { title: "", render: (_, r) => r.source === "manual" && <Button size="small" type="link" onClick={() => onSell(r)}>卖出</Button> },
      ]}
    />
  );
}

function SlotsTable({ rows, onStop }: { rows: SimSlot[]; onStop: (slot: SimSlot) => void }) {
  return (
    <Table<SimSlot>
      size="small"
      rowKey="id"
      dataSource={rows}
      pagination={false}
      locale={{ emptyText: "还没有跟单。在“自选股”页点“加入模拟”" }}
      columns={[
        { title: "股票", render: (_, r) => <span>{r.name} <Typography.Text type="secondary">{r.symbol}</Typography.Text></span> },
        { title: "策略", render: (_, r) => <Tooltip title={paramsText(r.params)}>{r.label ?? r.strategy}</Tooltip> },
        { title: "开始", dataIndex: "start_date" },
        { title: "分配资金", render: (_, r) => money(r.cash, 0) },
        { title: "当前价值", render: (_, r) => <span style={{ color: cnColor(r.value - r.cash) }}>{money(r.value, 0)}（{pct((r.value / r.cash - 1) * 100)}）</span> },
        { title: "持股", dataIndex: "shares" },
        {
          title: "状态 / 明日",
          render: (_, r) => (
            <Space size={4} wrap>
              <Tag color={SLOT_STATUS[r.status][1]}>{SLOT_STATUS[r.status][0]}</Tag>
              {r.pending && <Tag color={r.pending === "BUY" ? "red" : "green"}>明日开盘{r.pending === "BUY" ? "买入" : "卖出"}</Tag>}
              {r.notes.length > 0 && (
                <Tooltip title={r.notes.map((n) => `${n.date} ${n.note}`).join("\n")}>
                  <Tag>顺延 {r.notes.length}</Tag>
                </Tooltip>
              )}
              {r.error && <Typography.Text type="danger">{r.error}</Typography.Text>}
            </Space>
          ),
        },
        {
          title: "",
          render: (_, r) =>
            r.status === "active" && (
              <Popconfirm title="停止跟单？有持仓的话下一交易日开盘清仓，资金回到可用现金。" onConfirm={() => onStop(r)}>
                <Button size="small" type="link" danger>停止</Button>
              </Popconfirm>
            ),
        },
      ]}
    />
  );
}

function OrdersTable({ rows, onCancel }: { rows: SimOrder[]; onCancel: (o: SimOrder) => void }) {
  return (
    <Table<SimOrder>
      size="small"
      rowKey="id"
      dataSource={[...rows].reverse()}
      pagination={{ pageSize: 20, hideOnSinglePage: true }}
      locale={{ emptyText: "暂无手动订单" }}
      columns={[
        { title: "下单日", dataIndex: "placed_date" },
        { title: "股票", render: (_, r) => <span>{r.name} <Typography.Text type="secondary">{r.symbol}</Typography.Text></span> },
        { title: "方向", render: (_, r) => <span style={{ color: cnColor(r.side === "BUY" ? 1 : -1) }}>{r.side === "BUY" ? "买入" : "卖出"}</span> },
        { title: "股数", dataIndex: "shares" },
        { title: "状态", render: (_, r) => <Tooltip title={r.reason}><Tag color={ORDER_STATUS[r.status][1]}>{ORDER_STATUS[r.status][0]}</Tag></Tooltip> },
        { title: "成交", render: (_, r) => (r.fill ? `${r.fill.date} @ ${r.fill.price}（费 ${r.fill.fee}）` : r.reason ?? "—") },
        { title: "", render: (_, r) => r.status === "pending" && <Button size="small" type="link" onClick={() => onCancel(r)}>撤单</Button> },
      ]}
    />
  );
}

function TradesTable({ rows }: { rows: SimTrade[] }) {
  return (
    <Table<SimTrade>
      size="small"
      rowKey={(r, i) => `${r.date}-${r.symbol}-${r.side}-${i}`}
      dataSource={rows}
      pagination={{ pageSize: 20, hideOnSinglePage: true }}
      locale={{ emptyText: "还没有成交" }}
      columns={[
        { title: "日期", dataIndex: "date" },
        { title: "股票", render: (_, r) => <span>{r.name} <Typography.Text type="secondary">{r.symbol}</Typography.Text></span> },
        { title: "方向", render: (_, r) => <span style={{ color: cnColor(r.side === "BUY" ? 1 : -1) }}>{r.side === "BUY" ? "买入" : "卖出"}</span> },
        { title: "成交价", dataIndex: "price" },
        { title: "股数", dataIndex: "shares" },
        { title: "费用", dataIndex: "fee" },
        { title: "盈亏", render: (_, r) => (r.pnl === null ? "—" : <span style={{ color: cnColor(r.pnl) }}>{signed(r.pnl)}</span>) },
        { title: "来源", render: (_, r) => (r.source === "strategy" ? <Tag color="purple">{r.strategy}</Tag> : <Tag>手动</Tag>) },
      ]}
    />
  );
}

function ScoreTable({ rows }: { rows: SimScore[] }) {
  return (
    <Table<SimScore>
      size="small"
      rowKey="strategy"
      dataSource={rows}
      pagination={false}
      locale={{ emptyText: "还没有策略跟单" }}
      footer={() => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          统计的是模拟仓里已平仓的跟单交易；“体检夏普”是这些股票在该策略下近 5 年样本外夏普的平均值，用来对比历史表现能否延续到实盘。
        </Typography.Text>
      )}
      columns={[
        { title: "策略", dataIndex: "label" },
        { title: "跟单数", dataIndex: "slots" },
        { title: "已平仓", dataIndex: "closed_trades" },
        { title: "胜率", render: (_, r) => (r.win_rate_pct === null ? "—" : `${r.win_rate_pct}%`) },
        { title: "平均收益", render: (_, r) => <span style={{ color: cnColor(r.avg_return_pct) }}>{pct(r.avg_return_pct)}</span> },
        { title: "盈亏比", render: (_, r) => ratio(r.profit_factor) },
        { title: "累计盈亏", render: (_, r) => <span style={{ color: cnColor(r.pnl) }}>{signed(r.pnl)}</span> },
        { title: "体检夏普", render: (_, r) => ratio(r.checkup_sharpe) },
      ]}
    />
  );
}
