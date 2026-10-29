import { Flex, Select, Typography } from "antd";
import { useMemo } from "react";
import type { Stock } from "../types";

type Props = {
  stocks: Stock[];
  loading: boolean;
  id?: string;
  /** 这些代码显示为“已添加”并禁用 */
  disabledSymbols?: string[];
} & (
  | { multiple?: false; value?: string; onChange?: (value: string) => void }
  | { multiple: true; value?: string[]; onChange?: (value: string[]) => void }
);

interface StockOption {
  value: string;
  label: string;
  name: string;
  exchange: string;
  search: string;
  disabled: boolean;
}

export default function StockSelect({ stocks, loading, id, value, onChange, multiple, disabledSymbols }: Props) {
  const options = useMemo<StockOption[]>(() => {
    const disabled = new Set(disabledSymbols ?? []);
    return stocks.map((stock) => ({
      value: stock.symbol,
      label: `${stock.symbol} ${stock.name}`,
      name: stock.name,
      exchange: stock.exchange,
      search: `${stock.symbol}${stock.name}`,
      disabled: disabled.has(stock.symbol),
    }));
  }, [stocks, disabledSymbols]);

  return (
    <Select
      id={id}
      showSearch
      allowClear={!!multiple}
      mode={multiple ? "multiple" : undefined}
      maxTagCount={multiple ? "responsive" : undefined}
      value={value}
      onChange={onChange as (value: string | string[]) => void}
      options={options}
      loading={loading}
      placeholder="输入代码或名称搜索，如 600519 / 贵州茅台"
      optionFilterProp="label"
      filterOption={(input, option) =>
        String((option as StockOption | undefined)?.search ?? "")
          .toLowerCase()
          .includes(input.trim().toLowerCase())
      }
      optionRender={(option) => {
        const data = option.data as StockOption;
        return (
          <Flex justify="space-between" align="center" gap={12}>
            <span>{data.name}</span>
            <Typography.Text type="secondary" style={{ fontSize: 11.5 }}>
              {data.disabled ? "已添加 · " : ""}
              {data.value} · {data.exchange}
            </Typography.Text>
          </Flex>
        );
      }}
      notFoundContent={loading ? "股票列表加载中…" : "没有匹配的股票"}
      style={{ width: "100%" }}
    />
  );
}
