import json
import math
import os
import random
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

try:
    from plyer import gps
except ImportError:
    gps = None

import requests
import tkintermapview
import winsound
from geopy.geocoders import Nominatim

# Konfiguracja mobilnego interfejsu.
START_LAT, START_LON = 50.334, 19.566
MAPBOX_TOKEN = "pk.eyJ1IjoiYW1pZ284OCIsImEiOiJjbTFrbXp6ZzAwM2g0MndzZHJ1ZnFhbWRoIn0.LqC6NID-zXbLw0yqVn93lA"
TLO, PANEL, KARTA = "#121212", "#1E1E1E", "#292929"
POMARANCZOWY, NIEBIESKI = "#FF5500", "#0078D7"
SCIEZKA_VOICES = os.path.join(os.path.dirname(__file__), "voices")
PLIK_LOKALIZACJI = os.path.join(os.path.dirname(__file__), "lokalizacje.json")

root = tk.Tk()
root.title("TomTom GO Mobile")
root.geometry("420x750")
root.resizable(False, False)
root.configure(bg=TLO)
geolocator = Nominatim(user_agent="tomtom-go-mobile-sms/1.0")

# Stan aplikacji.
WYBRANY_LEKTOR = "data34"
WYGENEROWANY_KOD = None
numer_telefonu = ""
dom_adres = None
dom_lat = dom_lon = None
praca_adres = None
praca_lat = praca_lon = None
punkty_symulacji = []
indeks_animacji = 0
symulacja_aktywna = False
zadanie_animacji = None
znacznik_pozycji = znacznik_celu = linia_trasy = None
trasa_dystans = 0.0
cel_podrozy = None
radary = [
    {"lat": 50.300, "lon": 19.540, "limit": 50},
    {"lat": 50.281, "lon": 19.565, "limit": 90},
    {"lat": 50.246, "lon": 19.590, "limit": 70},
]
znaczniki_radarow = []
odtworzone_radary = set()
znaczniki_poi = []
poi_widoczne = False
droga_platna_wykryta = False
PROFIL_TRASY = "mapbox/driving"
TRYB_TRASY = "Najszybsza (Standardowa)"
OMIJAJ_KORKI = tk.BooleanVar(value=False)
tryb_realny_gps = False
gps_lat = START_LAT
gps_lon = START_LON
gps_dokladnosc = None


def wczytaj_lokalizacje():
    global dom_adres, dom_lat, dom_lon, praca_adres, praca_lat, praca_lon
    try:
        with open(PLIK_LOKALIZACJI, "r", encoding="utf-8") as plik:
            dane = json.load(plik)
        dom = dane.get("dom", {})
        praca = dane.get("praca", {})
        dom_adres, dom_lat, dom_lon = dom.get("adres"), dom.get("lat"), dom.get("lon")
        praca_adres, praca_lat, praca_lon = praca.get("adres"), praca.get("lat"), praca.get("lon")
    except (OSError, json.JSONDecodeError, AttributeError):
        pass


def zapisz_lokalizacje():
    try:
        with open(PLIK_LOKALIZACJI, "w", encoding="utf-8") as plik:
            json.dump({
                "dom": {"adres": dom_adres, "lat": dom_lat, "lon": dom_lon},
                "praca": {"adres": praca_adres, "lat": praca_lat, "lon": praca_lon},
            }, plik, ensure_ascii=False, indent=2)
    except OSError as error:
        print(f"Lokalizacje: nie można zapisać danych: {error}")


def odtworz_komunikat_rlink(nazwa_pliku):
    """Odtwarza lokalny plik audio przez winsound bez blokowania mapy."""
    try:
        sciezka = os.path.join(os.path.dirname(__file__), "voices", nazwa_pliku)
        if not os.path.exists(sciezka):
            print(f"Audio: brak pliku {sciezka}")
            return False
        winsound.PlaySound(sciezka, winsound.SND_FILENAME | winsound.SND_ASYNC)
        return True
    except Exception as error:
        print(f"Błąd odtwarzania winsound: {error}")
        return False


