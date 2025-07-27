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
    # 新しいフィールドを追加
    story_data['dialogue_history'] = [] # 対話履歴
    story_data['generated_story_text'] = None # 対話から生成された物語
    story_data['picture_book_images'] = [] # 絵本の画像パスリスト
    stories.append(story_data)
    
    stories_file = os.path.join(app.config['DATA_FOLDER'], 'stories.json')
    with open(stories_file, 'w', encoding='utf-8') as f:
        json.dump(stories, f, ensure_ascii=False, indent=2)
    
    return story_data['id']

def append_dialogue_turn(story_id, user_input, ai_response, extracted_memory=None, image_path=None):
    """既存の物語に対話ターンを追加する"""
    stories = load_user_stories()
    for story in stories:
        if story['id'] == story_id:
            story['dialogue_history'].append({
                'user_input': user_input,
                'ai_response': ai_response,
                'extracted_memory': extracted_memory,
                'image_path': image_path,
                'timestamp': datetime.now().isoformat()
            })
            # current_ai_response を更新
            story['story'] = ai_response 
            break
    
    stories_file = os.path.join(app.config['DATA_FOLDER'], 'stories.json')
    with open(stories_file, 'w', encoding='utf-8') as f:
        json.dump(stories, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return render_template('index.html', static_url=app.static_url_path)

@app.route('/storybook_sample.html')
def storybook_sample():
    return render_template('storybook_sample.html')

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

@app.route('/api/start_dialogue', methods=['POST'])
def start_dialogue():
    data = request.json
    memory_text = data.get('memory_text')
    image_data = data.get('image_data')  # Base64エンコードされた画像データ
    audio_data = data.get('audio_data')  # Base64エンコードされた音声データ
    category = data.get('category', 'general')

    if not memory_text and not audio_data:
        return jsonify({'error': 'memory_text or audio_data is required'}), 400

    # APIキーが設定されていない場合のダミーレスポンス
    if not api_key:
        dummy_response = f"""【デモ用対話】

{memory_text or '音声から抽出された記憶'}

この記憶をもとに、AIが対話を開始します。実際にご利用いただくには、Gemini APIキーの設定が必要です。

AIは、あなたの思い出を深掘りし、新たな気づきを促すような質問を投げかけます。

※ これはデモ用のサンプル対話です。実際のAPIキーを設定すると、AIとの本格的な対話をお楽しみいただけます。"""
        
        # ダミーデータを保存
        story_data = {
            'memory_text': memory_text,
            'story': dummy_response, # storyはcurrent_ai_responseとして使用
            'category': category,
            'has_image': bool(image_data),
            'has_audio': bool(audio_data),
            'extracted_memory': '音声から抽出された記憶（デモ）' if audio_data else None,
            'image_path': None # ダミーなので画像パスはなし
        }
        story_id = save_user_story(story_data)
        append_dialogue_turn(story_id, memory_text or '音声入力', dummy_response, '音声から抽出された記憶（デモ）' if audio_data else None, None)
        
        return jsonify({
            'story': dummy_response,
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
                combined_memory = f"テキスト入力: {memory_text}

音声から抽出された記憶: {extracted_memory}"
            else:
                combined_memory = extracted_memory
        else:
            combined_memory = memory_text

        # カテゴリに応じたプロンプトの調整
        category_context = ""
        if category in REMINISCENCE_PROMPTS:
            category_context = f"これは「{REMINISCENCE_PROMPTS[category]['name']}」に関する記憶です。"

        # プロンプトの作成
        prompt = f"""{category_context}以下の記憶に基づいて、AIが対話を開始します。ユーザーの思い出を深掘りし、新たな気づきを促すような質問を投げかけてください。ユーザーが話しやすいように、共感的な言葉遣いを心がけてください。

記憶: {combined_memory}

AIからの最初の質問:"""

        # 画像がある場合は画像も含めて処理
        image_path_for_db = None
        if image_data:
            # Base64データをデコード
            image_bytes = base64.b64decode(image_data.split(',')[1])
            image = Image.open(io.BytesIO(image_bytes))
            
            # 画像を含むプロンプト
            prompt = f"""{category_context}添付された画像と以下の記憶に基づいて、AIが対話を開始します。ユーザーの思い出を深掘りし、新たな気づきを促すような質問を投げかけてください。画像の内容も対話に織り込んでください。ユーザーが話しやすいように、共感的な言葉遣いを心がけてください。

記憶: {combined_memory}

AIからの最初の質問:"""
            
            response = model.generate_content([prompt, image])

            # 画像を保存
            image_filename = f"story_{uuid.uuid4().hex}.png"
            image_save_dir = os.path.join('src', 'static', 'images')
            if not os.path.exists(image_save_dir):
                os.makedirs(image_save_dir)
            image_full_path = os.path.join(image_save_dir, image_filename)
            image_bytes = base64.b64decode(image_data.split(',')[1])
            with open(image_full_path, 'wb') as f:
                f.write(image_bytes)
            image_path_for_db = image_filename # DBにはファイル名だけ保存
        else:
            response = model.generate_content(prompt)
        
        dialogue_response = response.text
        
        # 物語データを保存
        story_data = {
            'memory_text': memory_text,
            'story': dialogue_response, # ここを対話の応答に
            'category': category,
            'has_image': bool(image_data),
            'has_audio': bool(audio_data),
            'extracted_memory': extracted_memory,
            'image_path': image_path_for_db
        }
        story_id = save_user_story(story_data)
        append_dialogue_turn(story_id, memory_text or '音声入力', dialogue_response, extracted_memory, image_path_for_db)
        
        return jsonify({
            'story': dialogue_response,
            'story_id': story_id,
            'extracted_memory': extracted_memory
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/continue_dialogue', methods=['POST'])
def continue_dialogue():
    """対話の続きを生成する"""
    data = request.json
    story_id = data.get('story_id')
    continuation_type = data.get('type', 'continue')  # 'continue', 'alternative', 'perspective'
    
    if not story_id:
        return jsonify({'error': 'story_id is required'}), 400
    
    # APIキーが設定されていない場合のダミーレスポンス
    if not api_key:
        dummy_continuation = f"""【デモ用続き】

AIが対話の続きを生成します。実際にご利用いただくには、Gemini APIキーの設定が必要です。

※ これはデモ用のサンプルです。実際のAPIキーを設定すると、AIとの本格的な対話をお楽しみいただけます。"""
        
        # ダミーデータを保存
        append_dialogue_turn(story_id, memory_text or '音声入力', dummy_continuation, '音声から抽出された記憶（デモ）' if audio_data else None, None)
        
        return jsonify({'continuation': dummy_continuation})
    
    try:
        # 元の物語（対話履歴）を取得
        stories = load_user_stories()
        original_story = None
        for story in stories:
            if story['id'] == story_id:
                original_story = story
                break
        
        if not original_story:
            return jsonify({'error': 'Story not found'}), 404
        
        model = genai.GenerativeModel('gemini-2.5-flash')

        # これまでの対話履歴を結合
        full_dialogue_history = ""
        for turn in original_story['dialogue_history']:
            full_dialogue_history += f"ユーザー: {turn['user_input']}\nAI: {turn['ai_response']}\n"
        full_dialogue_history += f"ユーザー: {memory_text or '音声入力'}\n"
        
        # 続きのタイプに応じたプロンプト
        if continuation_type == 'continue':
            prompt = f"""以下の対話の続きを生成してください。ユーザーの記憶をさらに深掘りし、新たな質問や共感的なコメントを返してください。

これまでの対話:
{full_dialogue_history}

AIからの次の質問:"""
        elif continuation_type == 'alternative':
            prompt = f"""以下の対話について、もし別の視点や質問があったらどうなっていたかを想像して、別バージョンの対話を生成してください。

これまでの対話:
{full_dialogue_history}

AIからの別の質問:"""
        elif continuation_type == 'perspective':
            prompt = f"""以下の対話を、別の角度から見て、ユーザーに新しい気づきを与えるような質問を生成してください。

これまでの対話:
{full_dialogue_history}

AIからの新しい視点での質問:"""

        # 音声データがある場合は音声から記憶を抽出
        extracted_memory = None
        if audio_data:
            audio_bytes = base64.b64decode(audio_data.split(',')[1])
            temp_audio_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            temp_audio_file.write(audio_bytes)
            temp_audio_file.close()
            audio_prompt = "この音声から話されている記憶や思い出の内容を詳しく文字起こしして、要約してください。"
            audio_response = model.generate_content([audio_prompt, genai.upload_file(temp_audio_file.name)])
            extracted_memory = audio_response.text
            os.unlink(temp_audio_file.name)
            prompt += f"\n\n(音声から抽出された追加情報: {extracted_memory})"

        # 画像がある場合は画像も含めて処理
        image_path_for_db = None
        if image_data:
            image_bytes = base64.b64decode(image_data.split(',')[1])
            image = Image.open(io.BytesIO(image_bytes))
            prompt_with_image = [prompt, image]
            response = model.generate_content(prompt_with_image)

            # 画像を保存
            image_filename = f"story_{uuid.uuid4().hex}.png"
            image_save_dir = os.path.join('src', 'static', 'images')
            if not os.path.exists(image_save_dir):
                os.makedirs(image_save_dir)
            image_full_path = os.path.join(image_save_dir, image_filename)
            with open(image_full_path, 'wb') as f:
                f.write(image_bytes)
            image_path_for_db = image_filename # DBにはファイル名だけ保存
        else:
            response = model.generate_content(prompt)
        
        continuation = response.text
        
        # 対話ターンを保存
        append_dialogue_turn(story_id, memory_text or '音声入力', continuation, extracted_memory, image_path_for_db)
        
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

@app.route('/api/generate_story_from_dialogue', methods=['POST'])
def generate_story_from_dialogue():
    """対話履歴から物語を生成する"""
    data = request.json
    story_id = data.get('story_id')

    if not story_id:
        return jsonify({'error': 'story_id is required'}), 400

    if not api_key:
        dummy_story = "【デモ用物語】\n\n対話履歴から物語が生成されます。APIキーを設定してください。"
        stories = load_user_stories()
        for story in stories:
            if story['id'] == story_id:
                story['generated_story_text'] = dummy_story
                break
        stories_file = os.path.join(app.config['DATA_FOLDER'], 'stories.json')
        with open(stories_file, 'w', encoding='utf-8') as f:
            json.dump(stories, f, ensure_ascii=False, indent=2)
        return jsonify({'story': dummy_story})

    try:
        stories = load_user_stories()
        original_story = None
        for story in stories:
            if story['id'] == story_id:
                original_story = story
                break

        if not original_story:
            return jsonify({'error': 'Story not found'}), 404

        model = genai.GenerativeModel('gemini-2.5-flash')

        # 対話履歴を結合してプロンプトを作成
        dialogue_text = ""
        for turn in original_story['dialogue_history']:
            dialogue_text += f"ユーザー: {turn['user_input']}\nAI: {turn['ai_response']}\n"

        prompt = f"""以下の対話履歴に基づいて、心温まる物語を生成してください。
        高齢者が読みやすいように、平易な言葉で、具体的な描写を交えてください。
        対話の中で語られた感情や風景、五感で感じたことなども含めて、豊かな物語にしてください。

        対話履歴:
        {dialogue_text}

        物語:"""

        response = model.generate_content(prompt)
        generated_story = response.text

        # 生成された物語を保存
        for story in stories:
            if story['id'] == story_id:
                story['generated_story_text'] = generated_story
                break
        stories_file = os.path.join(app.config['DATA_FOLDER'], 'stories.json')
        with open(stories_file, 'w', encoding='utf-8') as f:
            json.dump(stories, f, ensure_ascii=False, indent=2)

        return jsonify({'story': generated_story})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate_picture_book', methods=['POST'])
def generate_picture_book():
    """物語の各ページの説明に基づいて画像を生成する"""
    data = request.json
    story_id = data.get('story_id')

    if not story_id:
        return jsonify({'error': 'story_id is required'}), 400

    if not api_key:
        dummy_images = ["sample_image1.png", "sample_image2.png"] # ダミー画像パス
        stories = load_user_stories()
        for story in stories:
            if story['id'] == story_id:
                story['picture_book_images'] = dummy_images
                break
        stories_file = os.path.join(app.config['DATA_FOLDER'], 'stories.json')
        with open(stories_file, 'w', encoding='utf-8') as f:
            json.dump(stories, f, ensure_ascii=False, indent=2)
        return jsonify({'images': dummy_images})

    try:
        stories = load_user_stories()
        original_story = None
        for story in stories:
            if story['id'] == story_id:
                original_story = story
                break

        if not original_story or not original_story.get('generated_story_text'):
            return jsonify({'error': 'Generated story not found for this ID'}), 404

        model = genai.GenerativeModel('gemini-2.5-flash') # 画像生成モデル

        # 物語をページごとに分割し、各ページの画像を生成するプロンプトを作成
        story_text = original_story['generated_story_text']
        # ここでは簡略化のため、物語全体から数枚の画像を生成するプロンプトを作成します。
        # より詳細な絵本にする場合は、物語を章やページに分割するロジックが必要です。
        prompt = f"""以下の物語の各ページに合うような、温かく優しいタッチのイラストを生成してください。
        物語の雰囲気に合った、高齢者にも親しみやすい絵柄でお願いします。
        物語:
        {story_text}

        生成する画像の具体的な説明（例: 1. 幼い頃の主人公が野原で遊んでいる様子, 2. 家族で食卓を囲む温かい風景）:
        """
        
        # ここで画像生成APIを呼び出す（Gemini APIの画像生成機能を使用）
        # 例: response = model.generate_content(prompt, generation_config={'response_mime_type': 'image/jpeg'})
        # 実際には、Gemini APIの画像生成機能の具体的な使い方に合わせて調整が必要です。
        # 現在のGemini APIでは直接画像を生成する機能は提供されていないため、
        # ここではダミーの画像パスを返すか、別の画像生成API（例: DALL-E, Midjourney）を統合する必要があります。
        
        # 現状ではダミーの画像パスを返します
        generated_image_paths = []
        # ダミーの画像生成ロジック
        for i in range(3): # 3枚のダミー画像を生成する例
            dummy_image_filename = f"picture_book_{story_id}_{i}.png"
            dummy_image_path = os.path.join('src', 'static', 'images', dummy_image_filename)
            # 実際にはここで画像を生成し、保存する
            # 例: Image.new('RGB', (60, 30), color = 'red').save(dummy_image_path)
            generated_image_paths.append(dummy_image_filename) # ファイル名のみ保存

        # 生成された画像パスを保存
        for story in stories:
            if story['id'] == story_id:
                story['picture_book_images'] = generated_image_paths
                break
        stories_file = os.path.join(app.config['DATA_FOLDER'], 'stories.json')
        with open(stories_file, 'w', encoding='utf-8') as f:
            json.dump(stories, f, ensure_ascii=False, indent=2)

        return jsonify({'images': generated_image_paths})
