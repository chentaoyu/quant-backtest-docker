import { Button, Card, Empty, Flex, List, Tag, Typography } from "antd";
import { HistoryOutlined, ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { useMemo } from "react";
import type { RunSummary, Stock, StrategyMeta } from "../types";
import { pct, toneColor } from "../format";

const { Text } = Typography;

interface Props {
  runs: RunSummary[];
  stocks: Stock[];
  strategies: StrategyMeta[];
  activeRun: string | null;
  loading: boolean;
  onOpen: (runId: string) => void;
  onRefresh: () => void;
}

export default function HistoryPanel({
  runs,
  stocks,
  strategies,
  activeRun,
  loading,
  onOpen,
  onRefresh,
}: Props) {
  const names = useMemo(() => {
    const map: Record<string, string> = {};
    for (const stock of stocks) map[stock.symbol] = stock.name;
    return map;
  }, [stocks]);

  const strategyLabels = useMemo(() => {
    const map: Record<string, string> = {};
    for (const strategy of strategies) map[strategy.name] = strategy.label;
    return map;
  }, [strategies]);

  return (
    <Card
      className="history-card"
      title={
        <span className="card-title">
          <HistoryOutlined /> 运行历史
        </span>
      }
      extra={
        <Button
          type="text"
          size="small"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={onRefresh}
        />
      }
    >
      <List<RunSummary>
        dataSource={runs}
        loading={loading}
        locale={{
          emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有运行记录" />,
        }}
        renderItem={(item) => (
          <List.Item
            className={`history-item${activeRun === item.run_id ? " active" : ""}`}
            onClick={() => onOpen(item.run_id)}
          >
            <div style={{ width: "100%", minWidth: 0 }}>
              <Flex justify="space-between" align="center" gap={8}>
                <span className="history-name" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                  {names[item.symbol] ?? item.symbol}
                  <Text type="secondary" style={{ fontWeight: 400, fontSize: 11, marginLeft: 6 }}>
                    {item.symbol}
                  </Text>
                </span>
                <Tag
                  color={item.return_pct !== null && item.return_pct >= 0 ? "green" : "red"}
                  style={{ marginInlineEnd: 0, color: toneColor(item.return_pct) }}
                >
                  {pct(item.return_pct)}
                </Tag>
              </Flex>
              <div className="history-meta">
                {strategyLabels[item.strategy] ?? item.strategy} · {item.source} ·{" "}
                {item.split ? "样本外" : "全样本"} · {dayjs(item.created_at).format("MM-DD HH:mm")}
              </div>
            </div>
          </List.Item>
        )}
      />
    </Card>
  );
}
