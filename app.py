import gradio as gr
import uuid
import os
import requests
import time
import json
import base64
import socket
from dotenv import load_dotenv

# ==========================================
# 1. 环境变量配置 (从 .env 文件自动加载)
# ==========================================
load_dotenv()

COZE_API_TOKEN = os.getenv("COZE_API_TOKEN", "")
CHAT_BOT_ID = os.getenv("CHAT_BOT_ID", "")
SCRIPT_BOT_ID = os.getenv("SCRIPT_BOT_ID", "")
COZE_WORKFLOW_ID = os.getenv("COZE_WORKFLOW_ID", "")

# 禁用代理，避免系统代理干扰 Coze API 直连
NO_PROXY = {"http": None, "https": None} 

# ==========================================
# 2. 核心 API 引擎：扣子 (Coze) v3 接口调用
# ==========================================
def call_coze_bot_v3(bot_id, user_id, message):
    """
    通用扣子 v3 智能体对话接口。
    流程：发起对话请求 -> 轮询等待处理完成 -> 获取最终回复内容
    """
    if not COZE_API_TOKEN or not bot_id:
        return "⚠️ 系统提示：环境变量中缺失 API Token 或 Bot ID，请检查 .env 文件。"

    headers = {
        "Authorization": f"Bearer {COZE_API_TOKEN}",
        "Content-Type": "application/json"
    }

    # 第一步：发起对话 (Create Chat)
    chat_url = "https://api.coze.cn/v3/chat"
    payload = {
        "bot_id": bot_id,
        "user_id": user_id,
        "additional_messages": [
            {"role": "user", "content": message, "content_type": "text"}
        ]
    }

    try:
        chat_res = requests.post(chat_url, headers=headers, json=payload, proxies=NO_PROXY).json()
        if chat_res.get("code") != 0:
            return f"接口请求失败: {chat_res.get('msg', '未知错误')}"
        
        chat_id = chat_res["data"]["id"]
        conversation_id = chat_res["data"]["conversation_id"]

        # 第二步：轮询检查对话状态 (Retrieve Chat)
        retrieve_url = f"https://api.coze.cn/v3/chat/retrieve?chat_id={chat_id}&conversation_id={conversation_id}"
        while True:
            ret_res = requests.get(retrieve_url, headers=headers, proxies=NO_PROXY).json()
            status = ret_res["data"]["status"]
            
            if status == "completed":
                break
            elif status in ["failed", "canceled", "requires_action"]:
                return f"对话被中断，状态代码: {status}"
            
            time.sleep(1) # 每秒轮询一次，直到完成

        # 第三步：获取最新生成的回复 (List Messages)
        msg_url = f"https://api.coze.cn/v3/chat/message/list?chat_id={chat_id}&conversation_id={conversation_id}"
        msg_res = requests.get(msg_url, headers=headers, proxies=NO_PROXY).json()
        
        # 遍历消息，寻找属于 bot (assistant) 且类型为 answer 的回复
        messages = msg_res.get("data", [])
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("type") == "answer":
                return msg.get("content", "")
        
        return "未从服务器获取到有效回复内容。"
        
    except Exception as e:
        return f"系统调用异常: {str(e)}"