def zatrzymaj_symulacje():
    """Anuluje zaplanowany krok sztucznej jazdy."""
    global symulacja_aktywna, zadanie_animacji
    symulacja_aktywna = False
    if zadanie_animacji is not None:
        root.after_cancel(zadanie_animacji)
        zadanie_animacji = None


def on_location_received(**kwargs):
    """Odbiera pozycję z Androida i przekazuje aktualizację do wątku GUI."""
    try:
        lat = float(kwargs.get("lat"))
        lon = float(kwargs.get("lon"))
        speed = float(kwargs.get("speed", 0) or 0)
        accuracy = kwargs.get("accuracy")
    except (TypeError, ValueError):
        return
    if tryb_realny_gps:
        root.after(0, lambda: aktualizuj_pozycje_gps(lat, lon, speed, accuracy))


def aktualizuj_pozycje_gps(lat, lon, speed, accuracy):
    """Aktualizuje mapę i kokpit na podstawie najnowszej pozycji GPS."""
    global gps_lat, gps_lon, gps_dokladnosc, znacznik_pozycji
    gps_lat, gps_lon, gps_dokladnosc = lat, lon, accuracy
    if znacznik_pozycji is None:
        znacznik_pozycji = map_widget.set_marker(lat, lon, text="🚗 Ty")
    else:
        znacznik_pozycji.set_position(lat, lon)
    map_widget.set_position(lat, lon)
    predkosc_kmh = speed * 3.6 if speed < 30 else speed
    if cel_podrozy is not None:
        dystans = odległość_km((lat, lon), cel_podrozy)
        widget_odleglosc.config(text=f"{dystans:.1f} km")
        widget_czas.config(text=f"{round(dystans / max(30, predkosc_kmh) * 60)} min")
    widget_predkosc.config(text=f"{round(predkosc_kmh)} km/h")
    sprawdz_fotoradar_na_pozycji((lat, lon))
    ustaw_status("GPS na żywo aktywny.", "#81C784")


def sprawdz_fotoradar_na_pozycji(punkt):
    """Wspólne odliczanie radarów dla GPS rzeczywistego i symulacji."""
    najblizszy = min(
        (odległość_km(punkt, (radar["lat"], radar["lon"])) * 1000, radar)
        for radar in radary
    )
    if najblizszy[0] < 500:
        etykieta_radaru.config(text=f"FOTORADAR ZA: {round(najblizszy[0])} m")
    else:
        etykieta_radaru.config(text="FOTORADAR ZA: ---")
    identyfikator = id(najblizszy[1])
    if najblizszy[0] < 400 and identyfikator not in odtworzone_radary:
        odtworzone_radary.add(identyfikator)
        odtworz_komunikat_rlink(wybrany_plik(True))


def uruchom_gps_na_zywo():
    """Włącza prawdziwy GPS na Androidzie albo bezpieczny tryb oczekiwania na PC."""
    global tryb_realny_gps
    zatrzymaj_symulacje()
    tryb_realny_gps = True
    if gps is None:
        ustaw_status("GPS niedostępny na tym komputerze. Gotowe na Androida.", "#FFB74D")
        map_widget.set_position(START_LAT, START_LON)
        map_widget.set_zoom(14)
        return
    try:
        gps.configure(on_location=on_location_received, status_callback=None)
        gps.start(minTime=1000, minDistance=1)
        ustaw_status("Nasłuchiwanie prawdziwego sygnału GPS...", "#81C784")
    except Exception as error:
        tryb_realny_gps = False
        print(f"GPS: nie można uruchomić odbiornika: {error}")
        ustaw_status("Nie udało się uruchomić GPS na żywo.", "#FF5555")


def ustaw_status(tekst, kolor="#BDBDBD"):
    napis_statusu.config(text=tekst, fg=kolor)


def wybrany_plik(radar=True):
    if WYBRANY_LEKTOR == "data34":
        return "data34.mp3" if radar else "data36.mp3"
    return "data25.mp3" if radar else "data27.mp3"


