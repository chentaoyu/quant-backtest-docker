import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Col,
  DatePicker,
  Flex,
  Form,
  InputNumber,
  Row,
  Select,
  Space,
  Switch,
  Tooltip,
  Typography,
} from "antd";
import {
  BookOutlined,
  ControlOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type { FormInstance } from "antd";
import { useMemo, useState } from "react";
import type { FormValues, Meta, RangeSpec, Stock } from "../types";
import StockSelect from "./StockSelect";
import StrategyGuide from "./StrategyGuide";

const { Text } = Typography;

interface Props {
  meta: Meta;
  stocks: Stock[];
  stocksLoading: boolean;
  stocksWarning: string | null;
  form: FormInstance<FormValues>;
  running: boolean;
  elapsed: number;
  onSubmit: (values: FormValues) => void;
  onReset: () => void;
}

const EXCHANGE_LABEL: Record<string, string> = { SH: "沪市", SZ: "深市", BJ: "北交所" };

export default function ConfigPanel({
  meta,
  stocks,
  stocksLoading,
  stocksWarning,
  form,
  running,
  elapsed,
  onSubmit,
  onReset,
}: Props) {
  const { message } = AntApp.useApp();
  const [guideOpen, setGuideOpen] = useState(false);
  const strategyName = Form.useWatch("strategy", form) ?? "sma_cross";
  const optimize = Form.useWatch("optimize", form) ?? false;
  const splitEnabled = Form.useWatch("splitEnabled", form) ?? false;
  const source = Form.useWatch("source", form) ?? "auto";
  const symbol = Form.useWatch("symbol", form);
  const start = Form.useWatch("start", form);
  const end = Form.useWatch("end", form);
  const ranges = Form.useWatch("ranges", form) as Record<string, RangeSpec> | undefined;

  const strategy = meta.strategies.find((item) => item.name === strategyName);
  const selectedStock = stocks.find((item) => item.symbol === symbol);
  const cached = meta.symbols.find((item) => item.symbol === symbol);
  const chosenSource = source === "auto" ? meta.auto_source : source;

  const combos = useMemo(() => {
    if (!strategy || !ranges) return 0;
    let total = 1;
    for (const param of strategy.params) {
      const range = ranges[param.name];
      if (
        !range ||
        !Number.isFinite(range.start) ||
        !Number.isFinite(range.stop) ||
        !Number.isFinite(range.step) ||
        range.step <= 0 ||
        range.stop < range.start
      ) {
        return 0;
      }
      total *= Math.floor((range.stop - range.start) / range.step) + 1;
    }
    return total;
  }, [strategy, ranges]);

  return (
    <Card
      className="config-card"
      title={
        <span className="card-title">
          <ControlOutlined /> 回测配置
        </span>
      }
      extra={
        <Tooltip title="恢复默认参数">
          <Button type="text" size="small" icon={<ReloadOutlined />} onClick={onReset} />
        </Tooltip>
      }
    >
      <Form<FormValues>
        form={form}
        layout="vertical"
        requiredMark={false}
        scrollToFirstError
        onFinish={onSubmit}
        onFinishFailed={() => message.warning("请检查表单填写")}
      >
        <div className="section-title">标的与数据</div>

        <Form.Item
          name="symbol"
          label={`股票（${stocks.length ? `${stocks.length} 只` : "加载中"}）`}
          rules={[{ required: true, message: "请选择股票" }]}
        >
          <StockSelect stocks={stocks} loading={stocksLoading} />
        </Form.Item>

        {selectedStock && (
          <div className="stock-meta" style={{ marginTop: -10, marginBottom: 12 }}>
            {selectedStock.name} · {EXCHANGE_LABEL[selectedStock.exchange] ?? selectedStock.exchange}
            {cached
              ? ` · 本地缓存 ${cached.rows} 根（${cached.start} → ${cached.end}）`
              : " · 本地无缓存，首次运行需联网拉取"}
            {cached && !cached.sources.includes(chosenSource) && (
              <Text type="warning"> · 当前源 {chosenSource} 无缓存</Text>
            )}
          </div>
        )}

        {stocksWarning && (
          <Alert
            type="warning"
            showIcon
            message={stocksWarning}
            style={{ marginBottom: 14, fontSize: 12 }}
          />
        )}

        <Form.Item name="source" label="数据源">
          <Select
            options={[
              { value: "auto", label: `自动（当前 ${meta.auto_source}）` },
              { value: "tushare", label: "Tushare Pro" },
              { value: "akshare", label: "AKShare" },
            ]}
          />
        </Form.Item>

        <Row gutter={10}>
          <Col span={12}>
            <Form.Item
              name="start"
              label="开始日期"
              rules={[{ required: true, message: "请选择开始日期" }]}
            >
              <DatePicker
                format="YYYY-MM-DD"
                allowClear={false}
                style={{ width: "100%" }}
                disabledDate={(current) => Boolean(end && current.isAfter(end, "day"))}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="end"
              label="结束日期"
              dependencies={["start"]}
              rules={[
                { required: true, message: "请选择结束日期" },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    const from = getFieldValue("start");
                    if (!value || !from || value.isAfter(from, "day")) return Promise.resolve();
                    return Promise.reject(new Error("需晚于开始日期"));
                  },
                }),
              ]}
            >
              <DatePicker
                format="YYYY-MM-DD"
                allowClear={false}
                style={{ width: "100%" }}
                disabledDate={(current) => Boolean(start && current.isBefore(start, "day"))}
              />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={10}>
          <Col span={14}>
            <Form.Item
              name="cash"
              label="初始资金"
              rules={[{ required: true, message: "请填写初始资金" }]}
            >
              <InputNumber<number>
                min={1000}
                step={10000}
                addonAfter="元"
                style={{ width: "100%" }}
                formatter={(value) =>
                  value === undefined || value === null
                    ? ""
                    : `${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")
                }
                parser={(value) => Number(String(value ?? "").replace(/,/g, ""))}
              />
            </Form.Item>
          </Col>
          <Col span={10}>
            <Form.Item
              name="commissionPct"
              label="单边费率"
              rules={[{ required: true, message: "请填写费率" }]}
            >
              <InputNumber min={0} max={5} step={0.01} addonAfter="%" style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item name="refresh" valuePropName="checked" label="强制刷新行情">
          <Switch checkedChildren="刷新" unCheckedChildren="优先缓存" />
        </Form.Item>

        <div className="section-title" style={{ marginTop: 4 }}>
          策略
        </div>

        <Form.Item name="strategy" label="策略" rules={[{ required: true }]}>
          <Select
            options={meta.strategies.map((item) => ({ value: item.name, label: item.label }))}
          />
        </Form.Item>
        <Flex
          justify="space-between"
          align="flex-start"
          gap={8}
          style={{ marginTop: -10, marginBottom: 12 }}
        >
          <Text type="secondary" className="field-note" style={{ flex: 1 }}>
            {strategy?.description ?? "选择一个策略后查看逻辑、适用行情和风险。"}
          </Text>
          <Button
            type="link"
            size="small"
            icon={<BookOutlined />}
            onClick={() => setGuideOpen(true)}
            style={{ paddingInline: 0, flexShrink: 0 }}
          >
            策略说明
          </Button>
        </Flex>

        <Row gutter={10}>
          {strategy?.params.map((param) => (
            <Col span={12} key={param.name}>
              <Form.Item
                name={["params", param.name]}
                label={param.label}
                rules={[{ required: true, message: "必填" }]}
              >
                <InputNumber
                  min={param.min}
                  max={param.max}
                  step={param.step}
                  style={{ width: "100%" }}
                />
              </Form.Item>
            </Col>
          ))}
        </Row>

        <Form.Item
          name="optimize"
          valuePropName="checked"
          label="参数优化"
          tooltip="在网格上穷举参数，以夏普比率最大选参；组合数上限 5000"
        >
          <Switch checkedChildren="网格优化" unCheckedChildren="固定参数" />
        </Form.Item>

        {optimize && strategy && (
          <div className="range-box">
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
              <Text strong style={{ fontSize: 12 }}>
                优化网格
              </Text>
              <Text type={combos > 5000 ? "danger" : "secondary"} style={{ fontSize: 11.5 }}>
                预计 {combos || "—"} 组
              </Text>
            </div>
            {strategy.params.map((param) => (
              <div className="range-row" key={param.name}>
                <span className="range-label">
                  {param.label}
                  <Text type="secondary" style={{ fontSize: 10.5, marginLeft: 6 }}>
                    起 / 止 / 步
                  </Text>
                </span>
                <Row gutter={6}>
                  {(["start", "stop", "step"] as const).map((key) => (
                    <Col span={8} key={key}>
                      <Form.Item name={["ranges", param.name, key]} noStyle>
                        <InputNumber
                          size="small"
                          min={key === "step" ? 1 : param.min}
                          max={param.max}
                          step={param.step}
                          placeholder={key === "start" ? "起" : key === "stop" ? "止" : "步"}
                          style={{ width: "100%" }}
                        />
                      </Form.Item>
                    </Col>
                  ))}
                </Row>
              </div>
            ))}
            {combos > 5000 && (
              <Text type="danger" style={{ fontSize: 11.5 }}>
                组合数超过 5000，请拉大步长或收窄区间。
              </Text>
            )}
          </div>
        )}

        <Form.Item
          name="splitEnabled"
          valuePropName="checked"
          label="样本外切分"
          tooltip="训练段用于选参，测试段只做验证；图表展示测试段"
        >
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

        {splitEnabled && (
          <Form.Item
            name="split"
            label="切分日期"
            dependencies={["start", "end"]}
            rules={[
              { required: true, message: "请选择切分日期" },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  const from = getFieldValue("start");
                  const to = getFieldValue("end");
                  if (!value || !from || !to) return Promise.resolve();
                  if (value.isAfter(from, "day") && value.isBefore(to, "day")) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error("需位于起止日期之间"));
                },
              }),
            ]}
          >
            <DatePicker
              format="YYYY-MM-DD"
              allowClear={false}
              style={{ width: "100%" }}
              disabledDate={(current) =>
                Boolean(
                  (start && current.isBefore(start, "day")) || (end && current.isAfter(end, "day")),
                )
              }
            />
          </Form.Item>
        )}

        <Space direction="vertical" size={0} style={{ width: "100%", marginTop: 4 }}>
          <Button
            type="primary"
            htmlType="submit"
            block
            size="large"
            loading={running}
            disabled={running}
            icon={running ? undefined : <ThunderboltOutlined />}
          >
            {running ? `回测中… ${elapsed.toFixed(0)}s` : "运行回测"}
          </Button>
          <div className="run-hint">
            首次取数、网格优化可能需要几秒到几十秒；结果会自动保存到运行历史。
          </div>
        </Space>
      </Form>

      <StrategyGuide
        strategies={meta.strategies}
        selected={[strategyName]}
        open={guideOpen}
        onClose={() => setGuideOpen(false)}
      />
    </Card>
  );
}
