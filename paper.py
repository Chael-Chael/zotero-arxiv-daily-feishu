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
                # 捕获 HTTP 错误
                if e.code == 404:
                    # 如果是 404 Not Found，说明源文件不存在，这是正常情况
                    logger.warning(f"Source for {self.arxiv_id} not found (404). Skipping source analysis.")
                    return None # 直接返回 None，后续依赖 tex 的代码会安全地处理
                else:
                    # 如果是其他 HTTP 错误 (如 503)，这可能是临时性问题，值得记录下来
                    logger.error(f"HTTP Error {e.code} when downloading source for {self.arxiv_id}: {e.reason}")
                    raise # 重新抛出异常，因为这可能是个需要关注的严重问题
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
    
    @cached_property
    def tldr(self) -> str:
        introduction = ""
        conclusion = ""
        if self.tex is not None:
            content = self.tex.get("all")
            if content is None:
                content = "\n".join(self.tex.values())
            #remove cite
            content = re.sub(r'~?\\cite.?\{.*?\}', '', content)
            #remove figure
            content = re.sub(r'\\begin\{figure\}.*?\\end\{figure\}', '', content, flags=re.DOTALL)
            #remove table
            content = re.sub(r'\\begin\{table\}.*?\\end\{table\}', '', content, flags=re.DOTALL)
            #find introduction and conclusion
            # end word can be \section or \end{document} or \bibliography or \appendix
            match = re.search(r'\\section\{Introduction\}.*?(\\section|\\end\{document\}|\\bibliography|\\appendix|$)', content, flags=re.DOTALL)
            if match:
                introduction = match.group(0)
            match = re.search(r'\\section\{Conclusion\}.*?(\\section|\\end\{document\}|\\bibliography|\\appendix|$)', content, flags=re.DOTALL)
            if match:
                conclusion = match.group(0)
        llm = get_llm()
        prompt = """请将以下论文的摘要翻译成__LANG__，保持完整性，不要过度简化或省略内容：

论文标题：__TITLE__

原文摘要：
__ABSTRACT__
"""
        prompt = prompt.replace('__LANG__', llm.lang)
        prompt = prompt.replace('__TITLE__', self.title)
        prompt = prompt.replace('__ABSTRACT__', self.summary)

        # use gpt-4o tokenizer for estimation
        enc = tiktoken.encoding_for_model("gpt-4o")
        prompt_tokens = enc.encode(prompt)
        prompt_tokens = prompt_tokens[:4000]  # truncate to 4000 tokens
        prompt = enc.decode(prompt_tokens)
        
        tldr = llm.generate(
            messages=[
                {
                    "role": "system",
                    "content": "你是一位专业的学术论文翻译助手，擅长将英文论文摘要准确、完整地翻译成目标语言。请保持学术风格，不要省略任何重要信息。",
                },
                {"role": "user", "content": prompt},
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