def wyślij_kod_sms(okno, pole_kodu, status):
    global WYGENEROWANY_KOD, numer_telefonu
    numer_telefonu = pole_numeru.get().strip()
    if not numer_telefonu:
        status.config(text="Wpisz numer telefonu.", fg="#FF6666")
        return
    WYGENEROWANY_KOD = str(random.randint(10000000, 99999999))
    pole_kodu.config(state=tk.NORMAL)
    status.config(text="Kod wysłany. Sprawdź zielony komunikat.", fg="#81C784")
    messagebox.showinfo(
        "Bramka SMS TomTom",
        f"Twój 8-cyfrowy kod weryfikacyjny to: {WYGENEROWANY_KOD}",
        parent=okno,
    )


def potwierdź_kod(okno, pole_kodu, status):
    if WYGENEROWANY_KOD is not None and pole_kodu.get().strip() == WYGENEROWANY_KOD:
        btn_profil.config(text="👤 Kierowca zweryfikowany!", bg="#2EA44F")
        ustaw_status("Numer telefonu zweryfikowany.", "#81C784")
        okno.destroy()
    else:
        status.config(text="Nieprawidłowy kod weryfikacyjny! Spróbuj ponownie", fg="#FF5555")


def otworz_profil():
    """Otwiera lokalne okno autoryzacji numerem telefonu."""
    okno = tk.Toplevel(root)
    okno.title("Autoryzacja SMS")
    okno.geometry("350x300")
    okno.resizable(False, False)
    okno.configure(bg=PANEL)
    tk.Label(okno, text="LOGOWANIE NUMEREM TELEFONU", bg=PANEL, fg="white",
             font=("Segoe UI", 12, "bold")).pack(pady=(20, 12))
    tk.Label(okno, text="Numer telefonu", bg=PANEL, fg="#DDDDDD").pack(anchor="w", padx=25)
    global pole_numeru
    pole_numeru = tk.Entry(okno, bg="#353535", fg="white", insertbackground="white", relief="flat")
    pole_numeru.pack(fill="x", padx=25, pady=(4, 10), ipady=7)
    status = tk.Label(okno, text="", bg=PANEL, fg="#BDBDBD", wraplength=290)
    status.pack(padx=20, pady=3)
    tk.Button(okno, text="WYŚLIJ KOD SMS",
              command=lambda: wyślij_kod_sms(okno, pole_kodu, status),
              bg=POMARANCZOWY, fg="white", relief="flat",
              font=("Segoe UI", 9, "bold")).pack(fill="x", padx=25, pady=6, ipady=7)
    tk.Label(okno, text="8-cyfrowy kod", bg=PANEL, fg="#DDDDDD").pack(anchor="w", padx=25, pady=(8, 0))
    pole_kodu = tk.Entry(okno, bg="#353535", fg="white", insertbackground="white", relief="flat", state=tk.DISABLED)
    pole_kodu.pack(fill="x", padx=25, pady=(4, 8), ipady=7)
    tk.Button(okno, text="POTWIERDŹ KOD",
              command=lambda: potwierdź_kod(okno, pole_kodu, status),
              bg="#2EA44F", fg="white", relief="flat",
              font=("Segoe UI", 9, "bold")).pack(fill="x", padx=25, ipady=7)


def ustaw_lektora(wartość):
    global WYBRANY_LEKTOR
    WYBRANY_LEKTOR = wartość
    etykieta_lektora.config(text="Głos: Katarzyna" if wartość == "data34" else "Głos: Andrzej")


def testuj_dźwięk():
    odtworz_komunikat_rlink(wybrany_plik(True))
    root.after(1500, lambda: odtworz_komunikat_rlink(wybrany_plik(False)))


