"""Beancount & Fava 导入规则配置 (Import Configuration)

支持：
1. 微信支付账单 CSV 导入 (WeChat Pay)
2. 支付宝交易账单 CSV 导入 (Alipay)
3. 通用/自定义 CSV 账单导入 (Generic CSV)
"""

from __future__ import annotations

import csv
import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from beangulp.importer import Importer
from fava.beans import create

if TYPE_CHECKING:
    from beancount.core import data
    from fava.beans.abc import Directive

DEFAULT_CURRENCY = "CNY"

# ==============================================================================
# 智能分类规则 (按关键词匹配，未命中的支出默认归入 Expenses:Unknown)
# 你可以在这里自由添加、修改关键词或对应的 Beancount 账户
# ==============================================================================
CATEGORY_RULES = [
    # 餐饮与外卖
    (
        [
            "美团", "饿了么", "麦当劳", "肯德基", "星巴克", "瑞幸", "外卖", "餐饮",
            "食堂", "咖啡", "茶姬", "喜茶", "汉堡", "烧烤", "火锅", "面馆",
        ],
        "Expenses:Food",
    ),
    # 超市买菜与便利店
    (
        [
            "盒马", "山姆", "超市", "便利店", "罗森", "全家", "永辉", "生鲜",
            "菜市场", "7-eleven", "便利蜂", "大润发", "沃尔玛",
        ],
        "Expenses:Groceries",
    ),
    # 交通出行
    (
        [
            "滴滴", "打车", "地铁", "公交", "高德", "铁路", "12306", "加油",
            "停车", "交通", "一卡通", "车费", "机票", "携程", "飞猪",
        ],
        "Expenses:Transport",
    ),
    # 生活缴费与通讯
    (
        ["话费", "充值", "电费", "水费", "燃气", "物业", "宽带"],
        "Expenses:Utilities",
    ),
    # 线上购物与数码
    (
        ["淘宝", "京东", "拼多多", "天猫", "唯品会", "apple", "苹果", "小米"],
        "Expenses:Shopping",
    ),
    # 休闲娱乐与数码订阅
    (
        [
            "电影", "网易云", "qq音乐", "爱奇艺", "腾讯视频", "b站", "哔哩哔哩",
            "会员", "游戏", "steam", "任天堂",
        ],
        "Expenses:Entertainment",
    ),
    # 医疗健康
    (
        ["药房", "医院", "药店", "诊所", "同仁堂"],
        "Expenses:Health",
    ),
]


# ==============================================================================
# 2. 支付账户/银行卡映射规则 (按账单中的“支付方式”关键词匹配对应资金账户)
# ==============================================================================
PAY_METHOD_RULES = [
    # 微信/支付宝原生渠道
    ("零钱通", "Assets:WeChat:LingQianTong"),
    ("零钱", "Assets:WeChat"),
    ("余额宝", "Assets:Alipay:YuEBao"),
    ("花呗", "Liabilities:Alipay:HuaBei"),
    # 银行卡映射（可填银行名或卡号后4位，如 "1234"）
    ("招商银行", "Assets:Bank:CMB"),
    ("工商银行", "Assets:Bank:ICBC"),
    ("建设银行", "Assets:Bank:CCB"),
    ("农业银行", "Assets:Bank:ABC"),
    ("中信银行", "Assets:Bank:CITIC"),
    ("中国银行", "Assets:Bank:BOC"),
    ("交通银行", "Assets:Bank:BOCOM"),
    ("信用卡", "Liabilities:CreditCard"),
]


def guess_expense_account(text: str) -> str:
    """根据交易对方和商品说明推测支出分类账户"""
    lower_text = text.lower()
    for keywords, account in CATEGORY_RULES:
        for kw in keywords:
            if kw.lower() in lower_text:
                return account
    return "Expenses:Unknown"


def guess_pay_method_account(pay_method: str, default_account: str) -> str:
    """根据账单支付方式/渠道推测资金出入账户"""
    if not pay_method:
        return default_account
    for kw, acc in PAY_METHOD_RULES:
        if kw in pay_method:
            return acc
    return default_account



