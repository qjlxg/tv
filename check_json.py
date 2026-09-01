import asyncio
import aiohttp
import json
import os
import time
import shutil

CONFIG_FILE = 'merged_tvbox_config.json'
# 提高并发到 200-500
CONCURRENT_LIMIT = 300 
# 缩短超时时间：连接 5s，总计 10s。检测存活不需要等太久
TIMEOUT = aiohttp.ClientTimeout(total=10, connect=5)

async def verify_site(session, site):
    """极致快速验证单个站点的 API 是否在线"""
    api_url = site.get('api')
    
    # 增加 ac=list 确保不是伪 200 页面
    try:
        async with session.get(api_url, params={'ac': 'list'}, timeout=TIMEOUT) as resp:
            # 只要是 200 且返回内容非空，即视为存活
            if resp.status == 200:
                # 尝试读取并校验 JSON 格式及内容
                try:
                    data = await resp.json(content_type=None)
                    # 必须包含 list 字段且不能为空
                    if isinstance(data, dict) and data.get("list"):
                        return site
                except:
                    # 如果不是有效的 JSON，则视为无效站
                    return None
    except:
        pass
    
    return None

async def main():
    if not os.path.exists(CONFIG_FILE):
        return

    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        try:
            config_data = json.load(f)
        except: return

    sites = config_data.get('sites', [])
    start_time = time.time()
    print(f"🚀 启动高速检测，并发数: {CONCURRENT_LIMIT}，总站数: {len(sites)}")

    # 优化连接器：禁用 SSL 检查，增大连接池，强制关闭连接
    connector = aiohttp.TCPConnector(
        limit=CONCURRENT_LIMIT, 
        ssl=False, 
        force_close=True, # 验证完即断开，释放句柄
        ttl_dns_cache=300, # 缓存 DNS 5 分钟
        family=2 # 强制使用 IPv4，防止 IPv6 网络问题
    )
    
    async with aiohttp.ClientSession(connector=connector) as session:
        # 使用 Semaphore 控制并发频率，防止过快被防火墙拦截
        sem = asyncio.Semaphore(CONCURRENT_LIMIT)
        
        async def sem_verify(site):
            async with sem:
                return await verify_site(session, site)

        tasks = [sem_verify(site) for site in sites]
        verified_results = await asyncio.gather(*tasks)

    active_sites = [s for s in verified_results if s is not None]
    
    # 安全检查：防止因网络波动导致全量误删
    if len(sites) > 0 and len(active_sites) < 5:
        print(f"⚠️ 警告：检测到的存活接口过少({len(active_sites)})，拒绝覆盖配置文件！")
        return

    # 保存结果前先备份
    if os.path.exists(CONFIG_FILE):
        shutil.copy(CONFIG_FILE, f"{CONFIG_FILE}.bak")

    # 保存结果
    config_data['sites'] = active_sites
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)

    end_time = time.time()
    print(f"\n⚡ 检测完成！耗时: {end_time - start_time:.2f} 秒")
    print(f"- 有效: {len(active_sites)} | 剔除: {len(sites) - len(active_sites)}")

if __name__ == "__main__":
    asyncio.run(main())
