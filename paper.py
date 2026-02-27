from typing import Optional
from functools import cached_property
from tempfile import TemporaryDirectory
import arxiv
import tarfile
import re
import time
from llm import get_llm
import requests
from requests.adapters import HTTPAdapter, Retry
from loguru import logger
import tiktoken
from contextlib import ExitStack
from urllib.error import HTTPError
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from openai import OpenAI



class ArxivPaper:
    def __init__(self,paper:arxiv.Result):
        self._paper = paper
        self.score = None
    
    @property
    def title(self) -> str:
        return self._paper.title
    
    @property
    def summary(self) -> str:
        return self._paper.summary
    
    @property
    def authors(self) -> list[str]:
        return self._paper.authors
    
    @cached_property
    def arxiv_id(self) -> str:
        return re.sub(r'v\d+$', '', self._paper.get_short_id())
    
    @property
    def pdf_url(self) -> str:
        if self._paper.pdf_url is not None:
            return self._paper.pdf_url
        
        pdf_url = f"https://arxiv.org/pdf/{self.arxiv_id}.pdf"
        if self._paper.links is not None:
            pdf_url = self._paper.links[0].href.replace('abs','pdf')

        ## Assign pdf_url to self._paper.pdf_url for pdf downloading (Issue #119)
        self._paper.pdf_url = pdf_url

        return pdf_url
    
    @cached_property
    def code_url(self) -> Optional[str]:
        s = requests.Session()
        retries = Retry(total=5, backoff_factor=0.1)
        s.mount('https://', HTTPAdapter(max_retries=retries))
        try:
            paper_list = s.get(f'https://paperswithcode.com/api/v1/papers/?arxiv_id={self.arxiv_id}').json()
        except Exception as e:
            logger.debug(f'Error when searching {self.arxiv_id}: {e}')
            return None

        if paper_list.get('count',0) == 0:
            return None
        paper_id = paper_list['results'][0]['id']

        try:
            repo_list = s.get(f'https://paperswithcode.com/api/v1/papers/{paper_id}/repositories/').json()
        except Exception as e:
            logger.debug(f'Error when searching {self.arxiv_id}: {e}')
            return None
        if repo_list.get('count',0) == 0:
            return None
        return repo_list['results'][0]['url']
    
    @cached_property
    def tex(self) -> dict[str,str]:
        with ExitStack() as stack:
            tmpdirname = stack.enter_context(TemporaryDirectory())
            # file = self._paper.download_source(dirpath=tmpdirname)
            try:
                # 尝试下载源文件
                file = self._paper.download_source(dirpath=tmpdirname)
            except HTTPError as e:
                # 捕获 HTTP 错误 (404=源文件不存在, 403=禁止访问, 503=服务暂不可用 等)
                logger.warning(f"Source for {self.arxiv_id} not available (HTTP {e.code}). Skipping source analysis.")
                return None
            except Exception as e:
                logger.error(f"Error when downloading source for {self.arxiv_id}: {e}")
                return None
            try:
                tar = stack.enter_context(tarfile.open(file))
            except tarfile.ReadError:
                logger.debug(f"Failed to find main tex file of {self.arxiv_id}: Not a tar file.")
                return None
 
            tex_files = [f for f in tar.getnames() if f.endswith('.tex')]
            if len(tex_files) == 0:
                logger.debug(f"Failed to find main tex file of {self.arxiv_id}: No tex file.")
                return None
            
            bbl_file = [f for f in tar.getnames() if f.endswith('.bbl')]
            match len(bbl_file) :
                case 0:
                    if len(tex_files) > 1:
                        logger.debug(f"Cannot find main tex file of {self.arxiv_id} from bbl: There are multiple tex files while no bbl file.")
                        main_tex = None
                    else:
                        main_tex = tex_files[0]
                case 1:
                    main_name = bbl_file[0].replace('.bbl','')
                    main_tex = f"{main_name}.tex"
                    if main_tex not in tex_files:
                        logger.debug(f"Cannot find main tex file of {self.arxiv_id} from bbl: The bbl file does not match any tex file.")
                        main_tex = None
                case _:
                    logger.debug(f"Cannot find main tex file of {self.arxiv_id} from bbl: There are multiple bbl files.")
                    main_tex = None
            if main_tex is None:
                logger.debug(f"Trying to choose tex file containing the document block as main tex file of {self.arxiv_id}")
            #read all tex files
            file_contents = {}
            for t in tex_files:
                f = tar.extractfile(t)
                content = f.read().decode('utf-8',errors='ignore')
                #remove comments
                content = re.sub(r'%.*\n', '\n', content)
                content = re.sub(r'\\begin{comment}.*?\\end{comment}', '', content, flags=re.DOTALL)
                content = re.sub(r'\\iffalse.*?\\fi', '', content, flags=re.DOTALL)
                #remove redundant \n
                content = re.sub(r'\n+', '\n', content)
                content = re.sub(r'\\\\', '', content)
                #remove consecutive spaces
                content = re.sub(r'[ \t\r\f]{3,}', ' ', content)
                if main_tex is None and re.search(r'\\begin\{document\}', content):
                    main_tex = t
                    logger.debug(f"Choose {t} as main tex file of {self.arxiv_id}")
                file_contents[t] = content
            
            if main_tex is not None:
                main_source:str = file_contents[main_tex]
                #find and replace all included sub-files
                include_files = re.findall(r'\\input\{(.+?)\}', main_source) + re.findall(r'\\include\{(.+?)\}', main_source)
                for f in include_files:
                    if not f.endswith('.tex'):
                        file_name = f + '.tex'
                    else:
                        file_name = f
                    main_source = main_source.replace(f'\\input{{{f}}}', file_contents.get(file_name, ''))
                file_contents["all"] = main_source
            else:
                logger.debug(f"Failed to find main tex file of {self.arxiv_id}: No tex file containing the document block.")
                file_contents["all"] = None
        return file_contents
    
    def _clean_tex_content(self) -> Optional[str]:
        """清理 TeX 内容，移除引用、图表、公式等非文本元素"""
        if self.tex is None:
            return None
        content = self.tex.get("all")
        if content is None:
            content = "\n".join(self.tex.values())
        # remove cite
        content = re.sub(r'~?\\cite.?\{.*?\}', '', content)
        # remove figure
        content = re.sub(r'\\begin\{figure\}.*?\\end\{figure\}', '', content, flags=re.DOTALL)
        content = re.sub(r'\\begin\{figure\*\}.*?\\end\{figure\*\}', '', content, flags=re.DOTALL)
        # remove table
        content = re.sub(r'\\begin\{table\}.*?\\end\{table\}', '', content, flags=re.DOTALL)
        content = re.sub(r'\\begin\{table\*\}.*?\\end\{table\*\}', '', content, flags=re.DOTALL)
        # remove bibliography
        content = re.sub(r'\\begin\{thebibliography\}.*?\\end\{thebibliography\}', '', content, flags=re.DOTALL)
        content = re.sub(r'\\bibliography\{.*?\}', '', content)
        # remove preamble (before \begin{document})
        doc_start = re.search(r'\\begin\{document\}', content)
        if doc_start:
            content = content[doc_start.end():]
        # remove \end{document}
        content = re.sub(r'\\end\{document\}', '', content)
        return content.strip()

    def _get_html_content(self) -> Optional[str]:
        """从 arXiv HTML 页面获取论文纯文本内容，作为 TeX 不可用时的降级方案"""
        url = f"https://arxiv.org/html/{self.arxiv_id}"
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                logger.debug(f"HTML version not available for {self.arxiv_id}")
                return None
        except Exception as e:
            logger.debug(f"Failed to fetch HTML for {self.arxiv_id}: {e}")
            return None
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 移除不需要的元素
        for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer']):
            tag.decompose()
        for tag in soup.find_all('figure'):
            tag.decompose()
        for tag in soup.find_all('table'):
            tag.decompose()
        # 移除参考文献部分
        for tag in soup.find_all(class_=re.compile(r'ltx_bibliography|ltx_references')):
            tag.decompose()
        
        # 获取主要文章内容
        article = soup.find('article') or soup.find(class_='ltx_document') or soup.find('body')
        if article is None:
            return None
        
        text = article.get_text(separator='\n', strip=True)
        # 清理多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        if len(text) < 100:  # 内容太短，可能不是有效的论文页面
            return None
        
        return text

    @cached_property
    def tldr(self) -> str:
        llm = get_llm()
        enc = tiktoken.encoding_for_model("gpt-4o")
        is_online_model = isinstance(llm.llm, OpenAI)
        
        # 三级降级策略：TeX全文 → HTML全文 → 摘要翻译
        paper_content = None
        content_source = None
        
        if is_online_model:
            # 优先尝试 TeX
            paper_content = self._clean_tex_content()
            if paper_content:
                content_source = "TeX"
            else:
                # TeX 不可用，尝试 HTML
                paper_content = self._get_html_content()
                if paper_content:
                    content_source = "HTML"
        
        if paper_content and content_source:
            # 使用完整论文内容 + 深度解读 prompt
            system_prompt = (
                "你是顶尖大学资深教授，精通【人工智能和计算机科学】领域。逻辑思维清晰。"
                "你现在的任务是帮助科研人员快速透彻地理解一篇学术论文。"
                "你需要将晦涩的学术语言转化为逻辑清晰、通俗易懂的中文讲解。\n"
                "语气风格：像一位耐心的导师，用'口语化'但'逻辑严密'的方式讲解。\n"
                "核心原则：遇到专业术语时，必须先用一个生活中的比喻/例子来解释它，然后再讲它的学术定义。\n"
                "格式要求：使用 Markdown 格式，使用加粗来突出重点，使用引用块来解释概念。"
            )
            
            user_prompt = f"""请读取以下论文的完整内容，并严格按照以下三个板块进行输出：

## ⚡ 核心三问 (The Elevator Pitch)
用最简练的语言（每个问题不超过 3 句话）直击要害：

**Q1: 这篇论文试图解决什么核心痛点/问题？** (What is the problem?)

**Q2: 作者提出了什么新的"杀手锏"方法/架构？** (What is the method?)
(简要说明该方法的核心创新点，区别于传统方法的地方)

**Q3: 最终效果/结论如何？** (What are the results?)
(列出 1-2 个关键数据证明其有效性)

## 📖 逻辑故事还原 (The Logic Flow)
不要堆砌技术细节，而是还原作者的思考路径。请按"起承转合"的结构讲解：

**背景 (Context):** 为什么大家之前解决不好这个问题？（现有方法的缺陷）

**破局 (Insight):** 作者是怎么灵光一现的？他的核心直觉 (Intuition) 是什么？
👉 [请插入一个通俗的比喻来解释这个核心直觉]

**拆解 (Deconstruction):** 这个方法具体分哪几步实现的？（用 1, 2, 3 列表简洁描述输入到输出的过程）

## 🔍 关键细节与启示 (Details & Takeaway)

**技术细节补充：** 补充 1-2 个最关键的技术实现细节（比如某个特殊的 Loss Function 或数据处理技巧）。

**一句话总结：** 如果我明天要在组会上介绍这篇文章，请给我一句最精辟的总结语。

---

论文标题：{self.title}

论文完整内容（来源：{content_source}）：
{paper_content}
"""
            # 截断到 100k tokens 以适应 128k 上下文窗口（留空间给 system prompt 和输出）
            prompt_tokens = enc.encode(user_prompt)
            original_token_count = len(prompt_tokens)
            if original_token_count > 100000:
                logger.warning(f"[{self.arxiv_id}] 论文内容过长，从 {original_token_count} tokens 截断到 100000 tokens")
                prompt_tokens = prompt_tokens[:100000]
                user_prompt = enc.decode(prompt_tokens)
            
            logger.info(f"[{self.arxiv_id}] 全文解读模式（{content_source}）| 原文 {original_token_count} tokens，实际发送 {len(prompt_tokens)} tokens")
        else:
            # 降级模式：仅翻译摘要（用于本地模型或无 TeX/HTML 的情况）
            system_prompt = "你是一位专业的学术论文翻译助手，擅长将英文论文摘要准确、完整地翻译成目标语言。请保持学术风格，不要省略任何重要信息。"
            user_prompt = f"""请将以下论文的摘要翻译成{llm.lang}，保持完整性，不要过度简化或省略内容：

论文标题：{self.title}

原文摘要：
{self.summary}
"""
            prompt_tokens = enc.encode(user_prompt)
            prompt_tokens = prompt_tokens[:4000]
            user_prompt = enc.decode(prompt_tokens)
            
            logger.info(f"[{self.arxiv_id}] 摘要翻译模式（降级）| {len(prompt_tokens)} tokens")

        tldr = llm.generate(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        return tldr

    @cached_property
    def affiliations(self) -> Optional[list[str]]:
        if self.tex is not None:
            content = self.tex.get("all")
            if content is None:
                content = "\n".join(self.tex.values())
            #search for affiliations
            possible_regions = [r'\\author.*?\\maketitle',r'\\begin{document}.*?\\begin{abstract}']
            matches = [re.search(p, content, flags=re.DOTALL) for p in possible_regions]
            match = next((m for m in matches if m), None)
            if match:
                information_region = match.group(0)
            else:
                logger.debug(f"Failed to extract affiliations of {self.arxiv_id}: No author information found.")
                return None
            prompt = f"Given the author information of a paper in latex format, extract the affiliations of the authors in a python list format, which is sorted by the author order. If there is no affiliation found, return an empty list '[]'. Following is the author information:\n{information_region}"
            # use gpt-4o tokenizer for estimation
            enc = tiktoken.encoding_for_model("gpt-4o")
            prompt_tokens = enc.encode(prompt)
            prompt_tokens = prompt_tokens[:4000]  # truncate to 4000 tokens
            prompt = enc.decode(prompt_tokens)
            llm = get_llm()
            affiliations = llm.generate(
                messages=[
                    {
                        "role": "system",
                        "content": "You are an assistant who perfectly extracts affiliations of authors from the author information of a paper. You should return a python list of affiliations sorted by the author order, like ['TsingHua University','Peking University']. If an affiliation is consisted of multi-level affiliations, like 'Department of Computer Science, TsingHua University', you should return the top-level affiliation 'TsingHua University' only. Do not contain duplicated affiliations. If there is no affiliation found, you should return an empty list [ ]. You should only return the final list of affiliations, and do not return any intermediate results.",
                    },
                    {"role": "user", "content": prompt},
                ]
            )

            try:
                affiliations = re.search(r'\[.*?\]', affiliations, flags=re.DOTALL).group(0)
                affiliations = eval(affiliations)
                affiliations = list(set(affiliations))
                affiliations = [str(a) for a in affiliations]
            except Exception as e:
                logger.debug(f"Failed to extract affiliations of {self.arxiv_id}: {e}")
                return None
            return affiliations

    @cached_property
    def affiliations_from_html(self) -> Optional[list[str]]:
        """从 arXiv HTML 页面提取作者机构信息"""
        url = f"https://arxiv.org/html/{self.arxiv_id}"
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                logger.debug(f"HTML version not available for {self.arxiv_id}")
                return self.affiliations  # 回退到 LaTeX 提取
        except Exception as e:
            logger.debug(f"Failed to fetch HTML for {self.arxiv_id}: {e}")
            return self.affiliations
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        affiliations = []
        
        # 尝试从作者区域提取机构信息
        # arXiv HTML 通常在 .ltx_authors 或 .authors 类中包含作者信息
        author_section = soup.find(class_='ltx_authors') or soup.find(class_='authors')
        if author_section:
            # 查找机构标签（通常是 .ltx_role_affiliation 或带有 affiliation 的元素）
            affil_elements = author_section.find_all(class_='ltx_role_affiliation')
            if not affil_elements:
                affil_elements = author_section.find_all(class_='ltx_contact_affiliation')
            if not affil_elements:
                # 尝试查找 superscript 标注的机构
                affil_elements = soup.find_all(class_='ltx_note_content')
            
            for elem in affil_elements:
                text = elem.get_text(strip=True)
                if text and len(text) > 2 and text not in affiliations:
                    affiliations.append(text)
        
        if affiliations:
            # 去重并限制数量
            seen = set()
            unique_affiliations = []
            for aff in affiliations:
                # 简化机构名（取第一部分或保留前50字符）
                aff_clean = aff[:80]
                if aff_clean not in seen:
                    seen.add(aff_clean)
                    unique_affiliations.append(aff_clean)
            return unique_affiliations[:5]  # 最多返回5个机构
        
        # 回退到 LaTeX 提取
        return self.affiliations

    @cached_property
    def framework_figure(self) -> Optional[str]:
        """获取论文框架图 URL（通过解析 arXiv HTML + LLM 选择）"""
        url = f"https://arxiv.org/html/{self.arxiv_id}"
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                logger.debug(f"HTML version not available for {self.arxiv_id}")
                return None
        except Exception as e:
            logger.debug(f"Failed to fetch HTML for {self.arxiv_id}: {e}")
            return None
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        figures_info = []
        
        for fig in soup.find_all('figure'):
            img = fig.find('img')
            caption = fig.find('figcaption')
            if img and img.get('src'):
                figures_info.append({
                    'url': urljoin(url, img['src']),
                    'caption': caption.get_text(strip=True)[:200] if caption else '',
                    'alt': img.get('alt', '')[:100]
                })
        
        if not figures_info:
            logger.debug(f"No figures found in HTML for {self.arxiv_id}")
            return None
        
        if len(figures_info) == 1:
            return figures_info[0]['url']
        
        # 使用 LLM 选择模型框架图
        prompt = "以下是一篇论文的图片描述列表，请选出最能展示模型框架/架构的那张图，只返回其索引(0-based数字)，如果没有框架图则返回-1:\n"
        for i, fig in enumerate(figures_info):
            caption_text = fig['caption'] or fig['alt'] or '(无描述)'
            prompt += f"{i}: {caption_text}\n"
        
        llm = get_llm()
        try:
            result = llm.generate(
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个学术论文图片分析助手。请根据图片描述选出展示模型架构/框架的图片。只返回一个数字索引，不要其他内容。",
                    },
                    {"role": "user", "content": prompt},
                ]
            )
            idx = int(re.search(r'-?\d+', result).group(0))
            if 0 <= idx < len(figures_info):
                return figures_info[idx]['url']
        except Exception as e:
            logger.debug(f"Failed to select framework figure for {self.arxiv_id}: {e}")
        
        # 回退：返回第一张图
        return figures_info[0]['url']
