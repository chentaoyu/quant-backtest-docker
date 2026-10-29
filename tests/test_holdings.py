import pytest

import holdings


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(holdings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(holdings, "HOLDINGS_FILE", tmp_path / "holdings.json")
    monkeypatch.setattr(holdings, "_names", lambda: {"600519": "贵州茅台", "002241": "歌尔股份"})


def test_parse_broker_table_with_header():
    text = "证券代码\t证券名称\t股票余额\t参考成本价\n600519\t贵州茅台\t100\t1500\n2241\t歌尔\t300\t23.5"
    rows = holdings.parse_import(text)
    assert [r["item"]["symbol"] for r in rows] == ["600519", "002241"]
    assert rows[1]["item"]["name"] == "歌尔股份"


def test_parse_without_header_and_errors():
    rows = holdings.parse_import("600519,100,1500,2024-01-02\n999999,1,1\n600519,100,1000\n002241,abc,1")
    assert rows[0]["ok"] and rows[0]["merged"]
    assert rows[0]["item"]["shares"] == 200 and rows[0]["item"]["cost_price"] == 1250
    assert "不存在" in rows[1]["error"]
    assert "合并" in rows[2]["error"]
    assert "数字" in rows[3]["error"]


def test_commit_append_merges_and_replace_overwrites():
    holdings.commit_import(holdings.parse_import("600519,100,1500"), "append")
    holdings.commit_import(holdings.parse_import("600519,100,1000"), "append")
    assert holdings.list_holdings()[0]["shares"] == 200
    holdings.commit_import(holdings.parse_import("002241,300,23.5"), "replace")
    assert [h["symbol"] for h in holdings.list_holdings()] == ["002241"]


def test_normalize_symbol():
    assert holdings.normalize_symbol("SH600519") == "600519"
    assert holdings.normalize_symbol("600519.SH") == "600519"
    assert holdings.normalize_symbol(2241) == "002241"
