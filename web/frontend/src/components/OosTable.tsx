import { Alert, Card, Flex, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { OosBlock, OosSegment } from "../types";
import { paramsText, pct, plainPct, ratio, signed } from "../format";

const { Text } = Typography;

interface Props {
  oos: OosBlock;
}

interface SegmentColumn {
  key: string;
  label: string;
  segment: OosSegment;
  primary?: boolean;
}

interface RowData {
  key: string;
  label: string;
  values: Record<string, string>;
}

const ROWS: { key: string; label: string; format: (value: unknown) => string }[] = [
  { key: "Return [%]", label: "总收益", format: (value) => pct(value) },
  { key: "CAGR [%]", label: "年化收益", format: (value) => pct(value) },
  { key: "Sharpe Ratio", label: "夏普比率", format: (value) => ratio(value) },
  { key: "Max. Drawdown [%]", label: "最大回撤", format: (value) => plainPct(value) },
  { key: "# Trades", label: "交易次数", format: (value) => String(value ?? "—") },
  { key: "Win Rate [%]", label: "胜率", format: (value) => plainPct(value) },
];

export default function OosTable({ oos }: Props) {
  const segments: SegmentColumn[] = [
    { key: "train", label: "训练段", segment: oos.train },
    { key: "test", label: "测试段 · 训练参数", segment: oos.test_params, primary: true },
  ];
  if (
    oos.test_default &&
    paramsText(oos.test_default.params) !== paramsText(oos.test_params.params)
  ) {
    segments.push({ key: "default", label: "测试段 · 默认参数", segment: oos.test_default });
  }
  if (oos.test_oracle) {
    segments.push({ key: "oracle", label: "测试段 · 事后最优", segment: oos.test_oracle });
  }

  const columns: ColumnsType<RowData> = [
    {
      title: "指标",
      dataIndex: "label",
      key: "label",
      fixed: "left",
      width: 92,
      render: (value: string) => <Text strong>{value}</Text>,
    },
    ...segments.map((item) => ({
      title: (
        <div>
          <div>{item.label}</div>
          <Text type="secondary" style={{ fontSize: 10.5, fontWeight: 400 }}>
            {paramsText(item.segment.params)}
          </Text>
        </div>
      ),
      dataIndex: ["values", item.key],
      key: item.key,
      width: 150,
      className: item.primary ? "oos-primary" : undefined,
      render: (value: string) => <span style={{ fontVariantNumeric: "tabular-nums" }}>{value}</span>,
    })),
  ];

  const dataSource: RowData[] = ROWS.map((row) => ({
    key: row.key,
    label: row.label,
    values: Object.fromEntries(
      segments.map((item) => [item.key, row.format(item.segment.metrics[row.key])]),
    ),
  }));

  const decay = oos.sharpe_decay;
  const decayText = decay === null ? "—" : signed(decay, 2);

  return (
    <Card
      className="panel-card"
      title="样本外验证"
      extra={
        <Flex gap={6} wrap>
          <Tag color="orange">切分 {oos.split}</Tag>
          <Tag>{oos.mode === "optimize" ? "训练段优化" : "固定参数"}</Tag>
        </Flex>
      }
    >
      <Alert
        type={decay !== null && decay < -0.2 ? "warning" : "info"}
        showIcon
        style={{ marginBottom: 12 }}
        message={`训练 → 测试 夏普衰减 ${decayText}`}
        description={oos.sharpe_decay_note}
      />
      <Table<RowData>
        className="oos-table"
        columns={columns}
        dataSource={dataSource}
        pagination={false}
        size="small"
        scroll={{ x: 620 }}
      />
      <Text type="secondary" style={{ display: "block", fontSize: 11.5, marginTop: 8 }}>
        测试段不参与选参；「事后最优」只作参照，不能用于实盘。
      </Text>
    </Card>
  );
}
