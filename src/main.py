from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import google.generativeai as genai
from google.cloud import texttospeech
import os
import base64
from PIL import Image
import io
import tempfile
import uuid
import json
from datetime import datetime

app = Flask(__name__)
CORS(app)  # CORS設定を追加

# アップロードフォルダの設定
UPLOAD_FOLDER = 'uploads'
AUDIO_FOLDER = 'audio_files'
DATA_FOLDER = 'user_data'
for folder in [UPLOAD_FOLDER, AUDIO_FOLDER, DATA_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['AUDIO_FOLDER'] = AUDIO_FOLDER
app.config['DATA_FOLDER'] = DATA_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB制限

# Gemini APIキーの設定
api_key = os.environ.get("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

# 回想プロンプトのカテゴリ
REMINISCENCE_PROMPTS = {
    "childhood": {
        "name": "幼少期の思い出",
        "prompts": [
            "小学校の運動会で一番印象に残っていることは何ですか？",
            "子供の頃、一番好きだった遊びは何でしたか？",
            "家族と一緒に行った旅行で覚えていることはありますか？",
            "初めて自転車に乗れた時のことを覚えていますか？",
            "子供の頃の夏休みの思い出を教えてください。"
        ]
    },
    "school": {
        "name": "学生時代の出来事",
        "prompts": [
            "学生時代の一番の友達との思い出は何ですか？",
            "部活動や課外活動で印象に残っていることはありますか？",
            "学校の先生で特に印象に残っている方はいますか？",
            "文化祭や体育祭での思い出を教えてください。",
            "初恋の思い出はありますか？"
        ]
    },
    "work": {
        "name": "仕事での経験",
        "prompts": [
            "初めての給料で何を買いましたか？",
            "仕事で一番やりがいを感じた瞬間はいつですか？",
            "職場の同僚との思い出で印象に残っていることはありますか？",
            "仕事で大きな成功を収めた時のことを教えてください。",
            "転職や昇進の時の気持ちを覚えていますか？"
        ]
    },
    "family": {
        "name": "家族との時間",
        "prompts": [
            "結婚式の日のことを覚えていますか？",
            "お子さんが生まれた時の気持ちを教えてください。",
            "家族で過ごした特別な記念日はありますか？",
            "お孫さんとの思い出で印象に残っていることはありますか？",
            "家族みんなで笑った楽しい出来事はありますか？"
        ]
    },
    "hobbies": {
        "name": "趣味や特技",
        "prompts": [
            "一番熱中した趣味は何でしたか？",
            "料理で得意だった（得意な）メニューはありますか？",
            "スポーツや運動で楽しかった思い出はありますか？",
            "手作りで何かを作った思い出はありますか？",
            "音楽や芸術で心に残っている体験はありますか？"
        ]
    }
}

def load_user_stories():
    """ユーザーの物語データを読み込む"""
    stories_file = os.path.join(app.config['DATA_FOLDER'], 'stories.json')
    if os.path.exists(stories_file):
        with open(stories_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_user_story(story_data):
    """ユーザーの物語データを保存する"""
    stories = load_user_stories()
    story_data['id'] = str(uuid.uuid4())
    story_data['created_at'] = datetime.now().isoformat()
    stories.append(story_data)
    
    stories_file = os.path.join(app.config['DATA_FOLDER'], 'stories.json')
    with open(stories_file, 'w', encoding='utf-8') as f:
        json.dump(stories, f, ensure_ascii=False, indent=2)
    
    return story_data['id']

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/get_prompts/<category>')
def get_prompts(category):
    """指定されたカテゴリのプロンプトを取得"""
    if category in REMINISCENCE_PROMPTS:
        return jsonify(REMINISCENCE_PROMPTS[category])
    return jsonify({'error': 'Category not found'}), 404

@app.route('/api/get_all_categories')
def get_all_categories():
    """すべてのカテゴリを取得"""
    categories = {}
    for key, value in REMINISCENCE_PROMPTS.items():
        categories[key] = value['name']
    return jsonify(categories)

@app.route('/api/generate_story', methods=['POST'])
def generate_story():
    data = request.json
    memory_text = data.get('memory_text')
    image_data = data.get('image_data')  # Base64エンコードされた画像データ
    audio_data = data.get('audio_data')  # Base64エンコードされた音声データ
    category = data.get('category', 'general')

    if not memory_text and not audio_data:
        return jsonify({'error': 'memory_text or audio_data is required'}), 400

    # APIキーが設定されていない場合のダミーレスポンス
    if not api_key:
        dummy_story = f"""【デモ用物語】

{memory_text or '音声から抽出された記憶'}

この記憶をもとに、心温まる物語が生成されます。実際にご利用いただくには、Gemini APIキーの設定が必要です。

物語では、あなたの大切な思い出が、より豊かで感動的なストーリーとして蘇ります。登場人物の表情や、その時の風景、感じた気持ちなどが、詳細に描写されます。

※ これはデモ用のサンプル物語です。実際のAPIキーを設定すると、AIが生成した本格的な物語をお楽しみいただけます。"""
        
        # ダミーデータを保存
        story_data = {
            'memory_text': memory_text,
            'story': dummy_story,
            'category': category,
            'has_image': bool(image_data),
            'has_audio': bool(audio_data)
        }
        story_id = save_user_story(story_data)
        
        return jsonify({
            'story': dummy_story,
            'story_id': story_id,
            'extracted_memory': '音声から抽出された記憶（デモ）' if audio_data else None
        })

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # 音声データがある場合は音声から記憶を抽出
        extracted_memory = None
        if audio_data:
            # Base64データをデコードして一時ファイルに保存
            audio_bytes = base64.b64decode(audio_data.split(',')[1])
            temp_audio_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            temp_audio_file.write(audio_bytes)
            temp_audio_file.close()
            
            # 音声ファイルをアップロード
            audio_file = genai.upload_file(temp_audio_file.name)
            
            # 音声から記憶を抽出
            audio_prompt = "この音声から話されている記憶や思い出の内容を詳しく文字起こしして、要約してください。"
            audio_response = model.generate_content([audio_prompt, audio_file])
            extracted_memory = audio_response.text
            
            # 一時ファイルを削除
            os.unlink(temp_audio_file.name)
            
            # 抽出された記憶をテキストと組み合わせ
            if memory_text:
                combined_memory = f"テキスト入力: {memory_text}\n\n音声から抽出された記憶: {extracted_memory}"
            else:
                combined_memory = extracted_memory
        else:
            combined_memory = memory_text

        # カテゴリに応じたプロンプトの調整
        category_context = ""
        if category in REMINISCENCE_PROMPTS:
            category_context = f"これは「{REMINISCENCE_PROMPTS[category]['name']}」に関する記憶です。"

        # プロンプトの作成
        prompt = f"""{category_context}以下の記憶に基づいて、心温まる物語を生成してください。高齢者が読みやすいように、平易な言葉で、具体的な描写を交えてください。登場人物の感情や、その時の風景、五感で感じたことなども含めて、豊かな物語にしてください。

記憶: {combined_memory}

物語:"""

        # 画像がある場合は画像も含めて処理
        if image_data:
            # Base64データをデコード
            image_bytes = base64.b64decode(image_data.split(',')[1])
            image = Image.open(io.BytesIO(image_bytes))
            
            # 画像を含むプロンプト
            prompt = f"""{category_context}添付された画像と以下の記憶に基づいて、心温まる物語を生成してください。高齢者が読みやすいように、平易な言葉で、具体的な描写を交えてください。画像の内容も物語に織り込んでください。登場人物の感情や、その時の風景、五感で感じたことなども含めて、豊かな物語にしてください。

記憶: {combined_memory}

物語:"""
            
            response = model.generate_content([prompt, image])
        else:
            response = model.generate_content(prompt)
        
        story = response.text
        
        # 物語データを保存
        story_data = {
            'memory_text': memory_text,
            'story': story,
            'category': category,
            'has_image': bool(image_data),
            'has_audio': bool(audio_data),
            'extracted_memory': extracted_memory
        }
        story_id = save_user_story(story_data)
        
        return jsonify({
            'story': story,
            'story_id': story_id,
            'extracted_memory': extracted_memory
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/continue_story', methods=['POST'])
def continue_story():
    """物語の続きを生成する"""
    data = request.json
    story_id = data.get('story_id')
    continuation_type = data.get('type', 'continue')  # 'continue', 'alternative', 'perspective'
    
    if not story_id:
        return jsonify({'error': 'story_id is required'}), 400
    
    # APIキーが設定されていない場合のダミーレスポンス
    if not api_key:
        dummy_continuation = f"""【デモ用続き】

物語の続きや別の視点からの物語が生成されます。実際にご利用いただくには、Gemini APIキーの設定が必要です。

※ これはデモ用のサンプルです。実際のAPIキーを設定すると、AIが生成した本格的な続きをお楽しみいただけます。"""
        
        return jsonify({'continuation': dummy_continuation})
    
    try:
        # 元の物語を取得
        stories = load_user_stories()
        original_story = None
        for story in stories:
            if story['id'] == story_id:
                original_story = story
                break
        
        if not original_story:
            return jsonify({'error': 'Story not found'}), 404
        
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # 続きのタイプに応じたプロンプト
        if continuation_type == 'continue':
            prompt = f"""以下の物語の続きを生成してください。自然な流れで物語を発展させ、感動的な結末に向かうようにしてください。

元の物語:
{original_story['story']}

続き:"""
        elif continuation_type == 'alternative':
            prompt = f"""以下の物語について、もし別の選択や展開があったらどうなっていたかを想像して、別バージョンの物語を生成してください。

元の物語:
{original_story['story']}

別の展開:"""
        elif continuation_type == 'perspective':
            prompt = f"""以下の物語を、別の登場人物の視点から語り直してください。新しい発見や感情を含めて物語を再構築してください。

元の物語:
{original_story['story']}

別の視点から:"""
        
        response = model.generate_content(prompt)
        continuation = response.text
        
        return jsonify({'continuation': continuation})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_stories')
def get_stories():
    """保存された物語一覧を取得"""
    stories = load_user_stories()
    # 最新順にソート
    stories.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(stories)

@app.route('/api/text_to_speech', methods=['POST'])
def text_to_speech():
    data = request.json
    text = data.get('text')
    
    if not text:
        return jsonify({'error': 'Text is required'}), 400
    
    # APIキーが設定されていない場合のダミーレスポンス
    if not api_key:
        return jsonify({'error': 'APIキーが設定されていないため、音声生成機能は利用できません。'}), 400
    
    try:
        # Google Cloud Text-to-Speech クライアントを初期化
        client = texttospeech.TextToSpeechClient()

        synthesis_input = texttospeech.SynthesisInput(text=text)

        # 音声設定（日本語、女性、標準的な声）
        voice = texttospeech.VoiceSelectionParams(
            language_code="ja-JP", ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )

        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        
        # 一意のファイル名を生成
        audio_filename = f"story_{uuid.uuid4().hex}.mp3"
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
        
        # 音声ファイルを保存
        with open(audio_path, 'wb') as f:
            f.write(response.audio_content)
        
        return jsonify({'audio_url': f'/api/audio/{audio_filename}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/audio/<filename>')
def serve_audio(filename):
    try:
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], filename)
        return send_file(audio_path, mimetype='audio/mpeg')
    except Exception as e:
        return jsonify({'error': str(e)}), 404

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
