import {
  App as AntApp,
  Alert,
  Button,
  Checkbox,
  Col,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Radio,
  Row,
  Segmented,
  Select,
  Space,
  Switch,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { loadNotifyPrefs, saveNotifyPrefs, type NotifyPrefs } from "../hooks/useAlertStream";
import type { AgentSettings, AgentStatus, LlmModel, ModelTestResult } from "../types";

const { Text } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
}

// 后端存比例（0–1），页面按百分比编辑
const PCT_FIELDS = ["breadth_warn", "move_warn", "move_alert"] as const;

interface FormValues {
  llm: AgentSettings["llm"] & { api_key?: string };
  monitor: Omit<AgentSettings["monitor"], "disabled_rules"> & { enabled_rules: string[] };
  notify: NotifyPrefs;
}

function toForm(s: AgentSettings): FormValues {
  const monitor = { ...s.monitor, enabled_rules: Object.keys(s.rules).filter((r) => !s.monitor.disabled_rules.includes(r)) };
  for (const f of PCT_FIELDS) monitor[f] = Math.round(s.monitor[f] * 100);
  return { llm: { ...s.llm, api_key: "" }, monitor, notify: loadNotifyPrefs() };
}

function modelLabel(m: LlmModel) {
  return (
    <Space size={6}>
      <span>{m.name}</span>
      {m.params && <Text type="secondary" style={{ fontSize: 12 }}>{m.params}</Text>}
      {m.quant && <Text type="secondary" style={{ fontSize: 12 }}>{m.quant}</Text>}
      {m.size_gb !== undefined && <Text type="secondary" style={{ fontSize: 12 }}>{m.size_gb} GB</Text>}
      {m.loaded && <Tag color="green" style={{ marginInlineEnd: 0 }}>已加载</Tag>}
    </Space>
  );
}

