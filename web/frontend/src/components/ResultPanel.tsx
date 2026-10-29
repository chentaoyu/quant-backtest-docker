import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Flex,
  Row,
  Statistic,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { ExportOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { useState } from "react";
import type { Metrics, OosBlock, RunResult, StrategyMeta } from "../types";
import { money, num, pct, plainPct, ratio, toneColor } from "../format";
import EquityChart from "./EquityChart";
import OosTable from "./OosTable";
import TradesTable from "./TradesTable";

const { Text, Title } = Typography;

const METRIC_LABELS: Record<string, string> = {
  Start: "开始日期",
  End: "结束日期",
  Duration: "数据区间",
  "Exposure Time [%]": "持仓时间",
  "Equity Final [$]": "期末权益",
  "Equity Peak [$]": "权益峰值",
  "Commissions [$]": "手续费",
  "Return [%]": "总收益",
  "Buy & Hold Return [%]": "买入持有",
  "Return (Ann.) [%]": "年化收益",
  "Volatility (Ann.) [%]": "年化波动",
  "CAGR [%]": "复合年化",
  "Sharpe Ratio": "夏普比率",
  "Sortino Ratio": "索提诺比率",
  "Calmar Ratio": "卡玛比率",
  "Alpha [%]": "阿尔法",
  Beta: "贝塔",
  "Max. Drawdown [%]": "最大回撤",
  "Avg. Drawdown [%]": "平均回撤",
  "Max. Drawdown Duration": "最长回撤",
  "Avg. Drawdown Duration": "平均回撤",
  "# Trades": "交易次数",
  "Win Rate [%]": "胜率",
  "Best Trade [%]": "最佳交易",
  "Worst Trade [%]": "最差交易",
  "Avg. Trade [%]": "平均交易",
  "Max. Trade Duration": "最长持有",
  "Avg. Trade Duration": "平均持有",
  "Profit Factor": "盈亏比",
  "Expectancy [%]": "期望收益",
  SQN: "SQN",
  "Kelly Criterion": "凯利值",
};

const GROUPS: { key: string; label: string; keys: string[] }[] = [
  {
    key: "core",
    label: "收益与风险",
    keys: [
      "Start",
      "End",
      "Duration",
      "Exposure Time [%]",
      "Equity Final [$]",
      "Equity Peak [$]",
      "Commissions [$]",
      "Return [%]",
      "Buy & Hold Return [%]",
      "Return (Ann.) [%]",
      "Volatility (Ann.) [%]",
      "CAGR [%]",
    ],
  },
  {
    key: "risk",
    label: "回撤与相对指标",
    keys: [
      "Sharpe Ratio",
      "Sortino Ratio",
      "Calmar Ratio",
      "Alpha [%]",
      "Beta",
      "Max. Drawdown [%]",
      "Avg. Drawdown [%]",
      "Max. Drawdown Duration",
      "Avg. Drawdown Duration",
    ],
  },
  {
    key: "trade",
    label: "交易统计",
    keys: [
      "# Trades",
      "Win Rate [%]",
      "Best Trade [%]",
      "Worst Trade [%]",
      "Avg. Trade [%]",
      "Max. Trade Duration",
      "Avg. Trade Duration",
      "Profit Factor",
      "Expectancy [%]",
      "SQN",
      "Kelly Criterion",
    ],
  },
];

function formatMetric(key: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (key.includes("[%]")) {
    const n = num(value);
    return n === null ? String(value) : `${n.toFixed(2)}%`;
  }
  if (key.includes("[$]")) return money(value, 0);
  if (key === "# Trades") return String(value);
  if (key === "Start" || key === "End") return String(value).slice(0, 10);
  if (
    ["Sharpe Ratio", "Sortino Ratio", "Calmar Ratio", "Beta", "Profit Factor", "SQN", "Kelly Criterion"].includes(
      key,
    )
  ) {
    return ratio(value);
  }
  return String(value);
}

function MetricDetails({ metrics }: { metrics: Metrics }) {
  const known = new Set(GROUPS.flatMap((group) => group.keys));
  const extraKeys = Object.keys(metrics).filter((key) => !known.has(key));
  const items = GROUPS.map((group) => ({
    key: group.key,
    label: group.label,
    children: (
      <Descriptions
        size="small"
        column={{ xs: 1, sm: 1, md: 2 }}
        colon={false}
        labelStyle={{ color: "#64748b", width: 120 }}
      >
        {group.keys
          .filter((key) => key in metrics)
          .map((key) => (
            <Descriptions.Item key={key} label={METRIC_LABELS[key] ?? key}>
              <span style={{ fontVariantNumeric: "tabular-nums" }}>{formatMetric(key, metrics[key])}</span>
            </Descriptions.Item>
          ))}
      </Descriptions>
    ),
  }));

  if (extraKeys.length) {
    items.push({
      key: "extra",
      label: "其他",
      children: (
        <Descriptions size="small" column={{ xs: 1, sm: 1, md: 2 }} colon={false}>
          {extraKeys.map((key) => (
            <Descriptions.Item key={key} label={METRIC_LABELS[key] ?? key}>
              {formatMetric(key, metrics[key])}
            </Descriptions.Item>
          ))}
        </Descriptions>
      ),
    });
  }

  return (
    <Card className="panel-card" title="全部指标">
      <Collapse ghost items={items} defaultActiveKey={["core"]} />
    </Card>
  );
}

interface Props {
  result: RunResult;
  stockName: string;
  strategies: StrategyMeta[];
}

export default function ResultPanel({ result, stockName, strategies }: Props) {
  const [tab, setTab] = useState("chart");
  const metrics = result.metrics;
  const strategyLabel =
    strategies.find((item) => item.name === result.config.strategy)?.label ?? result.config.strategy;

  const returnPct = metrics["Return [%]"];
  const annual = metrics["CAGR [%]"];
  const sharpe = metrics["Sharpe Ratio"];
  const drawdown = metrics["Max. Drawdown [%]"];
  const trades = metrics["# Trades"];
  const winRate = metrics["Win Rate [%]"];

  const sourceColor = result.data.source === "tushare" ? "geekblue" : "blue";

  return (
    <div>
      <Flex className="result-head" justify="space-between" align="flex-start" wrap gap={12}>
        <div>
          <Flex align="center" gap={8} wrap>
            <Title level={4} style={{ margin: 0 }}>
              {stockName || result.config.symbol}
            </Title>
            <Text code>{result.config.symbol}</Text>
          </Flex>
          <div className="result-sub">
            {strategyLabel} · {result.data.start} → {result.data.end} · {result.data.rows} 根 ·{" "}
            {dayjs(result.created_at).format("MM-DD HH:mm")} · {result.duration_sec.toFixed(2)}s
          </div>
          <Flex gap={6} wrap style={{ marginTop: 8 }}>
            <Tag color={sourceColor}>{result.data.source}</Tag>
            <Tag color={result.config.split ? "orange" : "green"}>
              {result.config.split ? "样本外" : "全样本"}
            </Tag>
            <Tag>{result.config.optimize ? "网格优化" : "固定参数"}</Tag>
            <Tag>{result.data.cached ? "缓存" : "联网"}</Tag>
            {result.config.split && <Tag>{result.config.split} 切分</Tag>}
          </Flex>
        </div>
        <Button icon={<ExportOutlined />} href={result.report_url} target="_blank" rel="noreferrer">
          完整报告
        </Button>
      </Flex>

      {result.warnings.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="数据提示"
          description={
            <ul style={{ margin: 0, paddingInlineStart: 18 }}>
              {result.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          }
        />
      )}

      <Row gutter={[10, 10]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8} xl={8}>
          <Card size="small" className="kpi-card">
            <Statistic
              title="总收益"
              value={pct(returnPct)}
              valueStyle={{ color: toneColor(returnPct) }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} xl={8}>
          <Card size="small" className="kpi-card">
            <Statistic
              title="年化收益"
              value={pct(annual)}
              valueStyle={{ color: toneColor(annual) }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} xl={8}>
          <Card size="small" className="kpi-card">
            <Statistic
              title="夏普比率"
              value={ratio(sharpe)}
              valueStyle={{ color: toneColor(sharpe) }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} xl={8}>
          <Card size="small" className="kpi-card">
            <Statistic
              title="最大回撤"
              value={plainPct(drawdown)}
              valueStyle={{ color: "#b91c1c" }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} xl={8}>
          <Card size="small" className="kpi-card">
            <Statistic title="交易次数" value={String(trades ?? "—")} />
          </Card>
        </Col>
        <Col xs={12} sm={8} xl={8}>
          <Card size="small" className="kpi-card">
            <Statistic title="胜率" value={plainPct(winRate)} />
          </Card>
        </Col>
      </Row>

      <Card
        className="panel-card"
        title="净值与回撤"
        extra={
          <Text type="secondary" style={{ fontSize: 11.5 }}>
            初始资金 {money(result.config.cash)}
          </Text>
        }
      >
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            {
              key: "chart",
              label: "净值 / 回撤",
              children: (
                <>
                  <EquityChart data={result.equity} />
                  <p className="chart-note">悬停查看每日净值与回撤；滚轮可缩放时间轴。</p>
                </>
              ),
            },
            {
              key: "bokeh",
              label: "Bokeh 交互图",
              children:
                tab === "bokeh" ? (
                  <>
                    <iframe
                      className="bokeh-frame"
                      src={result.report_url}
                      title="Bokeh 回测图表"
                      loading="lazy"
                    />
                    <p className="chart-note">
                      Bokeh 脚本从 cdn.bokeh.org 加载，首次打开需要联网；离线时看「净值 / 回撤」。
                    </p>
                  </>
                ) : null,
            },
          ]}
        />
      </Card>

      {result.oos && <OosTable oos={result.oos as OosBlock} />}
      <MetricDetails metrics={metrics} />
      <TradesTable
        trades={result.trades}
        cash={result.config.cash}
        commission={result.config.commission}
      />
    </div>
  );
}
