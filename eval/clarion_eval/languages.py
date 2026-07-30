"""The languages the evaluation covers, and how to detect each one surviving
into an output that was supposed to be English.

Clarion's structuring step has one hard requirement: whatever the speaker said,
the output is English. Measuring that is easy for languages written in their own
script — a single Persian, Arabic, Chinese or Russian codepoint in the output is
proof the model failed. It is *not* easy for Spanish and French, which share the
Latin alphabet with English. A model that echoes its Spanish input untouched
produces zero non-Latin characters and would score a perfect "fully English"
under a script check.

So detection is per-language and each language declares which method applies:

    script          — exact. Any codepoint in the language's blocks is residue.
    function_words  — heuristic. Counts high-frequency source-language words that
                      are not English words.

The distinction is carried through into the run files and the report, because a
heuristic and a proof should not be printed in the same column without saying
which is which.

`tests/test_languages.py` runs every function-word detector across every English
gloss in the dataset and every English string in the fixture corpus, and fails on
a single false positive. The word lists below are therefore empirically clean
against the English this harness actually sees, not merely clean by assertion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Script ranges ────────────────────────────────────────────────────────────

_ARABIC = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Presentation Forms-A
    (0xFE70, 0xFEFF),  # Presentation Forms-B
)

_CYRILLIC = (
    (0x0400, 0x04FF),  # Cyrillic
    (0x0500, 0x052F),  # Cyrillic Supplement
    (0x2DE0, 0x2DFF),  # Cyrillic Extended-A
    (0xA640, 0xA69F),  # Cyrillic Extended-B
)

_HAN = (
    (0x3000, 0x303F),  # CJK Symbols and Punctuation (。 、 「 」)
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0xFF00, 0xFF65),  # Fullwidth forms (？ ！ ，) — excludes halfwidth katakana
)


# ── Function-word markers ────────────────────────────────────────────────────
#
# Rules for adding a word here:
#   1. High frequency in the source language, so untranslated text trips it.
#   2. Not an English word, and not a plausible standalone lowercase token in
#      English developer prose.
#   3. Not a technical identifier anyone would name a symbol.
#
# Rule 2 is stricter than it first looks, because matching folds case. That makes
# every short article a liability: `los` matches "Los Angeles", `un` matches
# "UN", `est` matches "EST", `el` matches "El Paso", `al` matches "Al". And two
# survive as English borrowings in their own right — `de` in "de facto", `la` in
# "à la carte". All of them are therefore excluded, along with the words that
# are simply English too:
#   Spanish — no, son, van, red, me, mi, a, e, o, y, en, ser, ver, mas, fin, sale,
#             sea, sean, hay, dice, ante, lo, con, principal
#   French  — on, plus, son, et, a, y, en, car, pas, dur, air, page, note, route,
#             test, version, charge, lent, arrive, dossier, champ, commence,
#             message, minute, grand, unique
#
# Losing the articles would leave some utterances hanging on a single marker, so
# the lists lean instead on unambiguous developer vocabulary — `columna`,
# `requête`, `pantalla`, `fichier`. Those carry no English collision at all, and
# `tests/test_languages.py` measures the resulting margin on every shipped row.

_SPANISH_WORDS = frozenset(
    """
    que qué una unos unas del para por pero
    está están estoy estás estaba estaban esté cuando cuándo donde dónde
    porque esto esta este estas estos ese esa esos esas aquel aquella
    muy más también tampoco hacer haciendo hecho tiene tienen tengo tenía
    había desde entre hasta hacia sin sobre bajo tras según
    todo todos toda todas cada quiero quiere queremos necesito necesita
    así aquí ahí allí algo alguna alguno algunos algunas otra otras otro otros
    nada nunca siempre ahora después antes mismo misma mismos
    puede pueden puedo podría debería debe deben hace
    cómo cuál cuáles mientras aunque sino cualquier además luego entonces
    su sus mí ti nos vosotros ellos ellas usted
    página páginas usuario usuarios archivo archivos carpeta
    columna columnas tabla tablas línea líneas botón campo campos
    consulta consultas cambios rama ramas memoria pantalla pantallas versión
    prueba pruebas función funciones datos fecha fechas
    agregar añadir cambiar mover dejar poner escribir leer correr
    falla fallan pasa pasan queda quedan vuelve vuelven salen entra entran
    llega llegan devuelve devuelven muestra muestran guarda guardan
    borra borran carga cargan actualiza actualizan sigue siguen
    lento lenta rápido rápida primero primera nuevo nueva viejo
    tamaño tiempo número sólo solamente cosa cosas manera forma
    creo creemos rompe rompen problema problemas contenedor modelo
    empieza empiezan subir bajar quinta quinto valor valores
    llamada llamadas cadena cadenas tipo petición peticiones
    respuesta respuestas servidor mensaje mensajes ejemplo intentos
    minuto minutos horas días semanas segundos milisegundos
    duplicados vacío vacía inválido inválida único única índice
    implementar instalar eliminar reemplazar validar convertir procesar
    generar ejecutar actualizar guardar cargar mostrar devolver llamar usar
    activar desactivar
    cinco seis siete ocho nueve diez veinte treinta cuarenta cincuenta
    cien ciento doscientos trescientos cuatrocientos quinientos
    segundo tercero cuarto
    """.split()
)

_FRENCH_WORDS = frozenset(
    """
    que qui quoi une des du au aux dans pour avec mais très être avoir
    fait faire veux veut veulent voudrais voulons faut sais savoir
    c'est qu'il qu'elle qu'on parce quand où cette cet ces ça ceci cela
    ainsi donc alors tout tous toute toutes chaque aussi moins comme
    quelque quelques autre autres rien jamais toujours maintenant après avant
    même peut peuvent peux doit dois doivent dit disent sont était étaient
    soit sera serait j'ai n'est n'ai il elle ils elles nous vous leur leurs
    mon ma mes ses notre votre nos vos lui celui celle ceux
    sans sous sur entre vers chez depuis pendant lorsque puisque afin
    déjà encore beaucoup trop assez peu ne se si ce à
    ajoute écris corrige découpe mets utilise renvoie renvoient
    fichier fichiers colonne colonnes ligne lignes
    utilisateur utilisateurs bouton requête requêtes
    données mémoire écran erreur erreurs chargé charger lancer
    ajouter changer déplacer garder mettre écrire lire
    plante échoue échouent arrivent lente rapide
    nouveau nouvelle vieux branche branches changements modifications
    taille temps nombre seul seule chose choses façon manière
    ensuite puis pareil marche marchent tourne tournent
    affiche affichent enregistre supprime sauf pourtant vraiment plutôt
    souvent parfois modèle remonter première premier deuxième troisième
    quatrième cinquième valeur valeurs chaîne chaînes appel appels
    réponse réponses serveur exemple secondes millisecondes
    doublons vide invalide casse cassé cassés bloque lourd lourde
    petit petite petites fuite fuseau horaire
    trois quatre cinq huit neuf dix vingt trente quarante cinquante mille
    """.split()
)

# Characters that essentially never occur in English developer prose.
_SPANISH_CHARS = frozenset("¿¡ñÑ")
_FRENCH_CHARS = frozenset("œŒ")

# French elision — l'endpoint, d'environnement, qu'on, j'ai, n'est.
#
# A single letter from this set followed by an apostrophe at a word boundary is
# a near-perfect French signal, and it survives where the word list does not:
# "Mets un rate limit sur l'endpoint de login" is recognisably French to a
# reader, but its only giveaway token is the elided article.
#
# English contractions do not collide. They elide *after* the stem — "don't",
# "it's", "we've" — so the apostrophe is never preceded by a lone word-initial
# letter. The one English form that fits the shape, "o'clock", uses `o`, which
# is deliberately not in the set.
_FRENCH_ELISION = r"\b[ldjnmtsc]'(?=[a-zà-öø-ÿ])"


@dataclass(frozen=True)
class Language:
    code: str
    """ISO 639-1, used as the dataset `lang` field and the utterance id prefix."""

    name: str
    """English name, for reports."""

    endonym: str
    """The language's name in itself, for the judge prompt."""

    script: str
    """Writing system. Informational; `detection` is what drives the metric."""

    detection: str
    """`script` (exact) or `function_words` (heuristic)."""

    region: str
    """Cohere's Tiny Aya regional grouping, per Cohere's model documentation."""

    expected_variant: str
    """The Tiny Aya variant whose regional tuning claims to cover this language.

    This is the evaluation's hypothesis, not its conclusion. If Water does not
    actually beat Global on French, that result gets published as-is.
    """

    ranges: tuple = ()
    words: frozenset = frozenset()
    chars: frozenset = frozenset()
    patterns: tuple = ()
    """Extra regexes counted as residue, for signals a word list cannot express."""

    aliases: tuple = field(default_factory=tuple)
    """Alternative codes accepted when loading a dataset (e.g. `zh-CN`)."""


