"""Style profile: the fixed feature vector, the (median, MAD) baseline and robust-z
distance on synthetic samples; the direction gate `/eval-prose --only style` applies
before a feature may be called a calibrated marker."""
import math
from statistics import fmean

import pytest

from lib.morph import Morph
from lib.style_profile import FEATURES, baseline, distance, profile

MORPH_OFF = Morph(available=False)

PLAIN = [
    "Очаг выявлен в шестом сегменте печени. Зона абляции однородна. Осложнений "
    "не зафиксировано. Пациента выписали на третьи сутки. Контроль назначили "
    "через месяц.",
    "Метод основан на сравнении двух серий изображений. Каждое измерение "
    "повторяли дважды. Расхождение не превышало погрешности. Данные усредняли "
    "по пациентам.",
    "Протокол одобрил этический комитет. Все пациенты подписали согласие. "
    "Критерии включения описали ранее.",
]
# Канцелярит-заготовка: одно предложение на 40+ слов, связки, номинализации, скобка.
HEAVY = (
    "Проведение сравнительной оценки эффективности предложенной методики "
    "оптимизации протоколов лучевой диагностики очаговых изменений печени "
    "требует, однако, дальнейшего уточнения критериев отбора пациентов (включая, "
    "кроме того, оценку сопутствующей патологии), что при этом предполагает "
    "стандартизацию описания выявленных изменений специалистами отделения "
    "лучевой диагностики и клинической морфологии."
)
HEAVY_LIKE = [
    HEAVY,
    "Внедрение стандартизации протоколов описания потребовало, однако, "
    "пересмотра критериев отбора (включая, кроме того, уточнение формулировок), "
    "что при этом обеспечило сопоставимость заключений исследователей.",
]
DULL = "Очаг выявлен. " * 30
RICH = (
    "Хирург отступил от края. Раневая полость промыта антисептиком. Дренаж "
    "удалили утром. Больной получал анальгетики. Температура нормализовалась "
    "постепенно. Аппетит восстановился полностью. Шов сняли на десятые сутки."
)


def test_profile_has_the_fixed_feature_set():
    p = profile(PLAIN[0], MORPH_OFF)
    assert set(p) == set(FEATURES)
    assert all(isinstance(v, float) for v in p.values())


def test_text_without_prose_profiles_to_zeros():
    assert profile("", MORPH_OFF) == dict.fromkeys(FEATURES, 0.0)
    assert profile("```python\nx = 1\n```\n", MORPH_OFF) == dict.fromkeys(FEATURES, 0.0)


def test_heavy_prose_reads_longer_and_more_connected():
    d = distance(profile(HEAVY, MORPH_OFF), baseline(PLAIN, MORPH_OFF))
    for k in ("wps", "long_sent_share", "connectives_per_sent", "nom_density",
              "parens_per_sent"):
        assert d[k] > 0, k


def test_lexical_repetition_lowers_mattr():
    assert profile(DULL, MORPH_OFF)["mattr"] < profile(RICH, MORPH_OFF)["mattr"]


def test_distance_sign_matches_the_corpus_direction():
    """The calibration gate itself: a feature counts as a marker only when the
    machine-vs-human direction of the sample corpus repeats on a held-out text —
    here the heavy corpus against the plain baseline."""
    human = [profile(t, MORPH_OFF) for t in PLAIN]
    machine = [profile(t, MORPH_OFF) for t in HEAVY_LIKE]
    held_out = distance(profile(HEAVY_LIKE[1], MORPH_OFF),
                        baseline(PLAIN[:2], MORPH_OFF))
    for k in ("wps", "connectives_per_sent", "nom_density"):
        dir_corpus = (fmean(c[k] for c in machine) > fmean(c[k] for c in human)) - \
            (fmean(c[k] for c in machine) < fmean(c[k] for c in human))
        assert dir_corpus == (1 if held_out[k] > 0 else -1), k


def test_degenerate_baseline_zero_mad():
    base = baseline(PLAIN[:1] * 3, MORPH_OFF)
    assert all(mad == 0.0 for _, mad in base.values())
    same = distance(profile(PLAIN[0], MORPH_OFF), base)
    assert all(v == 0.0 for v in same.values())
    other = distance(profile(RICH, MORPH_OFF), base)
    assert any(math.isinf(v) for v in other.values())


def test_baseline_of_no_samples_is_flat():
    assert baseline([], MORPH_OFF) == {k: (0.0, 0.0) for k in FEATURES}


def test_rare_ratio_flags_words_outside_the_dictionary():
    if not Morph.load().available:
        pytest.skip("требуется extra morph")
    normal = profile(PLAIN[0], Morph.load())
    gibberish = profile(
        "Зоргофикация выполнена с квуфрениостью и поднимальностью. Квуфрениость "
        "зоргофикации подтверждена длительностью. Трастовик квуфренил.", Morph.load())
    assert gibberish["rare_ratio"] > normal["rare_ratio"]
    assert gibberish["rare_ratio"] > 0.5 > normal["rare_ratio"]
    assert profile(PLAIN[0], MORPH_OFF)["rare_ratio"] == 0.0
