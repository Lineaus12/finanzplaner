# ==============================================
# passenger_wsgi.py
# IONOS Webhosting nutzt Phusion Passenger als WSGI-Server.
# Diese Datei ist der Einstiegspunkt.
# ==============================================

import sys
import os

# Pfad zum Projektordner hinzufügen
# Auf IONOS: Passe diesen Pfad an deinen tatsächlichen Pfad an
INTERP = os.path.join(os.environ['HOME'], '.local', 'bin', 'python3')
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

# Projektordner in den Python-Pfad
sys.path.insert(0, os.path.dirname(__file__))

# Flask App importieren
from app import app as application

# Datenbank beim Start initialisieren
from app import init_db
init_db()