def otwórz_ustawienia():
    okno = tk.Toplevel(root)
    okno.title("Ustawienia TomTom GO")
    okno.geometry("370x430")
    okno.configure(bg=PANEL)
    notebook = ttk.Notebook(okno)
    notebook.pack(fill="both", expand=True, padx=12, pady=12)
    głosy = tk.Frame(notebook, bg=PANEL)
    pobierz = tk.Frame(notebook, bg=PANEL)
    trasa = tk.Frame(notebook, bg=PANEL)
    notebook.add(głosy, text="GŁOSY")
    notebook.add(pobierz, text="POBIERZ GŁOSY")
    notebook.add(trasa, text="TRASA")
    tk.Label(głosy, text="Wybierz lektora nawigacji:", bg=PANEL, fg="white",
             font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=18, pady=(20, 10))
    wybor = tk.StringVar(value=WYBRANY_LEKTOR)
    tk.Radiobutton(głosy, text="Katarzyna (Żeński R-Link)", variable=wybor, value="data34",
                   command=lambda: ustaw_lektora(wybor.get()), bg=PANEL, fg="white",
                   selectcolor="#444444", activebackground=PANEL).pack(anchor="w", padx=18, pady=4)
    tk.Radiobutton(głosy, text="Andrzej (Męski R-Link)", variable=wybor, value="data25",
                   command=lambda: ustaw_lektora(wybor.get()), bg=PANEL, fg="white",
                   selectcolor="#444444", activebackground=PANEL).pack(anchor="w", padx=18, pady=4)
    tk.Button(głosy, text="▶ TESTUJ DŹWIĘK", command=testuj_dźwięk,
              bg="#2EA44F", fg="white", relief="flat",
              font=("Arial", 10, "bold")).pack(fill="x", padx=18, pady=18, ipady=8)
    tk.Label(trasa, text="Preferowany typ trasy:", bg=PANEL, fg="white",
             font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=18, pady=(24, 8))
    tryb = tk.StringVar(value=TRYB_TRASY)
    tk.OptionMenu(
        trasa, tryb, "Najszybsza (Standardowa)", "Eko (Ekonomiczna)", "Najkrótsza",
        command=ustaw_tryb_trasy,
    ).pack(fill="x", padx=18, pady=5)
    tk.Checkbutton(
        trasa, text="Omijaj korki i utrudnienia (Live)", variable=OMIJAJ_KORKI,
        command=ustaw_profil_ruchu, bg=PANEL, fg="white", selectcolor="#444444",
        activebackground=PANEL, activeforeground="white",
    ).pack(anchor="w", padx=18, pady=14)
    tk.Label(pobierz, text="Głosy są instalowane do folderu voices projektu.",
             bg=PANEL, fg="#BDBDBD", wraplength=280).pack(padx=18, pady=20)
    pasek = tk.Label(pobierz, text="Postęp: 0%", bg="#252525", fg="white", font=("Arial", 10))
    pasek.pack(pady=5)
    tk.Button(pobierz, text="⬇ POBIERZ I INSTALUJ GŁOSY", command=lambda: symuluj_instalację(pasek),
              bg=POMARANCZOWY, fg="white", relief="flat",
              font=("Segoe UI", 9, "bold")).pack(fill="x", padx=18, pady=14, ipady=8)


def symuluj_instalację(pasek):
    os.makedirs(os.path.join(os.path.dirname(__file__), "voices"), exist_ok=True)
    def krok(procent):
        pasek.config(text=f"Postęp: {procent}%")
        if procent < 100:
            root.after(40, lambda: krok(procent + 5))
        else:
            ustaw_status("Instalacja zakończona! Głosy gotowe do użycia.", "#81C784")
    krok(0)


def odległość_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    wartosc = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(wartosc), math.sqrt(1 - wartosc))


def uzupełnij_kraj(adres):
    """Dopina Polskę, jeśli użytkownik nie podał kraju."""
    tekst = adres.strip()
    kraje = ("polska", "poland", "germany", "niemcy", "czech", "słowacja", "slovakia")
    if not any(kraj in tekst.lower() for kraj in kraje):
        return f"{tekst}, Polska"
    return tekst


def sprawdz_czy_platna(dane_trasy, nazwa_celu):
    """Skanuje cel i dane manewrów oraz pyta przed trasą przez drogę płatną."""
    global droga_platna_wykryta
    tekst = f"{nazwa_celu} {dane_trasy}".lower()
    slowa_platne = ("a4", "a1", "a2", "autostrada", "motorway", "toll", "paid", "płatna", "platna")
    if not any(slowo in tekst for slowo in slowa_platne):
        droga_platna_wykryta = False
        return True
    droga_platna_wykryta = True
    return messagebox.askyesno(
        "Ostrzeżenie TomTom",
        "Wykryto odcinek płatny na wyznaczonej trasie. Czy chcesz kontynuować?",
        parent=root,
    )


