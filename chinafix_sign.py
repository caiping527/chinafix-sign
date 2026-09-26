#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迅维网 (chinafix.com) 每日自动签到
-------------------------------------------------
认证方式：浏览器 Cookie（存放在 GitHub Secrets 的 CHINAFIX_COOKIE）
不使用账号密码自动登录，因为 chinafix 登录带验证码 + 风控，
自动登录脆弱且可能导致账号被临时锁定；而签到本身仅需 3 个 GET 请求。

支持：
  * 单账号 / 多账号（Secret 中每行一个账号的 Cookie，可写 "备注|Cookie"）
  * 签到结果通知：Server酱 / Telegram / Bark / 企业微信机器人
"""

import os
import re
import sys
import time
import html as html_lib
from datetime import datetime, timezone, timedelta

import requests

BASE = "https://www.chinafix.com"
SIGN_PAGE = BASE + "/plugin.php?id=k_misign:sign"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

CN_TZ = timezone(timedelta(hours=8))


# --------------------------------------------------------------------------
# 通知
# --------------------------------------------------------------------------
def notify_serverchan(title, content):
    key = os.getenv("SENDKEY") or os.getenv("SCKEY")
    if not key:
        return
    url = "https://sctapi.ftqq.com/%s.send" % key.strip()
    try:
        requests.post(url, data={"title": title, "desp": content}, timeout=15)
        print("[通知] Server酱 已发送")
    except Exception as e:
        print("[通知] Server酱 失败:", e)


def notify_telegram(title, content):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        return
    url = "https://api.telegram.org/bot%s/sendMessage" % token.strip()
    try:
        requests.post(url, data={
            "chat_id": chat_id.strip(),
            "text": title + "\n\n" + content,
            "disable_web_page_preview": "true",
        }, timeout=15)
        print("[通知] Telegram 已发送")
    except Exception as e:
        print("[通知] Telegram 失败:", e)


def notify_bark(title, content):
    raw = os.getenv("BARK_URL")
    if not raw:
        return
    raw = raw.strip().rstrip("/")
    # 只填了 key：https://api.day.app/<key>；填了完整地址则直接使用
    if raw.startswith("http"):
        url = raw
    else:
        url = "https://api.day.app/%s" % raw
    try:
        requests.post(url, json={"title": title, "body": content}, timeout=15)
        print("[通知] Bark 已发送")
    except Exception as e:
        print("[通知] Bark 失败:", e)


def notify_wecom(title, content):
    webhook = os.getenv("WECOM_WEBHOOK") or os.getenv("WECOM_KEY")
    if not webhook:
        return
    webhook = webhook.strip()
    if not webhook.startswith("http"):
        webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=" + webhook
    try:
        requests.post(webhook, json={
            "msgtype": "text",
            "text": {"content": title + "\n" + content},
        }, timeout=15)
        print("[通知] 企业微信 已发送")
    except Exception as e:
        print("[通知] 企业微信 失败:", e)


def send_notify(title, content):
    notify_serverchan(title, content)
    notify_telegram(title, content)
    notify_bark(title, content)
    notify_wecom(title, content)


# --------------------------------------------------------------------------
# 签到核心
# --------------------------------------------------------------------------
def make_session(cookie):
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
        "Cookie": cookie,
    })
    return s


def get_text(s, url, ajax=False, referer=None):
    headers = {}
    if referer:
        headers["Referer"] = referer
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Accept"] = "*/*"
    r = s.get(url, headers=headers, timeout=20)
    r.encoding = "gb18030"  # chinafix 为 GBK，gb18030 是其超集
    return r.status_code, r.text


def parse_stats(page):
    stats = {}
    m = re.search(r'g_upmine[^>]*>\s*([^<]+?)\s*</a>', page)
    stats["等级"] = m.group(1) if m else "-"
    m = re.search(r'id="lxdays"[^>]*value="(\d+)"', page)
    stats["连续签到"] = m.group(1) if m else "-"
    m = re.search(r'id="lxtdays"[^>]*value="(\d+)"', page)
    stats["累计签到"] = m.group(1) if m else "-"
    m = re.search(r'id="lxreward"[^>]*value="(\d+)"', page)
    stats["本次奖励"] = m.group(1) if m else "-"
    m = re.search(r'签到排名[：:]\s*(\d+)', page)
    stats["今日排名"] = m.group(1) if m else "-"
    return stats


def parse_username(page):
    m = re.search(
        r'home\.php\?mod=space(?:&|&amp;)uid=\d+[^>]*>\s*([^<]{1,30}?)\s*</a>',
        page)
    if m:
        return html_lib.unescape(m.group(1)).strip()
    return ""


def sign_one(cookie, label):
    s = make_session(cookie)

    # 1) 打开签到页
    sc, page = get_text(s, SIGN_PAGE, referer=BASE + "/")
    if sc != 200:
        return False, label, "HTTP %s，无法访问签到页" % sc, {}

    already = "您的签到排名" in page

    # 解析签到按钮链接
    m = re.search(r'id="JD_sign"[^>]*?href="([^"]*)"', page)
    href = html_lib.unescape(m.group(1)) if m else ""

    # 未登录时按钮指向 member.php ... action=login
    is_login_link = ("action=login" in href) or ("logging" in href and "login" in href)
    # 注意：已签到后 JD_sign 按钮会消失（href 为空），这属于"已登录且已签"，不能误判；
    # 只有在"未签到"且按钮指向登录页/缺失时，才是真的未登录。
    if not already and (is_login_link or not href):
        return False, label, "Cookie 已失效 / 未登录，请更新 CHINAFIX_COOKIE", {}

    sign_url = requests.compat.urljoin(BASE + "/", href)
    if "operation=qiandao" not in sign_url:
        fh = re.search(r'formhash=([a-f0-9]{6,})', page)
        if not fh:
            return False, label, "无法解析签到链接或 formhash，页面结构可能已变化", {}
        sign_url = SIGN_PAGE + "&operation=qiandao&formhash=" + fh.group(1)

    resp_snippet = ""
    if not already:
        # 2) 触发签到（AJAX）
        sep = "&" if "?" in sign_url else "?"
        sc2, resp = get_text(s, sign_url + sep + "inajax=1", ajax=True, referer=SIGN_PAGE)
        resp_snippet = resp
        if "您所在用户组不允许" in resp:
            return False, label, "当前用户组不允许签到", {}
        if not re.search(r'签到成功|今日已签|已签到|succeed', resp):
            # AJAX 未明确成功，退回普通 GET
            _, resp2 = get_text(s, sign_url, referer=SIGN_PAGE)
            resp_snippet += "\n" + resp2

    # 3) 重新打开签到页核对结果
    time.sleep(1.5)
    _, final = get_text(s, SIGN_PAGE, referer=SIGN_PAGE)
    stats = parse_stats(final)
    uname = parse_username(final)
    if uname:
        label = uname

    if "您的签到排名" in final:
        msg = "今日已签（此前已完成）" if already else "签到成功"
        return True, label, msg, stats

    return False, label, "已提交但页面未确认成功。响应片段：%s" % resp_snippet[:160], stats


def load_accounts(raw):
    accounts = []
    n = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("cookie:"):
            line = line.split(":", 1)[1].strip()
        label, cookie = "", line
        if "|" in line:
            pre, post = line.split("|", 1)
            # 仅当 "|" 前是纯备注（不含 = 和 ;）时，才按 "备注|Cookie" 解析；
            # 否则说明 "|" 是某个 Cookie 值的一部分（如 SERVERID=a|b|c），整行都算 Cookie。
            if ("=" not in pre) and (";" not in pre):
                label, cookie = pre.strip(), post.strip()
        if cookie:
            n += 1
            accounts.append((label or ("账号%d" % n), cookie))
    return accounts


def main():
    raw = os.getenv("CHINAFIX_COOKIE", "").strip()
    if not raw:
        print("未配置 CHINAFIX_COOKIE（GitHub 仓库 Settings → Secrets → Actions）")
        sys.exit(1)

    accounts = load_accounts(raw)
    if not accounts:
        print("CHINAFIX_COOKIE 中没有解析到有效 Cookie")
        sys.exit(1)

    now = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M")
    lines = ["时间：%s" % now, ""]
    ok_count = 0
    results = []

    for i, (label, cookie) in enumerate(accounts):
        if i > 0:
            time.sleep(3)
        try:
            ok, label, msg, stats = sign_one(cookie, label)
        except requests.RequestException as e:
            ok, msg, stats = False, "网络请求异常：%s" % e, {}
        results.append(ok)
        if ok:
            ok_count += 1
        mark = "[成功]" if ok else "[失败]"
        lines.append("%s %s：%s" % (mark, label, msg))
        if stats:
            lines.append(
                "    等级:%s | 连续:%s天 | 累计:%s天 | 本次奖励:%s下载分 | 今日排名:%s"
                % (stats.get("等级", "-"), stats.get("连续签到", "-"),
                   stats.get("累计签到", "-"), stats.get("本次奖励", "-"),
                   stats.get("今日排名", "-"))
        )
        print(lines[-1])
        if stats:
            print(lines[-1] if False else "    stats:", stats)

    total = len(accounts)
    lines.append("")
    lines.append("汇总：成功 %d / 共 %d" % (ok_count, total))

    title = "迅维网签到报告（成功 %d/%d）" % (ok_count, total)
    content = "\n".join(lines)
    print("\n" + content)
    send_notify(title, content)

    sys.exit(0 if ok_count == total else 1)


if __name__ == "__main__":
    main()
