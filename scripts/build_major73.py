"""Build spec/major73.csv: Census FOD1P degree codes -> the NY Fed's 73 majors.

Holian and Chiu follow the Abel-Deitz (NY Fed) 73-major scheme but print only
one of its rules (economics = 5501 + 6205 + 1102). Every other assignment here
is ours. `basis` says how sure it is:
  paper    - stated in Holian and Chiu (2026), p. 327
  name     - the Census label plainly matches one NY Fed name
  judgment - our call; test it against HC Table 3's unweighted counts (step 7)

Run from the repo root:  python3 scripts/build_major73.py
Reads the frozen code lists and NY Fed file in raw/benchmarks/; writes spec/major73.csv.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw" / "benchmarks"
YEARS = [2018, 2019, 2021, 2022, 2023, 2024]

P, N, J = "paper", "name", "judgment"
# code: (NY Fed major, basis, note)
MAP = {
    # Agriculture and environment
    "1100": ("Agriculture", N, ""), "1101": ("Agriculture", N, ""),
    "1102": ("Economics", P, "HC p. 327: agricultural economics is in economics"),
    "1103": ("Animal and Plant Sciences", N, ""),
    "1104": ("Agriculture", J, "food science: Agriculture or Nutrition Sciences"),
    "1105": ("Animal and Plant Sciences", N, ""),
    "1106": ("Animal and Plant Sciences", J, "soil science (code new in 2023)"),
    "1107": ("Animal and Plant Sciences", J, "veterinary medicine (code new in 2023)"),
    "1199": ("Agriculture", N, ""),
    "1301": ("Environmental Studies", N, ""), "1302": ("Environmental Studies", J, "forestry"),
    "1303": ("Environmental Studies", J, "natural resources management"),
    "1401": ("Architecture", N, ""),
    "1501": ("Ethnic Studies", N, ""),
    # Communications
    "1901": ("Communications", N, ""), "1902": ("Journalism", N, ""), "1903": ("Mass Media", N, ""),
    "1904": ("Advertising and Public Relations", N, ""),
    "2001": ("Communications", J, "communication technologies"),
    # Computing
    "2100": ("Information Systems & Management", J, "computer and information systems"),
    "2101": ("Information Systems & Management", J, "computer programming and data processing"),
    "2102": ("Computer Science", N, ""),
    "2105": ("Information Systems & Management", J, "information sciences"),
    "2106": ("Information Systems & Management", J, "computer administration, management, security"),
    "2107": ("Information Systems & Management", J, "computer networking"),
    "2201": ("Leisure and Hospitality", J, "cosmetology services and culinary arts"),
    # Education
    "2300": ("General Education", N, ""),
    "2301": ("General Education", J, "educational administration"),
    "2303": ("General Education", J, "school student counseling"),
    "2304": ("Elementary Education", N, ""),
    "2305": ("Secondary Education", J, "mathematics teacher education"),
    "2306": ("Miscellaneous Education", J, "physical and health education teaching"),
    "2307": ("Early Childhood Education", N, ""),
    "2308": ("Secondary Education", J, "science and computer teacher education"),
    "2309": ("Secondary Education", N, ""),
    "2310": ("Special Education", N, ""),
    "2311": ("Secondary Education", J, "social science or history teacher education"),
    "2312": ("General Education", J, "teacher education: multiple levels"),
    "2313": ("Miscellaneous Education", J, "language and drama education"),
    "2314": ("Miscellaneous Education", J, "art and music education"),
    "2399": ("Miscellaneous Education", N, ""),
    "3501": ("Miscellaneous Education", J, "library science"),
    # Engineering
    "2400": ("General Engineering", N, ""), "2401": ("Aerospace Engineering", N, ""),
    "2402": ("Miscellaneous Engineering", J, "biological engineering"),
    "2403": ("Miscellaneous Engineering", J, "architectural engineering"),
    "2404": ("Miscellaneous Engineering", J, "biomedical engineering"),
    "2405": ("Chemical Engineering", N, ""), "2406": ("Civil Engineering", N, ""),
    "2407": ("Computer Engineering", N, ""), "2408": ("Electrical Engineering", N, ""),
    "2409": ("Miscellaneous Engineering", J, "engineering mechanics, physics, science"),
    "2410": ("Miscellaneous Engineering", J, "environmental engineering"),
    "2411": ("Miscellaneous Engineering", J, "geological and geophysical engineering"),
    "2412": ("Industrial Engineering", N, ""),
    "2413": ("Miscellaneous Engineering", J, "materials engineering"),
    "2414": ("Mechanical Engineering", N, ""),
    "2415": ("Miscellaneous Engineering", J, "metallurgical"), "2416": ("Miscellaneous Engineering", J, "mining"),
    "2417": ("Miscellaneous Engineering", J, "naval architecture"), "2418": ("Miscellaneous Engineering", J, "nuclear"),
    "2419": ("Miscellaneous Engineering", J, "petroleum"), "2499": ("Miscellaneous Engineering", N, ""),
    "2500": ("Engineering Technologies", N, ""),
    "2501": ("Industrial Engineering", J, "engineering and industrial management"),
    "2502": ("Engineering Technologies", N, ""), "2503": ("Engineering Technologies", J, "industrial production tech"),
    "2504": ("Engineering Technologies", N, ""), "2599": ("Engineering Technologies", N, ""),
    # Humanities
    "2601": ("Foreign Language", J, "linguistics and comparative literature"),
    "2602": ("Foreign Language", N, ""), "2603": ("Foreign Language", N, ""),
    "2901": ("Family and Consumer Sciences", N, ""),
    "3201": ("Public Policy and Law", J, "court reporting (2018-19 only)"),
    "3202": ("Public Policy and Law", J, "pre-law and legal studies"),
    "3301": ("English Language", N, ""), "3302": ("English Language", J, "composition and rhetoric"),
    "3401": ("Liberal Arts", N, ""), "3402": ("Liberal Arts", J, "humanities"),
    "4801": ("Philosophy", N, ""), "4901": ("Theology and Religion", N, ""),
    "6402": ("History", N, ""), "6403": ("History", N, "Winters (2016) also merges these"),
    # Biology
    "3600": ("Biology", N, ""), "3601": ("Biochemistry", N, ""),
    "3602": ("Biology", J, "botany"), "3603": ("Biology", J, "molecular biology"),
    "3604": ("Biology", J, "ecology"), "3605": ("Biology", J, "genetics"),
    "3606": ("Biology", J, "microbiology"), "3607": ("Miscellaneous Biological Science", J, "pharmacology"),
    "3608": ("Biology", J, "physiology"), "3609": ("Biology", J, "zoology"),
    "3611": ("Miscellaneous Biological Science", J, "neuroscience"),
    "3699": ("Miscellaneous Biological Science", N, ""),
    # Mathematics and interdisciplinary
    "3700": ("Mathematics", N, ""), "3701": ("Mathematics", J, "applied mathematics"),
    "3702": ("Mathematics", J, "statistics and decision science"),
    "3801": ("Miscellaneous Technologies", J, "military technologies"),
    "4000": ("Interdisciplinary Studies", N, ""),
    "4001": ("International Affairs", J, "intercultural and international studies"),
    "4002": ("Nutrition Sciences", N, ""),
    "4005": ("Computer Science", J, "mathematics and computer science"),
    "4006": ("Interdisciplinary Studies", J, "cognitive science and biopsychology"),
    "4007": ("Interdisciplinary Studies", J, "interdisciplinary social sciences"),
    "4009": ("Business Analytics", J, "data science and data analytics (code new in 2023)"),
    "4101": ("Leisure and Hospitality", N, ""),
    # Physical sciences
    "5000": ("Miscellaneous Physical Sciences", J, "physical sciences, general"),
    "5001": ("Physics", J, "astronomy and astrophysics"),
    "5002": ("Earth Sciences", J, "atmospheric sciences"), "5003": ("Chemistry", N, ""),
    "5004": ("Earth Sciences", N, ""), "5005": ("Earth Sciences", N, ""),
    "5006": ("Earth Sciences", J, "oceanography"), "5007": ("Physics", N, ""),
    "5008": ("Miscellaneous Physical Sciences", J, "materials science"),
    "5098": ("Miscellaneous Physical Sciences", J, "multidisciplinary or general science"),
    "5102": ("Medical Technicians", J, "nuclear, industrial radiology, biological technologies"),
    # Psychology and social sciences
    "5200": ("Psychology", N, ""), "5201": ("Psychology", N, ""), "5202": ("Psychology", N, ""),
    "5203": ("Psychology", N, ""), "5205": ("Psychology", N, ""), "5206": ("Psychology", N, ""),
    "5299": ("Psychology", N, ""),
    "5301": ("Criminal Justice", N, ""), "5503": ("Criminal Justice", J, "criminology"),
    "5401": ("Public Policy and Law", J, "public administration"),
    "5402": ("Public Policy and Law", N, ""),
    "5403": ("Social Services", N, ""), "5404": ("Social Services", N, ""),
    "5500": ("General Social Sciences", N, ""),
    "5501": ("Economics", P, "HC p. 327"),
    "5502": ("Anthropology", N, ""), "5504": ("Geography", N, ""),
    "5505": ("International Affairs", N, ""), "5506": ("Political Science", N, ""),
    "5507": ("Sociology", N, ""), "5599": ("General Social Sciences", J, "miscellaneous social sciences"),
    "5601": ("Construction Services", N, ""),
    "5701": ("Miscellaneous Technologies", J, "electrical, mechanical, precision technologies"),
    "5901": ("Miscellaneous Technologies", J, "transportation sciences"),
    # Arts
    "6000": ("Fine Arts", N, ""), "6001": ("Performing Arts", J, "drama and theater"),
    "6002": ("Performing Arts", J, "music"), "6003": ("Performing Arts", J, "visual and performing arts"),
    "6004": ("Commercial Art & Graphic Design", N, ""),
    "6005": ("Fine Arts", J, "film, video, photographic arts"),
    "6006": ("Art History", N, ""), "6007": ("Fine Arts", J, "studio arts"),
    "6099": ("Fine Arts", J, "miscellaneous fine arts"),
    # Health
    "6100": ("Health Services", N, ""), "6102": ("Health Services", J, "communication disorders"),
    "6103": ("Health Services", J, "health and medical administrative services"),
    "6104": ("Medical Technicians", J, "medical assisting services"),
    "6105": ("Medical Technicians", N, ""), "6106": ("Health Services", J, "health preparatory programs"),
    "6107": ("Nursing", N, ""), "6108": ("Pharmacy", N, ""), "6109": ("Treatment Therapy", N, ""),
    "6110": ("Health Services", J, "community and public health"),
    "6199": ("Health Services", J, "miscellaneous health professions"),
    # Business
    "6200": ("General Business", N, ""), "6201": ("Accounting", N, ""),
    "6202": ("Finance", J, "actuarial science"),
    "6203": ("Business Management", N, ""),
    "6204": ("Business Management", J, "operations, logistics, e-commerce"),
    "6205": ("Economics", P, "HC p. 327: business economics is in economics"),
    "6206": ("Marketing", N, ""), "6207": ("Finance", N, ""),
    "6209": ("Business Management", J, "human resources"),
    "6210": ("International Affairs", J, "international business"),
    "6211": ("Leisure and Hospitality", J, "hospitality management"),
    "6212": ("Business Analytics", J, "management information systems and statistics; "
                                      "HC Table 3 shows Business Analytics before 4009 existed"),
    "6299": ("General Business", J, "miscellaneous business and medical administration"),
}


def main():
    nyfed = [r["Major"] for r in csv.DictReader(open(RAW / "nyfed-2024" / "college-labor-outcomes-by-major-data.csv"))]
    nyfed = [m for m in nyfed if m != "Overall"]
    labels, years_of = {}, {}
    for y in YEARS:
        items = json.load(open(RAW / "census-codelists" / f"FOD1P-{y}.json"))["values"]["item"]
        for code, label in items.items():
            if label.startswith("N/A"):
                continue  # less than a bachelor's degree
            labels.setdefault(code, label)
            years_of.setdefault(code, []).append(y)

    errors = []
    errors += [f"code {c} ({labels[c]}) has no group" for c in sorted(labels) if c not in MAP]
    errors += [f"mapped code {c} not in any code list" for c in sorted(MAP) if c not in labels]
    errors += [f"group '{MAP[c][0]}' (code {c}) is not a NY Fed name" for c in MAP if MAP[c][0] not in nyfed]
    used = {g for g, _, _ in MAP.values()}
    errors += [f"NY Fed major '{m}' gets no code" for m in nyfed if m not in used]

    out = ROOT / "spec" / "major73.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fod1p", "census_label", "nyfed_major", "basis", "years_present", "note"])
        for c in sorted(MAP):
            g, b, note = MAP[c]
            yrs = years_of.get(c, [])
            w.writerow([c, labels.get(c, ""), g, b, f"{min(yrs)}-{max(yrs)}" if yrs else "", note])

    counts = {b: sum(1 for v in MAP.values() if v[1] == b) for b in (P, N, J)}
    print(f"{len(MAP)} codes -> {len(used)} groups (NY Fed lists {len(nyfed)}); basis counts {counts}")
    if errors:
        print("\n".join(errors))
        sys.exit(1)


if __name__ == "__main__":
    main()