def wyczysc_poi():
    for znacznik in znaczniki_poi:
        map_widget.delete(znacznik)
    znaczniki_poi.clear()


def generuj_punkty_poi_na_trasie():
    """Nakłada małe POI wzdłuż trasy, bez stawiania markerów radarów."""
    wyczysc_poi()
    if len(punkty_symulacji) < 4:
        return
    indeksy = [len(punkty_symulacji) // 4, len(punkty_symulacji) // 2, len(punkty_symulacji) * 3 // 4]
    etykiety = ["⛽ ORLEN", "☕ MOP", "⛽ SHELL"]
    for indeks, etykieta in zip(indeksy, etykiety):
        punkt = punkty_symulacji[indeks]
        znaczniki_poi.append(map_widget.set_marker(
            punkt[0], punkt[1], text=etykieta,
            marker_color_circle="#777777", marker_color_outside="#AAAAAA",
            text_color="white", font=("Arial", 7, "bold")
        ))


def przelacz_widocznosc_poi():
    """Pokazuje lub ukrywa małe punkty użyteczności publicznej na trasie."""
    global poi_widoczne
    if not punkty_symulacji:
        ustaw_status("Najpierw wyznacz trasę, aby pokazać POI.", "#FFB74D")
        return
    if poi_widoczne:
        wyczysc_poi()
        poi_widoczne = False
        przycisk_poi.config(bg="#1E1E1E")
        ustaw_status("Punkty POI ukryte.", "#BDBDBD")
    else:
        generuj_punkty_poi_na_trasie()
        poi_widoczne = True
        przycisk_poi.config(bg="#2EA44F")
        ustaw_status("Punkty POI pokazane na trasie.", "#81C784")


def ustaw_tryb_trasy(wartość):
    global TRYB_TRASY
    TRYB_TRASY = wartość


def ustaw_profil_ruchu():
    global PROFIL_TRASY
    PROFIL_TRASY = "mapbox/driving-traffic" if OMIJAJ_KORKI.get() else "mapbox/driving"


def pobierz_trasę(s_lat, s_lon, c_lat, c_lon):
    """Pobiera geometrię Mapbox, a przy błędzie korzysta z OSRM."""
    profil = PROFIL_TRASY
    url = f"https://api.mapbox.com/directions/v5/{profil}/{s_lon},{s_lat};{c_lon},{c_lat}"
    parametry = {
        "geometries": "geojson",
        "overview": "full",
        "steps": "true",
        "access_token": MAPBOX_TOKEN,
    }
    try:
        odpowiedz = requests.get(url, params=parametry, timeout=15)
        odpowiedz.raise_for_status()
        dane = odpowiedz.json()
        trasa = dane["routes"][0]
        punkty = trasa["geometry"]["coordinates"]
        droga_platna = any(
            slowo in json_text.lower()
            for slowo in ("toll", "motorway", "a4", "paid")
            for json_text in [str(trasa)]
        )
    except Exception:
        url = f"https://router.project-osrm.org/route/v1/driving/{s_lon},{s_lat};{c_lon},{c_lat}"
        dane = requests.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=15).json()
        punkty = dane["routes"][0]["geometry"]["coordinates"]
        droga_platna = False
    return [(punkt[1], punkt[0]) for punkt in punkty], trasa if "trasa" in locals() else dane


