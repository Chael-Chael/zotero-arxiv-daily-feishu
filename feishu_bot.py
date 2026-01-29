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


def build_paper_table_row(paper: ArxivPaper, index: int) -> str:
    """构建表格行文本"""
    # 截断标题
    title = paper.title[:30] + "..." if len(paper.title) > 30 else paper.title
    # 获取发布日期
    pub_date = paper._paper.published.strftime('%Y-%m-%d') if paper._paper.published else 'N/A'
    
    return f"| {index} | {title} | {paper.arxiv_id} | {pub_date} | [PDF]({paper.pdf_url}) |"


def build_paper_detail(paper: ArxivPaper, index: int) -> str:
    """构建论文详细信息 Markdown"""
    # 处理作者
    author_list = [a.name for a in paper.authors]
    if len(author_list) <= 5:
        authors = ', '.join(author_list)
    else:
        authors = ', '.join(author_list[:3] + ['...'] + author_list[-2:])
    
    # 处理机构
    if paper.affiliations is not None:
        affiliations = ', '.join(paper.affiliations[:3])
        if len(paper.affiliations) > 3:
            affiliations += ', ...'
    else:
        affiliations = ''
    
    # 相关度
    stars = get_stars_text(paper.score) if paper.score else ''
    
    # 链接
    links = f"[arXiv](https://arxiv.org/abs/{paper.arxiv_id}) | [PDF]({paper.pdf_url})"
    if paper.code_url:
        links += f" | [Code]({paper.code_url})"
    
    detail = f"**📝 {index}. {paper.title}**\n"
    if stars:
        detail += f"⭐ 相关度: {stars}\n"
    detail += f"👤 {authors}\n"
    if affiliations:
        detail += f"🏛️ {affiliations}\n"
    detail += f"🔗 {links}\n\n"
    
    # 英文原文 + 中文翻译
    detail += f"**Abstract (原文)**\n{paper.summary}\n\n"
    detail += f"**摘要 (中文翻译)**\n{paper.tldr}\n"
    
    return detail


def build_message_content(daily_papers: list[ArxivPaper], monthly_papers: list[ArxivPaper]) -> str:
    """构建消息内容 Markdown"""
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    total = len(daily_papers) + len(monthly_papers)
    
    content = f"**ArXiv Today** 📚\n{today}\n\n"
    content += f"今日找到了 **{total}** 篇相关论文\n\n"
    
    # 每日新论文表格
    if daily_papers:
        content += "---\n### 📅 今日最新\n\n"
        content += "| 序号 | 论文标题 | arXiv ID | 日期 | 链接 |\n"
        content += "|:---:|:---|:---|:---:|:---:|\n"
        for i, paper in enumerate(daily_papers, 1):
            content += build_paper_table_row(paper, i) + "\n"
        content += "\n"
    
    # 月度论文表格
    if monthly_papers:
        content += "---\n### 📊 月度精选\n\n"
        content += "| 序号 | 论文标题 | arXiv ID | 日期 | 链接 |\n"
        content += "|:---:|:---|:---|:---:|:---:|\n"
        for i, paper in enumerate(monthly_papers, 1):
            content += build_paper_table_row(paper, i) + "\n"
        content += "\n"
    
    return content


def build_detail_content(papers: list[ArxivPaper], section_title: str) -> str:
    """构建详细摘要内容"""
    if not papers:
        return ""
    
    content = f"---\n### {section_title}\n\n"
    for i, paper in enumerate(tqdm(papers, desc=f'Building {section_title}'), 1):
        content += build_paper_detail(paper, i) + "\n---\n"
        time.sleep(5)  # 生成 TLDR 需要调用 LLM
    
    return content


def send_feishu_message(
    webhook_url: str, 
    daily_papers: list[ArxivPaper], 
    monthly_papers: list[ArxivPaper] = None,
    secret: Optional[str] = None
) -> bool:
    """
    发送消息到飞书群
    
    Args:
        webhook_url: 飞书自定义机器人 webhook 地址
        daily_papers: 每日新论文列表
        monthly_papers: 月度论文列表
        secret: 签名密钥（可选）
    
    Returns:
        是否发送成功
    """
    if monthly_papers is None:
        monthly_papers = []
    
    if len(daily_papers) == 0 and len(monthly_papers) == 0:
        # 空消息
        message = {
            "msg_type": "interactive",
            "card": {
                "schema": "2.0",
                "header": {
                    "title": {"tag": "plain_text", "content": "📚 ArXiv Today"},
                    "template": "blue"
                },
                "body": {
                    "elements": [
                        {"tag": "markdown", "content": "**今日没有新论文，休息一下吧！** 🎉"}
                    ]
                }
            }
        }
    else:
        # 构建表格概览
        overview = build_message_content(daily_papers, monthly_papers)
        
        # 构建详细摘要
        daily_details = build_detail_content(daily_papers, "📅 今日最新 - 详细摘要")
        monthly_details = build_detail_content(monthly_papers, "📊 月度精选 - 详细摘要")
        
        full_content = overview + daily_details + monthly_details
        
        message = {
            "msg_type": "interactive",
            "card": {
                "schema": "2.0",
                "header": {
                    "title": {"tag": "plain_text", "content": "📚 ArXiv Today"},
                    "template": "blue"
                },
                "body": {
                    "elements": [
                        {"tag": "markdown", "content": full_content}
                    ]
                }
            }
        }
    
    # 如果设置了签名密钥，添加签名
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
            logger.success("飞书消息发送成功！")
            return True
        else:
            logger.error(f"飞书消息发送失败: {result}")
            return False
            
    except Exception as e:
        logger.error(f"飞书消息发送异常: {e}")
        return False