REGISTRY: dict[str, Language] = {
    "fa": Language(
        code="fa",
        name="Persian",
        endonym="فارسی",
        script="Arabic",
        detection="script",
        region="West Asia",
        expected_variant="tiny-aya-earth",
        ranges=_ARABIC,
        aliases=("per", "fas"),
    ),
    "ar": Language(
        code="ar",
        name="Arabic",
        endonym="العربية",
        script="Arabic",
        detection="script",
        region="West Asia",
        expected_variant="tiny-aya-earth",
        ranges=_ARABIC,
        aliases=("ara",),
    ),
    "zh": Language(
        code="zh",
        name="Chinese",
        endonym="中文",
        script="Han",
        detection="script",
        region="Asia-Pacific",
        expected_variant="tiny-aya-water",
        ranges=_HAN,
        aliases=("zh-CN", "zh-Hans", "cmn"),
    ),
    "ru": Language(
        code="ru",
        name="Russian",
        endonym="русский",
        script="Cyrillic",
        detection="script",
        region="Europe",
        expected_variant="tiny-aya-water",
        ranges=_CYRILLIC,
        aliases=("rus",),
    ),
    "es": Language(
        code="es",
        name="Spanish",
        endonym="español",
        script="Latin",
        detection="function_words",
        region="Europe",
        expected_variant="tiny-aya-water",
        words=_SPANISH_WORDS,
        chars=_SPANISH_CHARS,
        aliases=("spa", "es-ES"),
    ),
    "fr": Language(
        code="fr",
        name="French",
        endonym="français",
        script="Latin",
        detection="function_words",
        region="Europe",
        expected_variant="tiny-aya-water",
        words=_FRENCH_WORDS,
        chars=_FRENCH_CHARS,
        patterns=(_FRENCH_ELISION,),
        aliases=("fra", "fre", "fr-FR"),
    ),
}


_ALIASES: dict[str, str] = {
    alias.lower(): lang.code for lang in REGISTRY.values() for alias in lang.aliases
}


def get(code: str) -> Language:
    """Resolves a language code, accepting the aliases each language declares."""
    key = (code or "").strip()
    if key in REGISTRY:
        return REGISTRY[key]
    resolved = _ALIASES.get(key.lower())
    if resolved:
        return REGISTRY[resolved]
    raise KeyError(
        f"Unknown language code {code!r}. Known: {', '.join(sorted(REGISTRY))}"
    )


def codes() -> list[str]:
    return sorted(REGISTRY)


def exact_detection() -> list[str]:
    """Languages whose residue check is a proof rather than a heuristic."""
    return sorted(c for c, l in REGISTRY.items() if l.detection == "script")


__all__ = ["Language", "REGISTRY", "codes", "exact_detection", "get"]
