import asyncio
import aiohttp
import json
import os
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import warnings
from bs4 import MarkupResemblesLocatorWarning
from datetime import datetime, timedelta

# 屏蔽 BS4 警告
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

VOD_FILE = 'vod.txt'
DISCOVERED_FILE = 'discovered.txt'
CONFIG_FILE = 'merged_tvbox_config.json'
CACHE_FILE = 'scan_cache.json'
CONCURRENT_LIMIT = 30
TIMEOUT = aiohttp.ClientTimeout(total=20)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

BAD_DOMAINS = {
    "baidu.com", "qq.com", "weibo.com", "github.com", "google.com", "cloudflare.com", "aliyun.com",
    "cnzz.com", "bdstatic.com", "googletagmanager.com", "google-analytics.com", "51.la",
    "facebook.com", "twitter.com", "youtube.com", "telegram.org"
}

KEYWORDS = {"vod", "maccms", "movie", "video", "tv", "yingshi", "ziyuan", "caiji"}

COMMON_PATHS = ["/api.php/provide/vod/", "/inc/apijson.php", "/api/xml.php", "/api/json.php"]

def normalize_url(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."): host = host[4:]
    return f"{parsed.scheme}://{host.rstrip('/')}"

def load_cache():
    return json.load(open(CACHE_FILE, 'r', encoding='utf-8')) if os.path.exists(CACHE_FILE) else {}

async def check_api(session, url):
    test_url = url.replace('/at/xml/', '/at/json/').replace('.xml', '.json')
    try:
        async with session.get(test_url, params={'ac': 'list'}, timeout=10, headers=HEADERS) as res:
            if res.status == 200:
                data = await res.json(content_type=None)
                # 深度校验：确保接口不仅返回分类，且含有视频列表及有效的播放地址字段
                if isinstance(data, dict):
                    vod_list = data.get("list", [])
                    if (len(data.get("class", [])) > 0 or len(vod_list) > 0):
                        # 如果存在视频列表，校验第一项是否含有播放地址，防止空壳站
                        if len(vod_list) > 0 and not vod_list[0].get("vod_play_url"):
                            return None, None
                        return test_url, data
    except: pass
    return None, None

async def probe_site(session, base_url, existing_apis, cache, discovered_set):
    today = datetime.now()
    norm_url = normalize_url(base_url)
    
    if norm_url in cache:
        last_check = datetime.strptime(cache[norm_url]['last_check'], '%Y-%m-%d')
        ttl = 7 if cache[norm_url].get('status') == 'verified' else 1
        if today - last_check < timedelta(days=ttl): return None

    try:
        async with session.get(base_url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True) as response:
            final_norm_url = normalize_url(str(response.url))
            html = await response.text(errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            
            # 强化发现机制：仅提取含特定关键字的域名链接
            for a in soup.find_all('a', href=True):
                full_link = urljoin(final_norm_url, a['href'])
                domain = urlparse(full_link).netloc.lower()
                if domain and domain != urlparse(final_norm_url).netloc:
                    clean_domain = domain.replace("www.", "")
                    if not any(clean_domain.endswith(b) for b in BAD_DOMAINS) and any(k in full_link for k in KEYWORDS):
                        discovered_set.add(f"{urlparse(full_link).scheme}://{domain}")

            title = soup.title.string.strip() if soup.title else urlparse(final_norm_url).netloc
            clean_name = re.sub(r'【.*?】|[-_].*|官网|官方|地址|域名|首页|采集站|资源站|发布页|影视|视频', '', title).strip()[:20]
            
            candidates = set(COMMON_PATHS)
            candidates.update(re.findall(r'/[/\w\-]+api\.php[^\s"\']*', html))
            for a in soup.find_all('a', href=True):
                if 'api' in a['href']: candidates.add(a['href'])

            for raw_api in candidates:
                api_url = urljoin(final_norm_url, raw_api).rstrip('./,; ')
                if api_url in existing_apis: continue
                final_api, data = await check_api(session, api_url)
                if final_api:
                    cache[final_norm_url] = {'last_check': today.strftime('%Y-%m-%d'), 'status': 'verified'}
                    return {
                        "key": urlparse(final_norm_url).netloc.replace('.', '_'),
                        "name": clean_name or "未知站点",
                        "type": 1, "api": final_api, "status": "verified",
                        "searchable": 1, "quickSearch": 1,
                        "categories": [c.get("type_name") for c in data.get('class', []) if c.get("type_name")][:12]
                    }
            cache[final_norm_url] = {'last_check': today.strftime('%Y-%m-%d'), 'status': 'failed'}
    except:
        cache[norm_url] = {'last_check': today.strftime('%Y-%m-%d'), 'status': 'failed'}
    return None

async def main():
    if not os.path.exists(VOD_FILE): return
    
    # 初始化固定的配置结构
    config_data = {
       # "spider": "https://gh.api.99988866.xyz/https://raw.githubusercontent.com/zhixc/CatVodTVSpider/main/jar/custom_spider.jar;md5;88f30019e7618e8dd5e6459ec4ae8bef",
        "lives": [
            {
                "name": "muzhi1991",
                "type": 0,
                "url": "https://gist.githubusercontent.com/muzhi1991/f03c212ce91f36d3669bebc062cc8405/raw/2f9c147b69dd9ef6794183966660a8006d9a6865/MyHomeIPTV.m3u",
                "playerType": 1,
                "epg": "http://epg.112114.xyz/?ch={name}&date={date}",
                "ua": "Mozilla/5.0(WindowsNT10.0;Win64;x64)AppleWebKit/537.36(KHTML,likeGecko)Chrome/108.0.0.0Safari/537.36"
            }
        ],
        "sites": []
    }
    
    # 如果存在已有的配置文件，合并 sites
    if os.path.exists(CONFIG_FILE):
        try:
            old_config = json.load(open(CONFIG_FILE, 'r', encoding='utf-8'))
            config_data['sites'] = old_config.get('sites', [])
        except: pass
        
    existing_apis = {s['api'] for s in config_data['sites']}
    
    # 持久化去重
    cache = load_cache()
    discovered_set = {line.strip() for line in open(DISCOVERED_FILE, 'r', encoding='utf-8')} if os.path.exists(DISCOVERED_FILE) else set()
    urls = list(set([l.strip() for l in open(VOD_FILE, 'r', encoding='utf-8-sig') if l.strip().startswith('http')]))

    connector = aiohttp.TCPConnector(limit=CONCURRENT_LIMIT, limit_per_host=3, ttl_dns_cache=300, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [probe_site(session, url, existing_apis, cache, discovered_set) for url in urls]
        results = await asyncio.gather(*tasks)

    for site in results:
        if site and site['api'] not in existing_apis:
            config_data['sites'].append(site)
            existing_apis.add(site['api'])

    json.dump(config_data, open(CONFIG_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    with open(DISCOVERED_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(discovered_set)) + '\n')
    json.dump(cache, open(CACHE_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    
    print(f"🎉 任务完成！当前发现池 {len(discovered_set)} 个，新增有效源 {len([s for s in results if s])} 个")

if __name__ == "__main__":
    asyncio.run(main())