export default function AgentSettingsDrawer({ open, onClose }: Props) {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<FormValues>();
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [models, setModels] = useState<LlmModel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, ModelTestResult | string>>({});

  const load = useCallback(async () => {
    try {
      const s = await api.agentSettings();
      setSettings(s);
      form.setFieldsValue(toForm(s));
      setError(null);
      api.agentStatus().then(setStatus).catch(() => setStatus(null));
      api.llmModels().then(setModels).catch(() => setModels([]));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Agent 服务不可用");
    }
  }, [form]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const save = async () => {
    const v = await form.validateFields();
    const { enabled_rules, ...monitor } = v.monitor;
    for (const f of PCT_FIELDS) monitor[f] = monitor[f] / 100;
    saveNotifyPrefs(v.notify);
    setSaving(true);
    try {
      const s = await api.saveAgentSettings({
        llm: v.llm,
        monitor: { ...monitor, disabled_rules: Object.keys(settings!.rules).filter((r) => !enabled_rules.includes(r)) },
      });
      setSettings(s);
      form.setFieldsValue(toForm(s));
      message.success("已保存，立即生效");
      api.agentStatus().then(setStatus).catch(() => {});
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    const s = await api.resetAgentSettings();
    setSettings(s);
    form.setFieldsValue(toForm(s));
    message.success("已恢复为 .env 默认值");
  };

  const test = async (field: "main" | "fast") => {
    const model = form.getFieldValue(["llm", field]) as string;
    setTesting(field);
    try {
      const r = await api.testModel(model);
      setTests((t) => ({ ...t, [field]: r }));
    } catch (e) {
      setTests((t) => ({ ...t, [field]: e instanceof Error ? e.message : "测试失败" }));
    } finally {
      setTesting(null);
      api.llmModels().then(setModels).catch(() => {});
    }
  };

  const modelField = (field: "main" | "fast", label: string, extra: string) => {
    const result = tests[field];
    const current = form.getFieldValue(["llm", field]) as string | undefined;
    const options = models.some((m) => m.name === current) || !current ? models : [{ name: current }, ...models];
    return (
      <Form.Item label={label} extra={extra} required>
        <Space.Compact style={{ width: "100%" }}>
          <Form.Item name={["llm", field]} noStyle rules={[{ required: true, message: "请选择模型" }]}>
            <Select showSearch placeholder="选择模型" options={options.map((m) => ({ value: m.name, label: modelLabel(m) }))} />
          </Form.Item>
          <Button loading={testing === field} onClick={() => void test(field)}>测试</Button>
        </Space.Compact>
        {result && (
          <div style={{ marginTop: 6, fontSize: 12 }}>
            {typeof result === "string" ? (
              <Text type="danger">{result}</Text>
            ) : (
              <Text type="secondary">
                {result.elapsed_sec}s · {result.tokens_per_sec ?? "—"} tok/s（首次含加载时间）· “{result.reply.slice(0, 40)}”
              </Text>
            )}
          </div>
        )}
      </Form.Item>
    );
  };

  const pctInput = (min: number, max: number) => <InputNumber min={min} max={max} addonAfter="%" style={{ width: "100%" }} />;

  return (
    <Drawer
      title="Agent 设置"
      width={560}
      open={open}
      onClose={onClose}
      destroyOnClose={false}
      footer={
        <Space style={{ display: "flex", justifyContent: "space-between" }}>
          <Popconfirm title="恢复所有页面设置为 .env 默认值？" onConfirm={() => void reset()}>
            <Button danger disabled={!settings}>恢复默认</Button>
          </Popconfirm>
          <Space>
            <Button onClick={onClose}>关闭</Button>
            <Button type="primary" loading={saving} disabled={!settings} onClick={() => void save()}>保存</Button>
          </Space>
        </Space>
      }
    >
      {error ? (
        <Alert type="warning" showIcon message="Agent 服务不可用" description={error} action={<Button onClick={() => void load()}>重试</Button>} />
      ) : (
        <Form form={form} layout="vertical" requiredMark={false}>
          <Tabs
            items={[
              {
                key: "llm",
                label: "模型",
                forceRender: true,
                children: (
                  <>
                    {status && (
                      <Alert
                        style={{ marginBottom: 16 }}
                        showIcon
                        type={status.llm.ok && !status.llm.missing?.length ? "success" : "warning"}
                        message={
                          !status.llm.ok
                            ? `连不上模型服务：${status.llm.error}`
                            : status.llm.missing?.length
                              ? `模型服务已连接，但缺少模型：${status.llm.missing.join("、")}（ollama pull 拉取）`
                              : `模型服务已连接 · ${models.length} 个可用模型`
                        }
                      />
                    )}
                    <Form.Item name={["llm", "base_url"]} label="接口地址" extra="OpenAI 兼容接口；容器内访问宿主机 Ollama 用 http://host.docker.internal:11434/v1"
                      rules={[{ required: true, type: "url", message: "请输入 http(s) 地址" }]}>
                      <Input />
                    </Form.Item>
                    <Form.Item name={["llm", "api_key"]} label="API Key">
                      <Input.Password placeholder={settings?.llm.api_key_set ? "已设置，留空不修改" : "本地 Ollama 无需填写"} autoComplete="new-password" />
                    </Form.Item>
                    {modelField("main", "主模型", "对话、研究、告警解读；建议 MoE 模型（如 35b-a3b），速度快")}
                    {modelField("fast", "快模型", "高频轻量任务；小模型容易脑补，重要场景用主模型")}
                    <Row gutter={16}>
                      <Col span={14}>
                        <Form.Item name={["llm", "reasoning"]} label="思考模式" extra="none 最快；开启后推理更充分但慢数倍">
                          <Segmented options={["none", "low", "medium", "high"]} />
                        </Form.Item>
                      </Col>
                      <Col span={10}>
                        <Form.Item name={["llm", "timeout"]} label="超时">
                          <InputNumber min={10} max={1800} addonAfter="秒" style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                    </Row>
                  </>
                ),
              },
              {
                key: "monitor",
                label: "盯盘",
                forceRender: true,
                children: (
                  <>
                    <Row gutter={16}>
                      <Col span={8}>
                        <Form.Item name={["monitor", "enabled"]} label="自动盯盘" valuePropName="checked" extra="交易时段自动检查">
                          <Switch />
                        </Form.Item>
                      </Col>
                      <Col span={16}>
                        <Form.Item name={["monitor", "interval"]} label="检查间隔">
                          <InputNumber min={15} max={3600} addonAfter="秒" style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                      <Col span={8}>
                        <Form.Item name={["monitor", "llm_note"]} label="AI 解读" valuePropName="checked" extra="注意及以上个股告警">
                          <Switch />
                        </Form.Item>
                      </Col>
                      <Col span={16}>
                        <Form.Item name={["monitor", "note_model"]} label="解读模型">
                          <Radio.Group options={[{ label: "主模型（推荐）", value: "main" }, { label: "快模型", value: "fast" }]} />
                        </Form.Item>
                      </Col>
                    </Row>

                    <Divider orientation="left" plain>个股阈值（按涨跌停幅度的比例，自动适配主板/创业板/ST）</Divider>
                    <Row gutter={16}>
                      <Col span={12}>
                        <Form.Item name={["monitor", "move_warn"]} label="注意" extra="主板 50% ≈ 涨跌 5%">{pctInput(5, 100)}</Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name={["monitor", "move_alert"]} label="告警" extra="主板 80% ≈ 涨跌 8%">{pctInput(5, 100)}</Form.Item>
                      </Col>
                    </Row>

                    <Divider orientation="left" plain>市场阈值</Divider>
                    <Row gutter={16}>
                      <Col span={8}>
                        <Form.Item name={["monitor", "index_warn"]} label="指数跌幅·注意">
                          <InputNumber max={0} step={0.5} addonAfter="%" style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                      <Col span={8}>
                        <Form.Item name={["monitor", "index_alert"]} label="指数跌幅·告警">
                          <InputNumber max={0} step={0.5} addonAfter="%" style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                      <Col span={8}>
                        <Form.Item name={["monitor", "index_up"]} label="指数涨幅·提示">
                          <InputNumber min={0} step={0.5} addonAfter="%" style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name={["monitor", "breadth_warn"]} label="普跌：下跌家数占比">{pctInput(50, 100)}</Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name={["monitor", "limit_down_alert"]} label="跌停潮：跌停家数">
                          <InputNumber min={1} addonAfter="家" style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                    </Row>

                    <Divider orientation="left" plain>启用的规则</Divider>
                    <Form.Item name={["monitor", "enabled_rules"]}>
                      <Checkbox.Group style={{ width: "100%" }}>
                        <Row gutter={[0, 8]}>
                          {Object.entries(settings?.rules ?? {}).map(([key, label]) => (
                            <Col span={8} key={key}><Checkbox value={key}>{label}</Checkbox></Col>
                          ))}
                        </Row>
                      </Checkbox.Group>
                    </Form.Item>
                  </>
                ),
              },
              {
                key: "notify",
                label: "通知",
                forceRender: true,
                children: (
                  <>
                    <Alert type="info" showIcon style={{ marginBottom: 16 }} message="通知偏好只对当前浏览器生效" />
                    <Form.Item name={["notify", "levels"]} label="弹窗提醒的级别" extra="未勾选的级别仍会记录在「盯盘」告警列表里">
                      <Checkbox.Group options={[{ label: "告警", value: "alert" }, { label: "注意", value: "warn" }, { label: "提示", value: "info" }]} />
                    </Form.Item>
                    <Form.Item name={["notify", "sticky"]} label="「告警」弹窗需手动关闭" valuePropName="checked" extra="关闭后 8 秒自动消失">
                      <Switch />
                    </Form.Item>
                  </>
                ),
              },
            ]}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            模型与盯盘设置保存在服务端（data/agent/settings.json），优先于 .env；「恢复默认」回到 .env 的值。
          </Text>
        </Form>
      )}
    </Drawer>
  );
}
