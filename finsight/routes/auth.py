"""认证路由：登录 / 注册 / 登出。"""
import logging

from flask import Blueprint, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from finsight.extensions import db
from finsight.models import User

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password or ""):
            session["user_id"] = user.id
            logger.info("用户 %s 登录成功", username)
            return redirect(url_for("report.chat"))

        return "账号或密码错误"
    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirmPassword") or ""
        if not username or not password or not confirm_password:
            return "请填写完整信息"
        if password != confirm_password:
            return "密码不一致"

        if User.query.filter_by(username=username).first():
            return "用户名已存在"

        new_user = User(username=username, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        logger.info("新用户注册: %s", username)

        return redirect(url_for("auth.register_success", username=username))

    return render_template("register.html")


@auth_bp.route("/register-success")
def register_success():
    username = request.args.get("username")
    return render_template("register-success.html", username=username)


@auth_bp.route("/logout")
def logout():
    session.clear()
    logger.info("用户已退出登录")
    return redirect(url_for("auth.login"))
