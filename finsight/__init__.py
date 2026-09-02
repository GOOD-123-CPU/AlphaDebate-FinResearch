"""finsight 应用工厂。"""
import logging
from pathlib import Path

from flask import Flask

from finsight.config import config


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = config.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = config.SQLALCHEMY_TRACK_MODIFICATIONS

    # 运行时目录
    config.RESULT_DIR.mkdir(exist_ok=True)
    config.CACHE_DIR.mkdir(exist_ok=True)
    Path(config.BASE_DIR / "instance").mkdir(exist_ok=True)

    # 日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    # 扩展
    from finsight.extensions import db

    db.init_app(app)

    # 蓝图
    from finsight.routes.auth import auth_bp
    from finsight.routes.qa import qa_bp
    from finsight.routes.report import report_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(qa_bp)

    # 建表 + 种子数据
    with app.app_context():
        from finsight.models import Company, User
        from werkzeug.security import generate_password_hash

        db.create_all()
        # 演示账号仅用于首次体验，README 提醒部署者上线前删除或修改密码
        if not User.query.first():
            demo = User(username="demo", password=generate_password_hash("password"))
            db.session.add(demo)
            db.session.commit()
        if not Company.query.first():
            db.session.add_all([Company(name=f"公司{chr(65 + i)}") for i in range(3)])
            db.session.commit()

    return app


# 模块级 app 实例供 gunicorn/waitress 等 WSGI 服务器直接引用：app:create_app() 或 app
# 直接运行本文件仅用于开发调试，生产部署见 docs/deployment.md
app = create_app()

if __name__ == "__main__":
    app.run(debug=False, use_reloader=False, host="127.0.0.1", port=5231)
