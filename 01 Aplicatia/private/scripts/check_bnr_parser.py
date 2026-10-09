#!/usr/bin/env python3
from loancopilot.business import parse_bnr_rate_page

CASES = [
    (
        "card",
        """<section><h2>Rata dobânzii de politică monetară</h2>
        <p>Valabilă din 8 aug.2024</p><strong>6,50 % p.a.</strong></section>""",
        "2024-08-08",
        6.50,
    ),
    (
        "tabel nou",
        """Data ultimei ședințe a CA pe probleme de politică monetară: 08.07.2026.
        (% per annum) Valabile din: Rata dobânzii de politică monetară,
        Rata dobânzii la facilitatea de creditare, Rata dobânzii la facilitatea de depozit.
        8 aug.2024 6,50 7,50 5,50 8 iul.2024 6,75 7,75 5,75""",
        "2024-08-08",
        6.50,
    ),
    (
        "tabel istoric numeric",
        """Rata dobânzii de politică monetară şi ratele dobânzilor la facilitățile permanente.
        Valabile din: Rata dobânzii de politică monetară Creditare Depozit
        08.08.2024 6.50 7.50 5.50 08.07.2024 6.75 7.75 5.75""",
        "2024-08-08",
        6.50,
    ),
    (
        "json în script",
        r'<html><script>window.data={"title":"Rata dob\u00e2nzii de politic\u0103 monetar\u0103","valid":"Valabil\u0103 din 8 aug.2024","rate":"6,50 % p.a."};</script></html>',
        "2024-08-08",
        6.50,
    ),
]

for name, raw, expected_date, expected_rate in CASES:
    item = parse_bnr_rate_page(raw, "https://www.bnr.ro/test")
    assert item["effective_date"] == expected_date, (name, item)
    assert item["rate"] == expected_rate, (name, item)
    print(f"OK {name}: {item['effective_date']} · {item['rate']:.2f}%")

try:
    parse_bnr_rate_page("<html>fără date monetare</html>", "https://www.bnr.ro/test")
except ValueError:
    print("OK control eroare: pagina fără date este respinsă")
else:
    raise AssertionError("Pagina fără date trebuia respinsă")
