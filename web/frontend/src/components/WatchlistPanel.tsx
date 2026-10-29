import {
  App as AntApp,
  Alert,
  Button,
  Card,
  Col,
  Drawer,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { DownOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { cnColor, paramsText, pct, ratio } from "../format";
import { useCheckupJob } from "../hooks/useCheckupJob";
import type { KlineResponse, Meta, WatchRow, WatchlistResponse } from "../types";
import { triggerText } from "./HoldingDrawer";
import KlineChart, { type PriceLine } from "./KlineChart";
import SimJoinModal from "./SimJoinModal";

interface Props {
  meta: Meta;
}

const SOURCE_TEXT = { auto: "自动 · 体检参数", checkup: "体检参数", default: "默认参数", manual: "手动参数" };

function signalTag(row: WatchRow) {
  const s = row.signal;
  if (!s) return <Typography.Text type="secondary">—</Typography.Text>;
  if (s.action) {
    return <Tag color={s.action === "BUY" ? "red" : "green"}>{s.action === "BUY" ? "今日买入信号" : "今日卖出信号"}</Tag>;
  }
  return (
    <span>
      <Tag color={s.hold ? "processing" : "default"}>{s.hold ? "持有中" : "空仓"}</Tag>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {s.since ? `自 ${s.since}` : ""}
      </Typography.Text>
    </span>
  );
}

export default function WatchlistPanel({ meta }: Props) {
  const { message } = AntApp.useApp();
  const [data, setData] = useState<WatchlistResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [group, setGroup] = useState("全部");
  const [onlySignal, setOnlySignal] = useState(false);
  const [adding, setAdding] = useState(false);
  const [addText, setAddText] = useState("");
  const [addGroup, setAddGroup] = useState("");
  const [editing, setEditing] = useState<WatchRow | null>(null);
  const [detail, setDetail] = useState<WatchRow | null>(null);
  const [joining, setJoining] = useState<WatchRow | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.watchlist();
      setData(result);
      setDetail((current) => (current ? result.rows.find((r) => r.symbol === current.symbol) ?? null : null));
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setLoading(false);
    }
  }, [message]);
  const checkupJob = useCheckupJob(load);
  const { setJob } = checkupJob;

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (data?.job) setJob(data.job);
  }, [data?.job, setJob]);

  const rows = useMemo(
    () =>
      (data?.rows ?? []).filter(
        (r) => (group === "全部" || r.group === group) && (!onlySignal || r.signal?.action),
      ),
    [data, group, onlySignal],
  );

  const add = async () => {
    try {
      const result = await api.addWatch(addText, addGroup || undefined);
      const parts = [`新增 ${result.added.length} 只`];
      if (result.skipped.length) parts.push(`已存在 ${result.skipped.length} 只`);
      if (result.invalid.length) parts.push(`代码不存在：${result.invalid.join("、")}`);
      message.info(parts.join("，"));
      setAdding(false);
      setAddText("");
      if (result.job) setJob(result.job);
      void load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const remove = async (symbol: string) => {
    await api.deleteWatch(symbol).catch((e: Error) => message.error(e.message));
    void load();
  };

  const nameOf = (symbol: string) => data?.rows.find((r) => r.symbol === symbol)?.name ?? symbol;

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card className="panel-card">
        <Row gutter={[12, 12]} align="middle">
          <Col flex="auto">
            <Space wrap>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setAdding(true)}>
                添加自选
              </Button>
              <Dropdown.Button
                disabled={checkupJob.running || !data?.rows.length}
                icon={<DownOutlined />}
                onClick={() => void checkupJob.start(false)}
                menu={{ items: [{ key: "all", label: "全部重新体检" }], onClick: () => void checkupJob.start(true) }}
              >
                策略体检
              </Dropdown.Button>
              <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
                刷新
              </Button>
              <Space size={6}>
                <Switch size="small" checked={onlySignal} onChange={setOnlySignal} />
                <span>只看今日有信号{data ? `（${data.signal_count}）` : ""}</span>
              </Space>
            </Space>
          </Col>
          {data?.rows[0]?.data_date && (
            <Col>
              <Typography.Text type="secondary">数据截至 {data.rows[0].data_date} 收盘</Typography.Text>
            </Col>
          )}
        </Row>
        {checkupJob.progressBar(nameOf)}
      </Card>

      <Card className="panel-card">
        {!loading && !data?.rows.length ? (
          <Empty description="还没有自选股。粘贴股票代码（可一次多个）添加，系统会自动做策略体检。">
            <Button type="primary" onClick={() => setAdding(true)}>
              添加自选
            </Button>
          </Empty>
        ) : (
          <>
            {(data?.groups.length ?? 0) > 1 && (
              <Segmented
                style={{ marginBottom: 12 }}
                value={group}
                onChange={(v) => setGroup(String(v))}
                options={["全部", ...(data?.groups ?? [])]}
              />
            )}
            <Table<WatchRow>
              rowKey="symbol"
              size="middle"
              loading={loading && !data}
              dataSource={rows}
              pagination={false}
              scroll={{ x: 1250 }}
              onRow={(r) => ({ onClick: () => setDetail(r), style: { cursor: "pointer" } })}
              columns={[
                {
                  title: "股票",
                  fixed: "left",
                  width: 120,
                  render: (_, r) => (
                    <div>
                      <div style={{ fontWeight: 600 }}>{r.name}</div>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {r.symbol} · {r.group}
                      </Typography.Text>
                    </div>
                  ),
                },
                {
                  title: "现价 / 涨跌",
                  width: 100,
                  sorter: (a, b) => (a.change_pct ?? 0) - (b.change_pct ?? 0),
                  render: (_, r) => (
                    <div style={{ color: cnColor(r.change_pct) }}>
                      <div>{r.close ?? "—"}</div>
                      <div>{pct(r.change_pct)}</div>
                    </div>
                  ),
                },
                {
                  title: "策略",
                  width: 150,
                  render: (_, r) =>
                    r.used ? (
                      <div>
                        <div>{r.used.label}</div>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {SOURCE_TEXT[r.used.source]} · 夏普 {ratio(r.used.oos_sharpe)}
                        </Typography.Text>
                      </div>
                    ) : (
                      <Typography.Text type="secondary">{r.checkup ? "无有效策略" : "待体检"}</Typography.Text>
                    ),
                },
                {
                  title: "状态 / 今日信号",
                  width: 170,
                  render: (_, r) => checkupJob.rowStatus(r.symbol) ?? (r.error ? <Tooltip title={r.error}><Tag color="error">分析失败</Tag></Tooltip> : signalTag(r)),
                },
                {
                  title: "明日触发价",
                  width: 210,
                  render: (_, r) => <span style={{ fontSize: 12.5 }}>{triggerText(r.signal?.triggers)}</span>,
                },
                {
                  title: "最近信号",
                  width: 130,
                  render: (_, r) => {
                    const e = r.signal?.last_event;
                    return e ? (
                      <span style={{ fontSize: 12.5 }}>
                        <span style={{ color: cnColor(e.action === "BUY" ? 1 : -1) }}>{e.action === "BUY" ? "买" : "卖"}</span>{" "}
                        {e.date} @ {e.price}
                      </span>
                    ) : (
                      "—"
                    );
                  },
                },
                {
                  title: "模拟",
                  width: 110,
                  render: (_, r) =>
                    r.sim.length ? (
                      <Tooltip title={r.sim.map((s) => s.account).join("、")}>
                        <Tag color="purple">跟单中 {r.sim.length}</Tag>
                      </Tooltip>
                    ) : (
                      <Button
                        size="small"
                        disabled={!r.used}
                        onClick={(e) => {
                          e.stopPropagation();
                          setJoining(r);
                        }}
                      >
                        加入模拟
                      </Button>
                    ),
                },
                {
                  title: "操作",
                  fixed: "right",
                  width: 120,
                  render: (_, r) => (
                    <Space size={0} onClick={(e) => e.stopPropagation()}>
                      <Button type="link" size="small" onClick={() => setEditing(r)}>
                        设置策略
                      </Button>
                      <Popconfirm title={`移除 ${r.name}？`} onConfirm={() => void remove(r.symbol)}>
                        <Button type="link" size="small" danger>
                          移除
                        </Button>
                      </Popconfirm>
                    </Space>
                  ),
                },
              ]}
            />
          </>
        )}
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
          信号按日线收盘价计算，次日开盘执行。仅供研究参考，不构成投资建议。
        </Typography.Paragraph>
      </Card>

      <Modal title="添加自选" open={adding} onCancel={() => setAdding(false)} onOk={() => void add()} okButtonProps={{ disabled: !addText.trim() }}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Input.TextArea rows={5} value={addText} onChange={(e) => setAddText(e.target.value)} placeholder="粘贴股票代码，空格/逗号/换行分隔，例如：600519 000858 300750" />
          <Input value={addGroup} onChange={(e) => setAddGroup(e.target.value)} placeholder={`分组（选填，默认“默认”）`} maxLength={20} />
        </Space>
      </Modal>

      <StrategyModal meta={meta} row={editing} onClose={() => setEditing(null)} onSaved={(job) => { setEditing(null); if (job) setJob(job); void load(); }} />
      <WatchDrawer row={detail} meta={meta} onClose={() => setDetail(null)} onEdit={setEditing} />
      <SimJoinModal
        target={joining && { symbol: joining.symbol, name: joining.name, strategyLabel: joining.used?.label ?? null, strategy: joining.strategy, params: joining.params }}
        onClose={() => setJoining(null)}
        onDone={() => {
          setJoining(null);
          void load();
        }}
      />
    </Space>
  );
}

