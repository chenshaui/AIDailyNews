import feedparser
import html2text
import os, json, re
from datetime import datetime, timedelta
from dateutil import tz
import dateparser
import requests
from bs4 import BeautifulSoup
from loguru import logger
from markdown import markdown
import base64
import time

# 统一时区
time_zone_value = "Asia/Shanghai"


class Article:
    title: str
    summary: str
    link: str
    cover_url: str  # 封面链接
    date: str
    info: dict
    # rss 配置信息
    config: dict
    evaluate: dict = None  # 来源于ai生成

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @staticmethod
    def make_with_dict(obj_dict):
        rss = Article()
        for key, value in obj_dict.items():
            setattr(rss, key, value)
        return rss


def load_rss_configs(resource):
    rss_configs = {}
    rss_categories = []
    rss_items = []

    def load_config_with(path):
        try:
            logger.info(f"Loading RSS configuration from {path}")
            with open(path, "r", encoding='utf-8') as fp:
                # 检查文件是否为空
                if fp.read().strip() == "":
                    raise ValueError(f"The file {path} is empty.")
                fp.seek(0)  # 重置文件指针
                data = json.loads(fp.read())
                rss_categories.extend(data.get("categories", []))
                rss_configs.update(data.get("configuration", {}))
        except (IOError, ValueError) as e:
            logger.error(f"Error reading or parsing file {path}: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON in file {path}: {e}")

    if os.path.isdir(resource):
        for file in os.listdir(resource):
            load_config_with(os.path.join(resource, file))
    else:
        load_config_with(resource)

    for rss_category in rss_categories:
        for rss in rss_category["items"]:
            rss["category"] = rss_category.get("category", "Daily News")
            if "rsshub_path" in rss:
                rss["url"] = rss_configs["rsshub_domain"] + rss["rsshub_path"]
            rss_items.append(rss)

    return rss_items


