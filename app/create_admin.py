"""Create a separate administrator account: python -m app.create_admin"""
from getpass import getpass
import sqlite3
import time

from app.auth import database, hash_password, init_db, RegisterInput


def main():
    print("Create a Carewise administrator. Use a separate email from user accounts.")
    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip()
    password = getpass("Admin password (8+ characters): ")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match. No account was created.")
    try:
        account = RegisterInput(name=name, email=email, password=password)
    except ValueError:
        raise SystemExit("Use a valid email, a name of at least 2 characters, and a password of 8-128 characters.")
    init_db()
    try:
        with database() as db:
            db.execute("INSERT INTO users (name, email, password_hash, created_at, role) VALUES (?, ?, ?, ?, 'admin')",
                       (account.name, account.email, hash_password(account.password), int(time.time())))
    except sqlite3.IntegrityError:
        raise SystemExit("That email already exists. Choose a separate administrator email.")
    print("Administrator created. Sign in at http://127.0.0.1:8000/admin/login")


if __name__ == "__main__":
    main()
