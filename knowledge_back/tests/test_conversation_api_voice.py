"""手动机器人语音测试，不由 pytest 执行。

python tests/test_conversation_api_voice.py --serial-no alohamini
需要 requests、dashscope，以及 Linux mpg123。
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
import os

import requests
from dotenv import load_dotenv
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat

# 独立脚本不会自动读取 Flask 的环境文件；使用脚本位置而非当前目录。
BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / '.env.local', override=False)
load_dotenv(BACKEND_ROOT / '.env', override=False)
load_dotenv(BACKEND_ROOT.parent / '.env', override=False)

# ========== 通义TTS固定配置（和你给的示例一致） ==========
dashscope.base_websocket_api_url = 'wss://llm-f9r7idf9omepz6cl.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference'
TTS_MODEL = "qwen-audio-3.1-tts-plus"
TTS_VOICE = "longanhuan_v3.1"
# =======================================================


def speak(text):
    """DashScope通义TTS，生成mp3播放，替换原来piper版本"""
    if not text.strip():
        return
    with tempfile.TemporaryDirectory(prefix='kbs-voice-') as folder:
        audio_path = Path(folder) / 'answer.mp3'
        api_key = os.environ.get('DASHSCOPE_VOICE_API_KEY')
        print(api_key)
        if not api_key:
            raise ValueError('请设置 DASHSCOPE_VOICE_API_KEY 或 DASHSCOPE_API_KEY 环境变量')
        dashscope.api_key = api_key
        synthesizer = SpeechSynthesizer(model=TTS_MODEL, voice=TTS_VOICE,
                                       format=AudioFormat.MP3_22050HZ_MONO_256KBPS)
        audio_bytes = synthesizer.call(text)
        if not isinstance(audio_bytes, bytes) or not audio_bytes:
            raise ValueError('语音服务未返回有效音频')
        with open(audio_path, 'wb') as f:
            f.write(audio_bytes)
        subprocess.run(['mpg123', '-q', str(audio_path)], check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description='输入问题，调用机器人接口并播报回答（DashScope TTS）')
    parser.add_argument('--base-url', default='http://127.0.0.1:5000')
    parser.add_argument('--serial-no', default='alohamini', help='数据库中机器人的序列号，不是名称')
    parser.add_argument('--timeout', type=float, default=210)
    parser.add_argument('--no-audio', action='store_true', help='仅文字测试，不调用语音')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout 必须大于 0')
    if not args.no_audio:
        missing = [name for name in ('mpg123',) if not shutil.which(name)]
        if missing:
            parser.error('缺少命令：' + ', '.join(missing) + '；可使用 --no-audio 仅测试文字')
    conversation_id, turn_no = None, None
    pending = None
    print(f'机器人：{args.serial_no}，服务：{args.base_url}')
    print('输入问题后回车；/new 新会话，/retry 重试未确认请求，/quit 退出。')
    print('使用机器人绑定的知识库、城市、时区及正式发布提示词。')
    with requests.Session() as session:
        while True:
            try:
                question = input('\n你：').strip()
            except (EOFError, KeyboardInterrupt):
                print('\n已退出'); break
            if question == '/quit':
                break
            if question == '/new':
                conversation_id, turn_no, pending = None, None, None
                print('下一次提问将创建新会话。'); continue
            if not question:
                continue
            if question == '/retry':
                if pending is None:
                    print('没有待重试请求。'); continue
            # 构造请求
            payload = {'serial_no': args.serial_no, 'request_id': str(uuid.uuid4()), 'question': question}
            route = '/api/v1/robot/query'
            if conversation_id:
                route = '/api/v1/robot/conversations/query'
                payload.update(conversation_id=conversation_id, expected_last_turn_no=turn_no)
            pending = (route, payload)
            try:
                route, payload = pending
                response = session.post(args.base_url.rstrip('/') + route, json=payload, timeout=args.timeout)
                result = response.json()
                if response.status_code >= 400 or result.get('code') != 0:
                    print(f'接口失败（HTTP {response.status_code}）：{result.get("message", result)}')
                    print('可 /retry 重试或 /new 新建会话。'); continue
                data = result['data']
                answer = data['answer']
                if not isinstance(answer, str) or not data.get('conversation_id') or not isinstance(data.get('turn_no'), int):
                    raise ValueError('接口缺少有效的回答或会话信息')
                conversation_id, turn_no = data['conversation_id'], data['turn_no']
                pending = None
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                print(f'请求结果未确认：{error}。可用 /retry 重试原请求。'); continue
            print(f'机器人：{answer}')
            print(f'[会话 {conversation_id} · 第 {turn_no} 轮 · {data.get("status", "")}]')
            if not args.no_audio:
                try:
                    speak(answer)
                except (OSError, subprocess.SubprocessError, Exception) as error:
                    print(f'语音播放失败：{error}。文字回答已收到，可继续追问。')


if __name__ == '__main__':
    main()
