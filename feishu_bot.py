"""
飞书自定义机器人消息发送模块
"""
import hashlib
import base64
import hmac
import time
import requests
import datetime
from typing import Optional
from loguru import logger
from paper import ArxivPaper
from tqdm import tqdm
import math


def gen_sign(timestamp: int, secret: str) -> str:
    """生成签名字符串用于飞书机器人安全校验"""
    string_to_sign = '{}\n{}'.format(timestamp, secret)
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(hmac_code).decode('utf-8')
    return sign


def get_stars_text(score: float) -> str:
    """根据相关度分数生成星级文本"""
    low = 6
    high = 8
    if score <= low:
        return ''
    elif score >= high:
        return '⭐⭐⭐⭐⭐'
    else:
        interval = (high - low) / 10
        star_num = math.ceil((score - low) / interval)
        full_star_num = int(star_num / 2)
        half_star_num = star_num - full_star_num * 2
        return '⭐' * full_star_num + ('½' if half_star_num else '')


def build_paper_table(papers: list[ArxivPaper], start_index: int = 1) -> list[dict]:
    """构建论文表格元素"""
    if not papers:
        return []
    
    # 表格头
    header = {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "grey",
        "columns": [
            {"tag": "column", "width": "auto", "elements": [{"tag": "markdown", "content": "**序号**"}]},
            {"tag": "column", "width": "weighted", "weight": 3, "elements": [{"tag": "markdown", "content": "**论文标题**"}]},
            {"tag": "column", "width": "weighted", "weight": 1, "elements": [{"tag": "markdown", "content": "**arXiv ID**"}]},
            {"tag": "column", "width": "auto", "elements": [{"tag": "markdown", "content": "**论文日期**"}]},
            {"tag": "column", "width": "auto", "elements": [{"tag": "markdown", "content": "**链接**"}]},
        ]
    }
    
    rows = [header]
    
    for i, paper in enumerate(papers, start_index):
        # 截断标题
        title = paper.title[:35] + "..." if len(paper.title) > 35 else paper.title
        # 使用 API 返回的发布日期（精确到天）
        if paper._paper.published:
            pub_date = paper._paper.published.strftime('%Y-%m-%d')
        else:
            # 回退：从 arXiv ID 解析发布年月 (格式: YYMM.NNNNN)
            try:
                arxiv_id_prefix = paper.arxiv_id.split('.')[0]
                year = 2000 + int(arxiv_id_prefix[:2])
                month = int(arxiv_id_prefix[2:])
                pub_date = f"{year}-{month:02d}"
            except (ValueError, IndexError):
                pub_date = 'N/A'
        
        row = {
            "tag": "column_set",
            "flex_mode": "none",
            "columns": [
                {"tag": "column", "width": "auto", "elements": [{"tag": "markdown", "content": f"{i}"}]},
                {"tag": "column", "width": "weighted", "weight": 3, "elements": [{"tag": "markdown", "content": title}]},
                {"tag": "column", "width": "weighted", "weight": 1, "elements": [{"tag": "markdown", "content": paper.arxiv_id}]},
                {"tag": "column", "width": "auto", "elements": [{"tag": "markdown", "content": pub_date}]},
                {"tag": "column", "width": "auto", "elements": [{"tag": "markdown", "content": f"[PDF]({paper.pdf_url})"}]},
            ]
        }
        rows.append(row)
    
    return rows


def build_paper_detail_element(paper: ArxivPaper, index: int) -> list[dict]:
    """构建单篇论文详细信息元素"""
    # 处理作者
    author_list = [a.name for a in paper.authors]
    if len(author_list) <= 5:
        authors = ', '.join(author_list)
    else:
        authors = ', '.join(author_list[:3] + ['...'] + author_list[-2:])
    
    elements = [
        {"tag": "hr"},
        {"tag": "markdown", "content": f"**📝 {index}. {paper.title}**"},
    ]
    
    # 相关度星级
    stars = get_stars_text(paper.score) if paper.score else ''
    if stars:
        elements.append({"tag": "markdown", "content": f"⭐ 相关度: {stars}"})
    
    # arXiv ID 和链接
    links = f"[arXiv](https://arxiv.org/abs/{paper.arxiv_id}) | [PDF]({paper.pdf_url})"
    if paper.code_url:
        links += f" | [Code]({paper.code_url})"
    elements.append({"tag": "markdown", "content": f"📎 arXiv ID: {paper.arxiv_id}"})
    elements.append({"tag": "markdown", "content": f"🔗 论文链接: {links}"})
    
    # 作者列表
    elements.append({"tag": "markdown", "content": f"👥 作者: {authors}"})
    
    # 作者机构
    affiliations = paper.affiliations_from_html
    if affiliations:
        aff_text = " | ".join(affiliations[:3])  # 最多展示3个机构
        if len(affiliations) > 3:
            aff_text += f" +{len(affiliations) - 3}"
        elements.append({"tag": "markdown", "content": f"🏛️ 机构: {aff_text}"})
    
    # 框架图 (飞书不支持外部图片URL，且markdown链接中的.png URL会被识别为image_key导致报错)
    if paper.framework_figure:
        html_page_url = f"https://arxiv.org/html/{paper.arxiv_id}"
        elements.append({"tag": "markdown", "content": f"📊 [查看模型框架图]({html_page_url})"})
    
    # 论文解读
    elements.append({"tag": "markdown", "content": "**论文解读**"})
    elements.append({"tag": "markdown", "content": paper.tldr})
    
    return elements


