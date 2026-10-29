import type { ThemeConfig } from "antd";

export const themeConfig: ThemeConfig = {
  token: {
    colorPrimary: "#2563eb",
    colorInfo: "#2563eb",
    colorSuccess: "#15803d",
    colorWarning: "#d97706",
    colorError: "#b91c1c",
    borderRadius: 8,
    colorBgLayout: "#f4f6fa",
    colorTextBase: "#0f172a",
    fontFamily:
      "'Inter', -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
    fontSize: 13,
  },
  components: {
    Card: {
      borderRadiusLG: 12,
    },
    Layout: {
      headerBg: "#ffffff",
      headerHeight: 62,
      headerPadding: "0 24px",
    },
    Table: {
      headerBg: "#f8fafc",
      headerColor: "#475569",
      cellPaddingBlockSM: 7,
      cellPaddingInlineSM: 10,
    },
    Tabs: {
      titleFontSize: 14,
    },
    Button: {
      controlHeight: 36,
      fontWeight: 600,
    },
    InputNumber: {
      controlHeight: 36,
    },
    Select: {
      controlHeight: 36,
    },
    DatePicker: {
      controlHeight: 36,
    },
  },
};
