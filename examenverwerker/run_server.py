"""Start Uvicorn en open de browser zodra de lokale webserver reageert.

De oude batchstart opende de browser direct vóórdat Uvicorn gereed was.
Op tragere computers leidde die race bij de eerste poging tot een
verbindings-time-out. Dit script start de server in het voorgrondproces,
controleert de echte HTTP-route en opent daarna pas de browser.
"""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn


HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}/"


def open_browser_when_ready() -> None:
    """Wacht op een HTTP-antwoord en open daarna pas de startpagina.

    Een TCP-poort die luistert, garandeert nog niet dat FastAPI de
    startpagina kan leveren. Daarom testen we de daadwerkelijke URL.
    De korte timeout per poging houdt de controle responsief; de totale
    wachttijd voorkomt dat een browservenster eindeloos blijft wachten.
    """
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=1.0) as response:
                if response.status == 200:
                    print("\nServer reageert. De browser wordt geopend.", flush=True)
                    webbrowser.open(URL)
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            # Uvicorn is nog bezig met initialiseren; probeer het opnieuw.
            time.sleep(0.25)

    print(
        "\nWAARSCHUWING: de server gaf binnen 30 seconden geen HTTP-antwoord. "
        "Controleer de foutmeldingen hierboven.",
        flush=True,
    )


if __name__ == "__main__":
    # De daemonthread controleert de server terwijl Uvicorn in ditzelfde
    # consolevenster draait. De serverlogs blijven zichtbaar en Ctrl+C blijft
    # het bekende stopmechanisme.
    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    uvicorn.run("examenverwerker.main:app", host=HOST, port=PORT)
