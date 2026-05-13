from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
import os
import requests
from datetime import datetime, timedelta
import base64
import json
import re
from sqlalchemy import text
import sys

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# ========== 模拟数据 ==========
EARTHQUAKES = [
    {
        'id': 1,
        'name': '四川甘孜地震',
        'lat': 30.0, 'lng': 101.0,
        'magnitude': 6.8,
        'date': '2025-10-16',
        'region': '四川省甘孜藏族自治州',
        'severity': '严重',
        'affected_area_km2': 25.6,
        'rescue_points': 8,
        'shelters': 12,
        'medical_facilities': 5,
        'total_buildings': 8500,
        'damaged_buildings': 3200,
        'collapsed_buildings': 850,
        'safe_buildings': 5450,
        'before_image_url': '',  # 可以填入真实图片URL
        'after_image_url': ''    # 可以填入真实图片URL
    },
    {
        'id': 2,
        'name': '广东梅州地震',
        'lat': 24.3, 'lng': 116.1,
        'magnitude': 5.2,
        'date': '2025-10-10',
        'region': '广东省梅州市',
        'severity': '中度',
        'affected_area_km2': 18.3,
        'rescue_points': 5,
        'shelters': 8,
        'medical_facilities': 3,
        'total_buildings': 6200,
        'damaged_buildings': 1800,
        'collapsed_buildings': 310,
        'safe_buildings': 4090,
        'before_image_url': '',
        'after_image_url': ''
    },
    {
        'id': 3,
        'name': '海南三亚地震',
        'lat': 18.2, 'lng': 109.5,
        'magnitude': 4.7,
        'date': '2025-10-05',
        'region': '海南省三亚市',
        'severity': '轻度',
        'affected_area_km2': 12.1,
        'rescue_points': 3,
        'shelters': 5,
        'medical_facilities': 2,
        'total_buildings': 4800,
        'damaged_buildings': 950,
        'collapsed_buildings': 120,
        'safe_buildings': 3730,
        'before_image_url': '',
        'after_image_url': ''
    }
]

# ========== 图层配置 ==========
LAYERS = {
    'affected_area': {'label': '受灾区域', 'color': '#FF0000', 'type': 'polygon'},
    'rescue_point': {'label': '救援点位', 'color': '#00FF00', 'type': 'marker'},
    'shelter': {'label': '避难场所', 'color': '#0000FF', 'type': 'marker'},
    'medical': {'label': '医疗设施', 'color': '#FFA500', 'type': 'marker'}
}


# ========== 纯规则灾害分类器（无任何第三方依赖） ==========
def disaster_classifier(text):
    """
    基于关键词的灾害类型识别
    返回格式与 Hugging Face pipeline 一致：[{"label": "...", "score": 0.x}]
    """
    text = str(text).lower()
    keywords = {
        "地震": ["地震", "震级", "余震", "震中", "地动", "地壳", "断层"],
        "洪水": ["洪水", "暴雨", "内涝", "淹", "涝", "积水", "水位", "洪峰"],
        "滑坡": ["滑坡", "泥石流", "塌方", "山体", "崩塌", "落石"],
        "建筑安全": ["裂缝", "倒塌", "危房", "墙体", "地基", "倾斜", "楼体"],
        "火灾": ["火灾", "着火", "燃烧", "火势", "消防", "烟雾"]
    }
    for label, words in keywords.items():
        if any(word in text for word in words):
            return [{"label": label, "score": 0.95}]
    return [{"label": "其他", "score": 0.7}]


# ========== 地震数据获取函数 ==========
def fetch_real_earthquakes(days=30):
    """从中国地震台网获取最近 N 天的地震数据"""
    try:
        end_time = datetime.now().strftime("%Y-%m-%d")
        start_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        url = "http://www.ceic.ac.cn/ajax/search"
        params = {
            "start": start_time,
            "end": end_time,
            "jingdu1": "", "jingdu2": "",
            "weidu1": "", "weidu2": "",
            "height1": "", "height2": "",
            "level1": "", "level2": ""
        }
        headers = {
            'User-Agent': 'Mozilla/5.0'
        }

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()  # 检查 HTTP 错误
        data = response.json()

        earthquakes = []
        for item in data.get('shuju', []):
            try:
                lat = float(item[2])
                lng = float(item[1])
                magnitude = float(item[3]) if item[3] else 0.0
                date_str = item[0].replace('年', '-').replace('月', '-').replace('日', '')

                if abs(lat) > 90 or abs(lng) > 180 or magnitude < 0:
                    continue

                # 根据震级估算房屋数据
                base_buildings = max(1000, int(magnitude * 1000))
                damage_rate = min(0.6, magnitude / 12.0)  # 损坏率
                collapse_rate = min(0.15, magnitude / 20.0)  # 倒塌率
                
                earthquakes.append({
                    'id': f"real_{len(earthquakes)}",
                    'name': f"{item[0]} {magnitude}级地震",
                    'lat': lat,
                    'lng': lng,
                    'magnitude': magnitude,
                    'date': date_str,
                    'region': item[6] if item[6] else '未知地区',
                    'severity': '严重' if magnitude >= 6.0 else ('中度' if magnitude >= 5.0 else '轻度'),
                    'affected_area_km2': max(5.0, magnitude * 2.0),
                    'rescue_points': max(1, int(magnitude)),
                    'shelters': max(2, int(magnitude * 1.5)),
                    'medical_facilities': max(1, int(magnitude * 0.8)),
                    'total_buildings': base_buildings,
                    'damaged_buildings': int(base_buildings * damage_rate),
                    'collapsed_buildings': int(base_buildings * collapse_rate),
                    'safe_buildings': base_buildings - int(base_buildings * damage_rate),
                    'before_image_url': '',  # 真实数据中可填入图片URL
                    'after_image_url': ''
                })
            except (ValueError, IndexError, TypeError):
                continue
        return earthquakes
    except Exception as e:
        print(f"⚠️ 获取真实地震数据失败: {e}")
        return []