def ruszaj_w_droge():
    global punkty_symulacji, znacznik_celu, linia_trasy, trasa_dystans, indeks_animacji, cel_podrozy
    try:
        adres_z_krajem = uzupełnij_kraj(pole_szukaj.get())
        pole_szukaj.delete(0, tk.END)
        pole_szukaj.insert(0, adres_z_krajem)
        lokalizacja = geolocator.geocode(adres_z_krajem, timeout=10)
        if not lokalizacja:
            raise ValueError("Nie znaleziono celu.")
        if znacznik_celu:
            map_widget.delete(znacznik_celu)
        if linia_trasy:
            map_widget.delete(linia_trasy)
        wyczysc_poi()
        global poi_widoczne
        poi_widoczne = False
        przycisk_poi.config(bg="#1E1E1E")
        punkty_symulacji, dane_trasy = pobierz_trasę(
            START_LAT, START_LON, lokalizacja.latitude, lokalizacja.longitude
        )
        cel_podrozy = (lokalizacja.latitude, lokalizacja.longitude)
        if not sprawdz_czy_platna(dane_trasy, lokalizacja.address):
            punkty_symulacji = []
            ustaw_status(
                "Anulowano - omijanie dróg płatnych",
                "#FFB74D",
            )
            btn_start.config(state=tk.DISABLED)
            btn_gps.config(state=tk.NORMAL)
            return
        trasa_dystans = sum(odległość_km(punkty_symulacji[i - 1], punkty_symulacji[i]) for i in range(1, len(punkty_symulacji)))
        znacznik_celu = map_widget.set_marker(lokalizacja.latitude, lokalizacja.longitude, text="CEL")
        linia_trasy = map_widget.set_path(punkty_symulacji, color=NIEBIESKI, width=6)
        map_widget.set_position(START_LAT, START_LON)
        map_widget.set_zoom(12)
        widget_odleglosc.config(text=f"{trasa_dystans:.1f} km")
        widget_czas.config(text=f"{round(trasa_dystans / 60 * 60)} min")
        btn_start.config(state=tk.NORMAL, bg=POMARANCZOWY)
        btn_gps.config(state=tk.NORMAL)
        ustaw_status("Wyznaczono trasę uliczną.", "#81C784")
        if droga_platna_wykryta:
            if messagebox.askyesno(
                "GPS na żywo",
                "Czy uruchomić prawdziwy sygnał GPS?",
                parent=root,
            ):
                uruchom_gps_na_zywo()
            else:
                root.after(100, uruchom_symulacje)
    except Exception as error:
        ustaw_status(f"Nie udało się wyznaczyć trasy: {error}", "#FF5555")


def pętla_animacji():
    global indeks_animacji, znacznik_pozycji, symulacja_aktywna
    if not symulacja_aktywna:
        return
    if indeks_animacji >= len(punkty_symulacji):
        symulacja_aktywna = False
        widget_predkosc.config(text="0 km/h")
        ustaw_status("Dojechałeś bezpiecznie do celu!", "#81C784")
        odtworz_komunikat_rlink(wybrany_plik(False))
        return
    punkt = punkty_symulacji[indeks_animacji]
    if znacznik_pozycji:
        map_widget.delete(znacznik_pozycji)
    znacznik_pozycji = map_widget.set_marker(punkt[0], punkt[1], text="🚗 Ty")
    map_widget.set_position(*punkt)
    postep = indeks_animacji / max(1, len(punkty_symulacji) - 1)
    widget_odleglosc.config(text=f"{max(0, trasa_dystans * (1 - postep)):.1f} km")
    widget_czas.config(text=f"{round(max(0, trasa_dystans * (1 - postep) / 60 * 60))} min")
    widget_predkosc.config(text="68 km/h")
    sprawdz_fotoradar_na_pozycji(punkt)
    indeks_animacji += 1
    root.after(100, pętla_animacji)


def uruchom_symulacje():
    global symulacja_aktywna, indeks_animacji, tryb_realny_gps
    if punkty_symulacji:
        tryb_realny_gps = False
        if gps is not None:
            try:
                gps.stop()
            except Exception:
                pass
        indeks_animacji = 0
        symulacja_aktywna = True
        odtworz_komunikat_rlink(wybrany_plik(True))
        pętla_animacji()


