import os
from dotenv import load_dotenv

# 加载 .env 文件中的变量
load_dotenv() 

# 然后正常读取即可
COZE_API_TOKEN = os.getenv("COZE_API_TOKEN", "").strip()
# 禁用外网 CDN，强制 Gradio 使用本地的 JS 和 CSS 文件
os.environ["GRADIO_NO_CDN"] = "1" 

import gradio as gr
import time
import json
import io
import base64
import tempfile
import requests
import os
import re
import html
import hashlib
from PIL import Image, ImageDraw
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlparse, quote

# ==========================================
# 环境变量或全局配置
# ==========================================
COZE_API_TOKEN = os.getenv("COZE_API_TOKEN", "").strip()
WORKFLOW_ID = os.getenv("COZE_WORKFLOW_ID", "7618946646898982947").strip()
COZE_API_BASE = os.getenv("COZE_API_BASE", "https://api.coze.cn").strip() or "https://api.coze.cn"
COZE_WORKFLOW_VERSION = os.getenv("COZE_WORKFLOW_VERSION", "").strip()

COZE_ASYNC_POLL_INTERVAL = int(os.getenv("COZE_ASYNC_POLL_INTERVAL", "2").strip() or "2")
COZE_SPLIT_COMPOSITE = (os.getenv("COZE_SPLIT_COMPOSITE", "0").strip().lower() in ("1", "true", "yes", "y"))
COZE_GRID_COLS = int(os.getenv("COZE_GRID_COLS", "3").strip() or "3")
COZE_GRID_MAX_ROWS = int(os.getenv("COZE_GRID_MAX_ROWS", "10").strip() or "10")
COZE_TRUST_ENV = (os.getenv("COZE_TRUST_ENV", "0").strip().lower() in ("1", "true", "yes", "y"))

# 新增缺失的超时、重试、异步开关常量
COZE_RETRIES = int(os.getenv("COZE_RETRIES", "2").strip() or "2")
COZE_CONNECT_TIMEOUT = int(os.getenv("COZE_CONNECT_TIMEOUT", "15").strip() or "15")
COZE_READ_TIMEOUT = int(os.getenv("COZE_READ_TIMEOUT", "180").strip() or "180")
COZE_ASYNC_MAX_WAIT = int(os.getenv("COZE_ASYNC_MAX_WAIT", "600").strip() or "600")
COZE_USE_ASYNC = (os.getenv("COZE_USE_ASYNC", "1").strip().lower() in ("1", "true", "yes", "y"))
COZE_SAVE_STATIC = (os.getenv("COZE_SAVE_STATIC", "1").strip().lower() in ("1", "true", "yes", "y"))

# ==========================================
# 核心设计规范 (Design System) - 自定义 CSS
custom_css = """
/* 1. 全局色彩与排版：保护视力，拒绝纯白纯黑 */
body, .gradio-container {
    background-color: #fafaf9 !important;
    color: #44403c !important;
    font-family: 'Comic Sans MS', 'Nunito', 'PingFang SC', sans-serif !important;
    font-size: 1.1rem !important;
    line-height: 1.6 !important;
}

/* 隐藏底部默认的 Gradio 页脚，保持页面干净 */
footer { display: none !important; }

/* 2. 形状：全局大圆角与无生硬边框 */
* {
    border-radius: 20px !important;
    border-color: transparent !important;
}

/* 3. 交互反馈与动画：生成按钮 (向日葵黄渐变) */
.generate-btn {
    background: linear-gradient(135deg, #facc15, #fbbf24) !important;
    color: #713f12 !important;
    font-weight: bold !important;
    font-size: 1.3rem !important;
    border: none !important;
    box-shadow: 0 8px 20px rgba(250, 204, 21, 0.3) !important;
    transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
}
.generate-btn:hover {
    transform: scale(1.05) !important;
    box-shadow: 0 12px 25px rgba(250, 204, 21, 0.5) !important;
    background: linear-gradient(135deg, #fbbf24, #f59e0b) !important;
}

/* 4. 奇妙画卷：画廊卡片悬浮上浮效果 */
.comic-card {
    background: rgba(255, 255, 255, 0.8) !important;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.04) !important;
    transition: transform 0.3s ease, box-shadow 0.3s ease !important;
}
.comic-card:hover {
    transform: translateY(-5px) !important;
    box-shadow: 0 15px 35px rgba(0, 0, 0, 0.08) !important;
}

/* 5. 创作控制台：毛玻璃拟态背景 (Glassmorphism) */
.glass-panel {
    background: rgba(255, 255, 255, 0.6) !important;
    backdrop-filter: blur(16px) !important;
    -webkit-backdrop-filter: blur(16px) !important;
    border: 1px solid rgba(255, 255, 255, 0.8) !important;
    box-shadow: 0 8px 32px rgba(31, 38, 135, 0.05) !important;
    padding: 20px !important;
}

/* 输入框和上传区基础样式优化 */
textarea, .upload-container {
    background: rgba(255, 255, 255, 0.9) !important;
    box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.02) !important;
    transition: box-shadow 0.3s ease !important;
}
textarea:focus, .upload-container:hover {
    box-shadow: 0 0 0 3px rgba(250, 204, 21, 0.4) !important;
}
"""

