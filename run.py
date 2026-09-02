"""统一启动入口。

用法：
    python run.py                 # 默认 127.0.0.1:5231
    python run.py --port 8080     # 自定义端口
    python run.py --host 0.0.0.0  # 允许外部访问（生产环境请使用 gunicorn/waitress）
"""
import argparse

from finsight import app


def main():
    parser = argparse.ArgumentParser(description="FinSightPro 智能研报平台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=5231, help="监听端口（默认 5231）")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    app.run(debug=args.debug, use_reloader=False, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