def _send_card_message(webhook_url: str, card: dict, secret: Optional[str] = None) -> bool:
    """发送单条卡片消息到飞书"""
    message = {
        "msg_type": "interactive",
        "card": card
    }
    
    if secret:
        timestamp = int(time.time())
        sign = gen_sign(timestamp, secret)
        message["timestamp"] = str(timestamp)
        message["sign"] = sign
    
    try:
        response = requests.post(
            webhook_url,
            json=message,
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        result = response.json()
        
        if result.get("code") == 0:
            return True
        else:
            logger.error(f"飞书消息发送失败: {result}")
            return False
            
    except Exception as e:
        logger.error(f"飞书消息发送异常: {e}")
        return False


def send_feishu_message(
    webhook_url: str, 
    grouped_results: dict[str, list[ArxivPaper]], 
    secret: Optional[str] = None
) -> bool:
    """
    发送消息到飞书群
    
    Args:
        webhook_url: 飞书 webhook URL
        grouped_results: 按方向分组的论文字典 {方向名: 论文列表}
        secret: 签名密钥
    """
    # 计算总论文数
    total = sum(len(papers) for papers in grouped_results.values())
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    if total == 0:
        # 空消息
        card = {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "📚 ArXiv Today"},
                "subtitle": {"tag": "plain_text", "content": today},
                "template": "blue"
            },
            "body": {
                "elements": [
                    {"tag": "markdown", "content": "**今日没有新论文，休息一下吧！** 🎉"}
                ]
            }
        }
        return _send_card_message(webhook_url, card, secret)
    
    success = True
    
    # === 第一条消息：概览和各方向表格 ===
    elements = []
    
    # 头部信息
    direction_count = len(grouped_results)
    if direction_count > 1:
        elements.append({
            "tag": "markdown", 
            "content": f"ArXiv Today 小助手来啦٩(๑>◡<๑)۶！\n今日找到了 **{total}** 篇相关论文，覆盖 **{direction_count}** 个方向 ⁽⁽٩(๑˃̶͈̀ ᗨ ˂̶͈́)۶⁾⁾"
        })
    else:
        elements.append({
            "tag": "markdown", 
            "content": f"ArXiv Today 小助手来啦٩(๑>◡<๑)۶！\n今日找到了 **{total}** 篇相关论文 ⁽⁽٩(๑˃̶͈̀ ᗨ ˂̶͈́)۶⁾⁾"
        })
    
    # 按方向展示表格
    for direction_name, papers in grouped_results.items():
        if not papers:
            continue
        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": f"### 📁 {direction_name}"})
        table_elements = build_paper_table(papers, start_index=1)
        elements.extend(table_elements)
    
    card = {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "📚 ArXiv Today"},
            "subtitle": {"tag": "plain_text", "content": today},
            "template": "blue"
        },
        "body": {
            "elements": elements
        }
    }
    
    if not _send_card_message(webhook_url, card, secret):
        success = False
    
    time.sleep(1)  # 发送间隔，避免限流
    
    # === 后续消息：每个方向的论文详情 ===
    BATCH_SIZE = 5
    
    for direction_name, papers in grouped_results.items():
        if not papers:
            continue
            
        for batch_start in range(0, len(papers), BATCH_SIZE):
            batch_papers = papers[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(papers) + BATCH_SIZE - 1) // BATCH_SIZE
            
            elements = []
            
            for i, paper in enumerate(tqdm(batch_papers, desc=f'Building {direction_name} details batch {batch_num}')):
                global_idx = batch_start + i + 1
                detail_elements = build_paper_detail_element(paper, global_idx)
                elements.extend(detail_elements)
                time.sleep(5)  # 等待 LLM 生成
            
            card = {
                "schema": "2.0",
                "header": {
                    "title": {"tag": "plain_text", "content": f"📁 {direction_name} - 详情"},
                    "subtitle": {"tag": "plain_text", "content": f"{today} ({batch_num}/{total_batches})"},
                    "template": "turquoise"
                },
                "body": {
                    "elements": elements
                }
            }
            
            if not _send_card_message(webhook_url, card, secret):
                success = False
            
            time.sleep(1)
    
    if success:
        logger.success("飞书消息发送成功！")
    
    return success