# ==========================================
# 页面骨架构建
# ==========================================
# 使用 Soft 主题作为底座，配合 custom_css 覆盖
theme = gr.themes.Soft(
    primary_hue="yellow",
    secondary_hue="blue",
    neutral_hue="stone",
    spacing_size="lg",
    radius_size="lg",
    text_size="lg"
)

with gr.Blocks(title="奇妙漫画工坊") as demo:
    gr.Markdown("# ✨ 漫画工坊\n")
    
    # 左右分栏布局
    with gr.Row():
        
        # ==========================================
        # 左侧：创作控制台 (占宽约 35%)
        # ==========================================
        with gr.Column(scale=35, elem_classes="glass-panel"):
            gr.Markdown("### 🎨 创作控制台")
            
            

            story_input = gr.Textbox(
                label="故事文本",
                placeholder="在这里写下故事吧...",
                lines=5,
                max_lines=10,
                show_label=True
            )
            
            
            
            reference_image = gr.Image(
                label="参考插画 (确保角色特征一致)",
                type="filepath",
                sources=["upload", "clipboard"],
                elem_classes="upload-container",
                height=200
            )

            
            
            generate_btn = gr.Button("✨ 生成漫画", elem_classes="generate-btn", size="lg")
            
        # ==========================================
        # 右侧：奇妙画卷 (占宽约 65%)
        # ==========================================
        with gr.Column(scale=65):
            gr.Markdown("### 🖼️ 奇妙画卷")
            
            comic_html = gr.HTML(
                value="",
                elem_classes="comic-card",
            )

    # ==========================================
    # 事件绑定与 API Mock 接入
    # ==========================================
    def _try_parse_json(text: str):
        if text is None:
            raise ValueError("empty")
        s = text.strip()
        # 移除可能存在的 markdown 代码块包裹
        if s.startswith("```json"):
            s = s[7:]
        elif s.startswith("```"):
            s = s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
        
        if not s:
            raise ValueError("empty")
        return json.loads(s)

    def _iter_image_candidates(obj):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            yield obj
            for key in ("images", "imgs", "image_list", "pictures", "panels", "frames"):
                val = obj.get(key)
                if isinstance(val, list):
                    for item in val:
                        yield item
            for v in obj.values():
                yield from _iter_image_candidates(v)
        elif isinstance(obj, list):
            for item in obj:
                yield item
                yield from _iter_image_candidates(item)

    def _pick_image_ref(item):
        if isinstance(item, str):
            s = item.strip().strip("`\"'").replace("\\/", "/")
            if s.startswith("http://") or s.startswith("https://"):
                return {"url": s, "caption": ""}
            if s.startswith("data:image/"):
                return {"data_url": s, "caption": ""}
            return None
        if not isinstance(item, dict):
            return None
        url = (
            item.get("final_comic")
            or item.get("finalComic")
            or item.get("url")
            or item.get("file_url")
            or item.get("image_url")
            or item.get("image")
        )
        file_id = item.get("file_id") or item.get("id")
        b64 = item.get("base64") or item.get("b64") or item.get("image_base64") or item.get("image_b64")
        caption = item.get("caption") or item.get("title") or item.get("name") or ""
        if url:
            s = str(url).strip().strip("`\"'").replace("\\/", "/")
            if s.startswith("http://") or s.startswith("https://"):
                return {"url": s, "caption": str(caption)}
            if s.startswith("data:image/"):
                return {"data_url": s, "caption": str(caption)}
        if b64 and isinstance(b64, str):
            return {"b64": b64, "caption": str(caption)}
        if file_id:
            return {"file_id": str(file_id), "caption": str(caption)}
        return None

    def _extract_first_http_url(text: str) -> str:
        s = (text or "").strip()
        if not s:
            return ""
        s = s.replace("\\/", "/")
        m = re.search(r"https?://[^\s\"'`\\]+", s)
        if not m:
            return ""
        return m.group(0).strip().strip("`\"'").rstrip("\\")

    def _find_first_str_by_keys(obj, keys):
        if isinstance(obj, str):
            return _extract_first_http_url(obj)
        if isinstance(obj, dict):
            name = obj.get("name") or obj.get("key")
            if isinstance(name, str) and name in keys:
                for vk in ("value", "val", "data", "url", "text", "content"):
                    vv = obj.get(vk)
                    if isinstance(vv, str) and vv.strip():
                        return vv.strip()
            for k in keys:
                v = obj.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            for v in obj.values():
                found = _find_first_str_by_keys(v, keys)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _find_first_str_by_keys(item, keys)
                if found:
                    return found
        return ""

    def _load_pil_from_data_url(data_url: str) -> Image.Image:
        prefix = "base64,"
        idx = data_url.find(prefix)
        if idx < 0:
            raise ValueError("invalid data url")
        b64 = data_url[idx + len(prefix):]
        raw = base64.b64decode(b64)
        return Image.open(io.BytesIO(raw)).convert("RGB")

    def _load_pil_from_url(url: str) -> Image.Image:
        session = requests.Session()
        session.trust_env = COZE_TRUST_ENV
        retry = Retry(
            total=COZE_RETRIES,
            connect=COZE_RETRIES,
            read=COZE_RETRIES,
            status=COZE_RETRIES,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        resp = session.get(
            url,
            timeout=(COZE_CONNECT_TIMEOUT, COZE_READ_TIMEOUT),
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.coze.cn/"},
        )
        if resp.status_code != 200:
            body = (resp.text or "")[:200]
            raise ValueError(f"http {resp.status_code}: {body}")
        content_type = (resp.headers.get("content-type") or "").lower()
        if content_type and not (content_type.startswith("image/") or "octet-stream" in content_type):
            snippet = (resp.text or "")[:200]
            raise ValueError(f"non-image content-type: {content_type}; body: {snippet}")
        try:
            return Image.open(io.BytesIO(resp.content)).convert("RGB")
        except Exception as e:
            raise ValueError(f"image decode failed: {type(e).__name__}; content-type: {content_type}") from e

    def _load_pil_from_ref(ref: dict) -> Image.Image:
        if "data_url" in ref:
            return _load_pil_from_data_url(ref["data_url"])
        if "b64" in ref:
            raw = base64.b64decode(ref["b64"])
            return Image.open(io.BytesIO(raw)).convert("RGB")
        if "url" in ref:
            return _load_pil_from_url(ref["url"])
        raise ValueError("unsupported image ref")

    def _infer_grid_rows(img: Image.Image, cols: int, max_rows: int) -> int:
        if cols <= 0:
            return 1
        best_rows = 1
        best_score = None
        target = 4 / 3
        for rows in range(1, max_rows + 1):
            cell_w = img.width / cols
            cell_h = img.height / rows
            if cell_h <= 0:
                continue
            ratio = cell_w / cell_h
            score = abs(ratio - target)
            if best_score is None or score < best_score:
                best_score = score
                best_rows = rows
        return best_rows

    def _split_grid(img: Image.Image, cols: int, rows: int):
        cols = max(1, int(cols))
        rows = max(1, int(rows))
        cell_w = img.width / cols
        cell_h = img.height / rows
        out = []
        for r in range(rows):
            for c in range(cols):
                left = int(round(c * cell_w))
                upper = int(round(r * cell_h))
                right = int(round((c + 1) * cell_w))
                lower = int(round((r + 1) * cell_h))
                tile = img.crop((left, upper, right, lower))
                out.append(tile)
        return out

    def _placeholder_image(text: str) -> Image.Image:
        img = Image.new("RGB", (800, 600), color="#f3f4f6")
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, 760, 560], outline="#9ca3af", width=6)
        safe = (text or "")[:500].encode("ascii", "backslashreplace").decode("ascii")
        draw.text((60, 80), safe[:200], fill="#111827")
        return img

    def _pil_to_data_url(img: Image.Image) -> str:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    def _render_comic_html(image_src: str, run_id: str = "", static_src: str = "") -> str:
        src = (image_src or "").strip().strip("`\"'")
        if not src:
            return ""
        # 修复可能存在的转义字符
        src = src.replace("\\u0026", "&").replace("\\/", "/")
        safe_src = html.escape(src, quote=True)
        static_src = (static_src or "").strip()
        safe_static = html.escape(static_src, quote=True) if static_src else ""
        safe_run = html.escape(run_id or "", quote=True)
        title = "合成图"
        if safe_run:
            title = f"合成图（run_id: {safe_run}）"
        links = f"<a href='{safe_src}' target='_blank' rel='noreferrer'>打开原图</a>"
        if safe_static:
            links = links + f"　|　<a href='{safe_static}' target='_blank' rel='noreferrer'>打开静态图</a>"
        return (
            f"<div style='width:100%;height:100%;overflow:auto'>"
            f"<div style='margin: 8px 0; font-weight: 600;'>{title}</div>"
            f"<div style='margin: 8px 0;'>{links}</div>"
            f"<img src='{safe_static or safe_src}' referrerpolicy='no-referrer' style='max-width:100%;height:auto;display:block;border-radius:16px'/>"
            f"</div>"
        )

    def _download_comic_to_static(url: str, run_id: str = "") -> str:
        if not COZE_SAVE_STATIC:
            return ""
        src = (url or "").strip().strip("`\"'").replace("\\u0026", "&").replace("\\/", "/")
        if not (src.startswith("http://") or src.startswith("https://")):
            return ""
        os.makedirs(STATIC_OUTPUT_DIR, exist_ok=True)
        key = run_id.strip() if run_id else hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]
        out_path = os.path.join(STATIC_OUTPUT_DIR, f"comic_{key}.png")
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            return out_path
        session = requests.Session()
        session.trust_env = COZE_TRUST_ENV
        retry = Retry(
            total=COZE_RETRIES,
            connect=COZE_RETRIES,
            read=COZE_RETRIES,
            status=COZE_RETRIES,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        resp = session.get(
            src,
            timeout=(COZE_CONNECT_TIMEOUT, COZE_READ_TIMEOUT),
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.coze.cn/"},
            stream=True,
        )
        if resp.status_code != 200:
            return ""
        max_bytes = 25 * 1024 * 1024
        total = 0
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 64):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    f.close()
                    try:
                        os.unlink(out_path)
                    except Exception:
                        pass
                    return ""
                f.write(chunk)
        return out_path if os.path.isfile(out_path) and os.path.getsize(out_path) > 0 else ""

    def _build_mock_images(progress=None):
        if progress:
            progress(0.8, desc="正在生成图片...")
        time.sleep(1)
        img = Image.new("RGB", (1200, 800), color="#fef08a")
        draw = ImageDraw.Draw(img)
        draw.rectangle([60, 60, 1140, 740], outline="#ffffff", width=18)
        if progress:
            progress(1.0, desc="完成")
        return _render_comic_html(_pil_to_data_url(img))

    def _coze_err_text(resp) -> str:
        try:
            data = resp.json()
        except Exception:
            return (resp.text or "")[:300]
        if not isinstance(data, dict):
            return str(data)[:300]
        msg = data.get("msg") or data.get("message") or ""
        logid = ""
        detail = data.get("detail")
        if isinstance(detail, dict):
            logid = detail.get("logid") or detail.get("logId") or ""
        if logid:
            return f"{msg} (logid={logid})"
        return msg or str(data)[:300]

    def _coze_post_json(url: str, token: str, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {token}"}
        session = requests.Session()
        session.trust_env = COZE_TRUST_ENV
        retry = Retry(
            total=COZE_RETRIES,
            connect=COZE_RETRIES,
            read=COZE_RETRIES,
            status=COZE_RETRIES,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["POST"]),
            raise_on_status=False,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        try:
            resp = session.post(
                url,
                headers=headers,
                json=payload,
                timeout=(COZE_CONNECT_TIMEOUT, COZE_READ_TIMEOUT),
            )
        except requests.exceptions.ReadTimeout:
            raise gr.Error(
                f"请求 Coze 超时（读取超时 {COZE_READ_TIMEOUT}s）。可能是网络/代理问题或工作流耗时较长。"
                "可尝试：切换网络/关闭代理，或增大 COZE_READ_TIMEOUT 环境变量。"
            )
        except requests.exceptions.ConnectTimeout:
            raise gr.Error(
                f"连接 Coze 超时（连接超时 {COZE_CONNECT_TIMEOUT}s）。请检查网络、代理或防火墙设置。"
            )
        if resp.status_code != 200:
            raise gr.Error(f"请求失败：HTTP {resp.status_code}，{_coze_err_text(resp)}")
        try:
            data = resp.json()
        except Exception:
            raise gr.Error(f"返回不是 JSON：{(resp.text or '')[:300]}")
        if isinstance(data, dict) and data.get("code") not in (None, 0, "0"):
            msg = data.get("msg") or data.get("message") or "unknown error"
            raise gr.Error(f"Coze 返回错误：{msg}")
        return data

    def _coze_get_json(url: str, token: str) -> dict:
        headers = {"Authorization": f"Bearer {token}"}
        session = requests.Session()
        session.trust_env = COZE_TRUST_ENV
        retry = Retry(
            total=COZE_RETRIES,
            connect=COZE_RETRIES,
            read=COZE_RETRIES,
            status=COZE_RETRIES,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        try:
            resp = session.get(url, headers=headers, timeout=(COZE_CONNECT_TIMEOUT, COZE_READ_TIMEOUT))
        except requests.exceptions.ReadTimeout:
            raise gr.Error(
                f"查询异步结果超时（读取超时 {COZE_READ_TIMEOUT}s）。可尝试增大 COZE_READ_TIMEOUT。"
            )
        except requests.exceptions.ConnectTimeout:
            raise gr.Error(
                f"连接 Coze 超时（连接超时 {COZE_CONNECT_TIMEOUT}s）。请检查网络、代理或防火墙设置。"
            )
        if resp.status_code != 200:
            raise gr.Error(f"请求失败：HTTP {resp.status_code}，{_coze_err_text(resp)}")
        try:
            data = resp.json()
        except Exception:
            raise gr.Error(f"返回不是 JSON：{(resp.text or '')[:300]}")
        if isinstance(data, dict) and data.get("code") not in (None, 0, "0"):
            msg = data.get("msg") or data.get("message") or "unknown error"
            raise gr.Error(f"Coze 返回错误：{msg}")
        return data

    def _coze_upload_file(file_path: str, token: str) -> str:
        base = COZE_API_BASE.rstrip("/")
        url = f"{base}/v1/files/upload"
        headers = {"Authorization": f"Bearer {token}"}
        session = requests.Session()
        session.trust_env = COZE_TRUST_ENV
        retry = Retry(
            total=COZE_RETRIES,
            connect=COZE_RETRIES,
            read=COZE_RETRIES,
            status=COZE_RETRIES,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["POST"]),
            raise_on_status=False,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        try:
            with open(file_path, "rb") as f:
                resp = session.post(
                    url,
                    headers=headers,
                    files={"file": (os.path.basename(file_path) or "image", f)},
                    timeout=(COZE_CONNECT_TIMEOUT, COZE_READ_TIMEOUT),
                )
        except requests.exceptions.ReadTimeout:
            raise gr.Error(
                f"上传图片到 Coze 超时（读取超时 {COZE_READ_TIMEOUT}s）。可能是网络/代理问题或图片较大。"
                "可尝试：切换网络/关闭代理，或增大 COZE_READ_TIMEOUT 环境变量。"
            )
        except requests.exceptions.ConnectTimeout:
            raise gr.Error(
                f"连接 Coze 超时（连接超时 {COZE_CONNECT_TIMEOUT}s）。请检查网络、代理或防火墙设置。"
            )
        if resp.status_code != 200:
            raise gr.Error(f"图片上传失败：HTTP {resp.status_code}，{_coze_err_text(resp)}")
        try:
            data = resp.json()
        except Exception:
            raise gr.Error(f"图片上传返回不是 JSON：{(resp.text or '')[:300]}")
        if isinstance(data, dict) and data.get("code") not in (None, 0, "0"):
            msg = data.get("msg") or data.get("message") or "unknown error"
            raise gr.Error(f"图片上传失败：{msg}")
        candidates = []
        if isinstance(data, dict):
            candidates.append(data.get("file_id"))
            candidates.append(data.get("id"))
            d = data.get("data")
            if isinstance(d, dict):
                candidates.append(d.get("file_id"))
                candidates.append(d.get("id"))
                fobj = d.get("file")
                if isinstance(fobj, dict):
                    candidates.append(fobj.get("file_id"))
                    candidates.append(fobj.get("id"))
        file_id = next((str(x) for x in candidates if x), "")
        if not file_id:
            raise gr.Error(f"图片上传成功但未找到 file_id：{data}")
        return file_id

    def _coze_workflow_run(workflow_id: str, parameters: dict, token: str, progress=None) -> dict:
        base = COZE_API_BASE.rstrip("/")
        url = f"{base}/v1/workflow/run"
        payload = {"workflow_id": workflow_id, "parameters": parameters}
        if COZE_WORKFLOW_VERSION:
            payload["workflow_version"] = COZE_WORKFLOW_VERSION
        if not COZE_USE_ASYNC:
            return _coze_post_json(url, token, payload)

        payload["is_async"] = True
        first = _coze_post_json(url, token, payload)
        execute_id = ""
        if isinstance(first, dict):
            d = first.get("data")
            if isinstance(d, dict):
                execute_id = str(d.get("execute_id") or d.get("executeId") or "")
            if not execute_id:
                execute_id = str(first.get("execute_id") or first.get("executeId") or "")
        if not execute_id:
            return first

        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > COZE_ASYNC_MAX_WAIT:
                raise gr.Error(f"工作流执行超过 {int(COZE_ASYNC_MAX_WAIT)} 秒仍未完成，请稍后重试。")
            if progress:
                progress(0.55, desc=f"⏳ 工作流运行中（已等待 {int(elapsed)}s）...")
            history_url = f"{base}/v1/workflows/{workflow_id}/run_histories/{execute_id}"
            history_resp = _coze_get_json(history_url, token)
            item = None
            if isinstance(history_resp, dict):
                data = history_resp.get("data")
                if isinstance(data, list) and data:
                    item = data[0]
                elif isinstance(data, dict):
                    item = data
                elif isinstance(history_resp.get("result"), dict):
                    item = history_resp["result"]
            if isinstance(item, dict):
                status = (item.get("execute_status") or item.get("executeStatus") or "").lower()
                if status == "success":
                    return {"data": item.get("output") or ""}
                if status == "fail":
                    msg = item.get("error_message") or item.get("errorMessage") or "unknown error"
                    raise gr.Error(f"工作流执行失败：{msg}")
                if status == "running":
                    time.sleep(COZE_ASYNC_POLL_INTERVAL)
                    continue

            time.sleep(COZE_ASYNC_POLL_INTERVAL)

    def _extract_structured_output(result: dict):
        if isinstance(result, dict):
            d = result.get("data")
            if isinstance(d, dict) and "data" in d:
                return d["data"]
            if d is not None:
                return d
            if "result" in result:
                return result["result"]
        return result

    def _coerce_ref_img_to_file_path(ref_img) -> str:
        if not ref_img:
            return ""
        if isinstance(ref_img, str):
            return ref_img
        if isinstance(ref_img, dict):
            for key in ("path", "name", "file_path", "filepath", "tmp_path"):
                val = ref_img.get(key)
                if isinstance(val, str):
                    return val
            return ""
        if isinstance(ref_img, Image.Image):
            f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            ref_img.save(f.name, format="PNG")
            f.close()
            return f.name
        try:
            import numpy as np

            if isinstance(ref_img, np.ndarray):
                img = Image.fromarray(ref_img)
                f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                img.save(f.name, format="PNG")
                f.close()
                return f.name
        except Exception:
            return ""
        return ""

    def _download_image_url_to_temp(image_url: str) -> str:
        url = (image_url or "").strip()
        if not url:
            return ""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise gr.Error("参考插画 URL 只支持 http/https。")
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            raise gr.Error("参考插画 URL 不支持本机地址。")
        session = requests.Session()
        session.trust_env = COZE_TRUST_ENV
        resp = session.get(
            url,
            stream=True,
            timeout=(COZE_CONNECT_TIMEOUT, COZE_READ_TIMEOUT),
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.coze.cn/"},
        )
        if resp.status_code != 200:
            raise gr.Error(f"下载参考插画失败：HTTP {resp.status_code}")
        content_type = (resp.headers.get("content-type") or "").lower()
        suffix = ".jpg"
        if "png" in content_type:
            suffix = ".png"
        elif "webp" in content_type:
            suffix = ".webp"
        elif "gif" in content_type:
            suffix = ".gif"
        elif "jpeg" in content_type:
            suffix = ".jpg"
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        max_bytes = 25 * 1024 * 1024
        total = 0
        for chunk in resp.iter_content(chunk_size=1024 * 64):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                f.close()
                os.unlink(f.name)
                raise gr.Error("下载的图片过大（>25MB），请换更小的图片。")
            f.write(chunk)
        f.close()
        return f.name

    def call_coze_workflow_api_mock(story, ref_img, progress=gr.Progress()):
        """
        接入 Coze Workflow API
        规范要求：向 Coze 发起请求时，务必使用原生的 Structured Output (结构化 JSON) 
        """
        if not story:
            raise gr.Error("请先在左侧写下你想生成漫画的故事文本。")
        token = COZE_API_TOKEN.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            gr.Warning("未配置 COZE_API_TOKEN，已切换到演示模式。")
            return _build_mock_images(progress)

        try:
            progress(0.2, desc="正在准备数据...")
            # 强制追加角色一致性指令，确保生成效果符合用户要求
            strict_prompt = (
                "\n\n【最高优先级系统指令：角色与服装绝对一致性】\n"
                "1. 你的首要任务是完全复刻参考插图中的人物形象，包括但不限于：发型、五官特征、服装款式、**服装颜色**（上衣、裤子/裙子、鞋子等）。\n"
                "2. 绝对禁止随意改变人物的衣服颜色和款式。请仔细识别参考图中的人物穿着，并在生成的每一个分镜提示词（Prompt）中，强制且详细地描述这些固定的服装特征。\n"
                "3. 如果参考图中有多个角色，请确保在每个场景中准确对应他们的穿着，不得混淆，不得修改！"
            )
            
            
                
            enhanced_story = story.strip() + strict_prompt
            parameters = {"book_content": enhanced_story}
            tmp_download = ""
            if ref_img:
                file_path = _coerce_ref_img_to_file_path(ref_img)
            else:
                file_path = ""

            if file_path:
                if not os.path.isfile(file_path):
                    raise gr.Error("参考插画读取失败，请重新选择图片文件或检查 URL。")
                file_id = _coze_upload_file(file_path, token)
                parameters["ref_image"] = {"file_id": file_id}
            else:
                gr.Warning("未提供参考插画：同一工作流也可能出现不同画风。为保持画风一致，请上传同风格参考图。")

            progress(0.5, desc="正在调用工作流...")
            result = _coze_workflow_run(WORKFLOW_ID, parameters, token, progress=progress)
            gr.Info("工作流调用成功。")
            structured = _extract_structured_output(result)
            if isinstance(structured, str):
                try:
                    output_obj = _try_parse_json(structured)
                except Exception:
                    output_obj = structured
            else:
                output_obj = structured

            if isinstance(output_obj, dict):
                inner = None
                for k in ("Output", "output", "result", "data"):
                    v = output_obj.get(k)
                    if isinstance(v, str):
                        try:
                            inner = _try_parse_json(v)
                            break
                        except Exception:
                            continue
                if inner is not None:
                    output_obj = inner

            output_dict = output_obj if isinstance(output_obj, dict) else {}
            if not output_dict and not isinstance(output_obj, str):
                try:
                    output_dict = json.loads(json.dumps(output_obj, ensure_ascii=False))
                except Exception:
                    output_dict = {}

            # === 修改后的严格 1:1 图文映射逻辑 ===
            # 1. 将你在左侧输入的故事文本按换行符切分成独立的句子列表
            text_lines = [line.strip() for line in story.strip().split('\n') if line.strip()]
            
            # 2. 纯净提取所有生成的图片链接
            image_urls = []
            for candidate in _iter_image_candidates(output_obj):
                ref = _pick_image_ref(candidate)
                if ref and ref.get("url"):
                    if ref["url"] not in image_urls:
                        image_urls.append(ref["url"])
            
            if not image_urls:
                all_text = json.dumps(output_obj, ensure_ascii=False).replace("\\/", "/")
                urls = re.findall(r"https?://[^\s\"'`\\]+", all_text)
                for u in urls:
                    if u not in image_urls:
                        image_urls.append(u)

            if not image_urls:
                print(f"工作流完整输出内容: {structured}")
                raise ValueError("未在结果中找到任何图片链接，请检查 Coze 输出格式。")

            progress(1.0, desc="完成")
            
            # 3. 核心：将左侧输入的句子与右侧生成的图片按顺序进行 1:1 严格绑定
            panels = []
            for i, url in enumerate(image_urls):
                # 依次取出一句台词，如果图片比台词多，多出的图片就不带字
                text_content = text_lines[i] if i < len(text_lines) else ""
                panels.append({"url": url, "text": text_content})
            
            # 4. 渲染最终的白底卡片 HTML
            html_content = (
                "<div style='width:100%; height:100%; overflow:auto; display: flex; flex-direction: column; gap: 24px; align-items: center; padding: 10px;'>"
            )
            
            for panel in panels:
                safe_url = html.escape(panel["url"], quote=True)
                safe_text = html.escape(panel["text"])
                
                text_html = ""
                if safe_text:
                    # 渲染卡片底部的文字，保留原汁原味的对话格式
                    text_html = f"<div style='margin-top: 12px; font-size: 1.15rem; color: #44403c; line-height: 1.6; padding: 0 8px;'>{safe_text}</div>"
                
                html_content += (
                    f"<div style='width: 100%; max-width: 800px; background: #ffffff; padding: 16px; border-radius: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.04);'>"
                    f"<img src='{safe_url}' referrerpolicy='no-referrer' "
                    f"style='width: 100%; height: auto; display: block; border-radius: 12px;'/>"
                    f"{text_html}"
                    f"</div>"
                )
            
            html_content += "</div>"
            
            return html_content
            
        except gr.Error as e:
            msg = str(e)
            if "HTTP 401" in msg or "access token invalid" in msg.lower():
                raise gr.Error(
                    "Token 无效或已过期（HTTP 401: access token invalid）。"
                    "请在 Coze 控制台生成新的个人访问令牌（PAT，通常以 pat_ 开头），"
                    "然后在本页填写或设置为环境变量 COZE_API_TOKEN。修改后需重启程序。"
                )
            raise
        except Exception as e:
            # 打印更详细的错误堆栈以便排查
            import traceback
            error_details = traceback.format_exc()
            print(f"请求异常详细信息:\n{error_details}")
            gr.Warning(f"请求发生异常: {str(e)}。已切换至演示模式。")
            return _build_mock_images(progress)
        finally:
            if "tmp_download" in locals() and tmp_download:
                try:
                    os.unlink(tmp_download)
                except Exception:
                    pass

    # 绑定点击事件，连接左侧输入与右侧画廊
    generate_btn.click(
        fn=call_coze_workflow_api_mock,
        inputs=[story_input, reference_image],
        outputs=[comic_html]
    )

if __name__ == "__main__":
    hosts = ["127.0.0.1", "localhost", "0.0.0.0", "api.coze.cn", "api.coze.com"]
    existing = os.getenv("NO_PROXY") or os.getenv("no_proxy") or ""
    parts = [p.strip() for p in existing.split(",") if p.strip()] if existing else []
    for h in hosts:
        if h not in parts:
            parts.append(h)
    merged = ",".join(parts)
    os.environ["NO_PROXY"] = merged
    os.environ["no_proxy"] = merged
    port_raw = os.getenv("GRADIO_SERVER_PORT", "").strip()
    server_port = int(port_raw) if port_raw.isdigit() else None
    import inspect
    STATIC_OUTPUT_DIR = "static_outputs"
    launch_sig = inspect.signature(demo.launch)
    if "allowed_paths" in launch_sig.parameters:
        demo.launch(server_name="127.0.0.1", server_port=server_port, allowed_paths=[STATIC_OUTPUT_DIR], share=True, theme=theme, css=custom_css)
    else:
        demo.launch(server_name="127.0.0.1", server_port=server_port)
