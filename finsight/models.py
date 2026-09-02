"""数据库 ORM 模型。"""
from datetime import datetime

from finsight.extensions import db


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)


class Company(db.Model):
    __tablename__ = "company"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    data = db.relationship("CompanyData", backref="company", lazy=True)


class CompanyData(db.Model):
    __tablename__ = "company_data"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("company.id"), nullable=False)
    data_type = db.Column(db.String(50), nullable=False)
    data_content = db.Column(db.Text, nullable=False)


class Task(db.Model):
    __tablename__ = "task"

    id = db.Column(db.String(36), primary_key=True)
    status = db.Column(db.String(20), nullable=False, default="处理中")
    result = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
