from playwright.sync_api import sync_playwright
import csv

URL = "https://www.nexusmods.com/games/morrowind/mods?sort=endorsements&timeRange=7"


def scrape_mods():
    mods = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        page = browser.new_page()

        page.goto(URL, wait_until="networkidle")

        # attendre le chargement des cartes
        page.wait_for_selector('[data-e2eid="mod-tile"]')

        cards = page.locator('[data-e2eid="mod-tile"]')

        for i in range(cards.count()):
            card = cards.nth(i)

            try:
                title = card.locator(
                    '[data-e2eid="mod-tile-title"]'
                ).inner_text().strip()

                mod_url = card.locator(
                    '[data-e2eid="mod-tile-title"]'
                ).get_attribute("href")

                description = card.locator(
                    '[data-e2eid="mod-tile-summary"]'
                ).inner_text().strip()

                image = card.locator("img").first.get_attribute("src")

                mods.append({
                    "name": title,
                    "description": description,
                    "url": mod_url,
                    "image": image
                })

            except Exception as e:
                print("Erreur :", e)

        browser.close()

    return mods


def save_csv(mods, filename="data/morrowind_mods.csv"):
    with open(filename, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "name",
                "description",
                "url",
                "image"
            ]
        )

        writer.writeheader()
        writer.writerows(mods)


if __name__ == "__main__":
    mods = scrape_mods()

    print(f"{len(mods)} mods récupérés")

    save_csv(mods)