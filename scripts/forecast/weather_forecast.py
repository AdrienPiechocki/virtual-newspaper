import requests
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime
import json, os, random, statistics
import argparse
import csv
import sys

# =========================
# CLIENT
# =========================

class OpenMeteoClient:
    WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

    CITIES = {
        "Paris": {"lat": 48.8566, "lon": 2.3522},
        "Tours": {"lat": 47.3948, "lon": 0.704},
        "Dijon": {"lat": 47.3220, "lon": 5.0415},
        "Le Havre": {"lat": 49.4944, "lon": 0.1079},
        "Lille": {"lat": 50.6292, "lon": 3.0573},
        "Strasbourg": {"lat": 48.5734, "lon": 7.7521},
        "Nantes": {"lat": 47.2184, "lon": -1.5536},
        "Brest": {"lat": 48.3905, "lon": -4.4860},
        "Bordeaux": {"lat": 44.8378, "lon": -0.5792},
        "Toulouse": {"lat": 43.6047, "lon": 1.4442},
        "Lyon": {"lat": 45.7640, "lon": 4.8357},
        "Marseille": {"lat": 43.2965, "lon": 5.3698},
        "Ajaccio": {"lat": 41.9267, "lon": 8.7369},
        "Reims": {"lat": 49.2653, "lon": 4.0285},
        "Limoges": {"lat": 45.8336, "lon": 1.2476},
    }

    def get_national_forecast(self) -> List[Dict]:

        city_data = {}

        # 1. Récupération API par ville
        for city, coords in self.CITIES.items():
            params = {
                "latitude": coords["lat"],
                "longitude": coords["lon"],
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "timezone": "Europe/Paris"
            }

            r = requests.get(self.WEATHER_URL, params=params)
            data = r.json()

            if "error" in data:
                raise ValueError(f"API error for {city}: {data}")

            daily = data.get("daily", {})

            city_data[city] = {
                "dates": daily.get("time", []),
                "t_max": daily.get("temperature_2m_max", []),
                "rain": daily.get("precipitation_sum", []),
                "weathercode": daily.get("weathercode", [])
            }

        # 2. Regroupement par jour (structure attendue par export_csv)
        forecast_by_day = []

        if not city_data:
            return []

        dates = next(iter(city_data.values()))["dates"]

        for i, date in enumerate(dates):
            day_entry = {
                "date": date,
                "cities": {}
            }

            for city, d in city_data.items():
                day_entry["cities"][city] = {
                    "t_max": d["t_max"][i],
                    "rain": d["rain"][i],
                    "weathercode": d["weathercode"][i],
                }

            forecast_by_day.append(day_entry)

        return forecast_by_day

    # =========================
    # BULLETIN
    # =========================

    WMO_DESCRIPTIONS = {
        0:  "ciel dégagé",       1:  "principalement dégagé",  2:  "partiellement nuageux",
        3:  "couvert",           16: "brume légère",            17: "orages isolés",
        18: "orages locaux",     19: "orages épars",            29: "averses orageuses",
        31: "légèrement nuageux",38: "nébulosité variable",     42: "averses possibles",
        45: "brouillard",        51: "bruine légère",           53: "bruine modérée",
        55: "bruine dense",      59: "averses et brouillard",
        61: "pluie faible",      63: "pluie modérée",           65: "pluie forte",
        71: "neige légère",      73: "neige modérée",           75: "neige forte",
        80: "averses légères",   81: "averses modérées",        82: "averses violentes",
        95: "orage",             96: "orage avec grêle",        99: "orage violent avec grêle",
    }

    def wmo_label(self, code: int) -> str:
        return self.WMO_DESCRIPTIONS.get(code, "conditions variables")

    def _effective_sky(self, code: int, rain: float, t_max: float) -> int:
        """
        Corrige le code WMO d'une région en croisant pluie et température.

        Open-Meteo renvoie fréquemment code=3 (couvert) pour des journées chaudes
        et sèches — biais connu du modèle. On déduit le ciel réel :
        - Pluie significative (≥ 1 mm) → on garde le code tel quel ou on force 61
        - Code nuageux/couvert + pas de pluie + journée chaude → on reclasse en
            partiellement nuageux (2) ou dégagé (1) selon la chaleur
        - Orages/neige → jamais modifiés
        """
        STORMY = {17, 18, 19, 29, 42, 95, 96, 99}
        SNOWY  = {71, 73, 75}

        # Phénomènes intenses : on ne touche pas
        if code in STORMY or code in SNOWY:
            return code

        # Pluie réelle confirmée par les mm → le code pluvieux est fiable
        if rain >= 1.0 and 51 <= code <= 82:
            return code

        # Code nuageux/couvert (3, 45 brouillard, 31, 38, 2…) + journée sèche
        if code in (2, 3, 31, 38, 45) and rain < 1.0:
            if rain < 0.5:
                if t_max >= 30:
                    return 0      # ciel dégagé
                elif t_max >= 24:
                    return 1      # principalement dégagé
                else:
                    return 2      # partiellement nuageux
            if t_max >= 22:
                # Journée douce sans pluie → partiellement nuageux
                return 2
            # Journée fraîche et sèche → on garde le nuageux (peut être réel)
            return code

        return code


    # =========================
    # EXPORT CSV
    # =========================

    def export_csv(self, forecast: List[Dict], path: str) -> None:
        """
        Exporte le forecast national en CSV, une ligne par ville/jour.
        """
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow([
                "date", "date_fr", "city", "lat", "lon", "t_max", "rain_mm", "sky_label",
            ])

            for day in forecast:
                date_str = day["date"]
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")

                jours = {
                    "Monday": "Lundi",
                    "Tuesday": "Mardi",
                    "Wednesday": "Mercredi",
                    "Thursday": "Jeudi",
                    "Friday": "Vendredi",
                    "Saturday": "Samedi",
                    "Sunday": "Dimanche",
                }

                mois = {
                    "January": "Janvier",
                    "February": "Février",
                    "March": "Mars",
                    "April": "Avril",
                    "May": "Mai",
                    "June": "Juin",
                    "July": "Juillet",
                    "August": "Août",
                    "September": "Septembre",
                    "October": "Octobre",
                    "November": "Novembre",
                    "December": "Décembre",
                }

                date_fr = (
                    f"{jours[date_obj.strftime('%A')]} "
                    f"{date_obj.strftime('%d')} "
                    f"{mois[date_obj.strftime('%B')]} "
                    f"{date_obj.strftime('%Y')}"
                )


                for city, d in day["cities"].items():
                    effective_code = self._effective_sky(d["weathercode"], d["rain"], d["t_max"])
                    writer.writerow([
                        day['date'],
                        date_fr,
                        city,
                        self.CITIES[city]['lat'],
                        self.CITIES[city]['lon'],
                        d["t_max"],
                        d["rain"],
                        self.wmo_label(effective_code),
                    ])

        print(f"CSV exporté : {path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Génère le bulletin météo national (script narré ou export CSV).")
    parser.add_argument("--csv", default="data/weather_bulletin.csv", metavar="FILE", help="Exporte le forecast en CSV (1 ligne par région/jour) au lieu d'imprimer le script narré")
    args = parser.parse_args()

    client = OpenMeteoClient()
    forecast = client.get_national_forecast()

    client.export_csv(forecast, args.csv)


if __name__ == "__main__":
    main()