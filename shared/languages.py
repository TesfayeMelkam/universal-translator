"""Single canonical language catalog used by the API, the web UI and (later) Android.

`nllb` is the NLLB-200 language code (used by the Hugging Face provider).
`speech_tag` is the BCP-47 tag handed to the browser's speech APIs. Whether a browser
actually has a recognizer/voice for that tag depends on the browser and OS, so the UI
checks availability at runtime instead of assuming support.
Support for a language does NOT mean equal translation quality.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Language:
    code: str            # ISO 639-1 (or 639-3 where no 2-letter code exists)
    english_name: str
    native_name: str
    script: str          # ISO 15924
    rtl: bool
    nllb: Optional[str]  # NLLB-200 code, None if the model does not cover it
    speech_tag: str      # BCP-47 tag for browser speech APIs
    group: str           # ethiopian | african | world

    def to_dict(self) -> dict:
        return asdict(self)


_L = Language
LANGUAGES: List[Language] = [
    # Ethiopian languages
    _L("am", "Amharic", "አማርኛ", "Ethi", False, "amh_Ethi", "am-ET", "ethiopian"),
    _L("om", "Afaan Oromo", "Afaan Oromoo", "Latn", False, "gaz_Latn", "om-ET", "ethiopian"),
    _L("ti", "Tigrinya", "ትግርኛ", "Ethi", False, "tir_Ethi", "ti-ET", "ethiopian"),
    _L("so", "Somali", "Soomaali", "Latn", False, "som_Latn", "so-SO", "ethiopian"),
    # More Ethiopian languages (v0.6). Most are NOT covered by any machine-translation engine this app uses,
    # so for them translation works only from your own data (phrasebook / cloud data source, see Setup -> Data).
    # The app shows "phrasebook only" next to such languages instead of pretending a model exists.
    _L("aa", "Afar", "Qafar af", "Latn", False, None, "aa-ET", "ethiopian"),
    _L("wal", "Wolaytta", "Wolayttatto", "Latn", False, None, "wal-ET", "ethiopian"),
    _L("sid", "Sidama", "Sidaamu Afoo", "Latn", False, None, "sid-ET", "ethiopian"),
    _L("ktb", "Kambaata", "Kambaatissa", "Latn", False, None, "ktb-ET", "ethiopian"),
    _L("hdy", "Hadiyya", "Hadiyyisa", "Latn", False, None, "hdy-ET", "ethiopian"),
    _L("gmv", "Gamo", "Gamo", "Latn", False, None, "gmv-ET", "ethiopian"),
    _L("sgw", "Gurage (Sebat Bet)", "ጉራጊኛ", "Ethi", False, None, "sgw-ET", "ethiopian"),
    _L("har", "Harari", "ሀረሪ", "Ethi", False, None, "har-ET", "ethiopian"),
    _L("anu", "Anuak", "Dha Anywaa", "Latn", False, None, "anu-ET", "ethiopian"),
    _L("gez", "Ge'ez", "ግዕዝ", "Ethi", False, None, "gez-ET", "ethiopian"),
    # African languages
    _L("sw", "Swahili", "Kiswahili", "Latn", False, "swh_Latn", "sw-KE", "african"),
    _L("ha", "Hausa", "Hausa", "Latn", False, "hau_Latn", "ha-NG", "african"),
    _L("yo", "Yoruba", "Yorùbá", "Latn", False, "yor_Latn", "yo-NG", "african"),
    _L("ig", "Igbo", "Igbo", "Latn", False, "ibo_Latn", "ig-NG", "african"),
    # World languages
    _L("en", "English", "English", "Latn", False, "eng_Latn", "en-US", "world"),
    _L("ar", "Arabic", "العربية", "Arab", True, "arb_Arab", "ar-SA", "world"),
    _L("fr", "French", "Français", "Latn", False, "fra_Latn", "fr-FR", "world"),
    _L("zh", "Chinese (Simplified)", "中文（简体）", "Hans", False, "zho_Hans", "zh-CN", "world"),
    _L("es", "Spanish", "Español", "Latn", False, "spa_Latn", "es-ES", "world"),
    _L("pt", "Portuguese", "Português", "Latn", False, "por_Latn", "pt-PT", "world"),
    _L("hi", "Hindi", "हिन्दी", "Deva", False, "hin_Deva", "hi-IN", "world"),
    _L("bn", "Bengali", "বাংলা", "Beng", False, "ben_Beng", "bn-BD", "world"),
    _L("ja", "Japanese", "日本語", "Jpan", False, "jpn_Jpan", "ja-JP", "world"),
    _L("ko", "Korean", "한국어", "Kore", False, "kor_Hang", "ko-KR", "world"),
    _L("tr", "Turkish", "Türkçe", "Latn", False, "tur_Latn", "tr-TR", "world"),
    _L("ru", "Russian", "Русский", "Cyrl", False, "rus_Cyrl", "ru-RU", "world"),
    _L("de", "German", "Deutsch", "Latn", False, "deu_Latn", "de-DE", "world"),
    _L("it", "Italian", "Italiano", "Latn", False, "ita_Latn", "it-IT", "world"),
    _L("id", "Indonesian", "Bahasa Indonesia", "Latn", False, "ind_Latn", "id-ID", "world"),
    _L("th", "Thai", "ไทย", "Thai", False, "tha_Thai", "th-TH", "world"),
    _L("vi", "Vietnamese", "Tiếng Việt", "Latn", False, "vie_Latn", "vi-VN", "world"),
    _L("fa", "Persian", "فارسی", "Arab", True, "pes_Arab", "fa-IR", "world"),
    _L("ur", "Urdu", "اردو", "Arab", True, "urd_Arab", "ur-PK", "world"),
    _L("nl", "Dutch", "Nederlands", "Latn", False, "nld_Latn", "nl-NL", "world"),
    _L("pl", "Polish", "Polski", "Latn", False, "pol_Latn", "pl-PL", "world"),
    _L("uk", "Ukrainian", "Українська", "Cyrl", False, "ukr_Cyrl", "uk-UA", "world"),
    _L("el", "Greek", "Ελληνικά", "Grek", False, "ell_Grek", "el-GR", "world"),
    _L("he", "Hebrew", "עברית", "Hebr", True, "heb_Hebr", "he-IL", "world"),
    _L("ta", "Tamil", "தமிழ்", "Taml", False, "tam_Taml", "ta-IN", "world"),
    # ---- Ethiopian-region languages covered by the translation model ----
    _L("nus", "Nuer", "Thok Naath", "Latn", False, "nus_Latn", "nus-SS", "ethiopian"),
    # ---- more African languages ----
    _L("af", "Afrikaans", "Afrikaans", "Latn", False, "afr_Latn", "af-ZA", "african"),
    _L("zu", "Zulu", "isiZulu", "Latn", False, "zul_Latn", "zu-ZA", "african"),
    _L("xh", "Xhosa", "isiXhosa", "Latn", False, "xho_Latn", "xh-ZA", "african"),
    _L("rw", "Kinyarwanda", "Ikinyarwanda", "Latn", False, "kin_Latn", "rw-RW", "african"),
    _L("rn", "Kirundi", "Ikirundi", "Latn", False, "run_Latn", "rn-BI", "african"),
    _L("sn", "Shona", "chiShona", "Latn", False, "sna_Latn", "sn-ZW", "african"),
    _L("st", "Southern Sotho", "Sesotho", "Latn", False, "sot_Latn", "st-ZA", "african"),
    _L("nso", "Northern Sotho", "Sepedi", "Latn", False, "nso_Latn", "nso-ZA", "african"),
    _L("tn", "Tswana", "Setswana", "Latn", False, "tsn_Latn", "tn-ZA", "african"),
    _L("ts", "Tsonga", "Xitsonga", "Latn", False, "tso_Latn", "ts-ZA", "african"),
    _L("ss", "Swati", "SiSwati", "Latn", False, "ssw_Latn", "ss-ZA", "african"),
    _L("ny", "Chichewa", "Chichewa", "Latn", False, "nya_Latn", "ny-MW", "african"),
    _L("mg", "Malagasy", "Malagasy", "Latn", False, "plt_Latn", "mg-MG", "african"),
    _L("wo", "Wolof", "Wolof", "Latn", False, "wol_Latn", "wo-SN", "african"),
    _L("ln", "Lingala", "Lingála", "Latn", False, "lin_Latn", "ln-CD", "african"),
    _L("kg", "Kongo", "Kikongo", "Latn", False, "kon_Latn", "kg-CD", "african"),
    _L("lua", "Luba-Kasai", "Tshiluba", "Latn", False, "lua_Latn", "lua-CD", "african"),
    _L("lg", "Luganda", "Luganda", "Latn", False, "lug_Latn", "lg-UG", "african"),
    _L("ak", "Akan (Twi)", "Twi", "Latn", False, "twi_Latn", "ak-GH", "african"),
    _L("ee", "Ewe", "Eʋegbe", "Latn", False, "ewe_Latn", "ee-GH", "african"),
    _L("fon", "Fon", "Fɔ̀ngbè", "Latn", False, "fon_Latn", "fon-BJ", "african"),
    _L("ff", "Fula", "Fulfulde", "Latn", False, "fuv_Latn", "ff-NG", "african"),
    _L("bm", "Bambara", "Bamanankan", "Latn", False, "bam_Latn", "bm-ML", "african"),
    _L("dyu", "Dyula", "Julakan", "Latn", False, "dyu_Latn", "dyu-BF", "african"),
    _L("mos", "Mossi", "Mooré", "Latn", False, "mos_Latn", "mos-BF", "african"),
    _L("knc", "Kanuri", "Kanuri", "Latn", False, "knc_Latn", "knc-NG", "african"),
    _L("bem", "Bemba", "Ichibemba", "Latn", False, "bem_Latn", "bem-ZM", "african"),
    _L("tum", "Tumbuka", "Chitumbuka", "Latn", False, "tum_Latn", "tum-MW", "african"),
    _L("sg", "Sango", "Sängö", "Latn", False, "sag_Latn", "sg-CF", "african"),
    _L("luo", "Luo", "Dholuo", "Latn", False, "luo_Latn", "luo-KE", "african"),
    _L("ki", "Kikuyu", "Gĩkũyũ", "Latn", False, "kik_Latn", "ki-KE", "african"),
    _L("kam", "Kamba", "Kikamba", "Latn", False, "kam_Latn", "kam-KE", "african"),
    _L("arz", "Egyptian Arabic", "مصرى", "Arab", True, "arz_Arab", "ar-EG", "african"),
    _L("ary", "Moroccan Arabic", "الدارجة", "Arab", True, "ary_Arab", "ar-MA", "african"),
    # ---- more world languages ----
    _L("sq", "Albanian", "Shqip", "Latn", False, "als_Latn", "sq-AL", "world"),
    _L("hy", "Armenian", "Հայերեն", "Armn", False, "hye_Armn", "hy-AM", "world"),
    _L("az", "Azerbaijani", "Azərbaycan dili", "Latn", False, "azj_Latn", "az-AZ", "world"),
    _L("eu", "Basque", "Euskara", "Latn", False, "eus_Latn", "eu-ES", "world"),
    _L("be", "Belarusian", "Беларуская", "Cyrl", False, "bel_Cyrl", "be-BY", "world"),
    _L("bg", "Bulgarian", "Български", "Cyrl", False, "bul_Cyrl", "bg-BG", "world"),
    _L("ca", "Catalan", "Català", "Latn", False, "cat_Latn", "ca-ES", "world"),
    _L("hr", "Croatian", "Hrvatski", "Latn", False, "hrv_Latn", "hr-HR", "world"),
    _L("bs", "Bosnian", "Bosanski", "Latn", False, "bos_Latn", "bs-BA", "world"),
    _L("cs", "Czech", "Čeština", "Latn", False, "ces_Latn", "cs-CZ", "world"),
    _L("da", "Danish", "Dansk", "Latn", False, "dan_Latn", "da-DK", "world"),
    _L("et", "Estonian", "Eesti", "Latn", False, "est_Latn", "et-EE", "world"),
    _L("fi", "Finnish", "Suomi", "Latn", False, "fin_Latn", "fi-FI", "world"),
    _L("gl", "Galician", "Galego", "Latn", False, "glg_Latn", "gl-ES", "world"),
    _L("ka", "Georgian", "ქართული", "Geor", False, "kat_Geor", "ka-GE", "world"),
    _L("gu", "Gujarati", "ગુજરાતી", "Gujr", False, "guj_Gujr", "gu-IN", "world"),
    _L("ht", "Haitian Creole", "Kreyòl ayisyen", "Latn", False, "hat_Latn", "ht-HT", "world"),
    _L("hu", "Hungarian", "Magyar", "Latn", False, "hun_Latn", "hu-HU", "world"),
    _L("is", "Icelandic", "Íslenska", "Latn", False, "isl_Latn", "is-IS", "world"),
    _L("ga", "Irish", "Gaeilge", "Latn", False, "gle_Latn", "ga-IE", "world"),
    _L("kn", "Kannada", "ಕನ್ನಡ", "Knda", False, "kan_Knda", "kn-IN", "world"),
    _L("kk", "Kazakh", "Қазақ тілі", "Cyrl", False, "kaz_Cyrl", "kk-KZ", "world"),
    _L("km", "Khmer", "ខ្មែរ", "Khmr", False, "khm_Khmr", "km-KH", "world"),
    _L("lo", "Lao", "ລາວ", "Laoo", False, "lao_Laoo", "lo-LA", "world"),
    _L("lv", "Latvian", "Latviešu", "Latn", False, "lvs_Latn", "lv-LV", "world"),
    _L("lt", "Lithuanian", "Lietuvių", "Latn", False, "lit_Latn", "lt-LT", "world"),
    _L("lb", "Luxembourgish", "Lëtzebuergesch", "Latn", False, "ltz_Latn", "lb-LU", "world"),
    _L("mk", "Macedonian", "Македонски", "Cyrl", False, "mkd_Cyrl", "mk-MK", "world"),
    _L("ms", "Malay", "Bahasa Melayu", "Latn", False, "zsm_Latn", "ms-MY", "world"),
    _L("ml", "Malayalam", "മലയാളം", "Mlym", False, "mal_Mlym", "ml-IN", "world"),
    _L("mt", "Maltese", "Malti", "Latn", False, "mlt_Latn", "mt-MT", "world"),
    _L("mr", "Marathi", "मराठी", "Deva", False, "mar_Deva", "mr-IN", "world"),
    _L("mn", "Mongolian", "Монгол", "Cyrl", False, "khk_Cyrl", "mn-MN", "world"),
    _L("ne", "Nepali", "नेपाली", "Deva", False, "npi_Deva", "ne-NP", "world"),
    _L("no", "Norwegian", "Norsk", "Latn", False, "nob_Latn", "nb-NO", "world"),
    _L("pa", "Punjabi", "ਪੰਜਾਬੀ", "Guru", False, "pan_Guru", "pa-IN", "world"),
    _L("ro", "Romanian", "Română", "Latn", False, "ron_Latn", "ro-RO", "world"),
    _L("sk", "Slovak", "Slovenčina", "Latn", False, "slk_Latn", "sk-SK", "world"),
    _L("sl", "Slovenian", "Slovenščina", "Latn", False, "slv_Latn", "sl-SI", "world"),
    _L("sr", "Serbian", "Српски", "Cyrl", False, "srp_Cyrl", "sr-RS", "world"),
    _L("si", "Sinhala", "සිංහල", "Sinh", False, "sin_Sinh", "si-LK", "world"),
    _L("sv", "Swedish", "Svenska", "Latn", False, "swe_Latn", "sv-SE", "world"),
    _L("tl", "Filipino", "Filipino", "Latn", False, "tgl_Latn", "fil-PH", "world"),
    _L("te", "Telugu", "తెలుగు", "Telu", False, "tel_Telu", "te-IN", "world"),
    _L("uz", "Uzbek", "Oʻzbek", "Latn", False, "uzn_Latn", "uz-UZ", "world"),
    _L("cy", "Welsh", "Cymraeg", "Latn", False, "cym_Latn", "cy-GB", "world"),
    _L("my", "Burmese", "မြန်မာ", "Mymr", False, "mya_Mymr", "my-MM", "world"),
    _L("ps", "Pashto", "پښتو", "Arab", True, "pbt_Arab", "ps-AF", "world"),
    _L("sd", "Sindhi", "سنڌي", "Arab", True, "snd_Arab", "sd-PK", "world"),
    _L("jv", "Javanese", "Basa Jawa", "Latn", False, "jav_Latn", "jv-ID", "world"),
    _L("su", "Sundanese", "Basa Sunda", "Latn", False, "sun_Latn", "su-ID", "world"),
    _L("ceb", "Cebuano", "Cebuano", "Latn", False, "ceb_Latn", "ceb-PH", "world"),
    _L("ilo", "Ilocano", "Ilokano", "Latn", False, "ilo_Latn", "ilo-PH", "world"),
    _L("war", "Waray", "Winaray", "Latn", False, "war_Latn", "war-PH", "world"),
    _L("mi", "Māori", "Te Reo Māori", "Latn", False, "mri_Latn", "mi-NZ", "world"),
    _L("sm", "Samoan", "Gagana Samoa", "Latn", False, "smo_Latn", "sm-WS", "world"),
    _L("fj", "Fijian", "Vosa Vakaviti", "Latn", False, "fij_Latn", "fj-FJ", "world"),
    _L("tg", "Tajik", "Тоҷикӣ", "Cyrl", False, "tgk_Cyrl", "tg-TJ", "world"),
    _L("tk", "Turkmen", "Türkmen", "Latn", False, "tuk_Latn", "tk-TM", "world"),
    _L("tt", "Tatar", "Татар", "Cyrl", False, "tat_Cyrl", "tt-RU", "world"),
    _L("ba", "Bashkir", "Башҡорт", "Cyrl", False, "bak_Cyrl", "ba-RU", "world"),
    _L("ug", "Uyghur", "ئۇيغۇرچە", "Arab", True, "uig_Arab", "ug-CN", "world"),
    _L("yi", "Yiddish", "ייִדיש", "Hebr", True, "ydd_Hebr", "yi", "world"),
    _L("fo", "Faroese", "Føroyskt", "Latn", False, "fao_Latn", "fo-FO", "world"),
    _L("oc", "Occitan", "Occitan", "Latn", False, "oci_Latn", "oc-FR", "world"),
    _L("ast", "Asturian", "Asturianu", "Latn", False, "ast_Latn", "ast-ES", "world"),
    _L("sc", "Sardinian", "Sardu", "Latn", False, "srd_Latn", "sc-IT", "world"),
    _L("scn", "Sicilian", "Sicilianu", "Latn", False, "scn_Latn", "scn-IT", "world"),
    _L("fur", "Friulian", "Furlan", "Latn", False, "fur_Latn", "fur-IT", "world"),
    _L("vec", "Venetian", "Vèneto", "Latn", False, "vec_Latn", "vec-IT", "world"),
    _L("pap", "Papiamento", "Papiamentu", "Latn", False, "pap_Latn", "pap-AW", "world"),
    _L("zh-hant", "Chinese (Traditional)", "中文（繁體）", "Hant", False, "zho_Hant", "zh-TW", "world"),
    _L("yue", "Cantonese", "粵語", "Hant", False, "yue_Hant", "yue-HK", "world"),
    _L("ckb", "Kurdish (Sorani)", "کوردیی ناوەندی", "Arab", True, "ckb_Arab", "ckb-IQ", "world"),
    _L("kmr", "Kurdish (Kurmanji)", "Kurdî", "Latn", False, "kmr_Latn", "kmr-TR", "world"),
    _L("bo", "Tibetan", "བོད་སྐད་", "Tibt", False, "bod_Tibt", "bo-CN", "world"),
    _L("eo", "Esperanto", "Esperanto", "Latn", False, "epo_Latn", "eo", "world"),
    _L("sa", "Sanskrit", "संस्कृतम्", "Deva", False, "san_Deva", "sa-IN", "world"),
    _L("as", "Assamese", "অসমীয়া", "Beng", False, "asm_Beng", "as-IN", "world"),
    _L("or", "Odia", "ଓଡ଼ିଆ", "Orya", False, "ory_Orya", "or-IN", "world"),
    _L("mai", "Maithili", "मैथिली", "Deva", False, "mai_Deva", "mai-IN", "world"),
    _L("bho", "Bhojpuri", "भोजपुरी", "Deva", False, "bho_Deva", "bho-IN", "world"),
    _L("ay", "Aymara", "Aymar aru", "Latn", False, "ayr_Latn", "ay-BO", "world"),
    _L("qu", "Quechua", "Runasimi", "Latn", False, "quy_Latn", "qu-PE", "world"),
    _L("gn", "Guarani", "Avañeʼẽ", "Latn", False, "grn_Latn", "gn-PY", "world"),
]

_BY_CODE: Dict[str, Language] = {l.code: l for l in LANGUAGES}

# Ethiopian languages that have NO machine-translation engine behind them in this app (data/phrasebook only).
# Quality for any language you add data for is only as good as that data: have a fluent speaker review it.
DATA_ONLY_ETHIOPIAN = ["aa", "wal", "sid", "ktb", "hdy", "gmv", "sgw", "har", "anu", "gez"]


def get_language(code: str) -> Optional[Language]:
    return _BY_CODE.get((code or "").strip().lower())


def is_supported(code: str) -> bool:
    return get_language(code) is not None


def search(query: str) -> List[Language]:
    q = (query or "").strip().lower()
    if not q:
        return list(LANGUAGES)
    return [l for l in LANGUAGES
            if q in l.code or q in l.english_name.lower() or q in l.native_name.lower()]


def as_dicts() -> List[dict]:
    return [l.to_dict() for l in LANGUAGES]
