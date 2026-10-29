import { Card, Descriptions, Drawer, Empty, Space, Tag, Typography } from "antd";
import type { StrategyMeta, StrategyNotes } from "../types";

const { Text, Paragraph } = Typography;

interface Props {
  strategies: StrategyMeta[];
  selected?: string[];
  open: boolean;
  onClose: () => void;
}

const ROWS: { key: keyof StrategyNotes; label: string }[] = [
  { key: "logic", label: "核心逻辑" },
  { key: "entry", label: "开仓条件" },
  { key: "exit", label: "平仓条件" },
  { key: "regime", label: "适用行情" },
  { key: "risk", label: "主要风险" },
];

export default function StrategyGuide({ strategies, selected = [], open, onClose }: Props) {
  const ordered = [...strategies].sort(
    (a, b) => Number(selected.includes(b.name)) - Number(selected.includes(a.name)),
  );

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="策略说明"
      width={560}
      rootClassName="strategy-guide-drawer"
    >
      <div className="strategy-guide-intro">
        <Text strong>六个策略，全部只做多</Text>
        <Paragraph type="secondary" style={{ margin: "4px 0 0", fontSize: 12.5 }}>
          信号在收盘确认，下一交易日开盘成交；不包含做空、杠杆和止损。先看适用行情和风险，再看参数。
        </Paragraph>
      </div>

      {ordered.length === 0 ? (
        <Empty description="暂无策略" />
      ) : (
        ordered.map((strategy) => {
          const notes = strategy.notes ?? {};
          const isSelected = selected.includes(strategy.name);
          return (
            <Card
              key={strategy.name}
              size="small"
              className="strategy-guide-card"
              title={
                <Space size={8}>
                  <Text strong>{strategy.label}</Text>
                  {isSelected && <Tag color="blue">当前已选</Tag>}
                </Space>
              }
            >
              <Text type="secondary" className="strategy-guide-summary">
                {strategy.description}
              </Text>
              <Descriptions
                size="small"
                column={1}
                colon={false}
                labelStyle={{ width: 66, color: "#64748b", fontSize: 12 }}
                contentStyle={{ fontSize: 12.5 }}
              >
                {ROWS.map((row) =>
                  notes[row.key] ? (
                    <Descriptions.Item key={row.key} label={row.label}>
                      {notes[row.key]}
                    </Descriptions.Item>
                  ) : null,
                )}
              </Descriptions>
              <div className="strategy-guide-params">
                <Text type="secondary">默认参数：</Text>
                {strategy.params
                  .map((param) => param.label + " " + param.default + "（" + param.min + "–" + param.max + "）")
                  .join(" · ")}
              </div>
            </Card>
          );
        })
      )}

      <Text type="secondary" className="strategy-guide-footnote">
        说明是策略逻辑摘要，不构成投资建议；历史回测不代表未来收益。
      </Text>
    </Drawer>
  );
}