function StrategyModal({ meta, row, onClose, onSaved }: { meta: Meta; row: WatchRow | null; onClose: () => void; onSaved: (job: import("../types").Job | null) => void }) {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<{ strategy: string; mode: "checkup" | "manual"; params: Record<string, number>; group: string; note: string }>();
  const strategy = Form.useWatch("strategy", form);
  const mode = Form.useWatch("mode", form);
  const spec = meta.strategies.find((s) => s.name === strategy);

  useEffect(() => {
    if (!row) return;
    form.setFieldsValue({
      strategy: row.strategy ?? "__auto__",
      mode: row.params ? "manual" : "checkup",
      params: row.params ?? row.used?.params ?? {},
      group: row.group,
      note: row.note,
    });
  }, [row, form]);

  const save = async () => {
    const v = await form.validateFields();
    const auto = v.strategy === "__auto__";
    try {
      const result = await api.saveWatch({
        symbol: row!.symbol,
        group: v.group,
        note: v.note,
        strategy: auto ? null : v.strategy,
        params: !auto && v.mode === "manual" ? v.params : null,
      });
      message.success("已保存");
      onSaved(result.job);
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <Modal title={`策略设置：${row?.name ?? ""}`} open={!!row} onCancel={onClose} onOk={() => void save()} width={560} destroyOnClose>
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item name="strategy" label="策略" extra="括号里是这只股票近 5 年滚动验证的样本外夏普，越高越稳">
          <Select
            options={[
              { value: "__auto__", label: `自动（体检主策略${row?.checkup?.best ? `：${meta.strategies.find((s) => s.name === row.checkup?.best)?.label}` : ""}）` },
              ...meta.strategies.map((s) => ({
                value: s.name,
                label: `${s.label}（${ratio(row?.sharpes?.[s.name])}）`,
              })),
            ]}
            onChange={(name: string) => {
              const s = meta.strategies.find((x) => x.name === name);
              if (s) form.setFieldValue("params", { ...s.defaults });
            }}
          />
        </Form.Item>
        {strategy && strategy !== "__auto__" && (
          <>
            <Form.Item name="mode" label="参数">
              <Radio.Group
                options={[
                  { value: "checkup", label: "用体检优化的参数（没体检则用默认）" },
                  { value: "manual", label: "手动设置" },
                ]}
              />
            </Form.Item>
            {mode === "manual" && spec && (
              <Row gutter={12}>
                {spec.params.map((p) => (
                  <Col span={8} key={p.name}>
                    <Form.Item name={["params", p.name]} label={p.label} rules={[{ required: true }]}>
                      <InputNumber min={p.min} max={p.max} step={p.step} style={{ width: "100%" }} />
                    </Form.Item>
                  </Col>
                ))}
              </Row>
            )}
          </>
        )}
        <Row gutter={12}>
          <Col span={10}>
            <Form.Item name="group" label="分组">
              <Input maxLength={20} />
            </Form.Item>
          </Col>
          <Col span={14}>
            <Form.Item name="note" label="备注">
              <Input maxLength={200} />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  );
}

function WatchDrawer({ row, meta, onClose, onEdit }: { row: WatchRow | null; meta: Meta; onClose: () => void; onEdit: (row: WatchRow) => void }) {
  const labelOf = (name: string) => meta.strategies.find((s) => s.name === name)?.label ?? name;
  const [kline, setKline] = useState<KlineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const used = row?.used;

  useEffect(() => {
    if (!row || !used) return;
    setKline(null);
    setError(null);
    api.klineWith(row.symbol, 1100, used.name, used.params).then(setKline).catch((e: Error) => setError(e.message));
  }, [row?.symbol, used?.name, JSON.stringify(used?.params)]); // eslint-disable-line react-hooks/exhaustive-deps

  const lines = useMemo<PriceLine[]>(() => {
    const t = row?.signal?.triggers;
    if (!t || t.fires_flat) return [];
    const color = t.action === "SELL" ? "#16a34a" : "#dc2626";
    const label = `${t.action === "SELL" ? "卖" : "买"}触发`;
    return [t.below, t.above].filter((p): p is number => p !== null).map((price) => ({ label, price, color }));
  }, [row]);

  return (
    <Drawer
      width={980}
      open={!!row}
      onClose={onClose}
      destroyOnClose
      title={row && <Space>{row.name}<Typography.Text type="secondary">{row.symbol}</Typography.Text></Space>}
      extra={row && <Button size="small" onClick={() => onEdit(row)}>设置策略</Button>}
    >
      {row && (
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          {used ? (
            <Alert
              type="info"
              showIcon
              message={`${used.label}（${paramsText(used.params)}）· ${SOURCE_TEXT[used.source]}`}
              description={`今日：${row.signal?.action ? (row.signal.action === "BUY" ? "买入信号" : "卖出信号") : row.signal?.hold ? "持有中" : "空仓"}；明日：${triggerText(row.signal?.triggers)}`}
            />
          ) : (
            <Alert type="warning" showIcon message="还没有可用策略：等体检完成，或点右上角手动指定策略" />
          )}
          {used &&
            (error ? (
              <Alert type="error" message={error} />
            ) : (
              <Spin spinning={!kline}>
                <KlineChart bars={kline?.bars ?? []} trades={kline?.signal?.trades} lines={lines} visibleBars={130} />
              </Spin>
            ))}
          {row.sharpes && Object.keys(row.sharpes).length > 0 && (
            <Table
              size="small"
              rowKey="name"
              pagination={false}
              title={() => <b>各策略近 5 年样本外夏普（体检结果）</b>}
              dataSource={Object.entries(row.sharpes).map(([name, sharpe]) => ({ name, sharpe }))}
              columns={[
                { title: "策略", dataIndex: "name", render: (name: string) => <Space>{labelOf(name)}{name === used?.name && <Tag color="blue">当前</Tag>}</Space> },
                { title: "样本外夏普", dataIndex: "sharpe", render: (v) => <span style={{ color: cnColor(v) }}>{ratio(v)}</span> },
              ]}
            />
          )}
        </Space>
      )}
    </Drawer>
  );
}