def read_file_lines(filepath: str | Path) -> tuple[list[str], str]:
    """读取文件内容，自动尝试常见中文编码"""
    path = Path(filepath)
    raw = path.read_bytes()
    for encoding in ["utf-8-sig", "utf-8", "gb18030", "gbk"]:
        try:
            return raw.decode(encoding).splitlines(), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace").splitlines(), "utf-8"


class WeChatImporter(Importer):
    """微信支付账单导入器 (WeChat Pay CSV Importer)"""

    @property
    def name(self) -> str:
        return "importers.wechat"

    def account(self, filepath: str) -> str:
        return "Assets:WeChat"

    def identify(self, filepath: str) -> bool:
        path = Path(filepath)
        if path.suffix.lower() != ".csv":
            return False
        try:
            lines, _ = read_file_lines(path)
            header_sample = "".join(lines[:25])
            return "微信支付账单明细" in header_sample or (
                "微信支付" in header_sample and "交易时间" in header_sample
            )
        except Exception:
            return False

    def extract(
        self, filepath: str, existing: data.Entries | None = None
    ) -> list[Directive]:
        entries: list[Directive] = []
        lines, _ = read_file_lines(filepath)

        header_idx = -1
        for i, line in enumerate(lines):
            if "交易时间" in line and "交易对方" in line:
                header_idx = i
                break

        if header_idx == -1:
            return entries

        reader = csv.DictReader(lines[header_idx:])
        for idx, row in enumerate(reader, start=header_idx + 2):
            row = {k.strip(): v.strip() for k, v in row.items() if k}
            tx_time = row.get("交易时间", "")
            if not tx_time:
                continue

            try:
                date = datetime.datetime.strptime(
                    tx_time, "%Y-%m-%d %H:%M:%S"
                ).date()
            except ValueError:
                try:
                    date = datetime.date.fromisoformat(tx_time[:10])
                except Exception:
                    continue

            tx_type = row.get("交易类型", "")
            payee = row.get("交易对方", "").strip() or "微信支付"
            narration = row.get("商品", "").strip() or tx_type
            direction = row.get("收/支", "")
            amount_str = (
                row.get("金额(元)", "")
                .replace("¥", "")
                .replace(",", "")
                .strip()
            )
            pay_method = row.get("支付方式", "")
            status = row.get("当前状态", "")
            tx_id = row.get("交易单号", "")

            try:
                amount = Decimal(amount_str)
            except Exception:
                continue

            # 确定微信资金出入账户（优先匹配用户自定义银行卡/零钱规则）
            base_account = guess_pay_method_account(
                pay_method, default_account="Assets:WeChat"
            )

            raw_source = ",".join(f"{k}:{v}" for k, v in row.items())
            meta = {
                "filename": str(filepath),
                "lineno": idx,
                "__source__": raw_source,
            }
            if tx_id:
                meta["tx_id"] = tx_id
            if pay_method:
                meta["method"] = pay_method

            if direction == "支出":
                category_account = guess_expense_account(
                    f"{payee} {narration}"
                )
                txn = create.transaction(
                    meta,
                    date,
                    "*",
                    payee,
                    narration,
                    frozenset(),
                    frozenset(),
                    [
                        create.posting(
                            category_account,
                            create.amount(amount, DEFAULT_CURRENCY),
                        ),
                        create.posting(
                            base_account,
                            create.amount(-amount, DEFAULT_CURRENCY),
                        ),
                    ],
                )
                entries.append(txn)
            elif direction == "收入":
                inc_account = (
                    "Income:Gifts"
                    if ("红包" in tx_type or "转账" in tx_type)
                    else "Income:Unknown"
                )
                txn = create.transaction(
                    meta,
                    date,
                    "*",
                    payee,
                    narration,
                    frozenset(),
                    frozenset(),
                    [
                        create.posting(
                            base_account,
                            create.amount(amount, DEFAULT_CURRENCY),
                        ),
                        create.posting(
                            inc_account,
                            create.amount(-amount, DEFAULT_CURRENCY),
                        ),
                    ],
                )
                entries.append(txn)
            else:
                txn = create.transaction(
                    meta,
                    date,
                    "*",
                    payee,
                    f"{tx_type}: {narration}",
                    frozenset(),
                    frozenset(),
                    [
                        create.posting(
                            "Assets:Transfer",
                            create.amount(amount, DEFAULT_CURRENCY),
                        ),
                        create.posting(
                            base_account,
                            create.amount(-amount, DEFAULT_CURRENCY),
                        ),
                    ],
                )
                entries.append(txn)

        return entries


