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
  * 通知策略：成功不通知、失败才通知；可选 Cookie 到期前（默认第 27 天）提醒更换
  * 通知渠道：企业微信自建应用(同青龙 QYWX_AM) / 企业微信群机器人 / Server酱 / Telegram / Bark
  * 失败自动重试一次以过滤偶发抖动；支持随机延迟（RANDOM_DELAY）
"""

import os
import re
import sys
import time
import random
import html as html_lib
from datetime import datetime, timezone, timedelta

import requests

BASE = "https://www.chinafix.com"
SIGN_PAGE = BASE + "/plugin.php?id=k_misign:sign"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

CN_TZ = timezone(timedelta(hours=8))

# 失效通知里附带的“重新抓 Cookie”简明步骤（怕用户忘记怎么操作）
COOKIE_HOWTO = (
    "———— 如何重新抓 Cookie（约1分钟）————\n"
    "1. 电脑浏览器打开 www.chinafix.com 登录，勾选“记住登录状态”；\n"
    "2. 打开签到页 www.chinafix.com/plugin.php?id=k_misign:sign，确认已登录；\n"
    "3. 按 F12 → 点 Network（网络）→ 再按 F5 刷新；\n"
    "4. 点最上面那条请求，右侧 Request Headers 里找 cookie:（看不到就点 view source）；\n"
    "5. 复制 cookie: 后整串（里面必须含“auth=”）；\n"
    "6. GitHub 仓库 Settings → Secrets and variables → Actions，点 CHINAFIX_COOKIE 铅笔，粘贴保存；\n"
    "7. Actions → chinafix-sign → Run workflow。"
)


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


def notify_wecom_app(title, content):
    """企业微信【自建应用】消息，复用青龙 QYWX_AM 字符串：
    corpid,corpsecret,touser,agentid[,消息类型] （第5段忽略，默认发文本）。"""
    raw = os.getenv("QYWX_AM") or os.getenv("WECOM_APP")
    if not raw:
        return
    parts = [p.strip() for p in raw.strip().split(",")]
    if len(parts) < 4:
        print("[通知] 企业微信应用 参数不全，应为 corpid,corpsecret,touser,agentid")
        return
    corpid, corpsecret, touser, agentid = parts[:4]
    try:
        tu = ("https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=%s&corpsecret=%s"
              % (corpid, corpsecret))
        rj = requests.get(tu, timeout=15).json()
        token = rj.get("access_token")
        if not token:
            print("[通知] 企业微信应用 获取 token 失败:", rj)
            return
        su = "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=%s" % token
        body = {
            "touser": touser,
            "msgtype": "text",
            "agentid": int(agentid) if agentid.isdigit() else agentid,
            "text": {"content": title + "\n" + content},
        }
        rj2 = requests.post(su, json=body, timeout=15).json()
        if rj2.get("errcode") == 0:
            print("[通知] 企业微信应用 已发送")
        else:
            print("[通知] 企业微信应用 失败:", rj2)
    except Exception as e:
        print("[通知] 企业微信应用 异常:", e)


def send_notify(title, content):
    notify_serverchan(title, content)
    notify_telegram(title, content)
    notify_bark(title, content)
    notify_wecom(title, content)
    notify_wecom_app(title, content)


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


def run_with_retry(cookie, label):
    """单个账号最多尝试 2 次，间隔 12 秒；签到幂等，重试安全，可过滤偶发网络/负载抖动。"""
    last = (False, label, "未知失败", {})
    for attempt in range(2):
        try:
            res = sign_one(cookie, label)
        except requests.RequestException as e:
            res = (False, label, "网络请求异常：%s" % e, {})
        if res[0]:
            return res
        last = res
        if attempt == 0:
            time.sleep(12)
    return last


def main():
    raw = os.getenv("CHINAFIX_COOKIE", "").strip()
    if not raw:
        print("未配置 CHINAFIX_COOKIE（GitHub 仓库 Settings → Secrets → Actions）")
        sys.exit(1)

    accounts = load_accounts(raw)
    if not accounts:
        print("CHINAFIX_COOKIE 中没有解析到有效 Cookie")
        sys.exit(1)

    # 随机延迟（分钟）：在固定的定时触发后，先随机等待 RANDOM_DELAY 分钟内的一段时间再签，
    # 使实际签到时间每天不固定（GitHub cron 本身不支持随机）。0 或不配置 = 不延迟。
    try:
        delay_max = int(os.getenv("RANDOM_DELAY", "0").strip())
    except ValueError:
        delay_max = 0
    if delay_max > 0:
        wait_s = random.randint(30, delay_max * 60)
        print("随机延迟 %d分%d秒 后开始签到……" % (wait_s // 60, wait_s % 60))
        time.sleep(wait_s)

    now = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M")
    lines = ["时间：%s" % now, ""]
    ok_count = 0
    results = []

    for i, (label, cookie) in enumerate(accounts):
        if i > 0:
            time.sleep(3)
        ok, label, msg, stats = run_with_retry(cookie, label)
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
    content = "\n".join(lines)
    print("\n" + content)

    # 通知策略：默认【成功不通知，失败才通知】。
    push_title = push_content = None
    if ok_count < total:
        push_title = "迅维网签到失败（成功 %d/%d），请更新 Cookie" % (ok_count, total)
        push_content = content + "\n\n" + COOKIE_HOWTO

    # 可选“到期提醒”（定时更换）：设置 COOKIE_SET_DATE=YYYY-MM-DD（上次登录/设置 Cookie 的日期），
    # 当 Cookie 年龄达到 REMIND_BEFORE（默认 27 天）时，即使当天签到成功也推送一次提醒，
    # 让你在约 30 天到期前主动更换。不设置日期则不提醒，保持成功静默。
    set_date = os.getenv("COOKIE_SET_DATE", "").strip()
    if push_title is None and set_date:
        try:
            d0 = datetime.strptime(set_date, "%Y-%m-%d").date()
            age = (datetime.now(CN_TZ).date() - d0).days
            try:
                remind_before = int(os.getenv("REMIND_BEFORE", "27").strip())
            except ValueError:
                remind_before = 27
            if age >= remind_before:
                push_title = "迅维 Cookie 已使用 %d 天，即将到期，请抽空更新" % age
                push_content = (
                    "上次设置 Cookie 的日期：%s，距今 %d 天。\n"
                    "迅维“记住登录”有效期约 30 天，建议在失效前重新登录抓 Cookie 并更新 Secret，"
                    "以免漏签。\n\n当天签到结果：成功 %d/%d。"
                    % (set_date, age, ok_count, total))
        except ValueError:
            print("COOKIE_SET_DATE 格式应为 YYYY-MM-DD，已忽略到期提醒")

    if push_title:
        send_notify(push_title, push_content)

    sys.exit(0 if ok_count == total else 1)


if __name__ == "__main__":
    main()