def call_coze_bot_v3_stream(bot_id, user_id, history):
    if not COZE_API_TOKEN or not bot_id:
        yield "⚠️ 系统提示：环境变量中缺失 API Token 或 Bot ID，请检查 .env 文件。"
        return

    headers = {
        "Authorization": f"Bearer {COZE_API_TOKEN}",
        "Content-Type": "application/json"
    }
    chat_url = "https://api.coze.cn/v3/chat"
    
    # 🌟 兼容经典 Gradio 格式：[[user_msg, bot_msg], ...]
    messages_payload = []
    for user_msg, bot_msg in history[:-1]:
        if user_msg and str(user_msg).strip():
            messages_payload.append({
                "role": "user",
                "content": str(user_msg).strip(),
                "content_type": "text"
            })
        if bot_msg and str(bot_msg).strip():
            messages_payload.append({
                "role": "assistant",
                "content": str(bot_msg).strip(),
                "content_type": "text"
            })

    payload = {
        "bot_id": bot_id,
        "user_id": str(user_id),
        "stream": True,
        "auto_save_conversation": False,
        "additional_messages": messages_payload
    }

    try:
        response = requests.post(
            chat_url, headers=headers, json=payload,
            stream=True, timeout=120, proxies=NO_PROXY
        )
        if response.status_code != 200:
            yield f"接口请求失败: HTTP {response.status_code}"
            return

        response.encoding = 'utf-8'

        current_event = None
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue

            if line.startswith("event:"):
                current_event = line[6:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    return

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if current_event == "conversation.message.delta":
                    if data.get("type") == "answer":
                        content = data.get("content", "")
                        if content:
                            yield content
                elif current_event == "conversation.chat.failed":
                    yield f"\n\n对话失败: {data.get('msg', '未知错误')}"
                    return
                elif current_event == "conversation.chat.completed":
                    return

    except requests.Timeout:
        yield "\n\n请求超时，请稍后重试。"
    except Exception as e:
        yield f"\n\n系统调用异常: {str(e)}"

# ==========================================
# 新增：图片转 Base64 的辅助函数
# ==========================================
# ==========================================
# 新增：将本地图片上传到扣子服务器的函数
# ==========================================
def upload_image_to_coze(image_path):
    """调用 Coze 文件上传 API，获取合法的 file_id"""
    if not image_path:
        return None, "未提供图片路径。"
    
    url = "https://api.coze.cn/v1/files/upload"
    headers = {
        "Authorization": f"Bearer {COZE_API_TOKEN}"
    }
    
    try:
        with open(image_path, "rb") as f:
            files = {"file": f}
            res = requests.post(url, headers=headers, files=files, proxies=NO_PROXY)
            print(f"[DEBUG] 图片上传响应: HTTP {res.status_code}, body={res.text[:500]}")
            res_data = res.json()
            
        if res_data.get("code") == 0:
            return res_data["data"]["id"], None
        else:
            error_msg = res_data.get("msg", "未知错误")
            print(f"图片上传失败，原因: {res_data}")
            return None, f"扣子图片上传失败：{error_msg}"
            
    except FileNotFoundError:
        return None, f"图片文件不存在：{image_path}"
    except Exception as e:
        print(f"图片上传异常: {str(e)}")
        return None, f"图片上传异常：{str(e)}"


def download_image_to_local(image_url):
    """将远程图片下载到本地临时文件，解决 Gradio SSRF 白名单限制。"""
    try:
        response = requests.get(image_url, timeout=30, stream=True, proxies=NO_PROXY)
        if response.status_code == 200:
            import tempfile
            suffix = os.path.splitext(image_url.split("?")[0])[1] or ".png"
            fd, local_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            with open(local_path, "wb") as f:
                for chunk in response.iter_content(8192):
                    f.write(chunk)
            return local_path
        return None
    except Exception as e:
        print(f"图片下载失败: {e}")
        return None


# ==========================================
# 修改：工作流调用函数 (增加 ref_image 参数)
# ==========================================
# ==========================================
# 修改：工作流调用函数
# ==========================================
def run_coze_workflow(script, image_param):
    if not COZE_WORKFLOW_ID:
        return None, "未配置 COZE_WORKFLOW_ID。", None
        
    headers = {
        "Authorization": f"Bearer {COZE_API_TOKEN}",
        "Content-Type": "application/json"
    }

    parameters = {
        "book_content": str(script or "")
    }

    if image_param:
        parameters["ref_image"] = json.dumps(
            {"file_id": str(image_param)},
            ensure_ascii=False
        )

    payload = {
        "workflow_id": COZE_WORKFLOW_ID,
        "parameters": parameters,
        "is_async": True
    }

    try:
        # 第一步：发起异步工作流执行
        async_url = "https://api.coze.cn/v1/workflow/run"
        async_res = requests.post(async_url, headers=headers, json=payload, timeout=30, proxies=NO_PROXY)
        async_data = async_res.json()
        print(f"[DEBUG] 工作流启动响应: {json.dumps(async_data, ensure_ascii=False)}")
        if async_data.get("code") != 0:
            print(f"异步工作流启动失败: {async_data}")
            return None, f"扣子工作流启动失败：{async_data.get('msg', '未知错误')}", None

        execute_id = async_data.get("data", {}).get("execute_id")
        if not execute_id:
            execute_id = async_data.get("execute_id")
        if not execute_id:
            data = async_data.get("data", {})
            if isinstance(data, dict):
                for key in data:
                    if "id" in key.lower() or "run" in key.lower():
                        execute_id = data[key]
                        break
            if not execute_id and isinstance(data, str):
                execute_id = data
        if not execute_id:
            data = async_data.get("data", {})
            if isinstance(data, dict) and data.get("output"):
                print("工作流同步返回结果，无需轮询。")
                output = data.get("output", "{}")
                if isinstance(output, str):
                    try:
                        data_dict = json.loads(output)
                    except json.JSONDecodeError:
                        data_dict = {"output": output}
                else:
                    data_dict = output or {}
                image_url = find_image_url(data_dict)
                if image_url:
                    local_path = download_image_to_local(image_url)
                    if local_path:
                        return local_path, None, data_dict
                    return None, f"图片下载失败，原始 URL：{image_url}", None
                return None, f"工作流已执行，但返回结果中没有图片 URL：{data_dict}", None
            return None, f"扣子工作流启动失败：未获取到 execute_id。响应内容: {json.dumps(async_data, ensure_ascii=False)}", None

        print(f"异步工作流已启动，execute_id: {execute_id}，开始轮询等待结果...")

        # 第二步：轮询查询异步工作流执行结果，最多等待 30 分钟
        # 【修复1】修正 Coze 获取工作流历史结果的正确 API 路径
        retrieve_url = f"https://api.coze.cn/v1/workflows/{COZE_WORKFLOW_ID}/run_histories/{execute_id}"
        max_wait_seconds = 1800  # 30 分钟
        poll_interval = 5  # 每 5 秒轮询一次
        elapsed = 0

        while elapsed < max_wait_seconds:
            time.sleep(poll_interval)
            elapsed += poll_interval

            # 【修复2】参数已经拼接在 URL 中，去掉 requests.get 中的 params 字典
            ret_res = requests.get(
                retrieve_url,
                headers=headers,
                timeout=30,
                proxies=NO_PROXY
            )
            ret_data = ret_res.json()

            if elapsed == poll_interval:
                print(f"[DEBUG] 轮询响应: {json.dumps(ret_data, ensure_ascii=False)}")

            if ret_data.get("code") != 0:
                print(f"查询工作流状态失败: {ret_data}")
                continue

            # 【修复3】部分版本 API 返回的 data 可能被包裹在列表里，增加兼容处理
            data = ret_data.get("data", {})
            if isinstance(data, list):
                data = data[0] if len(data) > 0 else {}

            # 【修复4】增加 .lower() 防止 Coze 返回 "Success" 导致的大写不匹配陷入死循环
            execute_status = str(
                data.get("execute_status") or
                data.get("status") or
                data.get("run_status") or
                data.get("state") or
                ""
            ).lower()
            
            print(f"工作流状态: {execute_status} (已等待 {elapsed}s)")

            if execute_status in ("success", "completed"):
                output = data.get("output", "{}")
                if isinstance(output, str):
                    try:
                        data_dict = json.loads(output)
                    except json.JSONDecodeError:
                        data_dict = {"output": output}
                else:
                    data_dict = output or {}

                image_url = find_image_url(data_dict)
                if image_url:
                    local_path = download_image_to_local(image_url)
                    if local_path:
                        return local_path, None, data_dict
                    return None, f"图片下载失败，原始 URL：{image_url}", None
                return None, f"工作流已执行，但返回结果中没有图片 URL：{data_dict}", None

            elif execute_status in ("failed", "fail"):
                # 获取具体的报错原因
                error_msg = data.get("error_message", data.get("output", "未知错误"))
                return None, f"扣子工作流执行失败：{error_msg}", None

            elif execute_status in ("running", "queued", "pending", ""):
                continue

        # 超时
        message = "扣子工作流执行超过 30 分钟仍未返回。请检查生图节点耗时，或适当增加 max_wait_seconds。"
        print(f"工作流调用超时: {message}")
        return None, message, None

    except requests.Timeout:
        message = "扣子工作流网络请求超时。"
        print(f"工作流调用超时: {message}")
        return None, message, None
    except (requests.RequestException, ValueError) as e:
        print(f"工作流调用异常: {str(e)}")
        return None, f"工作流调用异常：{str(e)}", None


def find_image_url(value):
    """从工作流返回值中递归提取图片 URL。"""
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return value
        import re
        urls = re.findall(r'https?://[^\s`\'")\\]+', value)
        if urls:
            return urls[0]
        return None
    if isinstance(value, dict):
        for key in ("image_url", "imageUrl", "url", "uri", "output", "data"):
            image_url = find_image_url(value.get(key))
            if image_url:
                return image_url
        for item in value.values():
            image_url = find_image_url(item)
            if image_url:
                return image_url
    if isinstance(value, list):
        for item in value:
            image_url = find_image_url(item)
            if image_url:
                return image_url
    return None


def parse_comic_panels(raw_data):
    """从工作流返回的原始数据中精准解析出所有漫画分镜（多图+文本）"""
    import re
    import json
    
    raw_text = ""
    
    # 1. 安全地提取纯文本 Markdown，剥离多余的 JSON 外壳
    if isinstance(raw_data, dict):
        for key in ("final_comic", "output", "data", "comic", "result"):
            val = raw_data.get(key)
            if isinstance(val, str):
                try:
                    inner_dict = json.loads(val)
                    if isinstance(inner_dict, dict) and "final_comic" in inner_dict:
                        raw_text = inner_dict["final_comic"]
                        break
                    elif isinstance(inner_dict, dict):
                        raw_text = list(inner_dict.values())[0]
                        break
                except json.JSONDecodeError:
                    if "http" in val:
                        raw_text = val
                        break
        # fallback
        if not raw_text:
            raw_text = json.dumps(raw_data, ensure_ascii=False)
    else:
        raw_text = str(raw_data)

    if not raw_text:
        return []

    # 2. 将字面上的 "\\n" 还原为真正的换行符
    raw_text = raw_text.replace('\\n', '\n')

    # 3. 强力切割：匹配由三个以上减号组成的分割线（忽略前后的空白与换行）
    blocks = re.split(r'\s*-{3,}\s*', raw_text)
    
    panels = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
            
        # 提取当前分段内的所有 URL
        urls = re.findall(r'https?://[^\s`\'")\\]+', block)
        image_url = urls[0] if urls else None
        
        # 4. 深度清理文本内容
        # 清除 Markdown 的图片语法：![xxx](url)
        text = re.sub(r'!\[.*?\]\(https?://[^\s`\'")\\]+\)', '', block)
        # 清除残留的独立 URL
        text = re.sub(r'https?://[^\s`\'")\\]+', '', text)
        
        # === 强力清除 JSON 外壳与乱码 ===
        # 清除包含 "node_status", "Output", "final_comic" 等字典键值对的废弃头部
        text = re.sub(r'\{.*?"final_comic[^:]*:[^a-zA-Z0-9\u4e00-\u9fa5]*', '', text)
        # 清除所有的转义反斜杠 (如 \\, \\\\)
        text = text.replace('\\', '')
        
        # === 新增：清除 Markdown 遗留的加粗星号 ===
        text = text.replace('**', '')
        
        # 清除开头和结尾残留的孤立标点（引号、大括号等）
        text = re.sub(r'^["{}\s]+', '', text)
        text = re.sub(r'["}\s]+$', '', text)
        
        text = text.strip()
        
        if image_url:
            panels.append({"image_url": image_url, "text": text})
            
    return panels


def render_comic_html(panels):
    """将分镜列表渲染为目标样式的列表排版，图片在上，文字在下"""
    import re
    
    if not panels:
        return "<div style='text-align:center;color:#999;padding:40px;'>等待生成漫画...</div>"
    
    html_parts = [
        "<div style='max-height:85vh; overflow-y:auto; padding:10px;'>"
    ]
    
    for i, panel in enumerate(panels):
        img_url = panel.get("image_url", "")
        text = panel.get("text", "")
        
        # 将 Markdown 加粗格式 **角色** 转换为 HTML 加粗 <strong>
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
        
        local_path = download_image_to_local(img_url) if img_url else None
        img_src = f"file={local_path}" if local_path else img_url
        
        # HTML/CSS 结构：模仿图二极简风格
        html_parts.append(
            f"<div style='margin-bottom: 20px;'>"
            f"<img src='{img_src}' "
            f"style='width:100%; border-radius:12px; display:block; margin:0 auto;' "
            f"onerror=\"this.onerror=null;this.src='{img_url}';\" />"
            f"<div style='margin-top: 15px; font-size: 16px; line-height: 1.6; color: #333; text-align: left; padding: 0 5px;'>"
            f"{text}"
            f"</div>"
            f"</div>"
        )
        
        # 添加列表图片之间的浅色分割线（最后一张图下方不需要）
        if i < len(panels) - 1:
            html_parts.append("<hr style='border:none; border-top:1px solid #E5E7EB; margin:25px 0;'/>")
            
    html_parts.append("</div>")
    return "".join(html_parts)


# ==========================================
# 3. 前端交互控制逻辑
# ==========================================
def user_send(user_message, input_mode, audio_input, video_input, history, session_id):
    """处理文字、语音和视频输入，并以流式打字机效果逐字输出机器人回复。"""
    message = ""
    if input_mode == "文字":
        message = (user_message or "").strip()
    elif input_mode == "语音":
        if audio_input:
            message = f"（用户发送了一条语音消息：{os.path.basename(audio_input)}）"
    elif input_mode == "视频通话":
        if video_input:
            message = f"（用户发起了一段视频通话：{os.path.basename(video_input)}）"

    if not message:
        yield "", None, None, history
        return

    # 🌟 经典格式：追加一个 [用户输入, 空的机器人回复] 的列表
    history.append([message, ""])
    yield "", None, None, history

    for chunk in call_coze_bot_v3_stream(CHAT_BOT_ID, session_id, history):
        # 🌟 经典格式：更新最后一条记录的索引 [1]（即机器人回复的部分）
        history[-1][1] += chunk
        yield "", None, None, history

def toggle_input_mode(input_mode):
    """根据输入方式显示对应的输入控件。"""
    return (
        gr.update(visible=input_mode == "文字"),
        gr.update(visible=input_mode == "语音"),
        gr.update(visible=input_mode == "视频通话")
    )

def start_new_scenario():
    """清空所有状态，开启新场景 ID"""
    return [], "", "<div style='text-align:center;color:#999;padding:40px;'>等待生成漫画...</div>", str(uuid.uuid4())


def show_clear_confirmation():
    """显示清空操作的二次确认区。"""
    return gr.update(visible=True)


def hide_clear_confirmation():
    """关闭清空操作的二次确认区。"""
    return gr.update(visible=False)

# ==========================================
# 修改：沟通结束与提炼函数 (增加 uploaded_image 参数)
# ==========================================
# ==========================================
# 修改：沟通结束与提炼函数
# ==========================================
def finish_and_extract(history, session_id, uploaded_image):
    if not history:
        return "聊天记录为空，没有任何可以总结的内容哦！", ""
    
    chat_log = ""
    # 🌟 经典格式提取对话
    for user_msg, bot_msg in history:
        if user_msg and str(user_msg).strip():
            chat_log += f"学生：{user_msg}\n"
        if bot_msg and str(bot_msg).strip():
            chat_log += f"AI：{bot_msg}\n"
    
    extracted_script = call_coze_bot_v3(SCRIPT_BOT_ID, session_id, chat_log)

    if extracted_script.startswith(("接口请求失败:", "系统调用异常:", "⚠️")):
        return extracted_script, ""
    
    if not uploaded_image:
        return extracted_script, ""

    coze_image_param, upload_error = upload_image_to_coze(uploaded_image)
    if not coze_image_param:
        print(f"finish_and_extract 图片上传失败: {upload_error}")
        return extracted_script, ""

    _, _, raw_data = run_coze_workflow(extracted_script, coze_image_param)
    
    if raw_data:
        panels = parse_comic_panels(raw_data)
        comic_html = render_comic_html(panels)
        return extracted_script, comic_html
    return extracted_script, ""

def generate_comic_with_reference(script, reference_image, session_id):
    """用提炼好的剧本 + 参考图生成漫画"""
    if not script or script.strip() == "":
        return "", "❌ 错误：请先完成第二步，生成剧本后再生成漫画！"
    if not reference_image:
        return "", "❌ 错误：请先上传参考图片，再生成漫画！"
    
    # 将本地图片上传给扣子，换取官方认可的 file_id
    coze_image_param, upload_error = upload_image_to_coze(reference_image)
    if not coze_image_param:
        return "", f"❌ 错误：参考图片上传失败：{upload_error}"
    
    # 调用工作流，传入参考图片
    _, workflow_error, raw_data = run_coze_workflow(script, coze_image_param)
    
    if raw_data:
        panels = parse_comic_panels(raw_data)
        comic_html = render_comic_html(panels)
        return comic_html, "✅ 成功：漫画已生成！"
    else:
        return "", f"❌ 错误：{workflow_error or '漫画生成失败，请检查工作流配置。'}"

def delete_reference_image():
    """删除已上传的参考图片"""
    return None

# ==========================================
# 4. Gradio 界面设计与 CSS 糖果风定制
# ==========================================
custom_css = """
/* 整体背景设为明亮的天空白 */
body, .gradio-container {
    background: linear-gradient(135deg, #FFF8E7 0%, #FFECD2 30%, #FFE5F1 60%, #E8F4FF 100%) !important;
    min-height: 100vh;
}
/* 主内容区域亮白背景 */
.main, .contain {
    background-color: rgba(255, 255, 255, 0.85) !important;
    border-radius: 24px !important;
    box-shadow: 0 8px 32px rgba(255, 140, 100, 0.15) !important;
}
/* 对话框的用户气泡变成明亮的珊瑚橙 */
.message.user {
    background: linear-gradient(135deg, #FF6B6B, #FF8E53) !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 20px 20px 4px 20px !important;
    box-shadow: 0 4px 15px rgba(255, 107, 107, 0.3) !important;
    font-weight: 500 !important;
}
/* 对话框的AI气泡变成明亮的柠檬黄 */
.message.bot {
    background: linear-gradient(135deg, #FFD93D, #FFB830) !important;
    color: #5C3D00 !important;
    border: none !important;
    border-radius: 20px 20px 20px 4px !important;
    box-shadow: 0 4px 15px rgba(255, 184, 48, 0.3) !important;
    font-weight: 500 !important;
}
/* 所有的按钮都变得圆润可爱，明亮配色 */
button, .lg.primary, .lg.secondary {
    border-radius: 25px !important;
    font-weight: 700 !important;
    transition: all 0.3s ease !important;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1) !important;
}
button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 25px rgba(0, 0, 0, 0.15) !important;
}
/* primary 按钮：明亮的紫罗兰渐变 */
.lg.primary, button.primary {
    background: linear-gradient(135deg, #A855F7, #6366F1) !important;
    border: none !important;
    color: #FFFFFF !important;
}
/* secondary 按钮：明亮的青色 */
.lg.secondary, button.secondary {
    background: linear-gradient(135deg, #06B6D4, #3B82F6) !important;
    border: none !important;
    color: #FFFFFF !important;
}
/* stop 按钮：明亮的玫红 */
button.stop, .lg.stop {
    background: linear-gradient(135deg, #EC4899, #F43F5E) !important;
    border: none !important;
    color: #FFFFFF !important;
}
/* 大标题居中，带明亮色彩 */
h2 {
    text-align: center;
    background: linear-gradient(135deg, #FF6B6B, #A855F7, #3B82F6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    font-weight: 900 !important;
    font-size: 2em !important;
}
/* Markdown 标题颜色 */
h3, h4 {
    color: #6366F1 !important;
    font-weight: 700 !important;
}
/* 输入框边框明亮 */
input, textarea, .input-container {
    border: 2px solid #FFB830 !important;
    border-radius: 16px !important;
    transition: all 0.3s ease !important;
}
input:focus, textarea:focus {
    border-color: #FF6B6B !important;
    box-shadow: 0 0 0 3px rgba(255, 107, 107, 0.2) !important;
}
/* Group 容器明亮 */
.gr-group {
    background: linear-gradient(135deg, #FFF5F5, #FFF8E7, #F5F0FF) !important;
    border-radius: 20px !important;
    border: 2px solid #FFD93D !important;
}
/* Label 标签加亮 */
label, .label-text {
    color: #6366F1 !important;
    font-weight: 700 !important;
}
/* Radio 按钮选中时明亮 */
input[type="radio"]:checked + label {
    background: linear-gradient(135deg, #FF6B6B, #FF8E53) !important;
    color: #FFFFFF !important;
}
"""

theme = gr.themes.Soft(
    primary_hue="orange",
    secondary_hue="yellow",
    neutral_hue="gray",
    font=[gr.themes.GoogleFont('Nunito'), 'ui-sans-serif', 'system-ui', 'sans-serif']
)

# 【修改点 1】：去掉了 Blocks 括号里的 theme 和 css
with gr.Blocks() as demo:
    gr.Markdown("## 🌟 奇妙沟通训练营 🌟")
    
    # 隐藏的后台会话状态
    session_id = gr.State(value=str(uuid.uuid4())) 
    
    with gr.Row():
        # ---------------- 左侧功能区 ----------------
        with gr.Column(scale=5):
            gr.Markdown("### 💬 第一步：情景演练")
            # ✅ 必须确保是这样（在括号最后加上 type 参数）：
            chatbot = gr.Chatbot(label="聊天室", height=380, avatar_images=(None, None))
            
            with gr.Row():
                input_mode = gr.Radio(
                    choices=["文字", "语音", "视频通话"],
                    value="文字",
                    label="输入方式",
                    info="选择一种方式开始对话",
                    scale=2
                )
                user_input = gr.Textbox(
                    show_label=False,
                    placeholder="在这里输入你想说的话，按回车发送...",
                    scale=4
                )
                send_btn = gr.Button("🚀 发送", variant="primary", scale=1)

            audio_input = gr.Audio(
                sources=["microphone", "upload"],
                type="filepath",
                label="语音消息（可录音或上传音频）",
                visible=False
            )
            video_input = gr.Video(
                sources=["webcam", "upload"],
                format="mp4",
                label="视频通话（可使用摄像头或上传视频）",
                visible=False
            )

            with gr.Row():
                clear_btn = gr.Button("🗑️ 清空并重新开始")

            with gr.Row(visible=False) as clear_confirmation:
                gr.Markdown("确定要清空当前聊天记录并重新开始吗？")
                confirm_clear_btn = gr.Button("确认清空", variant="stop")
                cancel_clear_btn = gr.Button("取消")
            
            gr.Markdown("### 📝 第二步：剧本总结")
            end_btn = gr.Button("✨ 沟通结束！将记录变剧本", variant="stop")
            script_output = gr.Textbox(label="提炼好的微型剧本", lines=6, interactive=True)
            
        # ---------------- 右侧展示区 ----------------
        with gr.Column(scale=5):
            gr.Markdown("### 🎨 第三步：你的专属连环画")
            
            # 参考图片上传区域
            with gr.Group():
                gr.Markdown("#### 📸 上传参考图片")
                reference_image = gr.Image(
                    label="点击上传参考图片（支持上传或拍照）",
                    sources=["upload", "webcam"],
                    type="filepath",
                    interactive=True
                )
                
                with gr.Row():
                    delete_img_btn = gr.Button("🗑️ 删除参考图片", variant="secondary", scale=1)
                    generate_comic_btn = gr.Button("🎬 生成漫画", variant="primary", scale=2)
            
            # 状态提示
            status_message = gr.Textbox(label="状态提示", interactive=False, visible=True)
            
            # 生成的漫画展示
            comic_output = gr.HTML(value="<div style='text-align:center;color:#999;padding:40px;'>等待生成漫画...</div>")

    # ---------------- 事件绑定 ----------------
    input_mode.change(
        fn=toggle_input_mode,
        inputs=[input_mode],
        outputs=[user_input, audio_input, video_input]
    )
    send_inputs = [user_input, input_mode, audio_input, video_input, chatbot, session_id]
    send_btn.click(fn=user_send, inputs=send_inputs, outputs=[user_input, audio_input, video_input, chatbot])
    user_input.submit(fn=user_send, inputs=send_inputs, outputs=[user_input, audio_input, video_input, chatbot])
    clear_btn.click(fn=show_clear_confirmation, inputs=[], outputs=[clear_confirmation])
    confirm_clear_btn.click(
        fn=start_new_scenario,
        inputs=[],
        outputs=[chatbot, script_output, comic_output, session_id]
    ).then(fn=hide_clear_confirmation, inputs=[], outputs=[clear_confirmation])
    cancel_clear_btn.click(fn=hide_clear_confirmation, inputs=[], outputs=[clear_confirmation])
    # "沟通结束"按钮：传递第三步的上传图片参数
    end_btn.click(fn=finish_and_extract, inputs=[chatbot, session_id, reference_image], outputs=[script_output, comic_output])
    
    # 生成漫画事件：使用提炼好的剧本 + 参考图片
    generate_comic_btn.click(
        fn=generate_comic_with_reference,
        inputs=[script_output, reference_image, session_id],
        outputs=[comic_output, status_message]
    )
    
    # 删除参考图片事件
    delete_img_btn.click(fn=delete_reference_image, inputs=[], outputs=[reference_image])
if __name__ == "__main__":
    configured_port = int(os.environ.get("PORT", 7860))
    server_port = configured_port
    for port in range(configured_port, configured_port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_socket:
            port_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                port_socket.bind(("127.0.0.1", port))
            except OSError:
                continue
            server_port = port
            break

    demo.launch(
        server_name="0.0.0.0", 
        server_port=server_port,
        theme=theme,
        css=custom_css
    )