class AlipayImporter(Importer):
    """支付宝账单导入器 (Alipay CSV Importer)"""

    @property
    def name(self) -> str:
        return "importers.alipay"

    def account(self, filepath: str) -> str:
        return "Assets:Alipay"

    def identify(self, filepath: str) -> bool:
        path = Path(filepath)
        if path.suffix.lower() != ".csv":
            return False
        try:
            lines, _ = read_file_lines(path)
            header_sample = "".join(lines[:35])
            return (
                "支付宝交易记录明细" in header_sample
                or ("alipay" in path.name.lower() and "交易号" in header_sample)
                or (
                    "商家订单号" in header_sample
                    and "交易创建时间" in header_sample
                )
            )
        except Exception:
            return False

    def extract(
        self, filepath: str, existing: data.Entries | None = None
    ) -> list[Directive]:
        entries: list[Directive] = []
        lines, _ = read_file_lines(filepath)

        header_idx = -1
        for i, line in enumerate(lines):
            if ("交易号" in line or "商家订单号" in line) and "交易对方" in line:
                header_idx = i
                break

        if header_idx == -1:
            return entries

        data_lines = [
            l
            for l in lines[header_idx:]
            if not l.startswith("---") and not l.startswith("#")
        ]
        reader = csv.DictReader(data_lines)
        for idx, row in enumerate(reader, start=header_idx + 2):
            row = {k.strip(): v.strip() for k, v in row.items() if k}
            tx_time = (
                row.get("付款时间")
                or row.get("交易创建时间")
                or row.get("交易时间", "")
            )
            if not tx_time:
                continue

            try:
                date = datetime.datetime.strptime(
                    tx_time, "%Y-%m-%d %H:%M:%S"
                ).date()
            except ValueError:
                try:
                    date = datetime.date.fromisoformat(tx_time[:10])
                except Exception:
                    continue

            status = row.get("交易状态", "")
            if any(s in status for s in ["交易关闭", "等待付款", "关闭"]):
                continue

            payee = row.get("交易对方", "").strip() or "支付宝交易"
            narration = (
                row.get("商品名称", "").strip()
                or row.get("商品说明", "").strip()
                or "消费"
            )
            direction = row.get("收/支", "").strip()
            amount_str = (
                row.get("金额（元）")
                or row.get("金额(元)")
                or row.get("金额", "")
            ).replace(",", "").strip()
            trade_no = row.get("交易号", "") or row.get("交易订单号", "")

            try:
                amount = Decimal(amount_str)
            except Exception:
                continue

            raw_source = ",".join(f"{k}:{v}" for k, v in row.items())
            meta = {
                "filename": str(filepath),
                "lineno": idx,
                "__source__": raw_source,
            }
            if trade_no:
                meta["trade_no"] = trade_no

            pay_method = (
                row.get("收/付款方式")
                or row.get("支付方式")
                or row.get("资金状态", "")
            )
            base_account = guess_pay_method_account(
                pay_method, default_account="Assets:Alipay"
            )

            if direction == "支出":
                category_account = guess_expense_account(
                    f"{payee} {narration}"
                )
                txn = create.transaction(
                    meta,
                    date,
                    "*",
                    payee,
                    narration,
                    frozenset(),
                    frozenset(),
                    [
                        create.posting(
                            category_account,
                            create.amount(amount, DEFAULT_CURRENCY),
                        ),
                        create.posting(
                            base_account,
                            create.amount(-amount, DEFAULT_CURRENCY),
                        ),
                    ],
                )
                entries.append(txn)
            elif direction == "收入":
                inc_account = "Income:Unknown"
                txn = create.transaction(
                    meta,
                    date,
                    "*",
                    payee,
                    narration,
                    frozenset(),
                    frozenset(),
                    [
                        create.posting(
                            base_account,
                            create.amount(amount, DEFAULT_CURRENCY),
                        ),
                        create.posting(
                            inc_account,
                            create.amount(-amount, DEFAULT_CURRENCY),
                        ),
                    ],
                )
                entries.append(txn)
            else:
                txn = create.transaction(
                    meta,
                    date,
                    "*",
                    payee,
                    narration,
                    frozenset(),
                    frozenset(),
                    [
                        create.posting(
                            "Assets:Transfer",
                            create.amount(amount, DEFAULT_CURRENCY),
                        ),
                        create.posting(
                            base_account,
                            create.amount(-amount, DEFAULT_CURRENCY),
                        ),
                    ],
                )
                entries.append(txn)

        return entries


