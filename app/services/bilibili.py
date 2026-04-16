"""
Bilibili API 服务（扩展版）
"""
import httpx
import json
import asyncio
import time
import hashlib
import os
import re
from typing import Optional, Dict, List, Any
from app.config import settings
from app.utils.logger import get_logger
from app.utils.helpers import extract_bvid

logger = get_logger(__name__)


def clean_html_text(text: str) -> str:
    """去除HTML标签（如B站搜索返回的 <em class="keyword"> 高亮标签）"""
    if not text:
        return ""
    # 移除所有 HTML 标签
    cleaned = re.sub(r'<[^>]+>', '', text)
    # 清理多余的空白字符
    cleaned = ' '.join(cleaned.split())
    return cleaned.strip()


class BilibiliService:
    """Bilibili API 服务"""

    def __init__(self, sessdata: str = None, bili_jct: str = None, dedeuserid: str = None):
        self.base_url = "https://api.bilibili.com"
        self.client = None
        # 优先使用传入的 cookie，否则回退到全局配置
        if sessdata or bili_jct or dedeuserid:
            self.cookies = {
                "SESSDATA": sessdata or "",
                "bili_jct": bili_jct or "",
                "DedeUserID": dedeuserid or "",
                "DedeUserID__ckMd5": "",
            }
        else:
            self.cookies = getattr(settings, "bilibili_cookies", {}) or {}
        self._wbi_keys = None  # WBI签名密钥缓存

    async def __aenter__(self):
        await self._ensure_client_async()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """关闭客户端"""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def _ensure_client_async(self):
        """确保 client 已初始化（异步版本）"""
        if self.client is None:
            # 构建完整的headers包含cookies
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.bilibili.com",
                "Origin": "https://www.bilibili.com",
            }
            # 添加cookies到header
            cookie_str = "; ".join([f"{k}={v}" for k, v in self.cookies.items() if v])
            if cookie_str:
                headers["Cookie"] = cookie_str

            self.client = httpx.AsyncClient(
                cookies=self.cookies,
                headers=headers,
                timeout=30.0,
                follow_redirects=True
            )

    # ============================================================
    # 二维码登录 API
    # ============================================================

    async def generate_qrcode(self) -> Dict[str, Any]:
        """
        生成登录二维码

        Returns:
            {
                "qrcode_key": str,
                "qrcode_url": str,
                "qrcode_image_base64": str
            }
        """
        try:
            await self._ensure_client_async()

            # 获取二维码密钥
            url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
            resp = await self.client.get(url)
            data = resp.json()

            if data.get("code") != 0:
                raise Exception(data.get("message", "生成二维码失败"))

            qrcode_key = data["data"]["qrcode_key"]
            qrcode_url = data["data"]["url"]

            # 生成二维码图片（base64）
            import qrcode
            import io
            import base64

            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(qrcode_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            img_base64 = base64.b64encode(buffer.getvalue()).decode()

            logger.info(f"生成二维码成功: {qrcode_key[:20]}...")

            return {
                "qrcode_key": qrcode_key,
                "qrcode_url": qrcode_url,
                "qrcode_image_base64": f"data:image/png;base64,{img_base64}"
            }

        except Exception as e:
            logger.error(f"生成二维码失败: {e}")
            raise

    async def poll_qrcode_status(self, qrcode_key: str) -> Dict[str, Any]:
        """
        轮询二维码登录状态

        Args:
            qrcode_key: 二维码密钥

        Returns:
            {
                "status": str,  # waiting/scanned/confirmed/expired
                "message": str,
                "cookies": dict,  # 登录成功后返回
                "refresh_token": str
            }
        """
        try:
            await self._ensure_client_async()

            url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
            params = {
                "qrcode_key": qrcode_key,
                "source": "main_web"
            }

            resp = await self.client.get(url, params=params)
            data = resp.json()

            # 临时调试：记录完整的响应数据
            logger.info(f"B站API完整响应: {data}")

            if data.get("code") != 0:
                return {
                    "status": "error",
                    "message": data.get("message", "轮询失败"),
                    "cookies": {},
                    "refresh_token": ""
                }

            url_data = data.get("data", {})
            logger.info(f"url_data完整内容: {url_data}")

            # 解析状态码
            # 86101: 未扫码
            # 86109: 二维码已过期
            # 86090: 已扫码（新状态码）
            # 86038: 可能是确认状态
            # 0: 登录成功（有credential）或扫码成功（旧版）
            code = url_data.get("code")
            credential = url_data.get("credential")

            logger.info(f"轮询二维码状态: code={code}, has_credential={bool(credential)}")

            if code == 86109:
                logger.info("二维码已过期")
                return {"status": "expired", "message": "二维码已过期，请刷新重试", "cookies": {}, "refresh_token": ""}
            elif code == 86101:
                logger.info("等待扫码")
                return {"status": "waiting", "message": "请扫描二维码", "cookies": {}, "refresh_token": ""}
            elif code == 86090:
                # 新的扫码状态
                logger.info("已扫码（新状态码86090），等待确认")
                return {
                    "status": "scanned",
                    "message": "扫码成功，请在手机上确认登录",
                    "cookies": {},
                    "refresh_token": ""
                }
            elif code == 86038:
                # 86038 = 二维码已失效
                message = url_data.get("message", "二维码已失效")
                logger.info(f"二维码已失效: {message}")
                return {"status": "expired", "message": message, "cookies": {}, "refresh_token": ""}
            elif code == 0:
                # B站新版API：code=0时，cookie在url参数中
                cross_domain_url = url_data.get("url", "")

                if cross_domain_url and "SESSDATA=" in cross_domain_url:
                    # 从URL中提取cookie
                    logger.info("从跨域URL中提取cookie")

                    # 解析URL参数获取cookie
                    from urllib.parse import parse_qs, urlparse
                    parsed_url = urlparse(cross_domain_url)
                    params = parse_qs(parsed_url.query)

                    cookies = {
                        "SESSDATA": params.get("SESSDATA", [""])[0],
                        "bili_jct": params.get("bili_jct", [""])[0],
                        "DedeUserID": params.get("DedeUserID", [""])[0],
                        "DedeUserID__ckMd5": params.get("DedeUserID__ckMd5", [""])[0],
                    }

                    logger.info(f"登录成功！从URL提取到cookie: SESSDATA={cookies['SESSDATA'][:20]}...")

                    return {
                        "status": "confirmed",
                        "message": "登录成功",
                        "cookies": cookies,
                        "refresh_token": url_data.get("refresh_token", "")
                    }
                else:
                    # 没有URL，可能是旧版API或扫码成功待确认
                    credential = url_data.get("credential")
                    if credential:
                        # 旧版：credential在data里
                        logger.info("登录成功！获取到credential（旧版）")
                        cookies = {
                            "SESSDATA": credential.get("SESSDATA", ""),
                            "bili_jct": credential.get("bili_jct", ""),
                            "DedeUserID": credential.get("DedeUserID", ""),
                            "DedeUserID__ckMd5": credential.get("DedeUserID__ckMd5", ""),
                        }
                        return {
                            "status": "confirmed",
                            "message": "登录成功",
                            "cookies": cookies,
                            "refresh_token": url_data.get("refresh_token", "")
                        }
                    else:
                        # 扫码成功待确认
                        logger.info("已扫码，等待确认")
                        return {
                            "status": "scanned",
                            "message": "扫码成功，请在手机上确认登录",
                            "cookies": {},
                            "refresh_token": ""
                        }
            else:
                logger.info(f"未知状态码: {code}")
                return {
                    "status": "waiting",
                    "message": f"状态码: {code}",
                    "cookies": {},
                    "refresh_token": ""
                }

        except Exception as e:
            logger.error(f"轮询二维码状态失败: {e}")
            return {"status": "error", "message": str(e), "cookies": {}, "refresh_token": ""}

    async def get_user_info(self) -> Dict[str, Any]:
        """
        获取登录用户信息

        Returns:
            用户信息字典
        """
        try:
            # 确保异步客户端已初始化
            await self._ensure_client_async()

            url = "https://api.bilibili.com/x/web-interface/nav"
            resp = await self.client.get(url)
            data = resp.json()

            if data.get("code") == 0:
                return data.get("data", {})
            else:
                return {}

        except Exception as e:
            logger.error(f"获取用户信息失败: {e}")
            return {}

    async def get_following_list(self, mid: int = None, pn: int = 1, ps: int = 50) -> Dict[str, Any]:
        """
        获取用户关注的UP主列表

        Args:
            mid: 用户ID，如果不传则获���当前登录用户
            pn: 页码，从1开始
            ps: 每页数量，最大50

        Returns:
            关注列表数据
        """
        try:
            # 如果没有提供mid，先获取当前用户的mid
            if not mid:
                user_info = await self.get_user_info()
                mid = user_info.get("mid", 0)
                if not mid:
                    logger.warning("无法获取用户mid，无法获取关注列表")
                    return {"total": 0, "list": []}

            await self._ensure_client_async()

            url = f"https://api.bilibili.com/x/relation/followings"
            params = {
                "vmid": mid,
                "pn": pn,
                "ps": ps,
                "order_type": "attention"  # 按关注顺序排序
            }

            resp = await self.client.get(url, params=params)
            data = resp.json()

            logger.debug(f"关注列表API响应: code={data.get('code')}, message={data.get('message')}")

            if data.get("code") == 0:
                followings = data.get("data", {}).get("list", [])
                total = data.get("data", {}).get("total", 0)

                logger.info(f"获取关注列表成功: 共{total}个UP主，当前页{len(followings)}个")

                return {
                    "total": total,
                    "list": followings,
                    "pn": pn,
                    "ps": ps
                }
            else:
                logger.warning(f"获取关注列表失败: code={data.get('code')}, message={data.get('message')}")
                logger.debug(f"完整响应: {data}")
                return {"total": 0, "list": []}

        except Exception as e:
            logger.error(f"获取关注列表异常: {e}")
            return {"total": 0, "list": []}

    async def get_all_followings(self, mid: int = None) -> List[Dict[str, Any]]:
        """
        获取所有关注的UP主（自动翻页）

        Args:
            mid: 用户ID，如果不传则获取当前登录用户

        Returns:
            完整的关注列表
        """
        all_followings = []
        pn = 1
        ps = 50  # 每页最大数量

        while True:
            result = await self.get_following_list(mid, pn, ps)
            followings = result.get("list", [])
            total = result.get("total", 0)

            if not followings:
                break

            all_followings.extend(followings)
            logger.info(f"已获取 {len(all_followings)}/{total} 个关注")

            # 如果已获取完所有数据，退出循环
            if len(all_followings) >= total:
                break

            pn += 1
            # 避免请求过快
            await asyncio.sleep(0.5)

        logger.info(f"获取关注列表完成: 共{len(all_followings)}个UP主")
        return all_followings

    async def _get_wbi_keys(self) -> tuple[str, str]:
        """获取WBI签名密钥"""
        if self._wbi_keys:
            return self._wbi_keys

        try:
            # 确保异步客户端已初始化
            await self._ensure_client_async()

            # 获取nav信息
            resp = await self.client.get(f"{self.base_url}/x/web-interface/nav")
            logger.info(f"nav API响应状态: {resp.status_code}")
            data = resp.json()

            if data.get("code") == 0 and data.get("data"):
                wbi_img = data["data"].get("wbi_img")
                if wbi_img and isinstance(wbi_img, dict):
                    wbi_img_url = wbi_img.get("img_url")
                    if wbi_img_url:
                        # 从URL中提取密钥
                        wbi_key = wbi_img_url.split("/")[-1].replace(".png", "")
                        self._wbi_keys = (wbi_key[:16], wbi_key[16:])
                        logger.info(f"成功获取WBI keys: {wbi_key[:16]}...")
                        return self._wbi_keys
                    else:
                        logger.warning("wbi_img_url为空")
                else:
                    logger.warning(f"wbi_img格式错误: {type(wbi_img)}, value: {wbi_img}")
            else:
                logger.warning(f"获取nav信息失败: code={data.get('code')}, message={data.get('message')}")
        except Exception as e:
            logger.error(f"Failed to get WBI keys: {e}")

        # 返回默认值
        return ("", "")

    async def _generate_wbi_signature(self, params: dict) -> dict:
        """生成WBI签名（异步版本）"""
        # 按key排序并混合
        sorted_params = dict(sorted(params.items()))
        query = "&".join([f"{k}={v}" for k, v in sorted_params.items()])

        # 获取密钥（异步获取）
        if not self._wbi_keys or self._wbi_keys == ("", ""):
            try:
                self._wbi_keys = await self._get_wbi_keys()
            except Exception as e:
                logger.warning(f"无法获取WBI keys: {e}，跳过签名")
                return params

        mix_key, _ = self._wbi_keys

        # 生成签名
        wbi_signature = hashlib.md5(f"{query}{mix_key}".encode()).hexdigest()

        params["wts"] = int(time.time())
        params["w_rid"] = wbi_signature

        return params

    # ============================================================
    # 搜索类 API
    # ============================================================

    async def search_bilibili(
        self,
        keyword: str,
        search_type: str = "video",
        page: int = 1,
        order: str = "totalrank",
        duration: int = 0,
        keyword_context: str = "",
        rid: int = 0
    ) -> Dict[str, Any]:
        """
        搜索B站内容

        Args:
            keyword: 搜索关键词
            search_type: 搜索类型 (video/mediakit/bangumi/foto/user)
            page: 页码
            order: 排序方式 (totalrank/click/pubdate/dm/stow)
            duration: 时长筛选 (0全部/1<10分钟/2-30分钟/3-60分钟/4>60分钟)
            keyword_context: 上下文关键词
            rid: 分区ID (0=全站, 36=知识, 1=动画, 4=游戏, etc.)

        Returns:
            搜索结果字典
        """
        try:
            # 确保客户端已初始化
            await self._ensure_client_async()

            # 使用WBI签名的综合搜索API
            url = f"{self.base_url}/x/web-interface/wbi/search/all/v2"

            # 构建搜索参数
            params = {
                "keyword": keyword,
                "page": page,
            }

            # 根据搜索类型设置相应的参数
            search_type_mapping = {
                "video": "video",
                "user": "bili_user",
                "bangumi": "media_bangumi",
                "mediakit": "media_ft"
            }
            if search_type in search_type_mapping:
                params["search_type"] = search_type_mapping[search_type]

            logger.info(f"Searching Bilibili with WBI signature: {keyword}")

            # 添加WBI签名
            wbi_params = await self._generate_wbi_signature(params)

            # 添加必要的请求头
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.bilibili.com/"
            }

            resp = await self.client.get(url, params=wbi_params, headers=headers)

            # 检查响应状态
            if resp.status_code != 200:
                logger.error(f"Search API returned HTTP {resp.status_code}")
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}",
                    "source": "bilibili_search"
                }

            # 尝试解析JSON
            try:
                data = resp.json()
                logger.info(f"Search API response code: {data.get('code')}")
                if data.get('code') != 0:
                    logger.info(f"Search API error message: {data.get('message', 'Unknown error')}")
            except Exception as json_err:
                logger.error(f"JSON parse error: {json_err}")
                return {
                    "success": False,
                    "error": f"JSON parse error: {json_err}",
                    "source": "bilibili_search"
                }

            # 检查数据是否为None
            if data is None:
                logger.error("Response data is None")
                return {
                    "success": False,
                    "error": "Response data is None",
                    "source": "bilibili_search"
                }

            # 新版WBI搜索API的响应格式
            if isinstance(data, dict):
                if data.get("code") != 0:
                    error_msg = data.get("message", "Unknown error")
                    logger.error(f"Search API error: {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg,
                        "source": "bilibili_search"
                    }

                # 新版WBI搜索API的响应格式
                # API 返回 data.result 数组，每个元素是 {result_type: "video", data: [...]}
                result_data = data.get("data", {})
                result_array = result_data.get("result", [])

                # 添加调试日志
                logger.info(f"Search result data keys: {result_data.keys()}")
                logger.info(f"Result array length: {len(result_array)}")

                # 根据 search_type 从 result 数组中提取对应的结果
                # search_type_mapping: video -> video, user -> bili_user, bangumi -> media_bangumi
                search_type_to_result_type = {
                    "video": "video",
                    "user": "bili_user",
                    "bangumi": "media_bangumi",
                    "mediakit": "media_ft"
                }

                items = []
                target_result_type = search_type_to_result_type.get(search_type, search_type)

                # 遍历 result 数组，找到匹配的 result_type
                for result_item in result_array:
                    if not isinstance(result_item, dict):
                        continue
                    item_type = result_item.get("result_type", "")
                    item_data = result_item.get("data", [])

                    # 如果指定了搜索类型，只提取匹配的结果
                    if target_result_type and item_type == target_result_type:
                        if isinstance(item_data, list):
                            items = item_data
                            break
                    # 如果没有指定类型，收集所有结果
                    elif not target_result_type:
                        if isinstance(item_data, list):
                            items.extend(item_data)

                logger.info(f"Extracted {len(items)} items for search_type={search_type}")

                # 清理搜索结果中的HTML标签（如 <em class="keyword">）
                for item in items:
                    if "title" in item:
                        item["title"] = clean_html_text(item["title"])
                    if "author" in item:
                        item["author"] = clean_html_text(item["author"])

                if len(items) == 0:
                    logger.warning(f"No items found! Available keys in result_list: {list(result_list.keys())}")

                return {
                    "success": True,
                    "numResults": len(items),
                    "pages": 1,
                    "items": items,
                    "source": "bilibili_search"
                }
        except Exception as e:
            import traceback
            logger.error(f"Search failed: {e}\n{traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_search"
            }

    async def get_hot_search_recommendations(self, limit: int = 10) -> Dict[str, Any]:
        """
        获取B站热搜推荐（无需认证）

        Args:
            limit: 返回数量

        Returns:
            热搜推荐字典
        """
        try:
            # 确保客户端已初始化
            await self._ensure_client_async()

            # 使用无需认证的热搜词API
            url = "https://s.search.bilibili.com/main/hotword"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.bilibili.com/"
            }

            resp = await self.client.get(url, headers=headers)

            if resp.status_code != 200:
                logger.error(f"Hot search API returned HTTP {resp.status_code}")
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}",
                    "source": "hot_search"
                }

            data = resp.json()

            if data.get("code") == 0:
                hot_list = data.get("list", [])[:limit]

                # 格式化为推荐格式
                items = []
                for hot_item in hot_list:
                    items.append({
                        "title": hot_item.get("show_name", hot_item.get("keyword", "")),
                        "keyword": hot_item.get("keyword", ""),
                        "heat_score": hot_item.get("heat_score", 0),
                        "icon": hot_item.get("icon", ""),
                        "type": "hot_search"
                    })

                return {
                    "success": True,
                    "numResults": len(items),
                    "items": items,
                    "source": "hot_search"
                }
            else:
                return {
                    "success": False,
                    "error": "API returned non-zero code",
                    "source": "hot_search"
                }

        except Exception as e:
            logger.error(f"Hot search failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "hot_search"
            }

    async def get_user_favorites(self, mid: int) -> List[Dict[str, Any]]:
        """获取用户收藏夹列表"""
        try:
            # 确保异步客户端已初始化
            await self._ensure_client_async()

            # B站收藏夹API (按优先级尝试)
            apis_to_try = [
                # API 1: 获取当前用户创建的所有收藏夹 (推荐)
                {
                    "name": "created/list-all",
                    "url": f"{self.base_url}/x/v3/fav/folder/created/list-all",
                    "params_fn": lambda: {"mid": str(mid), "web_location": "333.1370", "jsonp": "jsonp"}
                },
                # API 2: 获取导航栏收藏夹列表
                {
                    "name": "list4navigate",
                    "url": f"{self.base_url}/x/v3/fav/folder/list4navigate",
                    "params_fn": lambda: {}
                },
                # API 3: 获取收藏夹列表 (旧API备用)
                {
                    "name": "folder_list",
                    "url": f"{self.base_url}/x/v2/favfolder/folder",
                    "params_fn": lambda: {"upmid": str(mid), "ps": 100}
                }
            ]

            for i, api in enumerate(apis_to_try):
                try:
                    logger.debug(f"尝试API {i+1} ({api['name']}): GET {api['url']}")

                    # 普通GET请求
                    params = api["params_fn"]()
                    resp = await self.client.get(api["url"], params=params)

                    logger.debug(f"  响应状态: {resp.status_code}")

                    if resp.status_code == 200 and resp.text:
                        try:
                            data = resp.json()
                            code = data.get("code")
                            message = data.get("message", "")
                            logger.debug(f"  API返回code: {code}, message: {message}")

                            if code == 0:
                                # 成功
                                raw_data = data.get("data", [])
                                items = []

                                # 处理不同的数据格式
                                if isinstance(raw_data, list):
                                    # 格式1: 直接是列表
                                    for folder in raw_data:
                                        # list4navigate 格式: {"id":1,"name":"我创建的收藏夹","mediaListResponse":{"count":1,"list":[...]}}
                                        if "mediaListResponse" in folder:
                                            media_list = folder.get("mediaListResponse", {})
                                            fav_list = media_list.get("list")
                                            # 添加None检查
                                            if fav_list and isinstance(fav_list, list):
                                                for fav in fav_list:
                                                    items.append({
                                                        "id": fav.get("id"),
                                                        "fid": fav.get("fid"),
                                                        "mid": fav.get("mid"),
                                                        "title": fav.get("title", folder.get("name", "")),
                                                        "media_count": media_list.get("count", 0),
                                                        "cover": fav.get("cover", ""),
                                                    })
                                            else:
                                                # 如果fav_list为空或不是列表，记录警告并跳过
                                                logger.warning(f"  mediaListResponse.list 为空或无效: {fav_list}")
                                        else:
                                            # 普通列表格式
                                            items.append(folder)
                                elif isinstance(raw_data, dict):
                                    # 格式2: dict with "list" key
                                    items = raw_data.get("list", [])
                                    if not items:
                                        items = raw_data.get("items", [])

                                if items:
                                    logger.info(f"  成功! 获取到 {len(items)} 个收藏夹")
                                    for idx, item in enumerate(items[:5]):
                                        item_id = item.get('id', item.get('media_id', 'N/A'))
                                        title = item.get('title', 'N/A')
                                        count = item.get('media_count', item.get('count', 0))
                                        logger.info(f"    {idx+1}. {title} (id={item_id}, count={count})")
                                    return items
                                else:
                                    logger.warning(f"  返回数据为空: {data.get('data')}")
                            elif code == -101:
                                logger.warning(f"  需要登录 (code=-101)")
                            elif code == -400:
                                logger.warning(f"  请求错误 (code=-400)")
                        except Exception as json_err:
                            logger.warning(f"  JSON解析失败: {json_err}")
                            logger.info(f"  原始响应: {resp.text[:200]}")
                    else:
                        logger.warning(f"  HTTP状态码: {resp.status_code}")
                        if resp.status_code == 404:
                            logger.info(f"  响应内容: {resp.text[:200]}")

                except Exception as e:
                    logger.warning(f"  API {i+1} 异常: {e}")

            logger.error("所有收藏夹API均失败")
            return []

        except Exception as e:
            logger.error(f"Get user favorites failed: {e}")
            import traceback
            traceback.print_exc()
            return []


    async def get_all_favorite_videos(self, media_id: int) -> List[Dict[str, Any]]:
        """获取收藏夹中所有视频"""
        all_videos = []
        pn = 1
        ps = 20
        max_pages = 50  # 防止无限循环

        try:
            # 确保异步客户端已初始化
            await self._ensure_client_async()

            while pn <= max_pages:
                url = f"{self.base_url}/x/v3/fav/resource/list"
                params = {
                    "media_id": media_id,
                    "pn": pn,
                    "ps": ps,
                    "platform": "web"
                }

                # 添加WBI签名
                img_key, sub_key = await self._get_wbi_keys()
                params["img_key"] = img_key
                params["sub_key"] = sub_key
                wbi_params = await self._generate_wbi_signature(params)

                resp = await self.client.get(url, params=wbi_params)
                data = resp.json()

                if data.get("code") != 0:
                    break

                medias = data.get("data", {}).get("medias", [])
                if not medias:
                    break

                all_videos.extend(medias)

                # 检查是否还有更多页面
                if len(medias) < ps:
                    break

                pn += 1

            return all_videos
        except Exception as e:
            logger.error(f"Get all favorite videos failed: {e}")
            return []

    async def search_topic(self, tag_name: str) -> Dict[str, Any]:
        """搜索话题/标签"""
        try:
            url = f"{self.base_url}/x/tag/info"
            params = {"tag_name": tag_name}

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "data": data["data"],
                    "source": "bilibili_topic"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "Unknown error"),
                    "source": "bilibili_topic"
                }
        except Exception as e:
            logger.error(f"Topic search failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_topic"
            }

    # ============================================================
    # UP主相关 API
    # ============================================================

    async def get_up_info(self, mid: int) -> Dict[str, Any]:
        """获取UP主信息（需要WBI签名）"""
        try:
            url = f"{self.base_url}/x/space/wbi/acc/info"
            params = {"mid": mid}
            # params = self._generate_wbi_signature(params)  # 需要WBI签名

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "data": data["data"],
                    "source": "bilibili_up_info"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "Unknown error"),
                    "source": "bilibili_up_info"
                }
        except Exception as e:
            logger.error(f"Get UP info failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_up_info"
            }

    async def get_up_videos(
        self,
        mid: int,
        pn: int = 1,
        ps: int = 30,
        order: str = "pubdate"
    ) -> Dict[str, Any]:
        """获取UP主视频列表（需要WBI签名）"""
        try:
            url = f"{self.base_url}/x/space/wbi/arc/search"
            params = {
                "mid": mid,
                "ps": ps,
                "pn": pn,
                "order": order
            }
            # params = self._generate_wbi_signature(params)  # 需要WBI签名

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") == 0:
                list_data = data["data"]["list"]
                return {
                    "success": True,
                    "videos": list_data.get("vlist", []),
                    "page": list_data.get("page", {}),
                    "source": "bilibili_up_videos"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "Unknown error"),
                    "source": "bilibili_up_videos"
                }
        except Exception as e:
            logger.error(f"Get UP videos failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_up_videos"
            }

    # ============================================================
    # 评论相关 API
    # ============================================================

    async def get_comments(
        self,
        aid: int,
        mode: int = 2,
        ps: int = 20,
        next: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        获取视频评论

        Args:
            aid: 视频AV号
            mode: 2=热门评论, 3=时间线
            ps: 每页数量
            next: 下一页偏移量
        """
        try:
            url = f"{self.base_url}/x/v2/reply"
            params = {
                "oid": aid,
                "type": 1,  # 视频类型
                "mode": mode,
                "ps": ps
            }
            if next:
                params["next"] = next

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") == 0:
                replies = data["data"].get("replies", [])
                return {
                    "success": True,
                    "comments": replies,
                    "cursor": data["data"].get("cursor", {}),
                    "source": "bilibili_comments"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "Unknown error"),
                    "source": "bilibili_comments"
                }
        except Exception as e:
            logger.error(f"Get comments failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_comments"
            }

    async def get_comments_reply(
        self,
        aid: int,
        rpid: int,
        pn: int = 1
    ) -> Dict[str, Any]:
        """获取评论回复"""
        try:
            url = f"{self.base_url}/x/v2/reply/reply"
            params = {
                "oid": aid,
                "root": rpid,
                "type": 1,
                "pn": pn
            }

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "replies": data["data"].get("replies", []),
                    "page": data["data"].get("page", {}),
                    "source": "bilibili_comment_replies"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "Unknown error"),
                    "source": "bilibili_comment_replies"
                }
        except Exception as e:
            logger.error(f"Get comment replies failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_comment_replies"
            }

    # ============================================================
    # 热榜/排行榜 API
    # ============================================================

    async def get_trending(self, rid: int = 0) -> Dict[str, Any]:
        """
        获取排行榜

        Args:
            rid: 分区ID (0=全站)
        """
        try:
            url = f"{self.base_url}/x/web-interface/ranking/v2"
            params = {"rid": rid}

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "videos": data["data"].get("list", []),
                    "note": data["data"].get("note", ""),
                    "source": "bilibili_trending"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "Unknown error"),
                    "source": "bilibili_trending"
                }
        except Exception as e:
            import traceback
            logger.error(f"Get trending failed: {e}\n{traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_trending"
            }

    async def get_popular(self, special_id: Optional[str] = None) -> Dict[str, Any]:
        """获取特别推荐区"""
        try:
            url = f"{self.base_url}/x/web-interface/popular"
            params = {}
            if special_id:
                params["ps_idx"] = special_id

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "videos": data["data"].get("items", []),
                    "source": "bilibili_popular"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "Unknown error"),
                    "source": "bilibili_popular"
                }
        except Exception as e:
            logger.error(f"Get popular failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_popular"
            }

    # ============================================================
    # 话题相关 API
    # ============================================================

    async def get_topic_info(self, tag_name: str) -> Dict[str, Any]:
        """获取话题详情"""
        try:
            url = f"{self.base_url}/x/tag/info"
            params = {"tag_name": tag_name}

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "data": data["data"],
                    "source": "bilibili_topic_info"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "Unknown error"),
                    "source": "bilibili_topic_info"
                }
        except Exception as e:
            logger.error(f"Get topic info failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_topic_info"
            }

    async def get_topic_videos(self, tag_id: int, pn: int = 1, ps: int = 30) -> Dict[str, Any]:
        """获取话题下的视频"""
        try:
            url = f"{self.base_url}/x/tag/archives"
            params = {
                "tag_id": tag_id,
                "pn": pn,
                "ps": ps
            }

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "videos": data["data"].get("list", []),
                    "page": data["data"].get("page", {}),
                    "source": "bilibili_topic_videos"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "Unknown error"),
                    "source": "bilibili_topic_videos"
                }
        except Exception as e:
            logger.error(f"Get topic videos failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_topic_videos"
            }

    async def add_to_favorites(
        self,
        media_id: int,
        bvid: str,
    ) -> Dict[str, Any]:
        """添加视频到收藏夹

        Args:
            media_id: 收藏夹ID
            bvid: 视频BV号

        Returns:
            操���结果
        """
        try:
            # 获取视频的aid（B站API需要aid而不是bvid）
            video_info = await self.get_video_info(bvid=bvid)
            if not video_info.get("success"):
                return {
                    "success": False,
                    "error": f"无法获取视频信息: {video_info.get('error')}",
                    "source": "bilibili_add_favorites"
                }

            aid = video_info["data"].get("aid")
            if not aid:
                return {
                    "success": False,
                    "error": "视频信息中缺少aid",
                    "source": "bilibili_add_favorites"
                }

            # 调用B站收藏API
            url = f"{self.base_url}/x/v3/fav/resource/deal"
            payload = {
                "media_id": media_id,
                "resources": json.dumps([
                    {
                        "bvid": bvid,
                        "id": aid,
                        "type": 2  # 2表示视频类型
                    }
                ]),
                "csrf": self.cookies.get("bili_jct", "")
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.bilibili.com"
            }

            resp = await self.client.post(url, data=payload, headers=headers)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "message": "已添加到收藏夹",
                    "source": "bilibili_add_favorites"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "Unknown error"),
                    "source": "bilibili_add_favorites"
                }
        except Exception as e:
            logger.error(f"Add to favorites failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_add_favorites"
            }

    # ============================================================
    # 视频内容获取
    # ============================================================

    async def get_video_info(self, bvid: str) -> Dict[str, Any]:
        """
        获取视频基本信息（view 接口）

        Args:
            bvid: 视频 BV 号

        Returns:
            {
                "success": bool,
                "data": { "aid", "cid", "title", "desc", ... },
                "error": str
            }
        """
        try:
            await self._ensure_client_async()
            url = f"{self.base_url}/x/web-interface/view"
            params = {"bvid": bvid}

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "data": data.get("data", {}),
                    "source": "bilibili_view"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "获取视频信息失败"),
                    "source": "bilibili_view"
                }
        except Exception as e:
            logger.error(f"Get video info failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_view"
            }

    async def get_audio_url(self, bvid: str, cid: int) -> Optional[str]:
        """
        从播放信息接口获取音频流 URL（用于 ASR）

        Args:
            bvid: 视频 BV 号
            cid: 视频 cid

        Returns:
            音频 URL 或 None
        """
        try:
            await self._ensure_client_async()
            # 优先尝试带 WBI 签名的接口
            img_key, sub_key = await self._get_wbi_keys()
            params = {
                "bvid": bvid,
                "cid": cid,
                "qn": 120,          # 流畅 360P 以降低音频文件体积
                "fnval": 4048,      # 只请求 dash 音频流（不请求视频）
                "fnver": 0,
                "fourk": 0,
                "img_key": img_key,
                "sub_key": sub_key,
            }
            wbi_params = await self._generate_wbi_signature(params)

            url = f"{self.base_url}/x/player/playurl"
            resp = await self.client.get(url, params=wbi_params)
            data = resp.json()

            if data.get("code") != 0:
                # WBI 签名失败时尝试无签名接口（部分视频可用）
                logger.debug(f"playurl WBI 签名失败，尝试无签名接口: {data.get('message')}")
                plain_params = {
                    "bvid": bvid,
                    "cid": cid,
                    "qn": 120,
                    "fnval": 4048,
                    "fnver": 0,
                    "fourk": 0,
                }
                resp = await self.client.get(url, params=plain_params)
                data = resp.json()

            if data.get("code") == 0:
                dash = data.get("data", {}).get("dash", {})
                audios = dash.get("audio", [])
                if audios:
                    # 取最高码率的音频
                    best = max(audios, key=lambda a: a.get("bandwidth", 0))
                    audio_url = best.get("baseUrl") or best.get("src")
                    if audio_url:
                        logger.info(f"获取音频 URL 成功: {audio_url[:80]}...")
                        return audio_url
                logger.debug(f"[{bvid}] playurl 响应无 audio 字段: {list(data.get('data', {}).keys())}")
            else:
                logger.debug(f"获取音频 URL 失败: {data.get('message')}")
        except Exception as e:
            logger.error(f"Get audio URL failed: {e}")
        return None

    async def download_audio_to_file(self, url: str, file_path: str) -> bool:
        """
        下载音频文件到本地路径

        Args:
            url: 音频直链
            file_path: 本地保存路径

        Returns:
            是否下载成功
        """
        try:
            await self._ensure_client_async()
            # 使用 self.client（已配置 cookies）下载音频
            async with self.client.stream("GET", url, timeout=httpx.Timeout(300.0, connect=30.0)) as resp:
                if resp.status_code != 200:
                    logger.warning(f"下载音频失败 HTTP {resp.status_code}: {url[:80]}")
                    return False
                with open(file_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
            logger.info(f"音频下载完成: {file_path} ({os.path.getsize(file_path)} bytes)")
            return True
        except Exception as e:
            logger.error(f"Download audio failed: {e}")
            return False

    async def get_player_info(
        self, bvid: str, cid: int, aid: int = None
    ) -> Dict[str, Any]:
        """
        获取播放器信息（含字幕列表）

        Args:
            bvid: 视频 BV 号
            cid: 视频 cid
            aid: 视频 aid（可选，用于字幕接口）

        Returns:
            播放器响应字典
        """
        try:
            await self._ensure_client_async()
            # 优先使用 aid（数字 ID）请求字幕
            video_id = aid if aid else (await self.get_video_info(bvid)).get("data", {}).get("aid")
            if not video_id:
                return {}

            img_key, sub_key = await self._get_wbi_keys()
            params = {
                "avid": video_id,
                "cid": cid,
                "img_key": img_key,
                "sub_key": sub_key,
            }
            wbi_params = await self._generate_wbi_signature(params)

            url = f"{self.base_url}/x/player/v2"
            resp = await self.client.get(url, params=wbi_params)
            data = resp.json()

            if data.get("code") == 0:
                return data.get("data", {})
            logger.debug(f"get_player_info 失败: {data.get('message')}")
        except Exception as e:
            logger.error(f"Get player info failed: {e}")
        return {}

    async def download_subtitle(self, subtitle_url: str) -> Optional[str]:
        """
        下载 B 站字幕文件并转换为纯文本

        Args:
            subtitle_url: 字幕文件 URL（.ass 或 .srt）

        Returns:
            字幕纯文本或 None
        """
        if not subtitle_url:
            return None
        try:
            # 修正 URL 协议（可能缺少 https: 前缀）
            if subtitle_url.startswith("//"):
                subtitle_url = "https:" + subtitle_url

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(subtitle_url)
                resp.raise_for_status()
                raw = resp.text

            if subtitle_url.lower().endswith(".srt") or '"format":"srt"' in raw[:200]:
                return self._parse_srt(raw)
            else:
                return self._parse_ass(raw)
        except Exception as e:
            logger.error(f"Download subtitle failed: {e}")
            return None

    def _parse_ass(self, raw: str) -> str:
        """解析 ASS/SSA 字幕为纯文本"""
        import re
        lines = []
        in_dialogue = False
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("[Events]"):
                in_dialogue = True
                continue
            if in_dialogue and line.startswith("Dialogue:"):
                # ASS 格式: Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
                parts = line.split(",", 9)
                if len(parts) >= 10:
                    text = parts[9]
                    # 去除 ASS 样式标签 {\a9} {\r} {\an8} 等
                    text = re.sub(r"\{[^}]*\}", "", text)
                    # 去除 {\} 残留
                    text = text.replace("\\N", "\n").replace("\\n", "\n").strip()
                    if text:
                        lines.append(text)
        return "\n".join(lines)

    def _parse_srt(self, raw: str) -> str:
        """解析 SRT 字幕为纯文本"""
        import re
        lines = []
        for line in raw.splitlines():
            line = line.strip()
            # 跳过序号、时间码、空行
            if re.match(r"^\d+$", line):
                continue
            if re.match(r"\d{2}:\d{2}:\d{2}", line):
                continue
            if not line:
                continue
            lines.append(line)
        return "\n".join(lines)

    async def get_video_summary(
        self, bvid: str, cid: int, up_mid: int = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取 B 站 AI 视频摘要（机遇大模型）

        Args:
            bvid: 视频 BV 号
            cid: 视频 cid
            up_mid: UP 主 mid（可选）

        Returns:
            AI 摘要结果或 None
        """
        try:
            await self._ensure_client_async()
            url = f"{self.base_url}/x/ai/columbus/v1/video/summary"
            params = {
                "bvid": bvid,
                "cid": cid,
            }
            if up_mid:
                params["mid"] = up_mid

            resp = await self.client.get(url, params=params)
            data = resp.json()
            return data
        except Exception as e:
            logger.error(f"Get video summary failed: {e}")
            return None

    def _get_cookies(self) -> dict:
        """返回当前 Cookie 字典（供 ContentFetcher 等内部调用）"""
        return self.cookies

    # ============================================================
    # 收藏夹管理扩展 API
    # ============================================================

    async def get_favorite_content(
        self, media_id: int, pn: int = 1, ps: int = 20
    ) -> Dict[str, Any]:
        """
        获取收藏夹内容（带分页和详细信息）

        Args:
            media_id: 收藏夹 ID
            pn: 页码
            ps: 每页数量

        Returns:
            {
                "info": {...},           # 收藏夹信息
                "medias": [...],         # 视频列表
                "has_more": bool,        # 是否有更多
            }
        """
        try:
            await self._ensure_client_async()
            url = f"{self.base_url}/x/v3/fav/resource/list"
            params = {
                "media_id": media_id,
                "pn": pn,
                "ps": ps,
                "platform": "web"
            }

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") == 0:
                result_data = data.get("data", {})
                medias = result_data.get("medias", [])
                has_more = result_data.get("has_more", False)

                return {
                    "info": result_data.get("info", {}),
                    "medias": medias or [],
                    "has_more": has_more,
                }
            else:
                logger.error(f"获取收藏内容失败: {data.get('message')}")
                return {"info": {}, "medias": [], "has_more": False}
        except Exception as e:
            logger.error(f"Get favorite content failed: {e}")
            return {"info": {}, "medias": [], "has_more": False}

    async def move_favorite_resources(
        self, src_media_id: int, tar_media_id: int, resources: List[str]
    ) -> Dict[str, Any]:
        """
        移动收藏资源到另一个收藏夹

        Args:
            src_media_id: 源收藏夹 ID
            tar_media_id: 目标收藏夹 ID
            resources: 资源列表，格式 ["资源ID:类型", ...] 例如 ["123:2", "456:2"]

        Returns:
            操作结果
        """
        try:
            await self._ensure_client_async()
            url = f"{self.base_url}/x/v3/fav/resource/batch-move"

            payload = {
                "src_media_id": src_media_id,
                "tar_media_id": tar_media_id,
                "resources": "\n".join(resources),
                "csrf": self.cookies.get("bili_jct", "")
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.bilibili.com"
            }

            resp = await self.client.post(url, data=payload, headers=headers)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "message": "移动成功",
                    "source": "bilibili_move_resources"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "移动失败"),
                    "source": "bilibili_move_resources"
                }
        except Exception as e:
            logger.error(f"Move favorite resources failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_move_resources"
            }

    async def clean_favorite_resources(self, folder_id: int) -> Dict[str, Any]:
        """
        清理收藏夹中的失效资源

        Args:
            folder_id: 收藏夹 ID

        Returns:
            清理结果
        """
        try:
            await self._ensure_client_async()
            # 先获取收藏夹所有内容
            all_videos = await self.get_all_favorite_videos(folder_id)

            invalid_ids = []
            for video in all_videos:
                # 检查视频状态
                title = video.get("title", "")
                # 常见失效标题
                if title in ["已失效视频", "视频已失效", ""] or video.get("state") == -404:
                    invalid_ids.append(str(video.get("id", "")))

            if not invalid_ids:
                return {
                    "success": True,
                    "message": "没有失效资源需要清理",
                    "cleaned": 0,
                    "source": "bilibili_clean_resources"
                }

            # 批量删除失效资源
            url = f"{self.base_url}/x/v3/fav/resource/batch-del"

            # 资源类型：2=视频
            resources = [f"{vid}:2" for vid in invalid_ids]

            payload = {
                "media_id": folder_id,
                "resources": "\n".join(resources),
                "csrf": self.cookies.get("bili_jct", "")
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.bilibili.com"
            }

            resp = await self.client.post(url, data=payload, headers=headers)
            data = resp.json()

            if data.get("code") == 0:
                return {
                    "success": True,
                    "message": f"已清理 {len(invalid_ids)} 个失效资源",
                    "cleaned": len(invalid_ids),
                    "source": "bilibili_clean_resources"
                }
            else:
                return {
                    "success": False,
                    "error": data.get("message", "清理失败"),
                    "source": "bilibili_clean_resources"
                }
        except Exception as e:
            logger.error(f"Clean favorite resources failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_clean_resources"
            }

    def get_db_session(self):
        """
        获取数据库会话上下文管理器

        Returns:
            async_session_factory 上下文管理器，可用于 async with

        Example:
            async with bili_service.get_db_session() as db:
                await db.execute(...)
        """
        from app.database import async_session_factory
        return async_session_factory()

    # ============================================================
    # 追番 / 影视 / 历史 相关 API
    # ============================================================

    async def get_user_bangumi(self, mid: int, status: str = "watching") -> List[Dict[str, Any]]:
        """
        获取用户追番列表

        Args:
            mid: 用户UID（B站数字ID）
            status: 追番状态（目前未使用）

        Returns:
            追番列表，每个元素包含:
            {
                "season_id": int,
                "media_id": int,
                "title": str,
                "cover": str,
                "type": int,  # 1=番剧
                "progress": dict,
                "status": str,
                "url": str
            }
        """
        try:
            await self._ensure_client_async()

            # 使用新的追番 API
            url = "https://api.bilibili.com/x/space/bangumi/follow/list"
            params = {
                "vmid": mid,
                "type": 1,  # 1=番剧
                "pn": 1,
                "ps": 20
            }

            # 尝试添加WBI签名
            try:
                wbi_params = await self._generate_wbi_signature(params)
                resp = await self.client.get(url, params=wbi_params)
            except Exception as wbi_error:
                logger.debug(f"WBI签名失败，尝试无签名: {wbi_error}")
                resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(f"获取追番列表失败: {data.get('message', 'Unknown error')}")
                return []

            items = data.get("data", {}).get("list", []) or []

            # 转换为统一格式
            result = []
            for item in items:
                media_id = item.get("media_id", 0)
                season_id = item.get("season_id", 0)
                new_ep = item.get("new_ep", {})

                result.append({
                    "season_id": season_id,
                    "media_id": media_id,
                    "title": item.get("title", "未知"),
                    "cover": item.get("cover", ""),
                    "type": 1,  # 番剧类型
                    "progress": {
                        "watched_episodes": new_ep.get("index", 0),
                        "total_episodes": item.get("total_count", 0)
                    },
                    "status": status,
                    "publish_time": item.get("publish_time", ""),
                    "url": f"https://www.bilibili.com/bangumi/media/md{media_id}/"
                })

            logger.info(f"获取追番列表成功: {len(result)} ��")
            return result

        except Exception as e:
            logger.error(f"获取追番列表失败: {e}")
            return []

    async def get_user_drama(self, mid: int) -> List[Dict[str, Any]]:
        """
        获取用户追剧列表（电视剧/电影）

        Args:
            mid: 用户UID（B站数字ID）

        Returns:
            追剧列表，格式与追番相同
        """
        try:
            await self._ensure_client_async()

            # 使用相同的API，type=4 表示电视剧/电影
            url = "https://api.bilibili.com/x/space/bangumi/follow/list"
            params = {
                "vmid": mid,
                "type": 4,  # 4=电视剧/电影
                "pn": 1,
                "ps": 20
            }

            # 尝试添加WBI签名
            try:
                wbi_params = await self._generate_wbi_signature(params)
                resp = await self.client.get(url, params=wbi_params)
            except Exception as wbi_error:
                logger.debug(f"WBI签名失败，尝试无签名: {wbi_error}")
                resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(f"获取追剧列表失败: {data.get('message', 'Unknown error')}")
                return []

            items = data.get("data", {}).get("list", []) or []

            # 转换为统一格式（与追番相同）
            result = []
            for item in items:
                media_id = item.get("media_id", 0)
                season_id = item.get("season_id", 0)
                new_ep = item.get("new_ep", {})

                result.append({
                    "season_id": season_id,
                    "media_id": media_id,
                    "title": item.get("title", "未知"),
                    "cover": item.get("cover", ""),
                    "type": 4,  # 追剧类型
                    "progress": {
                        "watched_episodes": new_ep.get("index", 0),
                        "total_episodes": item.get("total_count", 0)
                    },
                    "status": "watching",
                    "publish_time": item.get("publish_time", ""),
                    "url": f"https://www.bilibili.com/bangumi/media/md{media_id}/"
                })

            logger.info(f"获取追剧列表成功: {len(result)} 条")
            return result

        except Exception as e:
            logger.error(f"获取追剧列表失败: {e}")
            return []

    async def get_watch_history(self, pn: int = 1, ps: int = 50) -> List[Dict[str, Any]]:
        """
        获取用户观看历史

        Args:
            pn: 页码，默认为1
            ps: 每页数量，默认50，最大50

        Returns:
            历史记录列表，每个元素包含:
            {
                "bvid": str,
                "aid": int,
                "title": str,
                "cover": str,
                "owner": {"mid": int, "name": str},
                "progress": int,  # 观看进度（秒）
                "duration": int,  # 视频总时长
                "view_at": int,   # 观看时间戳
                "tname": str,     # 分区名称
                "url": str
            }
        """
        try:
            await self._ensure_client_async()

            url = "https://api.bilibili.com/x/v2/history"
            params = {
                "pn": pn,
                "ps": min(ps, 50)  # 最大50条
            }

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(f"获取观看历史失败: {data.get('message', 'Unknown error')}")
                return []

            items = data.get("data", []) or []

            # 转换为统一格式
            result = []
            for item in items:
                bvid = item.get("bvid", "")
                if not bvid:
                    continue

                result.append({
                    "bvid": bvid,
                    "aid": item.get("aid", 0),
                    "title": item.get("title", "未知"),
                    "cover": item.get("pic", ""),
                    "owner": {
                        "mid": item.get("owner", {}).get("mid", 0),
                        "name": item.get("owner", {}).get("name", "未知")
                    },
                    "progress": item.get("progress", 0),
                    "duration": item.get("duration", 0),
                    "view_at": item.get("view_at", 0),
                    "tname": item.get("tname", ""),
                    "url": f"https://www.bilibili.com/video/{bvid}"
                })

            logger.info(f"获取观看历史成功: {len(result)} 条")
            return result

        except Exception as e:
            logger.error(f"获取观看历史失败: {e}")
            return []

    async def get_watchlater_list(self) -> List[Dict[str, Any]]:
        """
        获取稍后观看列表

        Returns:
            稍后观看列表，每个元素包含:
            {
                "bvid": str,
                "aid": int,
                "title": str,
                "cover": str,
                "owner": {"mid": int, "name": str},
                "duration": int,
                "add_time": int,  # 添加时间戳
                "url": str
            }
        """
        try:
            await self._ensure_client_async()

            url = "https://api.bilibili.com/x/v2/history/toview"

            resp = await self.client.get(url)
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(f"获取稍后观看列表失败: {data.get('message', 'Unknown error')}")
                return []

            items = data.get("data", {}).get("list", []) or []

            # 转换为统一格式
            result = []
            for item in items:
                bvid = item.get("bvid", "")
                if not bvid:
                    continue

                result.append({
                    "bvid": bvid,
                    "aid": item.get("aid", 0),
                    "title": item.get("title", "未知"),
                    "cover": item.get("pic", ""),
                    "owner": {
                        "mid": item.get("owner", {}).get("mid", 0),
                        "name": item.get("owner", {}).get("name", "未知")
                    },
                    "duration": item.get("duration", 0),
                    "add_time": item.get("add_time", 0),
                    "url": f"https://www.bilibili.com/video/{bvid}"
                })

            logger.info(f"获取稍后观看列表成功: {len(result)} 条")
            return result

        except Exception as e:
            logger.error(f"获取稍后观看列表失败: {e}")
            return []

    async def add_to_watchlater(self, bvid: str) -> Dict[str, Any]:
        """
        将视频添加到稍后观看

        Args:
            bvid: 视频BV号

        Returns:
            {
                "success": bool,
                "message": str,
                "source": "bilibili_add_to_watchlater"
            }
        """
        try:
            await self._ensure_client_async()

            url = "https://api.bilibili.com/x/v2/history/toview/add"

            # 先获取视频的 aid（有些接口需要 aid）
            video_info = await self.get_video_info(bvid)
            aid = video_info.get("data", {}).get("aid", 0) if video_info.get("success") else 0

            if not aid:
                return {
                    "success": False,
                    "error": "无法获取视频AID",
                    "source": "bilibili_add_to_watchlater"
                }

            payload = {
                "aid": aid,
                "csrf": self.cookies.get("bili_jct", "")
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"https://www.bilibili.com/video/{bvid}"
            }

            resp = await self.client.post(url, data=payload, headers=headers)
            result = resp.json()

            if result.get("code") == 0:
                logger.info(f"添加到稍后观看成功: {bvid}")
                return {
                    "success": True,
                    "message": "已添加到稍后观看",
                    "source": "bilibili_add_to_watchlater"
                }
            else:
                logger.warning(f"添加到稍后观看失败: {result.get('message', 'Unknown error')}")
                return {
                    "success": False,
                    "error": result.get("message", "添加失败"),
                    "source": "bilibili_add_to_watchlater"
                }

        except Exception as e:
            logger.error(f"添加到稍后观看失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_add_to_watchlater"
            }

    async def remove_from_watchlater(self, bvid: str) -> Dict[str, Any]:
        """
        从稍后观看列表移除视频

        Args:
            bvid: 视频BV号

        Returns:
            {
                "success": bool,
                "message": str,
                "source": "bilibili_remove_from_watchlater"
            }
        """
        try:
            await self._ensure_client_async()

            url = "https://api.bilibili.com/x/v2/history/toview/del"

            # 获取视频的 aid
            video_info = await self.get_video_info(bvid)
            aid = video_info.get("data", {}).get("aid", 0) if video_info.get("success") else 0

            if not aid:
                return {
                    "success": False,
                    "error": "无法获取视频AID",
                    "source": "bilibili_remove_from_watchlater"
                }

            payload = {
                "aid": aid,
                "csrf": self.cookies.get("bili_jct", "")
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"https://www.bilibili.com/video/{bvid}"
            }

            resp = await self.client.post(url, data=payload, headers=headers)
            result = resp.json()

            if result.get("code") == 0:
                logger.info(f"从稍后观看移除成功: {bvid}")
                return {
                    "success": True,
                    "message": "已从稍后观看移除",
                    "source": "bilibili_remove_from_watchlater"
                }
            else:
                return {
                    "success": False,
                    "error": result.get("message", "移除失败"),
                    "source": "bilibili_remove_from_watchlater"
                }

        except Exception as e:
            logger.error(f"从稍后观看移除失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "bilibili_remove_from_watchlater"
            }

    async def get_cinema_favorites(self) -> List[Dict[str, Any]]:
        """
        获取影视收藏夹列表（电影、纪录片、综艺等）

        注意：B站的电影、纪录片等内容通常在收藏夹中，
        需要通过收藏夹接口获取，然后筛选类型。

        Returns:
            影视收藏夹列表，每个元素包含:
            {
                "media_id": int,
                "title": str,
                "type": str,  # movie/documentary/variety/other
                "count": int,
                "cover": str,
                "url": str
            }
        """
        try:
            await self._ensure_client_async()

            # 先获取用户收藏夹列表
            url = "https://api.bilibili.com/x/v3/fav/folder/created/list-all"

            resp = await self.client.get(url)
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(f"获取影视收藏夹失败: {data.get('message', 'Unknown error')}")
                return []

            items = data.get("data", {}).get("list", []) or []

            # 筛选可能包含影视内容的收藏夹
            # 电影相关关键词
            movie_keywords = ["电影", "movie", "film", "影视", "剧集", "纪录片", "综艺", "追剧", "追番"]
            # 番剧相关关键词
            anime_keywords = ["番剧", "anime", "追番", "动漫"]

            result = []
            for item in items:
                title = item.get("title", "").lower()

                # 判断类型
                media_type = "other"
                if any(k in title for k in movie_keywords):
                    media_type = "movie"
                elif any(k in title for k in anime_keywords):
                    media_type = "anime"
                elif title in ["纪录片", "documentary"]:
                    media_type = "documentary"
                elif title in ["综艺", "variety"]:
                    media_type = "variety"

                # 获取收藏夹内视频数量
                fav_count = item.get("fav_count", 0)

                # 只返回有内容的收藏夹
                if fav_count > 0:
                    result.append({
                        "media_id": item.get("id", 0),
                        "title": item.get("title", "未知"),
                        "type": media_type,
                        "count": fav_count,
                        "cover": item.get("cover", ""),
                        "attr": item.get("attr", 0),
                        "url": f"https://api.bilibili.com/x/v3/fav/resource/list?media_id={item.get('id', 0)}"
                    })

            logger.info(f"获取影视收藏夹成功: {len(result)} 个")
            return result

        except Exception as e:
            logger.error(f"获取影视收藏夹失败: {e}")
            return []

    async def get_cinema_favorite_videos(self, media_id: int, pn: int = 1, ps: int = 20) -> List[Dict[str, Any]]:
        """
        获取影视收藏夹内的视频列表

        Args:
            media_id: 收藏夹ID
            pn: 页码
            ps: 每页数量

        Returns:
            视频列表，每个元素包含:
            {
                "bvid": str,
                "aid": int,
                "title": str,
                "cover": str,
                "owner": {"mid": int, "name": str},
                "duration": int,
                "pubdate": int,
                "url": str
            }
        """
        try:
            await self._ensure_client_async()

            url = "https://api.bilibili.com/x/v3/fav/resource/list"
            params = {
                "media_id": media_id,
                "pn": pn,
                "ps": ps
            }

            resp = await self.client.get(url, params=params)
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(f"获取影视收藏夹视频失败: {data.get('message', 'Unknown error')}")
                return []

            items = data.get("data", {}).get("medias", []) or []

            result = []
            for item in items:
                bvid = item.get("bvid", "")
                if not bvid:
                    continue

                result.append({
                    "bvid": bvid,
                    "aid": item.get("aid", 0),
                    "title": item.get("title", "未知"),
                    "cover": item.get("cover", ""),
                    "owner": {
                        "mid": item.get("upper", {}).get("mid", 0),
                        "name": item.get("upper", {}).get("name", "未知")
                    },
                    "duration": item.get("duration", 0),
                    "pubdate": item.get("pubdate", 0),
                    "url": f"https://www.bilibili.com/video/{bvid}"
                })

            logger.info(f"获取影视收藏夹视频成功: {len(result)} 个")
            return result

        except Exception as e:
            logger.error(f"获取影视收藏夹视频失败: {e}")
            return []
