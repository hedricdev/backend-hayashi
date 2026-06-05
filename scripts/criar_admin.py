import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from auth import hash_password
from models.usuario import Role, Usuario


def main():
    email = input("Email do admin: ").strip().lower()
    nome = input("Nome: ").strip()
    senha = input("Senha: ").strip()

    db = SessionLocal()
    try:
        if db.query(Usuario).filter(Usuario.email == email).first():
            print(f"Erro: já existe um usuário com o email {email}")
            return
        admin = Usuario(
            nome=nome,
            email=email,
            senha_hash=hash_password(senha),
            role=Role.admin,
        )
        db.add(admin)
        db.commit()
        print(f"Admin criado com sucesso: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
