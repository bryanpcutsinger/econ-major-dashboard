"""Job (OCCP) labels from the Census PUMS data dictionary (ledger E45; instructor ruling 2026-10-26).

The dictionary's VAL rows give each OCCP code a label such as "MGR-Chief Executives And Legislators". The page
shows "Chief executives and legislators": the group prefix dropped, then sentence case (proper nouns and
acronyms the dictionary capitalizes are kept by the KEEP list).
"""
import csv
import re

KEEP = {"Air", "Armed", "Forces", "ATM", "EMTs", "HVAC", "TV", "U.S.", "Web", "Military"}   # kept as printed


def tidy(raw):
    s = re.sub(r"^[A-Z]{3}-", "", raw.strip())                  # "MGR-", "BUS-", ... group prefix
    words = s.split(" ")
    out = [words[0]] + [w if (w in KEEP or w.isupper() or not w[:1].isupper()) else w.lower() for w in words[1:]]
    return " ".join(out)


def census_occp_labels(dictionary_csv):
    """{OCCP code (int): label} from a PUMS data dictionary CSV; non-numeric codes (e.g. 'bbbb') skipped."""
    labels = {}
    for row in csv.reader(open(dictionary_csv, encoding="utf-8-sig")):
        if len(row) > 6 and row[0] == "VAL" and row[1] == "OCCP" and row[4].isdigit() and row[4] == row[5]:
            labels[int(row[4])] = tidy(row[6])
    return labels


if __name__ == "__main__":
    import sys
    lab = census_occp_labels(sys.argv[1])
    print(len(lab))
    for k in list(lab)[:5] + [1006, 2205, 4720, 9830]:
        print(k, lab.get(k))