def parse_rss_config(rss_config):
    """仅获取当天的rss信息"""
    res = feedparser.parse(rss_config["url"],
                           agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    keymap = res.keymap
    today_rss = []
    # 默认一个rss源只获取一定数量信息
    max_count = rss_config.get("input_count", 4)

    for article in res[keymap["items"]]:
        # 获取当天信息
        time_zone = tz.gettz(time_zone_value)
        target_date = datetime.today().astimezone(time_zone).date()
        # issued > date > res.date
        article_date = unify_timezone(article.get(keymap["issued"],
                                                  article.get(keymap["date"],
                                                              res.get(keymap["date"]))))
        if article_date.date() != target_date:
            # logger.warning(f'{rss_config["url"]} content of {article_date.date()} is not equal to {target_date}')
            continue
        rss = gen_article_from(rss_item=article, rss_type=rss_config.get("type"),
                               image_enable=rss_config.get("image_enable", False),
                               rss_date=article_date.strftime("%Y-%m-%d %H:%M:%S"), channel=res[keymap["channel"]],
                               config=rss_config)
        if rss is None:
            # logger.warning(f'{rss_config["url"]} content is empty')
            continue
        today_rss.append(rss)
        if len(today_rss) >= max_count:
            logger.warning(f'{rss_config["url"]} content count of today is over {max_count}, break')
            return today_rss
    # 防止一个地址有过多内容，这里限定下数量
    if len(today_rss) == 0:
        logger.info(f'{rss_config["url"]} content of today is empty')
    else:
        logger.info(f'{rss_config["url"]} content count of today is {len(today_rss)}')
    return today_rss


def gen_article_from(rss_item, rss_type, image_enable=False, rss_date=None, channel=None, config=None):
    title = rss_item["title"]
    link = rss_item["link"]
    summary_raw = rss_item.get("summary", "")
    image_url = ""

    if rss_type == "link":
        summary = parse_web_page(url=link)
    elif rss_type == "code":
        summary = parse_github_readme(link)
    else:
        summary, image_url = transform_html2txt(summary_raw, image_enable=image_enable)

    if not summary or len(summary) < 10:
        return None

    article = Article(title=title,
                      summary=summary,
                      link=link,
                      date=rss_date,
                      info=channel,
                      config=config,
                      cover_url=image_url)
    return article


def transform_html2txt(content, image_enable=False):
    html_transform = html2text.HTML2Text(bodywidth=0)
    html_transform.ignore_links = True
    html_transform.ignore_images = not image_enable
    html_transform.ignore_tables = True
    html_transform.ignore_emphasis = True
    text = html_transform.handle(content)
    image_url = ""
    if image_enable:
        name, image_url = extract_image_links(text)
    return text, image_url


def unify_timezone(date_string):
    str_date = dateparser.parse(date_string,
                                settings={"TIMEZONE": time_zone_value,
                                          "RETURN_AS_TIMEZONE_AWARE": True})
    return str_date


def parse_web_page(url):
    try:
        response = requests.get(url, verify=False)
        logger.debug(f"fetch {url} status code: {response.status_code}")
        if response.status_code == 200:
            # 指定编码方式
            response.encoding = response.apparent_encoding
            # 使用BeautifulSoup解析HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            # 提取限定标签，简化取网页内容流程
            tags = soup.find_all(["h1", "h2", "p", "code"])
            # 不处理标签嵌套内容
            tags_text = [tag.get_text() for tag in tags if not tag.next.name]
            extracted_text = '\n'.join(tags_text)
            return extracted_text.strip()
        else:
            logger.error(f"fetch {url} failed. Status code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        logger.exception(f"fetch {url} get error: {e}")
        return None


def extract_image_links(text):
    # 定义匹配Markdown格式图片链接的正则表达式，输出为元组格式
    image_link_regex = r"!\[(.*?)\]\((.*?)\)"
    image_links = re.findall(image_link_regex, text)
    if image_links:
        return image_links[0]
    return "", ""


def parse_github_readme(repo_url):
    try:
        username, repo_name = repo_url.split("/")[-2:]
        api_url = f"https://api.github.com/repos/{username}/{repo_name}/readme"
        headers = {'Accept': 'application/vnd.github.v3+json'}
        retry_count = 0
        max_retries = 3

        while retry_count < max_retries:
            response = requests.get(api_url, headers=headers)
            logger.debug(f"fetch {api_url} status code: {response.status_code}")

            if response.status_code == 200:
                break
            elif response.status_code == 403 and 'X-RateLimit-Reset' in response.headers:
                reset_time = int(response.headers['X-RateLimit-Reset'])
                sleep_time = max(0, reset_time - time.time())
                sleep_time = min(sleep_time, 5)
                logger.warning(f"Rate limit exceeded. Sleeping for {sleep_time} seconds.")
                time.sleep(sleep_time)
                retry_count += 1
            else:
                response.raise_for_status()

        if retry_count == max_retries:
            logger.error(f"Max retries reached for {api_url}")
            return ''

        readme_content = response.json()["content"]
        readme_content = base64.b64decode(readme_content).decode("utf-8")

        html = markdown(readme_content)
        html = re.sub(r'<pre>(.*?)</pre>', '', html, flags=re.DOTALL)
        html = re.sub(r'<code>(.*?)</code>', '', html, flags=re.DOTALL)
        html = re.sub(r'```(.*?)```', '', html, flags=re.DOTALL)
        soup = BeautifulSoup(html, "html.parser")
        text = ''.join(soup.findAll(string=True))
        return text.strip()
    except Exception as e:
        logger.error(f"fetch {repo_url} get error: {e}")
        return None


def get_real_url(short_url):
    # get real url from short url
    response = requests.head(short_url, allow_redirects=True)
    return response.url


def rss_env():
    os.environ[""] = ""

if __name__ == '__main__':
    url = "https://www.theverge.com/2024/9/3/24234777/microsoft-apple-cloud-gaming-app-store-changes-xbox-cma"
    content = parse_web_page(url)
    print(content)
    url = "https://github.com/hmlongco/Factory"
    content = parse_github_readme(url)
    print(content)

