"""Flask 扩展实例（避免循环导入）。"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
