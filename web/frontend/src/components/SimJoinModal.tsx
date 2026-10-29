import { App as AntApp, Alert, Button, Checkbox, Form, Input, InputNumber, Modal, Select, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { SimAccountBrief } from "../types";

interface Props {
  target: { symbol: string; name: string; strategyLabel: string | null; strategy: string | null; params: Record<string, number> | null } | null;
  onClose: () => void;
  onDone: () => void;
}

/** 把一只股票按它当前的策略加入模拟仓跟单。 */
export default function SimJoinModal({ target, onClose, onDone }: Props) {
  const { message } = AntApp.useApp();
  const [accounts, setAccounts] = useState<SimAccountBrief[]>([]);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<{ account: string; newName: string; cash: number; entry_on_start: boolean }>();

  useEffect(() => {
    if (!target) return;
    api.simAccounts().then((list) => {
      setAccounts(list);
      form.setFieldsValue({ account: list[0]?.id ?? "__new__", newName: "策略验证", cash: 100000, entry_on_start: false });
    });
  }, [target, form]);

  const submit = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      let accountId = values.account;
      if (accountId === "__new__") accountId = (await api.createSimAccount(values.newName, 1_000_000)).id;
      await api.addSlot(accountId, {
        symbol: target!.symbol,
        cash: values.cash,
        strategy: target!.strategy,
        params: target!.params,
        entry_on_start: values.entry_on_start,
      });
      message.success(`${target!.name} 已加入模拟跟单，从下一个交易日开始按信号成交`);
      onDone();
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={`加入模拟仓：${target?.name ?? ""}`} open={!!target} onCancel={onClose} onOk={() => void submit()} confirmLoading={saving} destroyOnClose>
      <Space direction="vertical" style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message={`按「${target?.strategyLabel ?? "体检主策略"}」跟单，策略和参数在加入时冻结；之后改自选股的策略不影响这笔跟单。`}
        />
        <Form form={form} layout="vertical">
          <Form.Item name="account" label="模拟账户">
            <Select
              options={[
                ...accounts.map((a) => ({ value: a.id, label: a.name })),
                { value: "__new__", label: "+ 新建账户（初始 100 万）" },
              ]}
            />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(a, b) => a.account !== b.account}>
            {({ getFieldValue }) =>
              getFieldValue("account") === "__new__" && (
                <Form.Item name="newName" label="新账户名称" rules={[{ required: true }]}>
                  <Input maxLength={30} />
                </Form.Item>
              )
            }
          </Form.Item>
          <Form.Item name="cash" label="分配资金" rules={[{ required: true }]}>
            <InputNumber min={1000} step={10000} style={{ width: "100%" }} addonAfter="元" />
          </Form.Item>
          <Form.Item name="entry_on_start" valuePropName="checked">
            <Checkbox>如果策略当前处于持有状态，次日开盘立即建仓（默认等下一个买入信号）</Checkbox>
          </Form.Item>
        </Form>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          规则：信号次日开盘成交，100 股整数倍，佣金万 2.5（最低 5 元）+ 卖出印花税 0.05%，开盘涨停买不进、跌停卖不出则顺延。
        </Typography.Text>
      </Space>
    </Modal>
  );
}
