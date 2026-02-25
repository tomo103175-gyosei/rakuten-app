import streamlit as st
import random
import requests
from datetime import date
import os
from dotenv import load_dotenv
import google.generativeai as genai
import base64

# Streamlitのページ設定
st.set_page_config(
    page_title="My Daily Curation",
    page_icon="✨",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# .envファイルの読み込み
load_dotenv()

# ... (CSS and helper functions)

# JavaScriptによるコピー機能（完全に独立したiframeとして、日本語に対応）
def render_copy_component(label, text_to_copy):
    b64_text = base64.b64encode(text_to_copy.encode('utf-8')).decode('utf-8')
    
    btn_style = """
        <style>
        .copy-btn {
            width: 100%; height: 40px; border-radius: 20px;
            border: 1px solid #AED6F1; background-color: white; color: #5499C7;
            font-weight: bold; font-family: sans-serif; cursor: pointer;
            transition: all 0.3s; display: flex; align-items: center; justify-content: center;
        }
        .copy-btn:hover { background-color: #F0F8FF; border-color: #85C1E9; }
        .success { background-color: #2ECC71 !important; color: white !important; border: none !important; }
        </style>
    """
    
    js = f"""
        {btn_style}
        <button id="copyBtn" class="copy-btn">{label}</button>
        <script>
        document.getElementById('copyBtn').addEventListener('click', function() {{
            const b64 = '{b64_text}';
            
            // 日本語Unicode対応の確実な復号方式
            const binString = atob(b64);
            const bytes = new Uint8Array(binString.length);
            for (let i = 0; i < binString.length; i++) {{
                bytes[i] = binString.charCodeAt(i);
            }}
            const text = new TextDecoder().decode(bytes);
            
            function doCopy() {{
                if (navigator.clipboard) {{
                    return navigator.clipboard.writeText(text);
                }} else {{
                    const area = document.createElement('textarea');
                    area.value = text;
                    document.body.appendChild(area);
                    area.select();
                    document.execCommand('copy');
                    document.body.removeChild(area);
                    return Promise.resolve();
                }}
            }}

            doCopy().then(() => {{
                const btn = document.getElementById('copyBtn');
                btn.innerText = '✅ コピー完了';
                btn.classList.add('success');
                setTimeout(() => {{
                    btn.innerText = '{label}';
                    btn.classList.remove('success');
                }}, 2000);
            }}).catch(err => {{
                alert('コピーに失敗しました。');
            }});
        }});
        </script>
    """
    st.components.v1.html(js, height=50)

# --- セッション状態の初期化 ---
if 'ai_intros' not in st.session_state:
    st.session_state.ai_intros = {}

# CSSにネイティブボタン用スタイルを追加
def apply_custom_css():
    st.markdown("""
        <style>
        .stApp { background-color: #F8F9FA; color: #4A4A4A; font-family: 'Inter', 'Noto Sans JP', sans-serif; }
        h1, h2, h3 { color: #5D6D7E; text-align: center; }
        .product-card {
            background-color: white;
            padding: 20px;
            border-radius: 15px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            margin-bottom: 20px;
            border: 1px solid #EAECEE;
        }
        .rakuten-btn {
            display: block;
            background-color: #AED6F1;
            color: white !important;
            text-align: center;
            padding: 10px;
            border-radius: 25px;
            font-weight: bold;
            text-decoration: none;
            margin-top: 10px;
        }
        .stTabs [data-baseweb="tab-list"] { gap: 10px; justify-content: center; }
        .stTabs [data-baseweb="tab"] {
            height: 50px; background-color: #F2F4F4; border-radius: 10px 10px 0 0;
            padding: 10px 20px; color: #7F8C8D;
        }
        .stTabs [aria-selected="true"] { background-color: #AED6F1 !important; color: white !important; }
        @media (max-width: 640px) { .product-card { padding: 15px; } }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# --- API設定 ---
RAKUTEN_APP_ID = os.getenv("RAKUTEN_APP_ID", "")
RAKUTEN_ACCESS_KEY = os.getenv("RAKUTEN_ACCESS_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- 楽天検索関数 (IP制限のないv2版を使用) ---
def search_rakuten(keyword, hits=5):
    if not RAKUTEN_APP_ID:
        st.error("環境変数 RAKUTEN_APP_ID が見つかりません。")
        return []
    
    # より柔軟な v2 エンドポイントを使用
    url = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20170426"
    params = {
        "applicationId": RAKUTEN_APP_ID,
        "keyword": keyword,
        "format": "json",
        "hits": hits,
        "imageFlag": 1,
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        if response.status_code != 200:
            error_msg = data.get('error_description', data.get('error', 'Unknown Error'))
            st.error(f"楽天APIエラー ({response.status_code}): {error_msg}")
            # デバッグ用にパラメータ状態を表示（IDは伏せる）
            if not RAKUTEN_APP_ID:
                st.warning("RAKUTEN_APP_ID が空です。Secretsの設定を確認してください。")
            return []
        
        return data.get("Items", [])
    except Exception as e:
        st.error(f"接続エラー: {e}")
        return []

# --- Gemini紹介文生成関数 ---
def generate_intro(item_name, item_caption):
    if not GEMINI_API_KEY:
        return "Gemini APIキーが設定されていません。"
    try:
        # モデル名のフォールバック
        for model_name in ['gemini-2.0-flash', 'gemini-1.5-flash-latest', 'gemini-flash-latest']:
            try:
                model = genai.GenerativeModel(model_name)
                prompt = f"""あなたは「現役の化粧品開発者」であり、かつ「カフェでの資格勉強が趣味の社会人受験生」という二つの顔を持つ女性です。以下の商品について紹介文を作成してください。\n【商品名】: {item_name}\n【商品説明】: {item_caption}\n【制約】: 薬機法配慮、親しみやすい、#PR入り、200文字程度。"""
                response = model.generate_content(prompt)
                return response.text
            except:
                continue
        return "対応しているGeminiモデルが見つかりませんでした。"
    except Exception as e:
        return f"生成エラー: {e}"

# --- メインレイアウト ---
st.title("✨ App Curation")
tab1, tab2 = st.tabs(["✨ 本日の自動ピックアップ", "🔍 自分で検索＆作成"])

with tab1:
    st.subheader("今日のあなたにおすすめ")
    keywords = ["韓国コスメ", "スキンケア", "便利 文房具", "デスク周り 癒し"]
    random.seed(date.today().toordinal())
    daily_keyword = random.choice(keywords)
    items = search_rakuten(daily_keyword, hits=3)
    
    if items:
        for item in items:
            item_data = item['Item']
            
            # HTMLを組み立て（f-stringによるブレースの誤爆を防ぐ）
            card_html = (
                '<div class="product-card">'
                '<img src="' + item_data['mediumImageUrls'][0]['imageUrl'] + '" style="width:100%; border-radius:10px; margin-bottom:12px; border: 1px solid #F2F4F4;">'
                '<div style="font-weight:bold; font-size:1.1rem; line-height:1.4; margin-bottom:8px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">' + item_data['itemName'] + '</div>'
                '<div style="color:#E74C3C; font-weight:bold; font-size:1.4rem; margin-bottom:15px;">¥' + f"{item_data['itemPrice']:,}" + '</div>'
                '<a href="' + item_data['itemUrl'] + '" target="_blank" class="rakuten-btn">楽天で詳細を見る</a>'
                '</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)
            
            # リンクコピーボタン（リンクのみ）
            render_copy_component("🔗 リンクをコピー", item_data['itemUrl'])
            
            # AI紹介文生成
            if st.button(f"✨ AI紹介文を生成", key=f"gen_tab1_{item_data['itemCode']}"):
                with st.spinner("開発者視点で執筆中..."):
                    intro = generate_intro(item_data['itemName'], item_data['itemCaption'])
                    st.session_state.ai_intros[item_data['itemCode']] = intro
            
            # 生成済みの場合に表示
            if item_data['itemCode'] in st.session_state.ai_intros:
                intro_text = st.session_state.ai_intros[item_data['itemCode']]
                st.text_area("AI紹介文", value=intro_text, height=200, key=f"area_tab1_{item_data['itemCode']}")
                full_copy = f"{intro_text}\n\n▼詳細はこちら\n{item_data['itemUrl']}"
                render_copy_component("📋 まとめてコピー", full_copy)
            
            st.markdown("---")
    else:
        st.info("商品を取得できませんでした。API設定を確認してください。")

with tab2:
    st.subheader("商品を探す")
    search_keyword = st.text_input("キーワード入力", placeholder="例: 導入美容液")
    if search_keyword:
        search_items = search_rakuten(search_keyword, hits=5)
        for item in search_items:
            item_data = item['Item']
            st.markdown(f"""
                <div class="product-card">
                    <img src="{item_data['mediumImageUrls'][0]['imageUrl']}" style="width:100%; border-radius:10px; margin-bottom:12px; border: 1px solid #F2F4F4;">
                    <div style="font-weight:bold; font-size:1.1rem; line-height:1.4; margin-bottom:8px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">
                        {item_data['itemName']}
                    </div>
                    <div style="color:#E74C3C; font-weight:bold; font-size:1.4rem; margin-bottom:15px;">
                        ¥{item_data['itemPrice']:,}
                    </div>
                    <a href="{item_data['itemUrl']}" target="_blank" class="rakuten-btn">楽天で詳細を見る</a>
                </div>
            """, unsafe_allow_html=True)
            
            # リンクコピーボタン（リンクのみ）
            render_copy_component("🔗 リンクをコピー", item_data['itemUrl'])
            
            if st.button(f"✨ AI紹介文を生成", key=f"gen_tab2_{item_data['itemCode']}"):
                with st.spinner("AIが作成中..."):
                    intro = generate_intro(item_data['itemName'], item_data['itemCaption'])
                    st.session_state.ai_intros[item_data['itemCode']] = intro

            # 生成済みの場合に表示
            if item_data['itemCode'] in st.session_state.ai_intros:
                intro_text = st.session_state.ai_intros[item_data['itemCode']]
                st.text_area("AI紹介文", value=intro_text, height=200, key=f"area_tab2_{item_data['itemCode']}")
                full_copy = f"{intro_text}\n\n▼詳細はこちら\n{item_data['itemUrl']}"
                render_copy_component("📋 まとめてコピー", full_copy)
            
            st.markdown("---")