# ========== Flask 应用初始化 ==========
app = Flask(__name__)
app.config.from_object(Config)

# 数据库初始化
db = SQLAlchemy(app)

# 用户模型
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    ai_quota = db.Column(db.Integer, nullable=True)
    ai_used = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'

# 用户登录管理
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    try:
        # SQLAlchemy 2.0 兼容性：使用 session.get() 替代 query.get()
        return db.session.get(User, int(user_id))
    except Exception as e:
        print(f"加载用户错误: {e}")
        return None

# 房屋评估模型
class BuildingAssessment(db.Model):
    __tablename__ = 'building_assessments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(300), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    status_level = db.Column(db.Integer, nullable=False)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)
    cracks = db.Column(db.String(20), nullable=False)
    tilt = db.Column(db.String(20), nullable=False)
    foundation = db.Column(db.String(20), nullable=False)
    structure = db.Column(db.String(20), nullable=False)
    assessor = db.Column(db.String(50), nullable=True)
    assessment_date = db.Column(db.String(20), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    ai_model = db.Column(db.String(200), nullable=True)
    ai_analysis = db.Column(db.Text, nullable=True)
    assessment_source = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Task(db.Model):
    __tablename__ = 'tasks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='open')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SystemConfig(db.Model):
    __tablename__ = 'system_config'
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AiUsage(db.Model):
    __tablename__ = 'ai_usage'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    conversation_id = db.Column(db.Integer, nullable=True, index=True)
    model = db.Column(db.String(200), nullable=True)
    prompt_tokens = db.Column(db.Integer, nullable=True)
    completion_tokens = db.Column(db.Integer, nullable=True)
    total_tokens = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Conversation(db.Model):
    __tablename__ = 'conversations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    page_path = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    has_image = db.Column(db.Boolean, default=False, nullable=False)
    image_mime = db.Column(db.String(80), nullable=True)
    image_b64 = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def _level_from_label(label):
    mapping = {'无': 0, '良好': 0, '完好': 0, '轻微': 1, '中等': 2, '严重': 3}
    return mapping.get(label, 0)

def evaluate_building_safety(details, age):
    score = 0
    score += _level_from_label(details.get('cracks', '无'))
    score += _level_from_label(details.get('tilt', '无'))
    score += _level_from_label(details.get('foundation', '良好'))
    score += _level_from_label(details.get('structure', '完好'))
    if age and age >= 30:
        score += 1
    if score <= 1:
        status_level = 1
        status = '轻微'
    elif score <= 3:
        status_level = 2
        status = '中等'
    elif score <= 5:
        status_level = 3
        status = '严重'
    else:
        status_level = 4
        status = '危险'
    return status, status_level


def _is_sqlite():
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    return uri.startswith("sqlite:")


def ensure_schema():
    if not _is_sqlite():
        return
    with app.app_context():
        db.create_all()
        cols = {row[1] for row in db.session.execute(text("PRAGMA table_info(users)")).fetchall()}
        if "is_admin" not in cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"))
        if "ai_quota" not in cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN ai_quota INTEGER"))
        if "ai_used" not in cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN ai_used INTEGER NOT NULL DEFAULT 0"))
        cols = {row[1] for row in db.session.execute(text("PRAGMA table_info(building_assessments)")).fetchall()}
        if "user_id" not in cols:
            db.session.execute(text("ALTER TABLE building_assessments ADD COLUMN user_id INTEGER"))
        if "ai_model" not in cols:
            db.session.execute(text("ALTER TABLE building_assessments ADD COLUMN ai_model TEXT"))
        if "ai_analysis" not in cols:
            db.session.execute(text("ALTER TABLE building_assessments ADD COLUMN ai_analysis TEXT"))
        if "assessment_source" not in cols:
            db.session.execute(text("ALTER TABLE building_assessments ADD COLUMN assessment_source TEXT"))
        db.session.execute(
            text(
                "UPDATE building_assessments "
                "SET user_id = (SELECT id FROM users WHERE users.username = building_assessments.assessor) "
                "WHERE user_id IS NULL AND assessor IS NOT NULL"
            )
        )
        db.session.execute(text("UPDATE building_assessments SET assessment_source = 'user' WHERE assessment_source IS NULL"))
        db.session.commit()


def get_system_config(key, default=None):
    try:
        row = db.session.get(SystemConfig, key)
        if row and row.value is not None and str(row.value).strip() != "":
            return row.value
    except Exception:
        return default
    return default


def set_system_config(key, value):
    row = db.session.get(SystemConfig, key)
    if not row:
        row = SystemConfig(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value
    db.session.commit()


def _get_ark_auth():
    base_url = str(get_system_config("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")).rstrip("/")
    api_key = os.getenv("ARK_API_KEY")
    if not api_key:
        raise RuntimeError("缺少环境变量 ARK_API_KEY")
    return base_url, api_key


def _get_windows_system_proxy():
    if sys.platform != "win32":
        return None
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            proxy_enable, _ = winreg.QueryValueEx(k, "ProxyEnable")
            if not proxy_enable:
                return None
            proxy_server, _ = winreg.QueryValueEx(k, "ProxyServer")
            if not proxy_server:
                return None
            s = str(proxy_server).strip()
            if not s:
                return None
            return s
    except Exception:
        return None


def _normalize_proxy(proxy_value: str):
    v = (proxy_value or "").strip()
    if not v:
        return None
    if ";" in v and "=" in v:
        parts = {}
        for seg in v.split(";"):
            seg = seg.strip()
            if not seg or "=" not in seg:
                continue
            k, val = seg.split("=", 1)
            parts[k.strip().lower()] = val.strip()
        http_p = parts.get("http") or parts.get("https")
        https_p = parts.get("https") or parts.get("http")
        if not http_p and not https_p:
            return None
        if http_p and "://" not in http_p:
            http_p = "http://" + http_p
        if https_p and "://" not in https_p:
            https_p = "http://" + https_p
        return {"http": http_p, "https": https_p}

    if "://" not in v:
        v = "http://" + v
    return {"http": v, "https": v}


def ark_chat_completion(messages, model, temperature=0.2):
    base_url, api_key = _get_ark_auth()
    proxy = str(os.getenv("ARK_HTTPS_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or "").strip()
    if not proxy:
        proxy = _get_windows_system_proxy() or ""
    proxies = _normalize_proxy(proxy)
    verify_env = str(os.getenv("ARK_TLS_VERIFY") or "").strip().lower()
    ca_bundle = str(os.getenv("ARK_CA_BUNDLE") or "").strip()
    verify = True
    if ca_bundle:
        verify = ca_bundle
    elif verify_env in {"0", "false", "no"}:
        verify = False
    if OpenAI is not None and str(os.getenv("ARK_FORCE_REQUESTS") or "").strip() not in {"1", "true", "TRUE"}:
        try:
            client = OpenAI(base_url=base_url, api_key=api_key)
            resp = client.chat.completions.create(model=model, messages=messages, temperature=temperature)
            assistant_text = resp.choices[0].message.content or ""
            usage = getattr(resp, "usage", None)
            return (
                assistant_text,
                getattr(usage, "prompt_tokens", None) if usage else None,
                getattr(usage, "completion_tokens", None) if usage else None,
                getattr(usage, "total_tokens", None) if usage else None,
            )
        except Exception:
            pass

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60, proxies=proxies, verify=verify)
    except requests.exceptions.SSLError as e:
        raise RuntimeError(
            "网络/TLS 握手失败（常见于公司网络需走代理或证书拦截）。"
            "请设置环境变量 ARK_HTTPS_PROXY（或系统 HTTPS_PROXY），或配置 ARK_CA_BUNDLE。"
            f" 原始错误: {e}"
        )
    if r.status_code >= 400:
        try:
            data = r.json()
            msg = data.get("error", {}).get("message") or data.get("message") or r.text
        except Exception:
            msg = r.text
        raise RuntimeError(f"ARK 调用失败 ({r.status_code}): {msg}")
    data = r.json()
    assistant_text = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    return assistant_text, usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens")


def _consume_ai_quota_and_log(model_name, prompt_tokens=None, completion_tokens=None, total_tokens=None, conversation_id=None):
    u = db.session.get(User, current_user.id)
    if not u:
        return
    u.ai_used = int(u.ai_used or 0) + 1
    db.session.commit()
    db.session.add(
        AiUsage(
            user_id=current_user.id,
            conversation_id=conversation_id,
            model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )
    db.session.commit()


def _ai_quota_exhausted():
    u = db.session.get(User, current_user.id)
    return bool(u and u.ai_quota is not None and int(u.ai_used or 0) >= int(u.ai_quota))


def _try_parse_json(text_value):
    raw = (text_value or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def doubao_disaster_analyze(text_value):
    if _ai_quota_exhausted():
        raise RuntimeError("AI 调用额度已用尽")
    model_name = get_system_config("ARK_MODEL", "doubao-seed-1-6-vision-250815")
    system_prompt = (
        "你是灾情文本分析器。请根据输入的灾情描述，判断灾害类型与风险等级，并给出可执行建议。"
        "只输出 JSON，不要输出任何多余文字。"
    )
    user_prompt = (
        "请分析以下文本，只输出 JSON：\n"
        f"{text_value}\n\n"
        "JSON schema:\n"
        "{\n"
        '  "predicted_type": "地震|洪水|滑坡|台风|建筑倒塌|火灾|其他",\n'
        '  "confidence": 0.0,\n'
        '  "risk_level": "低|中|高|极高",\n'
        '  "key_reasons": ["..."],\n'
        '  "immediate_actions": ["..."]\n'
        "}\n"
    )
    assistant_text, prompt_tokens, completion_tokens, total_tokens = ark_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=model_name,
        temperature=0.2,
    )
    data = _try_parse_json(assistant_text)
    if not isinstance(data, dict):
        raise RuntimeError("AI 返回格式异常（未返回 JSON）")
    predicted_type = str(data.get("predicted_type") or "其他").strip() or "其他"
    try:
        confidence = float(data.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    risk_level = str(data.get("risk_level") or "").strip()
    key_reasons = data.get("key_reasons") if isinstance(data.get("key_reasons"), list) else []
    immediate_actions = data.get("immediate_actions") if isinstance(data.get("immediate_actions"), list) else []
    md = "### AI 智能分析\n\n"
    md += f"- 灾害类型：{predicted_type}\n"
    if risk_level:
        md += f"- 风险等级：{risk_level}\n"
    md += f"- 置信度：{confidence:.2f}\n"
    if key_reasons:
        md += "\n**关键依据**\n" + "\n".join([f"- {str(x)}" for x in key_reasons[:6]])
    if immediate_actions:
        md += "\n\n**立即建议**\n" + "\n".join([f"- {str(x)}" for x in immediate_actions[:8]])
    _consume_ai_quota_and_log(model_name, prompt_tokens, completion_tokens, total_tokens, conversation_id=None)
    return predicted_type, confidence, md


def doubao_building_assess(building_payload):
    if _ai_quota_exhausted():
        raise RuntimeError("AI 调用额度已用尽")
    model_name = get_system_config("ARK_MODEL", "doubao-seed-1-6-vision-250815")
    system_prompt = (
        "你是建筑安全评估助手。根据输入的建筑信息与现场特征，输出结构化建议。"
        "只输出 JSON，不要输出任何多余文字。"
    )
    user_prompt = (
        "请基于以下信息输出 JSON：\n"
        f"{json.dumps(building_payload, ensure_ascii=False)}\n\n"
        "JSON schema:\n"
        "{\n"
        '  "summary": "一句话结论",\n'
        '  "risk_points": ["..."],\n'
        '  "recommended_actions": ["..."],\n'
        '  "need_professional_inspection": true\n'
        "}\n"
    )
    assistant_text, prompt_tokens, completion_tokens, total_tokens = ark_chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=model_name,
        temperature=0.2,
    )
    data = _try_parse_json(assistant_text)
    if not isinstance(data, dict):
        raise RuntimeError("AI 返回格式异常（未返回 JSON）")
    summary = str(data.get("summary") or "").strip()
    risk_points = data.get("risk_points") if isinstance(data.get("risk_points"), list) else []
    recommended_actions = data.get("recommended_actions") if isinstance(data.get("recommended_actions"), list) else []
    need_prof = bool(data.get("need_professional_inspection"))
    md = "### AI 智能分析\n\n"
    if summary:
        md += f"**结论**：{summary}\n\n"
    md += "**风险点**\n"
    md += "\n".join([f"- {str(x)}" for x in (risk_points[:8] or ["未提供"])]) + "\n\n"
    md += "**建议措施**\n"
    md += "\n".join([f"- {str(x)}" for x in (recommended_actions[:10] or ["未提供"])]) + "\n\n"
    md += f"**是否建议专业复核**：{'是' if need_prof else '否'}"
    _consume_ai_quota_and_log(model_name, prompt_tokens, completion_tokens, total_tokens, conversation_id=None)
    return model_name, md


def is_admin():
    return bool(getattr(current_user, "is_authenticated", False) and getattr(current_user, "is_admin", False))


def admin_required():
    if not is_admin():
        abort(403)

# 初始化数据库
def init_db():
    try:
        with app.app_context():
            ensure_schema()
            # 创建默认管理员账户（如果不存在）
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                admin = User(username='admin')
                admin.set_password('admin')
                admin.is_admin = True
                db.session.add(admin)
                db.session.commit()
            elif not admin.is_admin:
                admin.is_admin = True
                db.session.commit()

            if not SystemConfig.query.filter_by(key="ARK_MODEL").first():
                set_system_config("ARK_MODEL", "doubao-seed-1-6-vision-250815")
            if not SystemConfig.query.filter_by(key="ARK_BASE_URL").first():
                set_system_config("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    except Exception as e:
        import traceback
        print(f"数据库初始化错误: {e}")
        print(traceback.format_exc())

# 初始化数据库
init_db()


# ========== 路由定义 ==========
@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            if not username or not password:
                flash('请输入用户名和密码', 'error')
                return render_template('login.html')
            
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                login_user(user)
                flash(f'欢迎回来，{username}！', 'success')
                if bool(getattr(user, "is_admin", False)):
                    return redirect(url_for('admin_index'))
                return redirect(url_for('dashboard'))
            else:
                flash('用户名或密码错误', 'error')
        return render_template('login.html')
    except Exception as e:
        import traceback
        print(f"登录页面错误: {e}")
        print(traceback.format_exc())
        flash(f'服务器错误: {str(e)}', 'error')
        return render_template('login.html'), 500


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        # 验证用户名
        if not username:
            flash('用户名不能为空', 'error')
        elif len(username) < 3:
            flash('用户名长度至少3位', 'error')
        # 检查用户名是否已存在
        elif User.query.filter_by(username=username).first():
            flash('用户名已存在', 'error')
        # 验证密码
        elif password != confirm_password:
            flash('两次输入的密码不一致', 'error')
        elif len(password) < 6:
            flash('密码长度必须大于6位', 'error')
        else:
            # 创建新用户
            try:
                new_user = User(username=username)
                new_user.set_password(password)
                db.session.add(new_user)
                db.session.commit()
                flash('注册成功，请登录', 'success')
                return redirect(url_for('login'))
            except Exception as e:
                db.session.rollback()
                flash(f'注册失败：{str(e)}', 'error')
    return render_template('register.html')


@app.route('/dashboard')
@login_required
def dashboard():
    stats = {
        'total_disasters': 12,
        'unsafe_buildings': 5,
        'active_alerts': 3
    }
    return render_template('dashboard.html', stats=stats)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/user-interaction', methods=['GET', 'POST'])
@login_required
def user_interaction():
    result = None
    if request.method == 'POST':
        user_text = request.form.get('report_text', '').strip()
        if user_text:
            try:
                predicted_type = None
                confidence = None
                ai_markdown = None
                source = None
                try:
                    predicted_type, confidence, ai_markdown = doubao_disaster_analyze(user_text)
                    source = "doubao"
                except Exception:
                    pred = disaster_classifier(user_text)
                    if isinstance(pred, list):
                        pred = pred[0]
                    predicted_type = pred.get('label')
                    confidence = float(pred.get('score') or 0.0)
                    source = "local"

                result = {
                    'text': user_text,
                    'predicted_type': predicted_type,
                    'confidence': float(confidence or 0.0),
                    'source': source,
                    'ai_markdown': ai_markdown
                }
                src_name = "Doubao" if source == "doubao" else "本地模型"
                flash(f"智能分析完成（{src_name}）：{predicted_type}（置信度 {float(confidence or 0.0):.2f}）", "info")
            except Exception as e:
                flash(f"分析失败：{str(e)}", "error")
        else:
            flash("请输入灾情描述文本！", "warning")
    return render_template('user_interaction.html', result=result)


@app.route('/disaster-analysis')
@login_required
def disaster_analysis():
    analysis_data = {
        'disaster_types': {'地震': 12, '洪水': 25, '滑坡': 8, '台风': 5, '建筑倒塌': 10},
        'trend_days': ['11-08', '11-09', '11-10', '11-11', '11-12', '11-13', '11-14'],
        'trend_counts': [3, 5, 2, 8, 6, 4, 7],
        'affected_locations': [
            {'name': '四川甘孜地震', 'lat': 30.0, 'lng': 101.0, 'type': '地震'},
            {'name': '广东暴雨洪涝', 'lat': 23.1, 'lng': 113.2, 'type': '洪水'},
            {'name': '重庆山体滑坡', 'lat': 29.5, 'lng': 106.5, 'type': '滑坡'},
            {'name': '北京老旧楼裂缝', 'lat': 39.9, 'lng': 116.4, 'type': '建筑倒塌'}
        ],
        'loss_assessment': [
            {'region': '四川省', 'loss': 12000},
            {'region': '广东省', 'loss': 8500},
            {'region': '重庆市', 'loss': 4200},
            {'region': '北京市', 'loss': 1800}
        ]
    }
    return render_template('disaster_analysis.html', data=analysis_data)


@app.route('/building-safety', methods=['GET', 'POST'])
@login_required
def building_safety():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            address = request.form.get('address', '').strip()
            btype = request.form.get('type', '').strip()
            age = int(request.form.get('age', '0') or 0)
            cracks = request.form.get('cracks', '无')
            tilt = request.form.get('tilt', '无')
            foundation = request.form.get('foundation', '良好')
            structure = request.form.get('structure', '完好')
            notes = request.form.get('notes', '').strip()
            status, status_level = evaluate_building_safety({
                'cracks': cracks,
                'tilt': tilt,
                'foundation': foundation,
                'structure': structure
            }, age)

            ai_model = None
            ai_analysis = None
            try:
                payload = {
                    "name": name,
                    "address": address,
                    "type": btype,
                    "age": age,
                    "rule_status": status,
                    "rule_status_level": status_level,
                    "details": {
                        "cracks": cracks,
                        "tilt": tilt,
                        "foundation": foundation,
                        "structure": structure,
                    },
                    "notes": notes or None,
                }
                ai_model, ai_analysis = doubao_building_assess(payload)
            except Exception:
                ai_model = None
                ai_analysis = None

            item = BuildingAssessment(
                user_id=current_user.id if current_user.is_authenticated else None,
                name=name,
                address=address,
                type=btype,
                age=age,
                status=status,
                status_level=status_level,
                cracks=cracks,
                tilt=tilt,
                foundation=foundation,
                structure=structure,
                assessor=current_user.username if current_user.is_authenticated else None,
                assessment_date=datetime.now().strftime('%Y-%m-%d'),
                notes=notes,
                ai_model=ai_model,
                ai_analysis=ai_analysis,
                assessment_source="user"
            )
            db.session.add(item)
            db.session.commit()
            flash('评估已提交并存储！', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'提交失败：{str(e)}', 'error')
        return redirect(url_for('building_safety'))

    region_filter = request.args.get('region', '')
    status_filter = request.args.get('status', '')

    query = BuildingAssessment.query
    if not is_admin():
        query = query.filter(BuildingAssessment.user_id == current_user.id)
    if region_filter:
        query = query.filter(BuildingAssessment.address.contains(region_filter))
    if status_filter:
        query = query.filter(BuildingAssessment.status == status_filter)
    rows = query.order_by(BuildingAssessment.created_at.desc()).all()

    buildings = []
    for r in rows:
        buildings.append({
            'id': r.id,
            'name': r.name,
            'address': r.address,
            'type': r.type,
            'age': r.age,
            'status': r.status,
            'status_level': r.status_level,
            'lat': r.lat,
            'lng': r.lng,
            'ai_model': r.ai_model,
            'ai_analysis': r.ai_analysis,
            'assessment_source': r.assessment_source,
            'damage_details': {
                'cracks': r.cracks,
                'tilt': r.tilt,
                'foundation': r.foundation,
                'structure': r.structure
            },
            'assessment_date': r.assessment_date,
            'assessor': r.assessor or 'AI评估',
            'notes': r.notes
        })

    stats = {
        'total': len(rows),
        'safe': len([b for b in rows if b.status_level == 1]),
        'medium': len([b for b in rows if b.status_level == 2]),
        'serious': len([b for b in rows if b.status_level == 3]),
        'danger': len([b for b in rows if b.status_level == 4])
    }

    return render_template(
        'building_safety.html',
        buildings=buildings,
        stats=stats,
        selected_region=region_filter,
        selected_status=status_filter
    )


@app.route('/map')
@login_required
def map_display():
    # 获取查询参数
    date_filter = request.args.get('date', '')
    location_filter = request.args.get('location', '').strip()
    layers = request.args.getlist('layer') or list(LAYERS.keys())
    data_source = request.args.get('source', 'real')

    # 获取数据
    if data_source == 'real':
        all_quakes = fetch_real_earthquakes(days=30)
        if not all_quakes:
            all_quakes = EARTHQUAKES
    else:
        all_quakes = EARTHQUAKES

    # 过滤数据
    filtered_quakes = all_quakes.copy()
    if date_filter:
        filtered_quakes = [q for q in filtered_quakes if q['date'] == date_filter]
    if location_filter:
        filtered_quakes = [q for q in filtered_quakes if location_filter in q['region']]

    # 计算统计信息（修复：原代码缺失此部分！）
    total_area = sum(q['affected_area_km2'] for q in filtered_quakes)
    total_rescue = sum(q['rescue_points'] for q in filtered_quakes)
    total_shelters = sum(q['shelters'] for q in filtered_quakes)
    total_medical = sum(q['medical_facilities'] for q in filtered_quakes)
    stats = {
        'total_area': round(total_area, 1),
        'total_rescue': total_rescue,
        'total_shelters': total_shelters,
        'total_medical': total_medical
    }

    return render_template(
        'map_display.html',
        earthquakes=filtered_quakes,
        layers=layers,
        stats=stats,
        selected_date=date_filter,
        selected_location=location_filter,
        data_source=data_source,
        # ✅ 关键：添加这一行！
        LAYERS=LAYERS  # 将全局变量 LAYERS 传入模板
    )

@app.context_processor
def inject_map_key():
    return dict(
        amap_key=get_system_config("AMAP_KEY", app.config['AMAP_KEY']),
        amap_security_code=get_system_config("AMAP_SECURITY_CODE", app.config['AMAP_SECURITY_CODE']),
        is_admin=is_admin()
    )


@app.route('/me')
@login_required
def me():
    my_assessments = BuildingAssessment.query.filter_by(user_id=current_user.id).order_by(BuildingAssessment.created_at.desc()).limit(50).all()
    return render_template('user_center.html', assessments=my_assessments)


@app.route('/admin')
@login_required
def admin_index():
    admin_required()
    total_users = int(User.query.count())
    total_assessments = int(BuildingAssessment.query.count())
    manual_assessments = int(BuildingAssessment.query.filter(BuildingAssessment.assessment_source == "manual").count())
    ai_calls = int(db.session.execute(text("SELECT COUNT(*) FROM ai_usage")).scalar() or 0)
    stats = {
        "total_users": total_users,
        "total_assessments": total_assessments,
        "manual_assessments": manual_assessments,
        "ai_calls": ai_calls,
    }
    return render_template("admin_dashboard.html", stats=stats)


@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    admin_required()
    if request.method == 'POST':
        user_id = int(request.form.get("user_id") or 0)
        target = db.session.get(User, user_id)
        if not target:
            flash("用户不存在", "error")
            return redirect(url_for("admin_users"))
        target.is_admin = bool(request.form.get("is_admin"))
        quota = request.form.get("ai_quota", "").strip()
        target.ai_quota = int(quota) if quota != "" else None
        if bool(request.form.get("reset_ai_used")):
            target.ai_used = 0
        new_password = (request.form.get("new_password") or "").strip()
        if new_password:
            target.set_password(new_password)
        db.session.commit()
        return redirect(url_for("admin_users"))
    rows = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", users=rows, view="users")


@app.route('/admin/admins', methods=['GET', 'POST'])
@login_required
def admin_admins():
    admin_required()
    if request.method == 'POST':
        user_id = int(request.form.get("user_id") or 0)
        target = db.session.get(User, user_id)
        if not target:
            flash("用户不存在", "error")
            return redirect(url_for("admin_admins"))
        want_admin = bool(request.form.get("is_admin"))
        if not want_admin:
            if int(target.id) == int(current_user.id):
                flash("不能取消当前登录管理员的管理员权限", "error")
                return redirect(url_for("admin_admins"))
            admin_count = int(User.query.filter_by(is_admin=True).count())
            if admin_count <= 1:
                flash("至少需要保留 1 个管理员账号", "error")
                return redirect(url_for("admin_admins"))
        target.is_admin = want_admin
        if bool(request.form.get("reset_ai_used")):
            target.ai_used = 0
        new_password = (request.form.get("new_password") or "").strip()
        if new_password:
            target.set_password(new_password)
        db.session.commit()
        return redirect(url_for("admin_admins"))
    rows = User.query.filter_by(is_admin=True).order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", users=rows, view="admins")


def _status_from_level(level_value: int):
    mapping = {1: "轻微", 2: "中等", 3: "严重", 4: "危险"}
    try:
        lv = int(level_value)
    except Exception:
        lv = 0
    return mapping.get(lv), lv


@app.route('/admin/manual-assessments', methods=['GET', 'POST'])
@login_required
def admin_manual_assessments():
    admin_required()
    if request.method == "POST":
        action = (request.form.get("action") or "create").strip().lower()
        if action == "delete":
            rid = int(request.form.get("assessment_id") or 0)
            row = db.session.get(BuildingAssessment, rid)
            if not row or row.assessment_source != "manual":
                flash("记录不存在", "error")
                return redirect(url_for("admin_manual_assessments"))
            db.session.delete(row)
            db.session.commit()
            flash("已删除人工测评记录", "success")
            return redirect(url_for("admin_manual_assessments"))

        user_id_raw = (request.form.get("user_id") or "").strip()
        user_id = int(user_id_raw) if user_id_raw.isdigit() else None
        if user_id is not None and not db.session.get(User, user_id):
            flash("目标用户不存在", "error")
            return redirect(url_for("admin_manual_assessments"))

        name = (request.form.get("name") or "").strip()
        address = (request.form.get("address") or "").strip()
        btype = (request.form.get("type") or "").strip()
        age = int(request.form.get("age") or 0)
        cracks = request.form.get("cracks", "无")
        tilt = request.form.get("tilt", "无")
        foundation = request.form.get("foundation", "良好")
        structure = request.form.get("structure", "完好")
        notes = (request.form.get("notes") or "").strip()
        analysis_text = (request.form.get("analysis") or "").strip()

        status_level_raw = (request.form.get("status_level") or "").strip()
        status = None
        status_level = None
        if status_level_raw.isdigit():
            status, status_level = _status_from_level(int(status_level_raw))
        if not status_level:
            status, status_level = evaluate_building_safety(
                {"cracks": cracks, "tilt": tilt, "foundation": foundation, "structure": structure},
                age,
            )

        item = BuildingAssessment(
            user_id=user_id,
            name=name or "未命名建筑",
            address=address or "-",
            type=btype or "其他",
            age=age,
            status=status,
            status_level=status_level,
            cracks=cracks,
            tilt=tilt,
            foundation=foundation,
            structure=structure,
            assessor=current_user.username,
            assessment_date=datetime.now().strftime('%Y-%m-%d'),
            notes=notes or None,
            ai_model="人工测评",
            ai_analysis=analysis_text or None,
            assessment_source="manual",
        )
        db.session.add(item)
        db.session.commit()
        flash("已新增人工测评记录", "success")
        return redirect(url_for("admin_manual_assessments"))

    users = User.query.order_by(User.created_at.desc()).all()
    rows = (
        BuildingAssessment.query.filter(BuildingAssessment.assessment_source == "manual")
        .order_by(BuildingAssessment.created_at.desc())
        .limit(80)
        .all()
    )
    return render_template("admin_manual_assessments.html", users=users, assessments=rows)


@app.route('/admin/config', methods=['GET', 'POST'])
@login_required
def admin_config():
    admin_required()
    if request.method == 'POST':
        set_system_config("ARK_MODEL", request.form.get("ARK_MODEL", "").strip() or "doubao-seed-1-6-vision-250815")
        set_system_config("ARK_BASE_URL", request.form.get("ARK_BASE_URL", "").strip() or "https://ark.cn-beijing.volces.com/api/v3")
        set_system_config("AMAP_KEY", request.form.get("AMAP_KEY", "").strip())
        set_system_config("AMAP_SECURITY_CODE", request.form.get("AMAP_SECURITY_CODE", "").strip())
        return redirect(url_for("admin_config"))
    cfg = {
        "ARK_MODEL": get_system_config("ARK_MODEL", "doubao-seed-1-6-vision-250815"),
        "ARK_BASE_URL": get_system_config("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "AMAP_KEY": get_system_config("AMAP_KEY", app.config.get("AMAP_KEY")),
        "AMAP_SECURITY_CODE": get_system_config("AMAP_SECURITY_CODE", app.config.get("AMAP_SECURITY_CODE")),
    }
    return render_template("admin_config.html", cfg=cfg)


@app.route('/admin/usage')
@login_required
def admin_usage():
    admin_required()
    rows = db.session.execute(
        text(
            "SELECT user_id, COUNT(*) as calls, SUM(COALESCE(total_tokens,0)) as tokens "
            "FROM ai_usage GROUP BY user_id ORDER BY tokens DESC"
        )
    ).fetchall()
    user_map = {u.id: u.username for u in User.query.all()}
    summary = [{"user_id": r[0], "username": user_map.get(r[0], str(r[0])), "calls": int(r[1] or 0), "tokens": int(r[2] or 0)} for r in rows]
    return render_template("admin_usage.html", summary=summary)


def _safe_page_context(ctx):
    if not isinstance(ctx, dict):
        return {}
    out = {}
    for k in ["title", "path", "url", "text"]:
        v = ctx.get(k)
        if v is None:
            continue
        s = str(v)
        if len(s) > 4000:
            s = s[:4000]
        out[k] = s
    return out


def _to_vision_content(text_value, image_data_url=None):
    parts = []
    if text_value and str(text_value).strip() != "":
        parts.append({"type": "text", "text": str(text_value)})
    if image_data_url:
        parts.append({"type": "image_url", "image_url": {"url": image_data_url}})
    return parts or [{"type": "text", "text": ""}]


def _offline_ai_fallback(user_text, has_image, page_context, raw_error):
    page_tip = ""
    if isinstance(page_context, dict) and (page_context.get("title") or page_context.get("path")):
        page_tip = f"- 当前页面：{page_context.get('title','')} {page_context.get('path','')}".strip()
    top = (
        "当前网络无法与火山引擎 Ark 建立稳定连接（TLS 握手被中断），所以暂时无法调用 Doubao。\n\n"
        "你可以这样一次性修复：\n"
        "1. 确认网络可访问 `https://ark.cn-beijing.volces.com`（公司网络通常需要代理/VPN）。\n"
        "2. 如果你在用代理软件（如 Clash），把 `ark.cn-beijing.volces.com` 加入“走代理/可访问”的规则（目前系统代理存在但该域名仍失败）。\n"
        "3. 如果公司做了 HTTPS 证书拦截，请配置 `ARK_CA_BUNDLE` 指向企业根证书。\n\n"
        "下面先给你一个离线应急建议（不依赖在线大模型）：\n"
    )
    tips = []
    if page_tip:
        tips.append(page_tip)
    if has_image:
        tips.append("- 你上传了图片：离线模式无法做视觉识别；网络恢复后可重新发送图片让我识别。")
    if user_text and user_text.strip():
        pred = disaster_classifier(user_text)
        label = pred[0]["label"] if isinstance(pred, list) and pred else "其他"
        tips.append(f"- 初步判断：{label}")
        if label == "地震":
            tips.append("- 建议：确认震中/震级/余震信息；排查建筑裂缝与燃气泄漏；优先疏散到空旷地带；建立人员清单与伤员转运路线。")
        elif label == "洪水":
            tips.append("- 建议：关注水位与降雨预报；封堵低洼入口；重要物资上移；规划临时安置点与救援路线。")
        elif label == "滑坡":
            tips.append("- 建议：立即划定警戒区；停止靠近坡体；关注降雨与二次滑坡风险；安排巡查与撤离路线。")
        elif label == "建筑安全":
            tips.append("- 建议：先人员撤离；记录裂缝/沉降/倾斜照片；禁止进入承重受损区域；联系专业鉴定并设置警戒线。")
        else:
            tips.append("- 建议：补充地点、时间、影响范围、人员伤亡与关键基础设施受损情况，以便进一步研判。")
    else:
        tips.append("- 你可以补充：地点、时间、影响范围、人员伤亡、道路/通信/电力情况。")

    detail = ""
    s = str(raw_error or "")
    if s:
        if len(s) > 260:
            s = s[:260] + "..."
        detail = "\n\n技术信息（用于排障）：\n" + s

    return top + "\n".join(tips) + detail


@app.route('/api/ai/chat', methods=['POST'])
@login_required
def api_ai_chat():
    content_type = (request.content_type or "").lower()
    payload = None
    image_data_url = None
    if "multipart/form-data" in content_type:
        text_value = request.form.get("text", "").strip()
        conversation_id = request.form.get("conversation_id", "").strip() or None
        page_context = _safe_page_context({"title": request.form.get("page_title"), "path": request.form.get("page_path"), "url": request.form.get("page_url"), "text": request.form.get("page_text")})
        f = request.files.get("image")
        if f and f.filename:
            raw = f.read()
            mime = f.mimetype or "image/png"
            image_data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"
        payload = {"text": text_value, "conversation_id": conversation_id, "page_context": page_context}
    else:
        payload = request.get_json(silent=True) or {}
        text_value = str(payload.get("text") or "").strip()
        conversation_id = str(payload.get("conversation_id") or "").strip() or None
        page_context = _safe_page_context(payload.get("page_context") or {})
        image_b64 = payload.get("image_base64")
        image_mime = payload.get("image_mime") or "image/png"
        if image_b64:
            image_data_url = f"data:{image_mime};base64,{str(image_b64).strip()}"

    if not text_value and not image_data_url:
        return jsonify({"error": "缺少 text 或 image"}), 400

    u = db.session.get(User, current_user.id)
    if u and u.ai_quota is not None and int(u.ai_used or 0) >= int(u.ai_quota):
        return jsonify({"error": "AI 调用额度已用尽"}), 403

    conv = None
    if conversation_id and conversation_id.isdigit():
        conv = Conversation.query.filter_by(id=int(conversation_id), user_id=current_user.id).first()
    if not conv:
        conv = Conversation(user_id=current_user.id, page_path=page_context.get("path"))
        db.session.add(conv)
        db.session.commit()
    elif page_context.get("path"):
        conv.page_path = page_context.get("path")
        db.session.commit()

    user_msg = ChatMessage(
        conversation_id=conv.id,
        role="user",
        content=text_value or "",
        has_image=bool(image_data_url),
        image_mime=(image_data_url.split(";")[0].replace("data:", "") if image_data_url else None),
        image_b64=(image_data_url.split(",")[1] if image_data_url and "," in image_data_url else None),
    )
    db.session.add(user_msg)
    db.session.commit()

    model_name = get_system_config("ARK_MODEL", "doubao-seed-1-6-vision-250815")
    page_text = page_context.get("text") or ""
    page_tip = ""
    if page_context.get("title") or page_context.get("path"):
        page_tip = f"当前页面：{page_context.get('title','')} {page_context.get('path','')}".strip()
    system_prompt = (
        "你是一个灾情管理系统的AI助手。你需要结合用户输入与当前页面上下文，给出可执行、具体的建议。"
        "当需要引用页面信息时，优先基于提供的页面文本与路径。输出使用 Markdown，代码块请使用对应语言标注。"
    )
    if page_tip or page_text:
        system_prompt += "\n" + (page_tip or "")
        if page_text:
            system_prompt += "\n页面内容摘要（可能被截断）:\n" + page_text[:3500]

    history = ChatMessage.query.filter_by(conversation_id=conv.id).order_by(ChatMessage.created_at.asc()).limit(20).all()
    messages = [{"role": "system", "content": system_prompt}]
    for m in history:
        if m.role == "user":
            img_url = None
            if m.has_image and m.image_b64:
                mime = m.image_mime or "image/png"
                img_url = f"data:{mime};base64,{m.image_b64}"
            messages.append({"role": "user", "content": _to_vision_content(m.content, img_url)})
        else:
            messages.append({"role": "assistant", "content": m.content})

    try:
        assistant_text, prompt_tokens, completion_tokens, total_tokens = ark_chat_completion(
            messages=messages,
            model=model_name,
            temperature=0.2,
        )
    except Exception as e:
        msg = str(e)
        if "ARK_API_KEY" in msg:
            return jsonify({"error": msg}), 401
        assistant_text = _offline_ai_fallback(text_value or "", bool(image_data_url), page_context, msg)
        assistant_msg = ChatMessage(conversation_id=conv.id, role="assistant", content=assistant_text or "")
        db.session.add(assistant_msg)
        db.session.commit()
        return jsonify(
            {
                "conversation_id": conv.id,
                "user_message_id": user_msg.id,
                "assistant_message_id": assistant_msg.id,
                "model": model_name,
                "assistant_markdown": assistant_text,
                "degraded": True,
                "error": msg,
            }
        )

    assistant_msg = ChatMessage(conversation_id=conv.id, role="assistant", content=assistant_text or "")
    db.session.add(assistant_msg)
    db.session.commit()

    u = db.session.get(User, current_user.id)
    if u:
        u.ai_used = int(u.ai_used or 0) + 1
        db.session.commit()

    db.session.add(
        AiUsage(
            user_id=current_user.id,
            conversation_id=conv.id,
            model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )
    db.session.commit()

    return jsonify(
        {
            "conversation_id": conv.id,
            "user_message_id": user_msg.id,
            "assistant_message_id": assistant_msg.id,
            "model": model_name,
            "assistant_markdown": assistant_text,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        }
    )


# ========== 启动配置 ==========
if __name__ == '__main__':
    port = int(os.environ.get("PORT") or 8000)
    debug = app.config['SERVER_NAME'] is None
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)
