import { Alert, Button, Modal, Radio, Space, Table, Tag, Typography, Upload, App as AntApp, Input } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { useState } from "react";
import { api } from "../api";
import type { ImportRow, Job } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  onImported: (job: Job | null) => void;
}

export const TEMPLATE_HEADER = "代码,股数,成本价,买入日期,止损%,止盈%,备注";

export function downloadTemplate() {
  const blob = new Blob([`\uFEFF${TEMPLATE_HEADER}\n`], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "持仓导入模板.csv";
  link.click();
  URL.revokeObjectURL(link.href);
}

export default function HoldingImport({ open, onClose, onImported }: Props) {
  const { message } = AntApp.useApp();
  const [text, setText] = useState("");
  const [rows, setRows] = useState<ImportRow[] | null>(null);
  const [mode, setMode] = useState<"append" | "replace">("append");
  const [loading, setLoading] = useState(false);
  const valid = rows?.filter((r) => r.ok).length ?? 0;

  const preview = async (content = text) => {
    setLoading(true);
    try {
      setRows((await api.previewImport(content)).rows);
    } catch (error) {
      setRows(null);
      message.error((error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const commit = async () => {
    setLoading(true);
    try {
      const result = await api.commitImport(text, mode);
      message.success(`已导入，当前共 ${result.holdings.length} 只持仓`);
      setText("");
      setRows(null);
      onImported(result.job);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="导入持仓"
      open={open}
      onCancel={onClose}
      width={820}
      destroyOnClose
      footer={
        <Space>
          <Radio.Group value={mode} onChange={(e) => setMode(e.target.value)} optionType="button" size="small">
            <Radio.Button value="append">追加（同股合并）</Radio.Button>
            <Radio.Button value="replace">覆盖全部持仓</Radio.Button>
          </Radio.Group>
          <Button onClick={() => void preview()} loading={loading} disabled={!text.trim()}>
            预览
          </Button>
          <Button type="primary" onClick={() => void commit()} loading={loading} disabled={!valid}>
            确认导入 {valid} 条
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" style={{ width: "100%" }} size={10}>
        <Typography.Text type="secondary">
          从券商 App 或 Excel 复制持仓表格直接粘贴，能识别“证券代码 / 股票余额 / 参考成本价”等常见表头；
          没有表头时按 <Typography.Text code>代码,股数,成本价[,买入日期]</Typography.Text> 的顺序。
          Excel 文件请复制单元格粘贴，或另存为 CSV 上传。
        </Typography.Text>
        <Input.TextArea
          rows={7}
          value={text}
          placeholder={`${TEMPLATE_HEADER}\n...`}
          onChange={(e) => {
            setText(e.target.value);
            setRows(null);
          }}
        />
        <Space>
          <Upload
            accept=".csv,.txt,.tsv"
            showUploadList={false}
            beforeUpload={(file) => {
              void file.text().then((content) => {
                setText(content);
                void preview(content);
              });
              return false;
            }}
          >
            <Button icon={<UploadOutlined />}>上传 CSV</Button>
          </Upload>
          <Button type="link" onClick={downloadTemplate}>
            下载模板
          </Button>
        </Space>
        {mode === "replace" && <Alert type="warning" showIcon message="覆盖模式会删除不在本次导入里的持仓" />}
        {rows && (
          <Table<ImportRow>
            size="small"
            rowKey="line"
            dataSource={rows}
            pagination={false}
            scroll={{ y: 260 }}
            columns={[
              { title: "行", dataIndex: "line", width: 50 },
              { title: "代码", render: (_, r) => r.item?.symbol ?? r.raw.symbol, width: 80 },
              { title: "名称", render: (_, r) => r.item?.name ?? r.raw.name ?? "—", width: 100 },
              { title: "股数", render: (_, r) => r.item?.shares ?? r.raw.shares, width: 80 },
              { title: "成本价", render: (_, r) => r.item?.cost_price ?? r.raw.cost_price, width: 90 },
              { title: "买入日期", render: (_, r) => r.item?.buy_date ?? "—", width: 110 },
              {
                title: "状态",
                render: (_, r) =>
                  r.ok ? (
                    <Tag color={r.merged ? "blue" : "green"}>{r.merged ? "已合并多行" : "可导入"}</Tag>
                  ) : (
                    <Typography.Text type="danger">{r.error}</Typography.Text>
                  ),
              },
            ]}
          />
        )}
      </Space>
    </Modal>
  );
}
