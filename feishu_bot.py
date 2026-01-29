"""
飞书自定义机器人消息发送模块
"""
import hashlib
import base64
import hmac
import time
import requests
from typing import Optional
from loguru import logger
from paper import ArxivPaper
from tqdm import tqdm
import math


def gen_sign(timestamp: int, secret: str) -> str:
    """
    生成签名字符串用于飞书机器人安全校验
    
    Args:
        timestamp: 时间戳（秒）
        secret: 签名密钥
    
    Returns:
        签名字符串
    """
    string_to_sign = '{}\n{}'.format(timestamp, secret)
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(hmac_code).decode('utf-8')
    return sign


def get_stars_text(score: float) -> str:
    """
    根据相关度分数生成星级文本
    """
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


def build_paper_card(paper: ArxivPaper, index: int) -> dict:
    """
    构建单篇论文的飞书卡片元素
    
    Args:
        paper: 论文对象
        index: 论文序号
    
    Returns:
        飞书卡片元素字典
    """
    # 处理作者列表
    author_list = [a.name for a in paper.authors]
    if len(author_list) <= 5:
        authors = ', '.join(author_list)
    else:
        authors = ', '.join(author_list[:3] + ['...'] + author_list[-2:])
    
    # 处理机构
    if paper.affiliations is not None:
        affiliations = paper.affiliations[:5]
        affiliations_str = ', '.join(affiliations)
        if len(paper.affiliations) > 5:
            affiliations_str += ', ...'
    else:
        affiliations_str = 'Unknown Affiliation'
    
    # 相关度星级
    stars = get_stars_text(paper.score) if paper.score else ''
    relevance_text = f"**Relevance:** {stars}" if stars else ""
    
    # 构建按钮
    buttons = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📄 PDF"},
            "type": "primary",
            "url": paper.pdf_url
        }
    ]
    
    if paper.code_url:
        buttons.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "💻 Code"},
            "type": "default",
            "url": paper.code_url
        })
    
    # 构建论文卡片元素
    elements = [
        {
            "tag": "markdown",
            "content": f"**{index}. {paper.title}**"
        },
        {
            "tag": "markdown",
            "content": f"👤 {authors}\n🏛️ *{affiliations_str}*"
        }
    ]
    
    if relevance_text:
        elements.append({
            "tag": "markdown",
            "content": relevance_text
        })
    
    elements.append({
        "tag": "markdown",
        "content": f"📝 **TLDR:** {paper.tldr}"
    })
    
    elements.append({
        "tag": "markdown",
        "content": f"🔗 arXiv: [{paper.arxiv_id}](https://arxiv.org/abs/{paper.arxiv_id})"
    })
    
    elements.append({
        "tag": "action",
        "actions": buttons
    })
    
    elements.append({
        "tag": "hr"
    })
    
    return elements


def build_empty_card() -> dict:
    """
    构建空结果的飞书卡片
    """
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "📚 Daily arXiv 推荐"},
                "template": "blue"
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": "**今日没有新论文，休息一下吧！** 🎉"
                    }
                ]
            }
        }
    }


def build_full_card(papers: list[ArxivPaper]) -> dict:
    """
    构建完整的飞书卡片消息
    
    Args:
        papers: 论文列表
    
    Returns:
        飞书卡片消息字典
    """
    import datetime
    today = datetime.datetime.now().strftime('%Y/%m/%d')
    
    elements = [
        {
            "tag": "markdown",
            "content": f"共推荐 **{len(papers)}** 篇论文，按相关度排序"
        },
        {
            "tag": "hr"
        }
    ]
    
    for i, paper in enumerate(tqdm(papers, desc='Building Feishu Card'), 1):
        paper_elements = build_paper_card(paper, i)
        elements.extend(paper_elements)
        time.sleep(10)  # 与原有邮件渲染保持一致的延迟
    
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": f"📚 Daily arXiv 推荐 - {today}"},
                "template": "blue"
            },
            "body": {
                "elements": elements
            }
        }
    }


def send_feishu_message(webhook_url: str, papers: list[ArxivPaper], secret: Optional[str] = None) -> bool:
    """
    发送消息到飞书群
    
    Args:
        webhook_url: 飞书自定义机器人 webhook 地址
        papers: 论文列表
        secret: 签名密钥（可选）
    
    Returns:
        是否发送成功
    """
    if len(papers) == 0:
        message = build_empty_card()
    else:
        message = build_full_card(papers)
    
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
            timeout=30
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
