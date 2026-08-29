"""College-specific assets and reference data."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

COLLEGES = {
    "ETEC": {
        "logo": PROJECT_ROOT / "assets" / "logos" / "etec.png",
        "template": PROJECT_ROOT / "template_etec.docx",
        "specialties": [
            "04130100-Менеджмент (қолдану салалары бойынша)/(по отраслям и по областям)",
            "04110100-Есеп және аудит/Учет и аудит",
            "04210100-Құқықтану/Правоведение",
            "06120100-Есептеу техникасы және ақпараттық желілер/Вычислительная техника и информационные сети",
            "10410300-Автомобиль көлігінде тасымалдауды ұйымдастыру және қозғалысты басқару/Организация перевозок и управление движением на автомобильном транспорте",
            "06130100-Бағдарламалық қызмет ету (түрлері бойынша)/Программное обеспечение (по видам)",
            "07130700-Электромеханикалық жабдықтарға техникалық қызмет көрсету, жөндеу және пайдалану",
            "07161300-Автомобиль көлігіне техникалық қызмет көрсету және пайдалану",
        ],
        "pck_chairs": ["Аманкалиев М.", "Серік А.М."],
    },
    "META": {
        "logo": PROJECT_ROOT / "assets" / "logos" / "meta.png",
        "template": PROJECT_ROOT / "template_meta.docx",
        "specialties": [],
        "pck_chairs": [],
    },
}


def get_college_config(college: str) -> dict:
    """Return the configured assets and reference data for a college."""
    return COLLEGES.get(str(college or "").upper(), COLLEGES["ETEC"])
