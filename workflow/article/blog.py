import os
from datetime import datetime
from dateutil import tz
from loguru import logger

current_directory = os.path.dirname(os.path.abspath(__file__))


class Blog:
    metadata: str
    guide: str
    categories: list

    def __init__(self, metadata, guide, categories):
        self.metadata = metadata
        self.guide = guide
        self.categories = categories

    def make_blog(self):
        return self.metadata + self.guide + "\n".join(self.categories)


def make_daily_markdown_with(articles, rss_list):
    tags = []
    article_titles = []

    category_list = []
    # 文章列表有可能因为评分打乱了排序，再次从原始配置获取顺序
    for rss in rss_list:
        if rss.config["category"] not in category_list:
            category_list.append(rss.config["category"])

    category_contents = []
    for category in category_list:
        for article in articles:
            if article.config["category"] != category:
                continue
            tags.extend(article.evaluate.get("tags", []))
            article_titles.append(article.evaluate["title"])

        category_contents.append(make_daily_category(category=category, articles=articles))

    md_path, meta_data, backup_md_path = make_meta_data(description="\n".join(article_titles), tags=tags)
    daily_guide = make_daily_guide(article_titles)
    if len(category_contents) == 0:
        logger.error("category content is empty!")
        return
    blog = Blog(metadata=meta_data, guide=daily_guide, categories=category_contents)
    logger.info(f"make blog success: {meta_data}")
    if md_path:
        with open(md_path, "w") as fp:
            fp.write(blog.make_blog())
            logger.info(f"write to file: {md_path}")
    if backup_md_path:
        with open(backup_md_path, "w") as fp:
            fp.write(blog.make_blog())
            logger.debug(f"write to file: {backup_md_path}")


def make_meta_data(description, tags):
    time_zone = tz.gettz("Asia/Shanghai")
    today_with_timezone = datetime.today().astimezone(time_zone)
    today_str = today_with_timezone.strftime("%Y-%m-%d")

    # 获取当前项目的根目录
    project_root = os.path.dirname(current_directory)
    news_folder = f"{project_root}/../news/"
    logger.info(f"news folder: {news_folder}")
    os.makedirs(news_folder, exist_ok=True)
    md_title = f"Daily News #{today_str}"
    # Expected "tag" to match "[^\/#\?]+?"
    tags_str = "".join([f'- "{str(tag).replace('/', '_')}"\n' for tag in set(tags)])
    data = f"""---
title: "{md_title}"
date: "{today_with_timezone.strftime("%Y-%m-%d %H:%M:%S")}"
description: "{description}"
tags: 
{tags_str}
---
"""

    md_path = os.path.join(news_folder, f"dailyNews_{today_str}.md")
    backup_md_path = ""
    return md_path, data, backup_md_path


def make_daily_category(category, articles):
    if not articles:
        return ""
    content = ""
    for article in articles:
        if article.config["category"] != category:
            continue
        cover = f"![]({article.cover_url})" if article.cover_url else ""
        article_intro = f"""
### [{article.evaluate["title"]}]({article.link})

来源：{article.info["title"]}

发布时间：{article.date}
{cover}
{article.evaluate["summary"]}
"""
        content += article_intro
    if content:
        content = f"## {category}\n" + content
    return content


def make_daily_guide(titles):
    guide = "".join([f"> - {item}\n" for item in titles])
    return f"\n{guide}\n"
