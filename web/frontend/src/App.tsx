import {
  App as AntApp,
  Button,
  Card,
  Col,
  Empty,
  Flex,
  Layout,
  Result,
  Row,
  Space,
  Spin,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { Form } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import ConfigPanel from "./components/ConfigPanel";
import HistoryPanel from "./components/HistoryPanel";
import HoldingsPanel from "./components/HoldingsPanel";
import ResultPanel from "./components/ResultPanel";
import type {
  BacktestPayload,
  FormValues,
  Meta,
  RunResult,
  RunSummary,
  Stock,
} from "./types";

const { Text } = Typography;

type View = "single" | "holdings";

function fallbackStocks(meta: Meta): Stock[] {
  return meta.symbols.map((item) => ({
    symbol: item.symbol,
    name: item.symbol,
    exchange: item.symbol.startsWith("6") ? "SH" : "SZ",
  }));
}

export default function App() {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<FormValues>();

  const [meta, setMeta] = useState<Meta | null>(null);
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [stocksLoading, setStocksLoading] = useState(true);
  const [stocksWarning, setStocksWarning] = useState<string | null>(null);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [loadingRun, setLoadingRun] = useState(false);
  const [activeRun, setActiveRun] = useState<string | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [booted, setBooted] = useState(false);
  const [view, setView] = useState<View>("single");

  const initForm = useCallback(
    (data: Meta) => {
      const strategy =
        data.strategies.find((item) => item.name === "sma_cross") ?? data.strategies[0];
      const symbol =
        data.symbols.find((item) => item.symbol === "600519")?.symbol ??
        data.symbols[0]?.symbol ??
        "600519";
      const start = dayjs(data.defaults.start);
      const end = dayjs(data.defaults.end);
      const span = Math.max(end.diff(start, "day"), 2);
      const split = start.add(Math.floor(span * 0.65), "day");

      form.setFieldsValue({
        symbol,
        source: "auto",
        start,
        end,
        cash: data.defaults.cash,
        commissionPct: Number((data.defaults.commission * 100).toFixed(4)),
        strategy: strategy?.name ?? "sma_cross",
        params: strategy ? { ...strategy.defaults } : {},
        optimize: false,
        splitEnabled: false,
        split,
        ranges: strategy ? JSON.parse(JSON.stringify(strategy.default_ranges)) : {},
        refresh: false,
      });
    },
    [form],
  );

  useEffect(() => {
    let cancelled = false;
    setBootError(null);
    setBooted(false);

    api
      .meta()
      .then((data) => {
        if (cancelled) return;
        setMeta(data);
        initForm(data);
        setBooted(true);

        setStocksLoading(true);
        api
          .stocks()
          .then((response) => {
            if (cancelled) return;
            setStocks(response.stocks);
            setStocksWarning(response.warning);
          })
          .catch((error: unknown) => {
            if (cancelled) return;
            setStocks(fallbackStocks(data));
            setStocksWarning(
              error instanceof Error
                ? `股票列表加载失败，先使用本地缓存标的：${error.message}`
                : "股票列表加载失败，先使用本地缓存标的",
            );
          })
          .finally(() => {
            if (!cancelled) setStocksLoading(false);
          });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setBootError(error instanceof Error ? error.message : "后端连接失败");
      });

    return () => {
      cancelled = true;
    };
  }, [initForm, retry]);

  const loadHistory = useCallback(
    async (silent = false) => {
      setHistoryLoading(true);
      try {
        const runs = await api.runs(30);
        setHistory(runs);
      } catch (error) {
        if (!silent) {
          message.error(error instanceof Error ? error.message : "读取运行历史失败");
        }
      } finally {
        setHistoryLoading(false);
      }
    },
    [message],
  );

  useEffect(() => {
    void loadHistory(true);
  }, [loadHistory]);

  const openRun = useCallback(
    async (runId: string) => {
      setLoadingRun(true);
      try {
        const data = await api.run(runId);
        setResult(data);
        setActiveRun(runId);
        window.history.replaceState(null, "", `#run=${runId}`);
        document.getElementById("result-anchor")?.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (error) {
        message.error(error instanceof Error ? error.message : "读取回测结果失败");
      } finally {
        setLoadingRun(false);
      }
    },
    [message],
  );

  const openedHash = useRef(false);
  useEffect(() => {
    if (openedHash.current) return;
    const match = window.location.hash.match(/^#run=(.+)$/);
    if (match) {
      openedHash.current = true;
      void openRun(decodeURIComponent(match[1]));
    }
  }, [openRun]);

  const strategyName = Form.useWatch("strategy", form);
  const previousStrategy = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!meta || !strategyName) return;
    if (previousStrategy.current === undefined) {
      previousStrategy.current = strategyName;
      return;
    }
    if (previousStrategy.current === strategyName) return;
    previousStrategy.current = strategyName;
    const strategy = meta.strategies.find((item) => item.name === strategyName);
    if (!strategy) return;
    form.setFieldsValue({
      params: { ...strategy.defaults },
      ranges: JSON.parse(JSON.stringify(strategy.default_ranges)),
    });
  }, [strategyName, meta, form]);

  const handleReset = useCallback(() => {
    if (!meta) return;
    initForm(meta);
    previousStrategy.current = undefined;
    message.info("已恢复默认配置");
  }, [initForm, message, meta]);

  const handleSubmit = useCallback(
    async (values: FormValues) => {
      if (!values.start.isBefore(values.end, "day")) {
        message.error("结束日期需晚于开始日期");
        return;
      }
      if (
        values.splitEnabled &&
        (!values.split ||
          !values.split.isAfter(values.start, "day") ||
          !values.split.isBefore(values.end, "day"))
      ) {
        message.error("切分日期需位于起止日期之间");
        return;
      }

      const strategyMeta = meta?.strategies.find((item) => item.name === values.strategy);
      const params = strategyMeta
        ? Object.fromEntries(
            strategyMeta.params.map((param) => [
              param.name,
              Number(values.params?.[param.name] ?? param.default),
            ]),
          )
        : values.params ?? {};
      const ranges = strategyMeta
        ? Object.fromEntries(
            strategyMeta.params.map((param) => [
              param.name,
              values.ranges?.[param.name] ?? strategyMeta.default_ranges[param.name],
            ]),
          )
        : values.ranges ?? {};

      const payload: BacktestPayload = {
        symbol: values.symbol,
        source: values.source,
        start: values.start.format("YYYYMMDD"),
        end: values.end.format("YYYYMMDD"),
        cash: values.cash,
        commission: values.commissionPct / 100,
        strategy: values.strategy,
        optimize: values.optimize,
        split: values.splitEnabled && values.split ? values.split.format("YYYYMMDD") : null,
        params,
        ranges: values.optimize ? ranges : {},
        refresh: values.refresh,
      };

      setRunning(true);
      setElapsed(0);
      const started = Date.now();
      const timer = window.setInterval(() => {
        setElapsed((Date.now() - started) / 1000);
      }, 200);

      try {
        const data = await api.backtest(payload);
        setResult(data);
        setActiveRun(data.run_id);
        window.history.replaceState(null, "", `#run=${data.run_id}`);
        message.success(`回测完成，用时 ${data.duration_sec.toFixed(2)}s`);
        void loadHistory(true);
        document.getElementById("result-anchor")?.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (error) {
        message.error(error instanceof Error ? error.message : "回测失败");
      } finally {
        window.clearInterval(timer);
        setRunning(false);
      }
    },
    [loadHistory, message, meta],
  );

  const stockName =
    stocks.find((item) => item.symbol === result?.config.symbol)?.name ??
    meta?.symbols.find((item) => item.symbol === result?.config.symbol)?.symbol ??
    "";

  return (
    <Layout>
      <Layout.Header className="app-header">
        <div className="header-inner">
          <div className="brand">
            <div className="brand-logo">Q</div>
            <div>
              <div className="brand-title">量化回测台</div>
              <div className="brand-sub">A 股日线 · 6 策略 · 持仓建议</div>
            </div>
          </div>
          <Space size={6} wrap>
            {meta && <Tag color="blue">数据源 {meta.auto_source}</Tag>}
            {meta && (
              <Tooltip
                title={
                  meta.tushare_token
                    ? "服务进程已读取到 TUSHARE_TOKEN"
                    : "服务进程没有读到 TUSHARE_TOKEN；.zshrc 只对交互式 shell 生效，建议放到项目 .env，或用 scripts/start_web.sh 启动"
                }
              >
                <Tag color={meta.tushare_token ? "green" : "default"}>
                  Tushare {meta.tushare_token ? "已连接" : "未配置"}
                </Tag>
              </Tooltip>
            )}
            <Tag>本地</Tag>
          </Space>
        </div>
      </Layout.Header>

      <Layout.Content>
        <div className="page">
          {bootError && !meta ? (
            <Result
              status="error"
              title="后端连接失败"
              subTitle={bootError}
              extra={
                <Button type="primary" onClick={() => setRetry((value) => value + 1)}>
                  重试
                </Button>
              }
            />
          ) : (
            <>
              <div className="view-switch">
                <Tabs
                  activeKey={view}
                  onChange={(key) => setView(key as View)}
                  items={[
                    { key: "single", label: "单标的回测" },
                    { key: "holdings", label: "我的持仓" },
                  ]}
                />
              </div>

              {view === "holdings" && meta ? (
                <HoldingsPanel meta={meta} stocks={stocks} stocksLoading={stocksLoading} />
              ) : (
            <Row gutter={[16, 16]} align="top">
              <Col xs={24} lg={8} xl={6}>
                {meta && booted ? (
                  <ConfigPanel
                    meta={meta}
                    stocks={stocks}
                    stocksLoading={stocksLoading}
                    stocksWarning={stocksWarning}
                    form={form}
                    running={running}
                    elapsed={elapsed}
                    onSubmit={handleSubmit}
                    onReset={handleReset}
                  />
                ) : (
                  <Card className="config-card" loading />
                )}
              </Col>

              <Col xs={24} lg={16} xl={13}>
                <div id="result-anchor" className="result-wrap">
                  <Spin spinning={loadingRun}>
                    {result ? (
                      <ResultPanel
                        result={result}
                        stockName={stockName}
                        strategies={meta?.strategies ?? []}
                      />
                    ) : (
                      <Card className="empty-card">
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={
                            <Space direction="vertical" size={4}>
                              <Text strong style={{ fontSize: 15 }}>
                                配置左侧参数，运行第一次回测
                              </Text>
                              <Text type="secondary">
                                选股票 → 选日期 → 选策略 → 运行，结果会自动进入右侧历史
                              </Text>
                            </Space>
                          }
                        >
                          <Flex gap={6} wrap justify="center">
                            <Tag>净值 / 回撤</Tag>
                            <Tag>样本外验证</Tag>
                            <Tag>逐笔交易</Tag>
                            <Tag>Bokeh 报告</Tag>
                          </Flex>
                        </Empty>
                      </Card>
                    )}
                  </Spin>
                </div>
              </Col>

              <Col xs={24} xl={5}>
                <HistoryPanel
                  runs={history}
                  stocks={stocks}
                  strategies={meta?.strategies ?? []}
                  activeRun={activeRun}
                  loading={historyLoading}
                  onOpen={(runId) => void openRun(runId)}
                  onRefresh={() => void loadHistory(false)}
                />
              </Col>
            </Row>
              )}
            </>
          )}
        </div>
      </Layout.Content>
    </Layout>
  );
}
