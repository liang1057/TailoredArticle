"""
本地接收服务
- 监听 0.0.0.0:5000
- 接收 POST /collect，JSON Body: {"url": "..."}
- 追加保存到 采集库/inbox/urls_pending.txt    , 由 collector 进程去读取并处理
- 开启 CORS，支持浏览器书签跨域发送
"""

import os
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 允许浏览器跨域请求

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(BASE_DIR, "采集库")
INBOX_FILE = os.path.join(WORKSPACE, "inbox", "urls_pending.txt")


@app.route('/collect', methods=['POST'])
def collect():
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()

    if not url or not url.startswith('http'):
        return jsonify({"status": "error", "msg": "invalid url"}), 400

    # 确保目录存在
    os.makedirs(os.path.dirname(INBOX_FILE), exist_ok=True)

    # 追加写入队列（时间戳 | URL）
    with open(INBOX_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {url}\n")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 收录: {url}")
    return jsonify({"status": "ok", "url": url}), 200


if __name__ == '__main__':
    # host='0.0.0.0' 允许局域网内其他设备访问
    # 树莓派迁移时，此文件原样复制即可运行
    app.run(host='0.0.0.0', port=5080, debug=False)