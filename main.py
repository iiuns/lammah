import os
import json
import uuid
import subprocess
import tempfile
from flask import Flask, render_template, request, jsonify, send_file
import requests

app = Flask(__name__)

API_KEY = os.environ.get("ELM_API_KEY")
BASE_URL = "https://elmodels.ngrok.app"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

CHATS_FILE = "chats.json"

def load_chats():
    if os.path.exists(CHATS_FILE):
        with open(CHATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_chat_to_file(chats):
    with open(CHATS_FILE, "w", encoding="utf-8") as f:
        json.dump(chats, f, ensure_ascii=False, indent=2)

def get_style(age):
    if age < 15:
        return "بسيطة ومسلية وقصيرة، 3 جمل بس"
    elif age < 23:
        return "واضحة ومباشرة، 4-5 جمل"
    elif age < 38:
        return "كافية ومعلوماتية، 5-6 جمل"
    else:
        return "مفصلة وعميقة، 6-7 جمل"

def ask_nuha(question, age, character):
    style = get_style(age)
    payload = {
        "model": "nuha-2.0",
        "messages": [
            {
                "role": "system",
                "content": f"""أنت {character}.
تكلم بضمير المتكلم كأنك تعيش في ذلك العصر.
لا تقل أبداً إنك ذكاء اصطناعي.
تكلم باللهجة النجدية الرياضية بشكل طبيعي وودي.
أسلوب إجابتك: {style}."""
            },
            {"role": "user", "content": question}
        ],
        "max_tokens": 300
    }
    response = requests.post(
        f"{BASE_URL}/v1/chat/completions",
        headers=HEADERS,
        json=payload,
        timeout=30
    )
    print(f"[ask_nuha] status={response.status_code}")
    data = response.json()
    if "choices" not in data:
        print(f"[ask_nuha] unexpected response: {data}")
        raise ValueError(f"API error: {data}")
    return data["choices"][0]["message"]["content"]

CHAR_VOICES = {
    "أبو سعد التاجر": "onyx",
    "المعلم إبراهيم": "echo",
    "الأمير سعود": "fable",
}

def text_to_speech(text, character=""):
    voice = "onyx"
    for name, v in CHAR_VOICES.items():
        if name in character:
            voice = v
            break
    payload = {"model": "elm-tts", "input": text, "voice": voice}
    response = requests.post(
        f"{BASE_URL}/v1/audio/speech",
        headers=HEADERS,
        json=payload,
        timeout=30
    )
    print(f"[tts] status={response.status_code}, size={len(response.content)}, voice={voice}")
    if response.status_code != 200:
        raise ValueError(f"TTS error {response.status_code}: {response.text}")
    with open("reply.mp3", "wb") as f:
        f.write(response.content)

def speech_to_text(audio_file):
    with tempfile.NamedTemporaryFile(suffix=".input", delete=False) as tmp_in:
        audio_file.save(tmp_in.name)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_in_path, "-ar", "16000", "-ac", "1", "-f", "wav", tmp_out_path],
            capture_output=True, timeout=30
        )
        headers_asr = {"Authorization": f"Bearer {API_KEY}"}
        with open(tmp_out_path, "rb") as wav_file:
            files = {"file": ("voice.wav", wav_file, "audio/wav"), "model": (None, "elm-asr")}
            response = requests.post(
                f"{BASE_URL}/v1/audio/transcriptions",
                headers=headers_asr,
                files=files,
                timeout=30
            )
        print(f"[stt] status={response.status_code}, body={response.text[:200]}")
        return response.json()["text"]
    finally:
        os.unlink(tmp_in_path)
        if os.path.exists(tmp_out_path):
            os.unlink(tmp_out_path)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/narrate', methods=['POST'])
def narrate():
    try:
        data = request.json
        text = data.get('text', '')
        voice = data.get('voice', 'shimmer')
        payload = {"model": "elm-tts", "input": text, "voice": voice}
        response = requests.post(f"{BASE_URL}/v1/audio/speech", headers=HEADERS, json=payload, timeout=30)
        if response.status_code != 200:
            return jsonify({"error": "tts failed"}), 500
        with open("reply.mp3", "wb") as f:
            f.write(response.content)
        return jsonify({"ok": True})
    except Exception as e:
        print(f"[/narrate] error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/greet', methods=['POST'])
def greet():
    try:
        data = request.json
        character = data.get('character', 'أبو سعد التاجر')
        character_name = data.get('character_name', 'أبو سعد التاجر')
        greeting = f"أهلاً! أنا {character_name}. وش تبي تعرف؟"
        text_to_speech(greeting, character)
        return jsonify({"greeting": greeting})
    except Exception as e:
        print(f"[/greet] error: {e}")
        return jsonify({"greeting": f"أهلاً! أنا {data.get('character_name','')}. وش تبي تعرف؟"}), 200

@app.route('/ask', methods=['POST'])
def ask():
    try:
        data = request.json
        age = data['age']
        question = data['question']
        character = data.get('character', 'أبو سعد التاجر، تاجر عريق من الدرعية في القرن الثامن عشر')
        reply = ask_nuha(question, age, character)
        text_to_speech(reply, character)
        return jsonify({"reply": reply})
    except Exception as e:
        print(f"[/ask] error: {e}")
        return jsonify({"error": str(e), "reply": "عذراً، صار خطأ. تأكد من المفتاح وحاول مرة ثانية."}), 500

@app.route('/ask-voice', methods=['POST'])
def ask_voice():
    try:
        age = int(request.form['age'])
        character = request.form.get('character', 'أبو سعد التاجر')
        audio = request.files['audio']
        question = speech_to_text(audio)
        reply = ask_nuha(question, age, character)
        text_to_speech(reply, character)
        return jsonify({"reply": reply, "question": question})
    except Exception as e:
        print(f"[/ask-voice] error: {e}")
        return jsonify({"error": str(e), "reply": "عذراً، صار خطأ في الصوت.", "question": ""}), 500

@app.route('/audio')
def audio():
    return send_file("reply.mp3", mimetype="audio/mpeg")

@app.route('/save-chat', methods=['POST'])
def save_chat():
    data = request.json
    chat_id = str(uuid.uuid4())[:8]
    chats = load_chats()
    chats[chat_id] = {
        "character": data['character'],
        "age": data['age'],
        "messages": data['messages'],
        "location": data.get('location', 'الدرعية')
    }
    save_chat_to_file(chats)
    return jsonify({"chat_id": chat_id})

@app.route('/chat/<chat_id>')
def view_chat(chat_id):
    chats = load_chats()
    if chat_id not in chats:
        return "المحادثة غير موجودة", 404
    return render_template('chat_view.html', chat=chats[chat_id])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
