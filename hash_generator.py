# ==============================================
# hash_generator.py
# Einmalig ausführen um deinen Passwort-Hash zu erstellen
# Dann den Hash in .env eintragen
# ==============================================

import hashlib
import getpass
import os

salt = input("Gib deinen PASSWORD_SALT ein (aus .env): ").strip()
passwort = getpass.getpass("Gib dein gewünschtes Passwort ein: ")

hash_wert = hashlib.sha256((salt + passwort).encode()).hexdigest()

print("\n" + "="*50)
print("Füge folgendes in deine .env Datei ein:")
print(f"APP_PASSWORD_HASH={hash_wert}")
print("="*50)
print("\nDas Passwort selbst NIEMALS irgendwo speichern!")