class GenericCSVImporter(Importer):
    """通用 CSV 账单导入器 (Generic CSV Importer)"""

    @property
    def name(self) -> str:
        return "importers.generic_csv"

    def account(self, filepath: str) -> str:
        return "Assets:Current"

    def identify(self, filepath: str) -> bool:
        path = Path(filepath)
        if path.suffix.lower() != ".csv":
            return False
        # 如果已被微信或支付宝识别，则不作为通用 CSV
        if WeChatImporter().identify(filepath) or AlipayImporter().identify(
            filepath
        ):
            return False
        try:
            lines, _ = read_file_lines(path)
            if not lines:
                return False
            first_line = lines[0].lower()
            return any(
                k in first_line
                for k in ["date", "日期", "amount", "金额", "payee", "对方"]
            )
        except Exception:
            return False

    def extract(
        self, filepath: str, existing: data.Entries | None = None
    ) -> list[Directive]:
        entries: list[Directive] = []
        lines, _ = read_file_lines(filepath)
        if not lines:
            return entries

        reader = csv.DictReader(lines)
        for idx, row in enumerate(reader, start=2):
            row = {k.strip(): v.strip() for k, v in row.items() if k}
            date_val = None
            for date_key in ["date", "Date", "日期", "交易日期"]:
                if date_key in row and row[date_key]:
                    try:
                        date_val = datetime.date.fromisoformat(
                            row[date_key][:10]
                        )
                        break
                    except Exception:
                        pass
            if not date_val:
                continue

            amount_val = None
            for amt_key in ["amount", "Amount", "金额", "金额(元)"]:
                if amt_key in row and row[amt_key]:
                    try:
                        amount_val = Decimal(
                            row[amt_key].replace("¥", "").replace(",", "").strip()
                        )
                        break
                    except Exception:
                        pass
            if amount_val is None:
                continue

            payee = (
                row.get("payee")
                or row.get("Payee")
                or row.get("交易对方")
                or row.get("对方")
                or ""
            )
            narration = (
                row.get("narration")
                or row.get("description")
                or row.get("商品")
                or row.get("备注")
                or "交易"
            )
            account_col = (
                row.get("account")
                or row.get("Account")
                or row.get("分类")
            )

            raw_source = ",".join(f"{k}:{v}" for k, v in row.items())
            meta = {
                "filename": str(filepath),
                "lineno": idx,
                "__source__": raw_source,
            }

            if amount_val < 0:
                cat_acc = account_col or guess_expense_account(
                    f"{payee} {narration}"
                )
                txn = create.transaction(
                    meta,
                    date_val,
                    "*",
                    payee,
                    narration,
                    frozenset(),
                    frozenset(),
                    [
                        create.posting(
                            cat_acc,
                            create.amount(abs(amount_val), DEFAULT_CURRENCY),
                        ),
                        create.posting(
                            "Assets:Current",
                            create.amount(amount_val, DEFAULT_CURRENCY),
                        ),
                    ],
                )
                entries.append(txn)
            else:
                cat_acc = account_col or "Income:Unknown"
                txn = create.transaction(
                    meta,
                    date_val,
                    "*",
                    payee,
                    narration,
                    frozenset(),
                    frozenset(),
                    [
                        create.posting(
                            "Assets:Current",
                            create.amount(amount_val, DEFAULT_CURRENCY),
                        ),
                        create.posting(
                            cat_acc,
                            create.amount(-amount_val, DEFAULT_CURRENCY),
                        ),
                    ],
                )
                entries.append(txn)

        return entries


# 注册所有生效的导入器
CONFIG: list[Importer] = [
    WeChatImporter(),
    AlipayImporter(),
    GenericCSVImporter(),
]
