import { Card, Empty, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { Trade } from "../types";
import { durationText, money } from "../format";

const { Text } = Typography;

interface Props {
  trades: Trade[];
  cash: number;
  commission: number;
}

export default function TradesTable({ trades, cash, commission }: Props) {
  const columns: ColumnsType<Trade> = [
    { title: "买入", dataIndex: "entry", key: "entry", width: 100 },
    { title: "卖出", dataIndex: "exit", key: "exit", width: 100 },
    {
      title: "数量",
      dataIndex: "size",
      key: "size",
      width: 90,
      align: "right",
      render: (value: number) => value.toLocaleString("zh-CN", { maximumFractionDigits: 0 }),
    },
    {
      title: "买入价",
      dataIndex: "entry_price",
      key: "entry_price",
      width: 100,
      align: "right",
      render: (value: number) => money(value, 2),
    },
    {
      title: "卖出价",
      dataIndex: "exit_price",
      key: "exit_price",
      width: 100,
      align: "right",
      render: (value: number) => money(value, 2),
    },
    {
      title: "盈亏",
      dataIndex: "pnl",
      key: "pnl",
      width: 110,
      align: "right",
      render: (value: number) => (
        <span className={value >= 0 ? "trade-pos" : "trade-neg"}>
          {value >= 0 ? "+" : ""}
          {money(value)}
        </span>
      ),
    },
    {
      title: "收益率",
      dataIndex: "return_pct",
      key: "return_pct",
      width: 92,
      align: "right",
      render: (value: number) => (
        <Tag color={value >= 0 ? "green" : "red"} style={{ marginInlineEnd: 0 }}>
          {value >= 0 ? "+" : ""}
          {value.toFixed(2)}%
        </Tag>
      ),
    },
    {
      title: "持有",
      dataIndex: "duration",
      key: "duration",
      width: 80,
      align: "right",
      render: (value: string) => durationText(value),
    },
  ];

  return (
    <Card
      className="panel-card"
      title={`交易明细（${trades.length} 笔）`}
      extra={
        <Text type="secondary" style={{ fontSize: 11.5 }}>
          {money(cash)} 初始资金 · 单边 {(commission * 100).toFixed(3)}%
        </Text>
      }
    >
      {trades.length ? (
        <Table<Trade>
          columns={columns}
          dataSource={trades}
          rowKey={(row) => `${row.entry}-${row.exit}-${row.size}`}
          size="small"
          pagination={{ pageSize: 8, showSizeChanger: false, showTotal: (total) => `共 ${total} 笔` }}
          scroll={{ x: 820 }}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该区间没有产生交易" />
      )}
    </Card>
  );
}
