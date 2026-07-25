import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import smtplib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str


def connection() -> psycopg.Connection:
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def init_db() -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    email_verified BOOLEAN NOT NULL DEFAULT false,
                    verification_token TEXT,
                    verification_expires_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token TEXT")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_expires_at TIMESTAMPTZ")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    preferred_fuel TEXT DEFAULT 'SP95-E10',
                    consumption_l_100km NUMERIC(5,2) DEFAULT 6.50,
                    tank_liters NUMERIC(5,2) DEFAULT 50.00,
                    language TEXT DEFAULT 'fr',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS favorite_stations (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    station_id TEXT NOT NULL,
                    station_name TEXT NOT NULL,
                    brand TEXT,
                    address TEXT,
                    city TEXT,
                    country TEXT,
                    fuel_type TEXT NOT NULL,
                    price_eur_l NUMERIC(6,3),
                    lat DOUBLE PRECISION,
                    lon DOUBLE PRECISION,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE(user_id, station_id, fuel_type)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS price_alerts (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    station_id TEXT,
                    fuel_type TEXT NOT NULL,
                    target_price NUMERIC(6,3) NOT NULL,
                    active BOOLEAN NOT NULL DEFAULT true,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        conn.commit()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return "pbkdf2_sha256$200000$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception as exc:
        logger.warning("Confirmation email failed for %s: %s", email, exc)
        return False


def create_token(user_id: str, email: str, expires_in: int = 60 * 60 * 24 * 30) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": int(time.time()) + expires_in,
        "jti": str(uuid.uuid4()),
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).digest()
    sig = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{body}.{sig}"


def read_token(token: str) -> CurrentUser | None:
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        if not hmac.compare_digest(actual, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if int(payload["exp"]) < int(time.time()):
            return None
        return CurrentUser(id=str(payload["sub"]), email=str(payload["email"]))
    except Exception:
        return None


def user_response(user_id: str, email: str) -> dict[str, Any]:
    token = create_token(user_id=user_id, email=email)
    return {
        "access_token": token,
        "refresh_token": token,
        "token_type": "bearer",
        "user": {"id": user_id, "email": email},
    }


def create_verification_token() -> tuple[str, datetime]:
    return secrets.token_urlsafe(32), datetime.now(timezone.utc) + timedelta(hours=24)


def set_verification_token(email: str) -> str | None:
    token, expires_at = create_verification_token()
    with connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                UPDATE users
                SET verification_token = %s,
                    verification_expires_at = %s
                WHERE email = %s
                RETURNING id
                """,
                (token, expires_at, email),
            ).fetchone()
        conn.commit()
    return token if row else None


def confirm_email_token(token: str) -> str | None:
    with connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                UPDATE users
                SET email_verified = true,
                    verification_token = NULL,
                    verification_expires_at = NULL
                WHERE verification_token = %s
                  AND verification_expires_at > now()
                RETURNING email
                """,
                (token,),
            ).fetchone()
        conn.commit()
    return str(row["email"]) if row else None


def send_confirmation_email(email: str, token: str) -> bool:
    if not settings.smtp_host or not settings.smtp_password:
        return False

    confirm_url = f"{settings.public_api_url.rstrip('/')}/auth/confirm?token={token}"
    message = EmailMessage()
    message["Subject"] = "Confirm your AVA SmartFuel account"
    message["From"] = settings.smtp_from
    message["To"] = email
    message.set_content(
        "\n".join(
            [
                "Bonjour,",
                "",
                "Merci de creer votre compte AVA SmartFuel.",
                "Confirmez votre email avec ce lien :",
                confirm_url,
                "",
                "Ce lien expire dans 24 heures.",
                "",
                "AVA SmartFuel",
                "support@avaintelligent.info",
            ]
        )
    )

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
        return True
    except Exception:
        return False