def uruchom_zapisana_lokalizacje(typ):
    """Ustawia adres Dom/Praca albo natychmiast wyznacza do niego trasę."""
    global dom_adres, dom_lat, dom_lon, praca_adres, praca_lat, praca_lon
    if typ == "dom":
        adres = dom_adres
        lat, lon = dom_lat, dom_lon
        tytul = "Konfiguracja Domu"
        prompt = "Wpisz swój adres domowy:"
    else:
        adres = praca_adres
        lat, lon = praca_lat, praca_lon
        tytul = "Konfiguracja Pracy"
        prompt = "Wpisz adres miejsca pracy:"

    if lat is not None:
        pole_szukaj.delete(0, tk.END)
        pole_szukaj.insert(0, adres)
        ruszaj_w_droge()
        return

    wpisany_adres = simpledialog.askstring(tytul, prompt, parent=root)
    if not wpisany_adres or not wpisany_adres.strip():
        return
    try:
        adres_z_krajem = uzupełnij_kraj(wpisany_adres)
        lokalizacja = geolocator.geocode(adres_z_krajem, timeout=10)
        if lokalizacja is None:
            raise ValueError("Nie znaleziono podanego adresu.")
        if typ == "dom":
            dom_adres, dom_lat, dom_lon = adres_z_krajem, lokalizacja.latitude, lokalizacja.longitude
            btn_dom.config(text="🏠 Jedź do: Dom", bg=POMARANCZOWY, fg="white")
        else:
            praca_adres, praca_lat, praca_lon = adres_z_krajem, lokalizacja.latitude, lokalizacja.longitude
            btn_praca.config(text="🏢 Jedź do: Praca", bg=POMARANCZOWY, fg="white")
        zapisz_lokalizacje()
        ustaw_status(f"Zapisano lokalizację: {adres_z_krajem}", "#81C784")
    except Exception as error:
        ustaw_status(f"Nie udało się znaleźć adresu: {error}", "#FF5555")


def lokalizuj_mnie():
    """Przybliża mapę do bieżącej pozycji startowej kierowcy."""
    map_widget.set_position(START_LAT, START_LON)
    map_widget.set_zoom(14)
    ustaw_status("Wyśrodkowano mapę na pozycji kierowcy.", "#81C784")


# Odczyt zapisanych adresów przed zbudowaniem przycisków.
wczytaj_lokalizacje()

# Górny panel mobilny.
panel_gorny = tk.Frame(root, bg=PANEL, height=52)
panel_gorny.pack(fill="x")
panel_gorny.pack_propagate(False)
pole_szukaj = tk.Entry(panel_gorny, bg="#303030", fg="white", insertbackground="white", relief="flat")
pole_szukaj.pack(side=tk.LEFT, fill="x", expand=True, padx=7, pady=8, ipady=5)
pole_szukaj.insert(0, "Kraków Sukiennice")
tk.Button(panel_gorny, text="🔍", command=ruszaj_w_droge, bg=POMARANCZOWY, fg="white", relief="flat", width=3).pack(side=tk.RIGHT, padx=4, pady=7)
btn_profil = tk.Button(panel_gorny, text="👤 PROFIL", command=otworz_profil, bg="#444444", fg="white", relief="flat", font=("Arial", 8, "bold"))
btn_profil.pack(side=tk.RIGHT, padx=3, pady=7)
tk.Button(panel_gorny, text="🎯", command=lokalizuj_mnie, bg="#303030", fg="white", relief="flat", width=3).pack(side=tk.RIGHT, padx=3, pady=7)
tk.Button(panel_gorny, text="⚙️", command=otwórz_ustawienia, bg="#303030", fg="white", relief="flat", width=3).pack(side=tk.RIGHT, padx=3, pady=7)

panel_skrotow = tk.Frame(root, bg=TLO, height=38)
panel_skrotow.pack(fill="x")
btn_dom = tk.Button(panel_skrotow, text="🏠 Ustaw Dom", command=lambda: uruchom_zapisana_lokalizacje("dom"), bg="#252525", fg="#888888", relief="flat")
btn_dom.pack(side=tk.LEFT, fill="x", expand=True, padx=4, pady=4)
btn_praca = tk.Button(panel_skrotow, text="🏢 Ustaw Pracę", command=lambda: uruchom_zapisana_lokalizacje("praca"), bg="#252525", fg="#888888", relief="flat")
btn_praca.pack(side=tk.LEFT, fill="x", expand=True, padx=4, pady=4)
if dom_lat is not None:
    btn_dom.config(text="🏠 Jedź do: Dom", bg=POMARANCZOWY, fg="white")
