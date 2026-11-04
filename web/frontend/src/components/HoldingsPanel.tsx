import {
  App as AntApp,
  Button,
  Card,
  Col,
  DatePicker,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { DownOutlined, ImportOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { cnColor, money, pct, ratio, signed } from "../format";
import type { Holding, HoldingAnalysis, HoldingsAnalysis, Job, Meta, Stock } from "../types";
import HoldingDrawer, { triggerText } from "./HoldingDrawer";
import HoldingImport, { downloadTemplate } from "./HoldingImport";
import StockSelect from "./StockSelect";
import { useCheckupJob } from "../hooks/useCheckupJob";

interface Props {
  meta: Meta;
  stocks: Stock[];
  stocksLoading: boolean;
}

type FormValues = Omit<Holding, "buy_date" | "name"> & { buy_date: Dayjs | null };

export default function HoldingsPanel({ meta, stocks, stocksLoading }: Props) {
  const { message } = AntApp.useApp();
  const [data, setData] = useState<HoldingsAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [importOpen, setImportOpen] = useState(false);
  const [editing, setEditing] = useState<Holding | "new" | null>(null);
  const [detail, setDetail] = useState<HoldingAnalysis | null>(null);
  const [form] = Form.useForm<FormValues>();

  const setJobRef = useRef<(job: Job | null) => void>(() => undefined);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.analysis();
      setData(result);
      if (result.job) setJobRef.current(result.job);
      setDetail((current) => (current ? result.rows.find((r) => r.symbol === current.symbol) ?? null : null));
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setLoading(false);
    }
  }, [message]);
  const checkupJob = useCheckupJob(load);
  const { job, running, setJob } = checkupJob;
  setJobRef.current = setJob;

  useEffect(() => {
    void load();
  }, [load]);

  const startCheckup = checkupJob.start;

  const openEdit = (holding: Holding | "new") => {
    setEditing(holding);
    form.resetFields();
    if (holding !== "new") {
      form.setFieldsValue({ ...holding, buy_date: holding.buy_date ? dayjs(holding.buy_date) : null });
    }
  };

  const save = async () => {
    const values = await form.validateFields();
    try {
      await api.saveHolding({ ...values, buy_date: values.buy_date ? values.buy_date.format("YYYY-MM-DD") : null });
      setEditing(null);
      message.success("已保存");
      await startCheckup(false);
      void load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const remove = async (symbol: string) => {
    try {
      await api.deleteHolding(symbol);
      void load();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const summary = data?.summary;
  const rows = data?.rows ?? [];

  const toolbar = (
    <Space wrap>
      <Button type="primary" icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>
        导入持仓
      </Button>
      <Button icon={<PlusOutlined />} onClick={() => openEdit("new")}>
        新增
      </Button>
      <Dropdown.Button
        disabled={running || !rows.length}
        icon={<DownOutlined />}
        onClick={() => void startCheckup(false)}
        menu={{ items: [{ key: "all", label: "全部重新体检" }], onClick: () => void startCheckup(true) }}
      >
        策略体检
      </Dropdown.Button>
      <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
        刷新
      </Button>
    </Space>
  );

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card className="panel-card">
        <Row gutter={[16, 16]} align="middle">
          <Col flex="auto">{toolbar}</Col>
          {summary?.data_date && (
            <Col>
              <Typography.Text type="secondary">数据截至 {summary.data_date} 收盘</Typography.Text>
            </Col>
          )}
        </Row>
        {checkupJob.progressBar((symbol) => rows.find((r) => r.symbol === symbol)?.name ?? symbol)}
        {summary && summary.count > 0 && (
          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={12} md={5}>
              <Statistic title="总市值" value={money(summary.market_value, 2)} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic
                title="浮动盈亏"
                value={`${signed(summary.pnl)}（${pct(summary.pnl_pct)}）`}
                valueStyle={{ color: cnColor(summary.pnl) }}
              />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="当日盈亏" value={signed(summary.day_pnl)} valueStyle={{ color: cnColor(summary.day_pnl) }} />
            </Col>
            <Col xs={12} md={9}>
              <div className="ant-statistic-title" style={{ marginBottom: 8 }}>
                今日建议
              </div>
              <Space size={4} wrap>
                {Object.entries(summary.advice_counts).map(([code, count]) => {
                  const sample = rows.find((r) => r.advice?.code === code)?.advice;
                  return (
                    <Tag key={code} color={sample?.color}>
                      {sample?.label} {count}
                    </Tag>
                  );
                })}
              </Space>
            </Col>
          </Row>
        )}
      </Card>

      <Card className="panel-card">
        {!loading && rows.length === 0 ? (
          <Empty description="还没有持仓。从券商 App / Excel 复制持仓表格粘贴导入，或下载模板填写。">
            <Space>
              <Button type="primary" onClick={() => setImportOpen(true)}>
                导入持仓
              </Button>
              <Button onClick={downloadTemplate}>下载模板</Button>
            </Space>
          </Empty>
        ) : (
          <Table<HoldingAnalysis>
            rowKey="symbol"
            size="middle"
            loading={loading && !data}
            dataSource={rows}
            pagination={false}
            scroll={{ x: 1250 }}
            onRow={(r) => ({ onClick: () => setDetail(r), style: { cursor: "pointer" } })}
            columns={[
              {
                title: "股票 / 市值",
                fixed: "left",
                width: 130,
                render: (_, r) => (
                  <div>
                    <div style={{ color: cnColor(r.change_pct), fontWeight: 600 }}>{r.name}</div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {r.symbol} · {r.market_value?.toFixed(0) ?? "—"}
                    </Typography.Text>
                  </div>
                ),
              },
              {
                title: "盈亏",
                width: 110,
                sorter: (a, b) => (a.pnl_pct ?? 0) - (b.pnl_pct ?? 0),
                render: (_, r) => (
                  <div style={{ color: cnColor(r.pnl) }}>
                    <div>{signed(r.pnl, 1)}</div>
                    <div>{pct(r.pnl_pct)}</div>
                  </div>
                ),
              },
              {
                title: "当日盈亏",
                width: 100,
                sorter: (a, b) => (a.change_pct ?? 0) - (b.change_pct ?? 0),
                render: (_, r) => (
                  <div style={{ color: cnColor(r.day_pnl) }}>
                    <div>{signed(r.day_pnl, 0)}</div>
                    <div>{pct(r.change_pct)}</div>
                  </div>
                ),
              },
              {
                title: "成本 / 现价",
                width: 100,
                render: (_, r) => (
                  <div>
                    <div style={{ color: "#7c3aed" }}>{r.cost_price}</div>
                    <div style={{ color: cnColor(r.change_pct) }}>{r.close ?? "—"}</div>
                  </div>
                ),
              },
              { title: "股数", dataIndex: "shares", width: 70 },
              {
                title: "今日建议",
                width: 150,
                render: (_, r) => {
                  const checking = checkupJob.rowStatus(r.symbol);
                  if (checking) return checking;
                  return r.error ? (
                    <Tooltip title={r.error}>
                      <Tag color="error">分析失败</Tag>
                    </Tooltip>
                  ) : (
                    r.advice && (
                      <Tooltip title={r.advice.reason}>
                        <Tag color={r.advice.color}>{r.advice.label}</Tag>
                      </Tooltip>
                    )
                  );
                },
              },
              {
                title: "主策略",
                width: 130,
                render: (_, r) =>
                  r.main ? (
                    <div>
                      <div>{r.main.label}</div>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        样本外夏普 {ratio(r.main.oos_sharpe)}
                      </Typography.Text>
                    </div>
                  ) : (
                    "—"
                  ),
              },
              {
                title: "明日触发价",
                width: 220,
                render: (_, r) => <span style={{ fontSize: 12.5 }}>{triggerText(r.main?.triggers)}</span>,
              },
              {
                title: "6 策略共识",
                width: 100,
                render: (_, r) =>
                  r.consensus && (
                    <span>
                      <span style={{ color: cnColor(1) }}>{r.consensus.bull} 多</span> /{" "}
                      <span style={{ color: cnColor(-1) }}>{r.consensus.bear} 空</span>
                    </span>
                  ),
              },
              {
                title: "操作",
                fixed: "right",
                width: 110,
                render: (_, r) => (
                  <Space size={0} onClick={(e) => e.stopPropagation()}>
                    <Button type="link" size="small" onClick={() => openEdit(r)}>
                      编辑
                    </Button>
                    <Popconfirm title={`删除 ${r.name}？`} onConfirm={() => void remove(r.symbol)}>
                      <Button type="link" size="small" danger>
                        删除
                      </Button>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        )}
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
          建议基于日线收盘价和规则策略的历史统计，次日开盘执行；止损/止盈优先于策略信号。仅供研究参考，不构成投资建议。
        </Typography.Paragraph>
      </Card>

      <HoldingImport
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={(next) => {
          setImportOpen(false);
          if (next) setJob(next);
          void load();
        }}
      />

      <Modal
        title={editing === "new" ? "新增持仓" : "编辑持仓"}
        open={editing !== null}
        onCancel={() => setEditing(null)}
        onOk={() => void save()}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="symbol" label="股票" rules={[{ required: true, message: "请选择股票" }]}>
            {editing === "new" ? <StockSelect stocks={stocks} loading={stocksLoading} /> : <Input disabled />}
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="shares" label="股数" rules={[{ required: true }]}>
                <InputNumber min={1} precision={0} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="cost_price" label="成本价" rules={[{ required: true }]}>
                <InputNumber min={0.001} step={0.01} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="stop_loss_pct" label="止损（浮亏 %）">
                <InputNumber min={0.1} max={99} placeholder="不设置" style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="take_profit_pct" label="止盈（浮盈 %）">
                <InputNumber min={0.1} max={99} placeholder="不设置" style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="buy_date" label="买入日期（选填）">
                <DatePicker style={{ width: "100%" }} disabledDate={(d) => d.isAfter(dayjs())} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="strategy" label="主策略">
                <Select
                  allowClear
                  placeholder="自动（按体检结果）"
                  options={meta.strategies.map((s) => ({ value: s.name, label: s.label }))}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="note" label="备注">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      <HoldingDrawer row={detail} onClose={() => setDetail(null)} onRecheck={(symbol) => void startCheckup(true, [symbol])} />
    </Space>
  );
}
