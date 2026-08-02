"""SMTP delivery for approved member applications."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


class EmailConfigurationError(RuntimeError):
    pass


def _send_message(message: EmailMessage) -> None:
    status = email_delivery_status()
    if not status["configured"]:
        raise EmailConfigurationError(status["message"])

    host = (os.getenv("SMTP_HOST") or "").strip()
    port = int(os.getenv("SMTP_PORT") or 587)
    username = (os.getenv("SMTP_USERNAME") or "").strip()
    password = os.getenv("SMTP_PASSWORD") or ""
    use_ssl = (os.getenv("SMTP_USE_SSL") or "false").strip().lower() in {"1", "true", "yes"}
    use_starttls = (os.getenv("SMTP_USE_STARTTLS") or "true").strip().lower() in {"1", "true", "yes"}

    context = ssl.create_default_context()
    client = smtplib.SMTP_SSL(host, port, timeout=30, context=context) if use_ssl else smtplib.SMTP(host, port, timeout=30)
    with client:
        if not use_ssl and use_starttls:
            client.starttls(context=context)
        if username:
            client.login(username, password)
        client.send_message(message)


def email_delivery_status() -> dict:
    host = (os.getenv("SMTP_HOST") or "").strip()
    sender = (os.getenv("SMTP_FROM") or os.getenv("SMTP_USERNAME") or "").strip()
    configured = bool(host and sender)
    return {
        "configured": configured,
        "sender": sender if configured else None,
        "message": "审批邮件服务已配置" if configured else "尚未配置 SMTP，不能通过申请并发送密码",
    }


def send_registration_approved(email: str, temporary_password: str, login_url: str) -> None:
    status = email_delivery_status()
    if not status["configured"]:
        raise EmailConfigurationError(status["message"])
    sender = str(status["sender"])

    message = EmailMessage()
    message["Subject"] = "您的 AI 创作平台账号已通过审核"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "\n".join(
            [
                "您好，您的注册申请已经通过。",
                "",
                f"登录邮箱：{email}",
                f"初始密码：{temporary_password}",
                f"登录地址：{login_url}",
                "",
                "请妥善保管该登录密码，不要转发给其他人。",
            ]
        )
    )

    _send_message(message)


def send_registration_application_received(applicant_email: str, review_url: str) -> None:
    status = email_delivery_status()
    if not status["configured"]:
        raise EmailConfigurationError(status["message"])
    recipient = (
        os.getenv("REGISTRATION_NOTIFICATION_EMAIL")
        or os.getenv("SITE_ADMIN_EMAIL")
        or ""
    ).strip()
    if not recipient:
        raise EmailConfigurationError("尚未配置注册申请通知邮箱")

    message = EmailMessage()
    message["Subject"] = "AI 创作平台有新的注册申请"
    message["From"] = str(status["sender"])
    message["To"] = recipient
    message.set_content(
        "\n".join(
            [
                "您好，平台收到一条新的普通用户注册申请。",
                "",
                f"申请邮箱：{applicant_email}",
                f"审核地址：{review_url}",
                "",
                "请登录管理员账号后决定通过或拒绝。",
            ]
        )
    )
    _send_message(message)