if praca_lat is not None:
    btn_praca.config(text="🏢 Jedź do: Praca", bg=POMARANCZOWY, fg="white")
etykieta_lektora = tk.Label(panel_skrotow, text="Głos: Katarzyna", bg=TLO, fg="#FFB74D", font=("Segoe UI", 7, "bold"))
etykieta_lektora.pack(side=tk.RIGHT, padx=5)

# Mapa z warstwą Traffic.
map_widget = tkintermapview.TkinterMapView(root, width=420, height=470, corner_radius=0)
map_widget.pack(fill="both", expand=True)
map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=m,traffic&x={x}&y={y}&z={z}", max_zoom=22)
map_widget.set_position(START_LAT, START_LON)
map_widget.set_zoom(12)
przycisk_poi = tk.Button(
    root, text="⛽", command=przelacz_widocznosc_poi,
    bg="#1E1E1E", fg="white", font=("Arial", 12, "bold"),
    relief="flat", bd=0, activebackground="#333333", activeforeground="white",
)
przycisk_poi.place(relx=0.88, rely=0.38, anchor="center", width=42, height=42)

nakladka_pasow = tk.Label(root, text="➔ Gotowy do jazdy", bg="#050505", fg="white", font=("Segoe UI", 10, "bold"))
nakladka_pasow.place(relx=.5, y=92, anchor="n", relwidth=.82, height=28)
panel_radaru = tk.Frame(root, bg="#202020")
panel_radaru.place(relx=.53, y=125, relwidth=.44, height=35)
etykieta_radaru = tk.Label(panel_radaru, text="FOTORADAR ZA: ---", bg="#303030", fg="white", font=("Segoe UI", 8, "bold"))
etykieta_radaru.pack(fill="both", expand=True)

# Kokpit kierowcy.
panel_dolny = tk.Frame(root, bg=PANEL, height=150)
panel_dolny.pack(fill="x")
panel_dolny.pack_propagate(False)
wiersz = tk.Frame(panel_dolny, bg=PANEL)
wiersz.pack(fill="x", pady=5)
widget_odleglosc = tk.Label(wiersz, text="0.0 km", bg=KARTA, fg="white", font=("Segoe UI", 13, "bold"))
widget_odleglosc.pack(side=tk.LEFT, fill="x", expand=True, padx=3)
widget_czas = tk.Label(wiersz, text="0 min", bg=KARTA, fg=POMARANCZOWY, font=("Segoe UI", 13, "bold"))
widget_czas.pack(side=tk.LEFT, fill="x", expand=True, padx=3)
widget_predkosc = tk.Label(wiersz, text="0 km/h", bg=KARTA, fg="#57D67A", font=("Segoe UI", 13, "bold"))
widget_predkosc.pack(side=tk.LEFT, fill="x", expand=True, padx=3)
panel_trybow = tk.Frame(panel_dolny, bg=PANEL)
panel_trybow.pack(fill="x", padx=8, pady=7)
btn_start = tk.Button(
    panel_trybow, text="🤖 SYMULACJA", command=uruchom_symulacje,
    state=tk.DISABLED, bg="#555555", fg="white", relief="flat",
    font=("Arial", 9, "bold"),
)
btn_start.pack(side=tk.LEFT, fill="x", expand=True, padx=2, ipady=8)
btn_gps = tk.Button(
    panel_trybow, text="🛰️ GPS NA ŻYWO", command=uruchom_gps_na_zywo,
    state=tk.NORMAL, bg="#0078D7", fg="white", relief="flat",
    font=("Arial", 9, "bold"),
)
btn_gps.pack(side=tk.RIGHT, fill="x", expand=True, padx=2, ipady=8)
napis_statusu = tk.Label(root, text="Wpisz cel i rozpocznij nawigację.", bg=TLO, fg="#BDBDBD", font=("Segoe UI", 8))
napis_statusu.pack(fill="x", padx=8, pady=2)

root.mainloop()
